import csv
import io
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.models.schemas import (
    EnrichChannelPayload,
    EnrichRequest,
    EnrichResponse,
    SearchResponse,
    SocialLink,
)
from app.services.bio_parser import format_socials_export
from app.services.enrich import EnrichTarget, enrich_channel_contacts, enrich_creators_inplace
from app.services.youtube import get_youtube_service

router = APIRouter()

SortOption = Literal["relevance", "subscribers", "views"]


def _require_query(q: str | None) -> str:
    if q is None or not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required.")
    return q.strip()


def _enrich_response(enriched: dict[str, dict]) -> EnrichResponse:
    channels = {
        channel_id: EnrichChannelPayload(
            email=payload.get("email"),
            phone=payload.get("phone"),
            socials=[SocialLink(**item) for item in payload.get("socials") or []],
        )
        for channel_id, payload in enriched.items()
    }
    return EnrichResponse(channels=channels)


@router.get("/search", response_model=SearchResponse)
def search(
    q: str | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=15),
    sort: SortOption = Query(default="relevance"),
) -> SearchResponse:
    """Fast path: YouTube API only. Returns full India/unknown pool (no About scrapes)."""
    query = _require_query(q)
    return get_youtube_service().search_creators(query, limit=limit, sort=sort)


@router.get("/enrich", response_model=EnrichResponse)
def enrich_get(
    ids: str = Query(default="", description="Comma-separated channel IDs (max 15)"),
) -> EnrichResponse:
    channel_ids = [part.strip() for part in ids.split(",") if part.strip()]
    if not channel_ids:
        return EnrichResponse(channels={})
    return _enrich_response(enrich_channel_contacts(channel_ids))


@router.post("/enrich", response_model=EnrichResponse)
def enrich_post(body: EnrichRequest) -> EnrichResponse:
    """About contacts + web email lookup for big creators (≥100k) missing YouTube email."""
    targets = [
        EnrichTarget(
            channel_id=item.channel_id,
            channel_name=item.channel_name,
            subscribers=item.subscribers,
        )
        for item in body.channels
        if (item.channel_id or "").strip()
    ]
    if not targets:
        return EnrichResponse(channels={})
    return _enrich_response(enrich_channel_contacts([], targets=targets))


@router.get("/export")
def export_csv(
    q: str | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=15),
    sort: SortOption = Query(default="relevance"),
) -> StreamingResponse:
    query = _require_query(q)
    service = get_youtube_service()
    result = service.search_creators(query, limit=limit, sort=sort)
    creators = service._sort_creators(list(result.creators), sort)[:limit]
    enrich_creators_inplace(creators)

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
    for creator in creators:
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
