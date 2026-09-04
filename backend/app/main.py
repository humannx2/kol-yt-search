from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.routes.pages import router as pages_router
from app.routes.search import router as search_router

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="YouTube Creator Search", version="0.1.0")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
app.state.templates = templates

app.include_router(search_router, prefix="/api")
app.include_router(pages_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
