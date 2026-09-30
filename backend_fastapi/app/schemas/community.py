from typing import Optional
from pydantic import BaseModel


class CustomEmojiCreateRequest(BaseModel):
    shortcode: str
    image_url: str
    category: Optional[str] = "custom"


class RealmUpdateRequest(BaseModel):
    name: Optional[str] = None
    reputation_threshold: Optional[int] = None
    stage_count: Optional[int] = None
    color_band: Optional[str] = None
    dedicated_contributor: Optional[bool] = None


class BlockUserRequest(BaseModel):
    reason: str


class UnblockUserRequest(BaseModel):
    pass


class TimeoutUserRequest(BaseModel):
    hours: int
    reason: str
