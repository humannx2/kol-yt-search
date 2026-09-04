# YouTube Creator Search

Keyword → YouTube Data API v3 → India/unknown country filter → fast creator pool → client sort/limit → lazy contact enrich.

Single FastAPI process serves both the JSON API and the web UI. No database, no auth, no Node/npm.

---

## How to run (local)

**1. Install**

```bash
cd backend
pip3 install -r requirements.txt
```

**2. Add your API key**

```bash
cp .env.example .env
```

Put your key in `backend/.env`:

```env
YOUTUBE_API_KEY=your_api_key_here
```

Get a key from [Google Cloud → YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com).

**3. Start**

```bash
cd backend
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

| Setting | Value |
|---------|--------|
| Root / working directory | `backend/` |
| Start command | `python run.py` |
| Health check | `GET /health` |
| Required secret | `YOUTUBE_API_KEY` |

`run.py` binds **`0.0.0.0`** and reads **`PORT`**.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `YOUTUBE_API_KEY` | **yes** | — | YouTube Data API v3 key |
| `PORT` | no | `8000` | Listen port |
| `HOST` | no | `0.0.0.0` | Bind address |
| `RELOAD` | no | `false` | Dev reload only |

---

## Latency model

Search is intentionally split into a **fast path** and a **lazy enrich** path:

1. **`GET /api/search`** — only YouTube Data API (`search` + `videos` + `channels`) + bio regex + India filter. Returns the **full** India/unknown creator pool. Typically a few seconds.
2. **Browser** — sorts and slices (5/10/15) **locally**. Changing sort/limit does **not** call search again.
3. **`GET /api/enrich?ids=...`** — fetches About / More info contacts **only for visible channels** (max 15), in **parallel**, with a **1-hour in-memory cache**. Uses YouTube **Innertube** (`browse` + About continuation) first, then HTML `ytInitialData` as fallback. Skips channels that already have contacts from the description.
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

- **Email** (channel description + About / More info text)
- **Phone** (same sources)
- **X**, **Telegram**, **Instagram** (description + About links)

Other websites are dropped. About/More info is loaded lazily via `/api/enrich` for visible creators missing any of these fields.

---

## System design

```text
Browser
  │
  ├─ GET /api/search?q=...     → full India/unknown pool (fast)
  │     sort/limit in JS
  │
  ├─ GET /api/enrich?ids=...   → About socials for visible ids (parallel + cache)
  │
  └─ Export CSV                → client CSV of current view
                                 (or GET /api/export for API clients)
```

### Project layout

```text
backend/
├── run.py
└── app/
    ├── routes/search.py       # /search /enrich /export
    ├── services/
    │   ├── youtube.py         # fast YouTube pipeline
    │   ├── bio_parser.py
    │   ├── channel_links.py   # Innertube About + HTML fallback
    │   ├── about_cache.py     # 1h TTL cache
    │   └── enrich.py          # parallel enrich
    ├── models/schemas.py
    ├── templates/index.html
    └── static/
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

### `GET /api/enrich`

| Param | Type | Description |
|-------|------|-------------|
| `ids` | string | Comma-separated channel IDs (max 15) |

```json
{
  "channels": {
    "UC...": {
      "socials": [{ "platform": "telegram", "value": "https://t.me/..." }]
    }
  }
}
```

Per-id failures return empty socials (no batch 502).

### `GET /api/export`

Same `q` / `limit` / `sort` as search. Fast search → sort/slice → enrich only those rows → CSV.

Columns:

```text
query_used, relevant_video_count, subs, views, socials, mobile number, email, country
```

---

## Quota note

≈ **102 units** per search (`search.list` 100 + `videos.list` 1 + `channels.list` 1). Enrich uses Innertube/HTML (no Data API quota). Server export re-runs the fast search + enriches ≤15 channels.

---

## Out of scope

Database, auth, Redis, Celery, Docker, AI scoring, HTTPS.
