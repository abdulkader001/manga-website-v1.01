from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class CommentCreateRequest(BaseModel):
    target_type: str
    target_id: int
    content: str
    parent_id: Optional[int] = None
    attachment_type: Optional[str] = None
    attachment_url: Optional[str] = None
    attachment_metadata: Optional[Dict[str, Any]] = None


class CommentEditRequest(BaseModel):
    content: str


class CommentVoteRequest(BaseModel):
    value: int


class CommentReactionRequest(BaseModel):
    emoji: str


class CommentReportRequest(BaseModel):
    reason: Optional[str] = None


class ModeratorRemoveRequest(BaseModel):
    reason: str


class ResolveReportRequest(BaseModel):
    actioned: bool


class CommentItem(BaseModel):
    id: int
    user_id: int
    username: Optional[str] = None
    user_email_masked: Optional[str] = None
    target_type: str
    target_id: int
    parent_id: Optional[int] = None
    depth: int
    content: Optional[str] = None
    deleted: bool
    removed: bool
    removed_reason: Optional[str] = None
    created_at: Optional[str] = None
    edited_at: Optional[str] = None
    source_language: Optional[str] = None
    like_count: int
    dislike_count: int
    attachment_type: Optional[str] = None
    attachment_url: Optional[str] = None
    attachment_metadata: Optional[Dict[str, Any]] = None
    translated_content: Optional[str] = None
    viewer_vote: Optional[int] = None
    reactions: List[Dict[str, Any]] = []
    rank: Optional[Dict[str, Any]] = None


class CommentListResponse(BaseModel):
    items: List[CommentItem]
    total: int
    limit: int
    offset: int
    sort: str


class CommentConfigResponse(BaseModel):
    max_length: int
    max_reply_depth: int
    base_emoji_count: int
    sort_options: List[str]
