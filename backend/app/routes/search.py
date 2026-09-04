from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import SearchResponse
from app.services.youtube import get_youtube_service

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
def search(q: str | None = Query(default=None)) -> SearchResponse:
    if q is None or not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required.")
    return get_youtube_service().search_creators(q.strip())
