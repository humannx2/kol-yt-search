# YouTube Creator Search

Keyword → YouTube Data API v3 → India/unknown country filter → contacts from bio → ranked creators.

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
curl -s 'http://127.0.0.1:8000/api/search?q=cricket&limit=5&sort=relevance' | python3 -m json.tool
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
| `PORT` | no | `8000` | HTTP port |
| `HOST` | no | `0.0.0.0` | Bind address |
| `RELOAD` | no | `false` | Dev reload only |

---

## What it does

1. Search YouTube for up to **50 relevant videos** for the query.
2. Load video + channel statistics and channel **description** / **country**.
3. Parse each channel bio for **email**, **phone**, and **social links**.
4. **Hard filter:** keep only creators with `country == IN` **or** unknown/missing country. Drop set countries that are not India.
5. Sort and return up to **N** creators (default 5, max 15).
6. Optionally **export CSV** with contact fields.

### Ranking / sort

| `sort` | Order |
|--------|--------|
| `relevance` (default) | `relevant_video_count`, then `combined_views` |
| `subscribers` | subscriber count desc (hidden/null last), then relevance |
| `views` | `combined_views` desc, then relevance |

### Country filter

Uses YouTube `channels.list` → `snippet.country` (ISO code).

- Keep: `IN`, missing, empty
- Drop: any other set country (e.g. `US`, `GB`)

### Contact extraction

From channel **description** text only (Data API; no About-page HTML scrape):

- First email match
- First plausible phone (Indian `+91` / 10-digit and general international patterns)
- Social URLs and labeled handles: Instagram, X/Twitter, Facebook, LinkedIn, Telegram, WhatsApp, YouTube, TikTok, Threads, plus generic websites

Missing values stay empty/`null` — nothing is invented.

### UI controls

- Sort dropdown: Relevance / Subscribers / Views
- Channels dropdown: 5 / 10 / 15
- Export CSV (after a successful search with results)
- Per creator: country badge, email, phone, socials, videos

---

## System design

```text
Browser
  │
  ├─ GET /                  → UI (sort, limit, export)
  ├─ GET /api/search        → JSON creators
  └─ GET /api/export        → CSV download
         │
         └─ YouTubeService.search_creators(q, limit, sort)
              search.list → videos.list → channels.list
              parse bio → filter IN|unknown → sort → slice
```

### Project layout

```text
backend/
├── run.py
├── app/
│   ├── main.py
│   ├── routes/search.py      # /api/search + /api/export
│   ├── services/
│   │   ├── youtube.py
│   │   └── bio_parser.py     # email / phone / socials / country helper
│   ├── models/schemas.py
│   ├── templates/index.html
│   └── static/
```

---

## HTTP API

### `GET /health`

```json
{ "status": "ok" }
```

### `GET /api/search`

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `q` | string | required | Search topic |
| `limit` | int | `5` | Creators to return (1–15) |
| `sort` | string | `relevance` | `relevance` \| `subscribers` \| `views` |

**Example**

```bash
curl -s 'http://127.0.0.1:8000/api/search?q=cricket&limit=10&sort=subscribers'
```

**Response `200` (shape)**

```json
{
  "query": "cricket",
  "result_count": 50,
  "sort": "subscribers",
  "limit": 10,
  "creators": [
    {
      "channel_id": "UC...",
      "channel_name": "Example",
      "channel_url": "https://www.youtube.com/channel/UC...",
      "thumbnail": "https://...",
      "subscribers": 1200000,
      "relevant_video_count": 4,
      "combined_views": 8400000,
      "country": "IN",
      "email": "hello@example.com",
      "phone": "+91 98765 43210",
      "socials": [
        { "platform": "instagram", "value": "https://instagram.com/..." }
      ],
      "videos": []
    }
  ]
}
```

`country` is `"IN"` or `null` (unknown). Non-India countries never appear.

**Errors:** `400` missing/blank `q`; `502` YouTube/upstream failure.

### `GET /api/export`

Same query params as `/api/search`. Returns CSV attachment `creators_export.csv`.

Columns (exact order):

```text
query_used, relevant_video_count, subs, views, socials, mobile number, email, country
```

| Column | Source |
|--------|--------|
| `query_used` | search query |
| `relevant_video_count` | videos for that creator in the result set |
| `subs` | channel subscribers (blank if hidden) |
| `views` | `combined_views` of relevant videos |
| `socials` | `platform:value` pairs joined by `; ` |
| `mobile number` | parsed phone |
| `email` | parsed email |
| `country` | `IN` or blank if unknown |

```bash
curl -L -o creators.csv \
  'http://127.0.0.1:8000/api/export?q=cricket&limit=10&sort=views'
```

---

## Quota note

≈ **102 units** per search/export call (`search.list` 100 + `videos.list` 1 + `channels.list` 1). Export re-runs the same pipeline.

---

## Out of scope

Database, auth, Redis, Celery, Docker, AI scoring, scraping YouTube About HTML beyond Data API description/country.
