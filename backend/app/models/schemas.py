from pydantic import BaseModel, Field


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
    videos: list[VideoResult] = Field(default_factory=list)


class SearchResponse(BaseModel):
    query: str
    result_count: int
    creators: list[CreatorResult] = Field(default_factory=list)
