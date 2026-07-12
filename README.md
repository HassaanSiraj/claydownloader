# Social Media Video Downloader (MVP)

Paste a link from Instagram, TikTok, or Facebook and download the video.
Built with FastAPI + yt-dlp + Celery/Redis.

## How it works

```
Browser (paste URL) → POST /api/download → API queues a Celery task in Redis
                     ← job_id (Celery task id)
                                            → Celery worker runs yt-dlp, reports
                                              progress into Redis result backend
Browser polls GET /api/status/{job_id} until status == "done"
Browser → GET /api/file/{job_id} → the video file
```

Downloads run in **Celery workers** (separate processes), so the API never
blocks and you can run multiple workers / add retries. Job state lives in
**Redis**, shared across API and worker processes. Files are auto-deleted 15
minutes after download.

- `app/celery_app.py` — Celery instance (Redis broker + result backend)
- `app/tasks.py` — the `download_video` task; reports progress via `update_state`
- `app/main.py` — API; reads state back via `AsyncResult`
- `app/downloader.py` — the yt-dlp wrapper

## Requirements

- Python 3.10+
- **ffmpeg** on your PATH (merge video+audio). macOS: `brew install ffmpeg`
- **Redis**. macOS: `brew install redis`

## Run (three processes)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# On macOS Python.org builds, wire up CA certs so yt-dlp's TLS works:
export SSL_CERT_FILE=$(python3 -c "import certifi; print(certifi.where())")

# 1. Redis
redis-server --daemonize yes

# 2. Celery worker (needs the same SSL_CERT_FILE export)
celery -A app.celery_app worker --loglevel=info --concurrency=2

# 3. API (in another terminal, same venv + SSL_CERT_FILE export)
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

## Run with Docker (one command)

```bash
docker compose up -d --build
```

Open http://127.0.0.1:8000. This starts Redis, the Celery worker, and the API
together. Stop with `docker compose down`.

## Deploying to Railway

Railway doesn't share a volume/filesystem between separate services, but the
worker downloads a file to disk and the API reads it back from disk — so all
three processes (Redis, Celery worker, API) run in **one Railway service**,
one container, via [`railway-start.sh`](railway-start.sh). [`railway.json`](railway.json)
tells Railway to build from the `Dockerfile` and run that script instead of
the Dockerfile's default `CMD`.

**One-time setup (in the Railway dashboard):**

1. Create a project, add a service pointing at this repo (or deploy once
   with `railway up` from the CLI to create it).
2. Project → **Settings → Tokens** → create a project token.
3. Service → **Settings → Networking** → generate a public domain if you want
   one (Railway auto-injects `PORT`; `railway-start.sh` binds to it).
4. Optional: **Settings → Volumes** → mount a volume at `/srv/downloads` if
   you want in-progress downloads to survive a restart/redeploy. Not required
   — files already auto-delete 15 minutes after download.

**CI (GitHub Actions → auto-deploy on push to `main`):** see
[`.github/workflows/deploy-railway.yml`](.github/workflows/deploy-railway.yml).
It needs, in the GitHub repo's **Settings → Secrets and variables → Actions**:

- Secret `RAILWAY_TOKEN` — the project token from step 2 above.
- Variable `RAILWAY_SERVICE_ID` — the service's ID (Service → Settings → the
  ID in the URL, or `railway status` from the CLI).

## Cookies (optional, helps Instagram/Facebook with gated content)

Instagram and TikTok generally work without cookies. Facebook and
age/login-gated Instagram content may need them. Two options, both read by
`app/downloader.py`:

**Option A — read cookies live from your browser (best for local use):**

```bash
export COOKIES_FROM_BROWSER=chrome   # or: safari | firefox | edge | brave
```

Set this on the **Celery worker** (that's the process that runs yt-dlp).
On macOS, Chrome works well; Safari's cookie file is sandboxed and needs the
terminal to have **Full Disk Access** in System Settings → Privacy.
Not applicable in Docker — no browser is installed in the container, so
`COOKIES_FROM_BROWSER` is left unset there.

**Option B — a cookies.txt file (best for servers, no browser installed):**

Export cookies in Netscape format (e.g. the "Get cookies.txt" browser
extension) and point to it:

```bash
export COOKIES_FILE=/path/to/cookies.txt
```

- **Keep yt-dlp updated** — platforms change constantly: `pip install -U yt-dlp`.
- **Scaling** — run more workers (`--concurrency` or more `celery worker`
  processes, even on other machines pointing at the same Redis). Add task
  retries with `@celery_app.task(autoretry_for=..., max_retries=3)`.
- Downloading may violate platform Terms of Service and copyright. Intended for
  content you have the right to download.
```
