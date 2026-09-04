import csv
import io
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.models.schemas import SearchResponse
from app.services.bio_parser import format_socials_export
from app.services.youtube import get_youtube_service

router = APIRouter()

SortOption = Literal["relevance", "subscribers", "views"]


def _require_query(q: str | None) -> str:
    if q is None or not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required.")
    return q.strip()


@router.get("/search", response_model=SearchResponse)
def search(
    q: str | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=15),
    sort: SortOption = Query(default="relevance"),
) -> SearchResponse:
    query = _require_query(q)
    return get_youtube_service().search_creators(query, limit=limit, sort=sort)


@router.get("/export")
def export_csv(
    q: str | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=15),
    sort: SortOption = Query(default="relevance"),
) -> StreamingResponse:
    query = _require_query(q)
    result = get_youtube_service().search_creators(query, limit=limit, sort=sort)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "query_used",
            "relevant_video_count",
            "subs",
            "views",
            "socials",
            "mobile number",
            "email",
            "country",
        ]
    )
    for creator in result.creators:
        writer.writerow(
            [
                result.query,
                creator.relevant_video_count,
                "" if creator.subscribers is None else creator.subscribers,
                creator.combined_views,
                format_socials_export(creator.socials),
                creator.phone or "",
                creator.email or "",
                creator.country or "",
            ]
        )

    buffer.seek(0)
    filename = "creators_export.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
