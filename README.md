# YouTube Creator Search

Keyword → YouTube Data API v3 → aggregate creators → top 5 ranked results.

Single FastAPI process serves both the JSON API and the web UI. No database, no auth, no Node/npm.

---

## Quick start

### Requirements

- Python 3.11+
- A [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com) key

### Install

```bash
cd backend
pip3 install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```env
YOUTUBE_API_KEY=your_api_key_here
```

### Run

```bash
cd backend
python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

| Surface | URL |
|---------|-----|
| Web UI | http://127.0.0.1:8000 |
| OpenAPI docs | http://127.0.0.1:8000/docs |
| Health | http://127.0.0.1:8000/health |

---

## What it does

1. You enter a topic (e.g. `nvidia earnings`).
2. The app searches YouTube for up to **50 relevant videos** (not channels).
3. It loads video + channel statistics.
4. Videos are grouped by `channel_id`.
5. Creators are ranked and the **top 5** are returned.

### Ranking (MVP)

Primary: `relevant_video_count` (how many of the 50 results belong to the channel)  
Secondary: `combined_views` (sum of views on those relevant videos)

```text
sort(creators, key=(relevant_video_count, combined_views), reverse=True)[:5]
```

UI labels these as **Top creators**, not “best” creators.

### UI features

- Search input (Enter to submit)
- Button disabled while request is in flight
- Loading: `Searching YouTube…`
- Empty: `No relevant creators found.`
- Error banner on API failure
- Per creator: thumbnail, name, subscribers, relevant video count, combined views, channel link
- Per video: thumbnail, title (opens YouTube), views, relative publish date
- Compact number formatting (`1.2M`, `842K`)

---

## System design

```text
Browser
  │
  ├─ GET /                     → Jinja template + static CSS/JS
  │                                JS calls /api/search
  │
  └─ GET /api/search?q=...     → FastAPI route (thin)
                                   │
                                   └─ YouTubeService.search_creators()
                                        │
                                        ├─ search.list   (videos, max 50, relevance)
                                        ├─ videos.list   (snippet + statistics)
                                        ├─ channels.list (snippet + statistics)
                                        ├─ group by channel_id
                                        ├─ rank + slice top 5
                                        └─ SearchResponse (Pydantic)
```

### Design choices

| Choice | Why |
|--------|-----|
| Search videos first, then derive creators | Product logic: who dominates a topic’s results |
| Group by `channel_id` | Names collide / change |
| No DB / cache | MVP proves the pipeline; every request is live |
| API key only on server | Never shipped to the browser |
| Same-origin UI | No CORS complexity |

### Quota note

Each search typically costs:

- 100 units — `search.list`
- 1 unit — `videos.list` (batch)
- 1 unit — `channels.list` (batch)

≈ **102 units** per query against the default 10,000/day quota.

### Project layout

```text
kol-yt-search/
├── README.md
├── .gitignore
└── backend/
    ├── .env.example
    ├── requirements.txt
    └── app/
        ├── main.py              # app, static mount, routers
        ├── config.py            # load YOUTUBE_API_KEY
        ├── models/schemas.py    # Pydantic response models
        ├── routes/
        │   ├── pages.py         # GET /
        │   └── search.py        # GET /api/search
        ├── services/
        │   └── youtube.py       # YouTube client + aggregate/rank
        ├── templates/
        │   └── index.html
        └── static/
            ├── css/app.css
            └── js/app.js
```

---

## HTTP API

Base URL: `http://127.0.0.1:8000`

### `GET /health`

Liveness check.

**Response `200`**

```json
{ "status": "ok" }
```

---

### `GET /`

HTML application shell. Static assets under `/static/*`.

---

### `GET /api/search`

Search YouTube and return the top 5 creators for the query.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `q` | string | yes | Search keyword / topic (whitespace-only rejected) |

**Example**

```bash
curl -s 'http://127.0.0.1:8000/api/search?q=nvidia%20earnings' | python3 -m json.tool
```

**Response `200`**

```json
{
  "query": "nvidia earnings",
  "result_count": 50,
  "creators": [
    {
      "channel_id": "UC...",
      "channel_name": "Example Channel",
      "channel_url": "https://www.youtube.com/channel/UC...",
      "thumbnail": "https://...",
      "subscribers": 1200000,
      "relevant_video_count": 6,
      "combined_views": 8400000,
      "videos": [
        {
          "video_id": "abc123",
          "title": "Nvidia Earnings Breakdown",
          "url": "https://www.youtube.com/watch?v=abc123",
          "thumbnail": "https://...",
          "views": 2100000,
          "published_at": "2026-08-28T12:00:00Z"
        }
      ]
    }
  ]
}
```

| Field | Notes |
|-------|--------|
| `result_count` | Videos successfully loaded after `videos.list` (≤ 50) |
| `creators` | Max length 5; may be shorter |
| `subscribers` | Exact integer when YouTube returns it; `null` if hidden |
| `videos[].views` | Exact integers in API; UI compresses for display |
| `videos` | Sorted by views descending within each creator |

**Empty results `200`**

```json
{
  "query": "some obscure string",
  "result_count": 0,
  "creators": []
}
```

**Errors**

| Status | When | Body |
|--------|------|------|
| `400` | Missing or blank `q` | `{"detail":"Query parameter 'q' is required."}` |
| `502` | Missing API key, YouTube HTTP error, or unexpected failure | `{"detail":"Unable to retrieve YouTube results."}` |

API keys and stack traces are never returned to clients.

---

## Environment

| Variable | Required | Description |
|----------|----------|-------------|
| `YOUTUBE_API_KEY` | yes | Google Cloud YouTube Data API v3 key |

Loaded from `backend/.env` (gitignored). Template: `backend/.env.example`.

---

## Dependencies

```text
fastapi
uvicorn[standard]
google-api-python-client
python-dotenv
pydantic
jinja2
```

---

## Out of scope (intentionally)

Database, auth, Redis, Celery, Docker, AI scoring, sentiment, engagement scores, trend detection, CSV export, saved searches.

---

## Smoke checks

```bash
curl -s http://127.0.0.1:8000/health
curl -s 'http://127.0.0.1:8000/api/search?q=tesla'
curl -s 'http://127.0.0.1:8000/api/search?q='          # expect 400
curl -s 'http://127.0.0.1:8000/api/search'              # expect 400
```

Suggested queries: `nvidia earnings`, `tesla`, `ai agents`, `python tutorial`, `football`.
