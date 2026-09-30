"""Pydantic schemas for the custom navigation tab endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class CustomTabCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., min_length=1, max_length=255)
    is_global: bool = False
    order: int | None = None

    @field_validator("title", "url", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        # Stripping here (rather than raising in an ``after`` validator) lets
        # ``min_length`` reject whitespace-only input through pydantic's
        # built-in error path. A raised ``ValueError`` instead lands a raw
        # exception object in errors()[0]["ctx"]["error"], which the shared
        # RequestValidationError handler passes straight to json.dumps and
        # 500s on.
        return value.strip() if isinstance(value, str) else value
