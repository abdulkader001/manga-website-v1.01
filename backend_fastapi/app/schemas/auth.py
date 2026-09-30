"""Pydantic schemas for authentication endpoints."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    """Payload for the login endpoint."""

    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """Payload for the refresh endpoint.

    F-66: ``refresh_token`` is optional because the browser cannot supply it.
    Its only copy lives in the ``httponly`` ``refresh_token_cookie``, so the
    shipped client posts a literal ``{}`` — a body that is present but carries
    no token. With a required field that is a 422 before the handler ever runs,
    which made session refresh impossible from a browser. The handler resolves
    the token from the body first and falls back to the cookie, and raises 401
    when neither carries one.
    """

    refresh_token: str | None = None


class TokenPair(BaseModel):
    """Response containing freshly minted access and refresh tokens."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
