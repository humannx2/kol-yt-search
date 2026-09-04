# YouTube Creator Search

Keyword → YouTube Data API v3 → India/unknown country filter → fast creator pool → client sort/limit → lazy contact enrich.

Single FastAPI process serves both the JSON API and the web UI. No database, no auth, no Node/npm.

---

## How to run (local)

**1. Install**

```bash
pip3 install -r requirements.txt
```

**2. Add your API key**

```bash
cp .env.example .env
```

Put your key in `.env` at the repo root:

```env
YOUTUBE_API_KEY=your_api_key_here
```

Get a key from [Google Cloud → YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com).

**3. Start**

```bash
python3 run.py
```

Dev reload: `RELOAD=true python3 run.py`

**4. Open**

| Surface | URL |
|---------|-----|
| Web UI | http://127.0.0.1:8000 |
| API docs | http://127.0.0.1:8000/docs |
| Health | http://127.0.0.1:8000/health |

```bash
curl -s 'http://127.0.0.1:8000/api/search?q=cricket' | python3 -m json.tool
```

---

## How to host

### Vercel (recommended)

1. Push this repo to GitHub/GitLab/Bitbucket.
2. In Vercel → **Add New Project** → import the repo.
3. Project settings:
   - **Root Directory:** `./` (repo root)
   - **Framework Preset:** Other
   - **Build Command:** leave empty
   - **Install Command:** leave empty (Vercel installs from `requirements.txt`)
4. Add Environment Variable:
   - `YOUTUBE_API_KEY` = your YouTube Data API v3 key
5. Deploy.

The serverless entrypoint is [`api/index.py`](api/index.py). `vercel.json` rewrites all routes to it and bundles `app/**` (templates + static).

Local check with Vercel CLI (optional):

```bash
npx vercel dev
```

Notes for serverless:

- Enrich / web-email can be slow; `vercel.json` sets `maxDuration` to **10s** (Hobby default cap without Fluid). Raise it on Pro / Fluid if needed.
- The in-memory About cache is **per warm instance** (not shared across all regions).
- Hobby plans without Fluid compute may need a lower concurrency or fewer enrich IDs if you hit timeouts.

### Generic PaaS (Render, Railway, Fly, etc.)

| Setting | Value |
|---------|--------|
| Root / working directory | repo root |
| Start command | `python run.py` |
| Health check | `GET /health` |
| Required secret | `YOUTUBE_API_KEY` |

`run.py` reads **`PORT`** and **`HOST`**.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `YOUTUBE_API_KEY` | **yes** | — | YouTube Data API v3 key |
| `PORT` | no | `8000` | Listen port |
| `HOST` | no | `127.0.0.1` | Bind address (`0.0.0.0` on most PaaS) |
| `RELOAD` | no | `false` | Dev reload only |

---

## Latency model

Search is intentionally split into a **fast path** and a **lazy enrich** path:

1. **`GET /api/search`** — only YouTube Data API (`search` + `videos` + `channels`) + bio regex + India filter. Returns the **full** India/unknown creator pool. Typically a few seconds.
2. **Browser** — sorts and slices (5/10/15) **locally**. Changing sort/limit does **not** call search again.
3. **`POST /api/enrich`** — fetches About / More info contacts **only for visible channels** (max 15), in **parallel**, with a **1-hour in-memory cache**. Uses YouTube **Innertube** first, then HTML fallback. For creators with **≥100k subscribers** and no YouTube email, runs a best-effort **web email** lookup (Bing + linked/site pages). `GET /api/enrich?ids=...` still works for About-only enrich.
4. **Export CSV** (UI) — builds CSV from the current on-screen rows (instant). Server `/api/export` still exists for API clients: fast search → sort/slice → enrich only those rows.

---

## What it does

1. Search YouTube for up to **50 relevant videos**.
2. Load video + channel statistics and channel description/country.
3. Parse description for email / phone / socials.
4. Keep creators with `country == IN` or unknown country.
5. Return the full filtered pool to the UI.
6. UI sorts/limits locally; then enriches contacts for visible cards.

### Ranking / sort (client-side)

| `sort` | Order |
|--------|--------|
| `relevance` (default) | `relevant_video_count`, then `combined_views` |
| `subscribers` | subscriber count desc (hidden/null last), then relevance |
| `views` | `combined_views` desc, then relevance |

### Country filter

- Keep: `IN`, missing, empty
- Drop: any other set country

### Contact extraction

Kept contacts only:

- **Email** (channel description + About / More info text; for ≥100k-sub creators with no YT email, best-effort public web lookup)
- **Phone** (same sources)
- **X**, **Telegram**, **Instagram** (description + About links)

Other websites are dropped from socials (but may be scraped for email when looking up big creators). About/More info is loaded lazily via `/api/enrich` for visible creators missing any of these fields.

---

## System design

```text
Browser
  │
  ├─ GET /api/search?q=...     → full India/unknown pool (fast)
  │     sort/limit in JS
  │
  ├─ POST /api/enrich          → About contacts (+ web email for ≥100k missing email)
  │
  └─ Export CSV                → client CSV of current view
                                 (or GET /api/export for API clients)
```

### Project layout

```text
.
├── api/
│   └── index.py           # Vercel serverless entry (exports FastAPI app)
├── app/
│   ├── main.py            # FastAPI app
│   ├── routes/search.py   # /search /enrich /export
│   ├── services/
│   │   ├── youtube.py
│   │   ├── bio_parser.py
│   │   ├── channel_links.py
│   │   ├── web_email.py
│   │   ├── about_cache.py
│   │   └── enrich.py
│   ├── models/schemas.py
│   ├── templates/index.html
│   └── static/
├── run.py                 # local / PaaS entry
├── requirements.txt
├── pyproject.toml
├── .python-version
├── runtime.txt
├── Procfile
├── vercel.json
├── .vercelignore
└── .env.example
```

---

## HTTP API

### `GET /health`

```json
{ "status": "ok" }
```

### `GET /api/search`

Fast path. Returns the **entire** India/unknown pool (not pre-sliced).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `q` | string | required | Search topic |
| `limit` | int | `5` | Echoed for clients (1–15); UI slices locally |
| `sort` | string | `relevance` | Echoed; UI sorts locally |

**Errors:** `400` missing/blank `q`; `502` YouTube/upstream failure.

### `POST /api/enrich`

Preferred by the UI. Body:

```json
{
  "channels": [
    { "channel_id": "UC...", "channel_name": "warikoo", "subscribers": 7130000 }
  ]
}
```

Returns About email/phone/socials. If YouTube has no email and `subscribers >= 100000`, also tries a public web email lookup.

### `GET /api/enrich`

| Param | Type | Description |
|-------|------|-------------|
| `ids` | string | Comma-separated channel IDs (max 15) |

About-only (no web email — no channel name/subscriber context).

```json
{
  "channels": {
    "UC...": {
      "email": "a@b.com",
      "socials": [{ "platform": "telegram", "value": "https://t.me/..." }]
    }
  }
}
```

Per-id failures return empty contacts (no batch 502).

### `GET /api/export`

Same `q` / `limit` / `sort` as search. Fast search → sort/slice → enrich only those rows → CSV.

Columns:

```text
query_used, relevant_video_count, subs, views, socials, mobile number, email, country
```

---

## Quota note

≈ **102 units** per search (`search.list` 100 + `videos.list` 1 + `channels.list` 1). Enrich uses Innertube/HTML + optional web scrape (no Data API quota). Server export re-runs the fast search + enriches ≤15 channels.

---

## Out of scope

Database, auth, Redis, Celery, Docker, AI scoring.
