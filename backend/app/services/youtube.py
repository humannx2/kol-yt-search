from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import HTTPException
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import get_youtube_api_key
from app.models.schemas import CreatorResult, SearchResponse, VideoResult

def _upstream_error() -> HTTPException:
    return HTTPException(
        status_code=502,
        detail="Unable to retrieve YouTube results.",
    )


class YouTubeService:
    def __init__(self) -> None:
        api_key = get_youtube_api_key()
        if not api_key:
            raise _upstream_error()
        self._client = build(
            "youtube",
            "v3",
            developerKey=api_key,
            cache_discovery=False,
        )

    def search_creators(self, query: str) -> SearchResponse:
        try:
            search_items = self._search_videos(query)
            if not search_items:
                return SearchResponse(query=query, result_count=0, creators=[])

            video_ids = [
                item["id"]["videoId"]
                for item in search_items
                if item.get("id", {}).get("videoId")
            ]
            videos = self._fetch_videos(video_ids)
            if not videos:
                return SearchResponse(query=query, result_count=0, creators=[])

            channel_ids = list({v["channel_id"] for v in videos if v["channel_id"]})
            channels = self._fetch_channels(channel_ids)
            creators = self._aggregate_and_rank(videos, channels)

            return SearchResponse(
                query=query,
                result_count=len(videos),
                creators=creators[:5],
            )
        except HTTPException:
            raise
        except HttpError:
            raise _upstream_error() from None
        except Exception:
            raise _upstream_error() from None

    def _search_videos(self, query: str) -> list[dict[str, Any]]:
        response = (
            self._client.search()
            .list(
                part="snippet",
                q=query,
                type="video",
                maxResults=50,
                order="relevance",
            )
            .execute()
        )
        return response.get("items", [])

    def _fetch_videos(self, video_ids: list[str]) -> list[dict[str, Any]]:
        videos: list[dict[str, Any]] = []
        for chunk in _chunked(video_ids, 50):
            response = (
                self._client.videos()
                .list(part="snippet,statistics,contentDetails", id=",".join(chunk))
                .execute()
            )
            for item in response.get("items", []):
                snippet = item.get("snippet") or {}
                statistics = item.get("statistics") or {}
                video_id = item.get("id", "")
                videos.append(
                    {
                        "video_id": video_id,
                        "title": snippet.get("title") or "",
                        "channel_id": snippet.get("channelId") or "",
                        "channel_name": snippet.get("channelTitle") or "",
                        "published_at": snippet.get("publishedAt"),
                        "thumbnail": _best_thumbnail(snippet.get("thumbnails") or {}),
                        "views": _safe_int(statistics.get("viewCount")),
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                    }
                )
        return videos

    def _fetch_channels(self, channel_ids: list[str]) -> dict[str, dict[str, Any]]:
        channels: dict[str, dict[str, Any]] = {}
        for chunk in _chunked(channel_ids, 50):
            response = (
                self._client.channels()
                .list(part="snippet,statistics", id=",".join(chunk))
                .execute()
            )
            for item in response.get("items", []):
                channel_id = item.get("id", "")
                snippet = item.get("snippet") or {}
                statistics = item.get("statistics") or {}
                subscribers = (
                    _safe_int(statistics["subscriberCount"])
                    if "subscriberCount" in statistics
                    else None
                )
                channels[channel_id] = {
                    "channel_id": channel_id,
                    "channel_name": snippet.get("title") or "",
                    "channel_url": f"https://www.youtube.com/channel/{channel_id}",
                    "thumbnail": _best_thumbnail(snippet.get("thumbnails") or {}),
                    "subscribers": subscribers,
                }
        return channels

    def _aggregate_and_rank(
        self,
        videos: list[dict[str, Any]],
        channels: dict[str, dict[str, Any]],
    ) -> list[CreatorResult]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for video in videos:
            if video["channel_id"]:
                grouped[video["channel_id"]].append(video)

        creators: list[CreatorResult] = []
        for channel_id, channel_videos in grouped.items():
            channel = channels.get(channel_id, {})
            video_results = [
                VideoResult(
                    video_id=v["video_id"],
                    title=v["title"],
                    url=v["url"],
                    thumbnail=v.get("thumbnail"),
                    views=v.get("views", 0),
                    published_at=v.get("published_at"),
                )
                for v in channel_videos
            ]
            video_results.sort(key=lambda v: v.views, reverse=True)

            creators.append(
                CreatorResult(
                    channel_id=channel_id,
                    channel_name=channel.get("channel_name")
                    or channel_videos[0].get("channel_name")
                    or "",
                    channel_url=channel.get("channel_url")
                    or f"https://www.youtube.com/channel/{channel_id}",
                    thumbnail=channel.get("thumbnail"),
                    subscribers=channel.get("subscribers"),
                    relevant_video_count=len(channel_videos),
                    combined_views=sum(v.get("views", 0) for v in channel_videos),
                    videos=video_results,
                )
            )

        creators.sort(
            key=lambda c: (c.relevant_video_count, c.combined_views),
            reverse=True,
        )
        return creators


def _safe_int(value: Any) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _best_thumbnail(thumbnails: dict[str, Any]) -> str | None:
    for key in ("high", "medium", "default"):
        url = (thumbnails.get(key) or {}).get("url")
        if url:
            return url
    return None


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


_service: YouTubeService | None = None


def get_youtube_service() -> YouTubeService:
    global _service
    if _service is None:
        _service = YouTubeService()
    return _service
