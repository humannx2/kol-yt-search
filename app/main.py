from __future__ import annotations

import sys
from pathlib import Path

# Repo root on sys.path so `import app...` works under uvicorn, Vercel, or direct import.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.routes.pages import router as pages_router
from app.routes.search import router as search_router

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="YouTube Creator Search", version="0.1.0")

_static_dir = BASE_DIR / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.state.templates = templates

app.include_router(search_router, prefix="/api")
app.include_router(pages_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
