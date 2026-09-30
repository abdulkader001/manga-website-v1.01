"""Pydantic schemas for user data transfer."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from ..models import UserRole


class UserBase(BaseModel):
    """Shared attributes for user schemas.

    F-SSS-02: deliberately no ``access_token``/``refresh_token`` fields.
    ``User.access_token``/``refresh_token`` are properties that decrypt the
    stored OAuth provider tokens; ``UserRead`` (below) is used with
    ``from_attributes=True`` directly against ``User`` ORM instances for
    ``GET /auth/me``, so declaring these fields here previously serialized
    the decrypted plaintext tokens into every profile response.
    """

    email: str | None = None
    role: UserRole = UserRole.USER
    is_active: bool = True
    is_main_admin: bool = False
    is_secondary_admin: bool = False
    provider: str | None = None
    username: str | None = None
    name: str | None = None
    google_sub: str | None = None
    permanent: bool = False
    language: str = Field(default="en", max_length=10)
    profile_image: str | None = None


class UserCreate(UserBase):
    """Schema for creating a new user."""

    email: EmailStr


class UserUpdate(BaseModel):
    """Schema for updating existing users."""

    email: EmailStr | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    is_main_admin: bool | None = None
    is_secondary_admin: bool | None = None
    provider: str | None = None
    username: str | None = None
    name: str | None = None
    google_sub: str | None = None
    permanent: bool | None = None
    language: str | None = Field(default=None, max_length=10)
    profile_image: str | None = None


class UserRead(UserBase):
    """Schema returned for read operations."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime | None = None
    email_masked: str | None = None


class UserInDB(UserRead):
    """Internal schema mirroring the database representation."""

    model_config = ConfigDict(from_attributes=True)
