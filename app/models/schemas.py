from typing import Literal

from pydantic import BaseModel, Field

SortOption = Literal["relevance", "subscribers", "views"]


class SocialLink(BaseModel):
    platform: str
    value: str


class VideoResult(BaseModel):
    video_id: str
    title: str
    url: str
    thumbnail: str | None = None
    views: int = 0
    published_at: str | None = None


class CreatorResult(BaseModel):
    channel_id: str
    channel_name: str
    channel_url: str
    thumbnail: str | None = None
    subscribers: int | None = None
    relevant_video_count: int
    combined_views: int
    country: str | None = None
    email: str | None = None
    phone: str | None = None
    socials: list[SocialLink] = Field(default_factory=list)
    videos: list[VideoResult] = Field(default_factory=list)


class SearchResponse(BaseModel):
    query: str
    result_count: int
    sort: SortOption = "relevance"
    limit: int = 5
    creators: list[CreatorResult] = Field(default_factory=list)


class EnrichChannelRequest(BaseModel):
    channel_id: str
    channel_name: str = ""
    subscribers: int | None = None


class EnrichRequest(BaseModel):
    channels: list[EnrichChannelRequest] = Field(default_factory=list)


class EnrichChannelPayload(BaseModel):
    email: str | None = None
    phone: str | None = None
    socials: list[SocialLink] = Field(default_factory=list)


class EnrichResponse(BaseModel):
    channels: dict[str, EnrichChannelPayload] = Field(default_factory=dict)
