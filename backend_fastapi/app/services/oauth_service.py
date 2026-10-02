"""OAuth and SSO integration services."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.settings import settings
from ..models import User
from ..services.auth_service import get_user_by_email, normalize_email
from ..utils.sanitizer import strip_all_html

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_OAUTH_SCOPES = "openid email profile"
GOOGLE_STATE_COOKIE = "google_oauth_state"
GOOGLE_STATE_TTL = 600
GOOGLE_CALLBACK_ROUTE_NAME = "google_oauth_callback"


class OAuthExchangeError(Exception):
    """Raised when the OAuth token exchange fails."""


class OAuthUserError(Exception):
    """Raised when the OAuth payload is missing required user information."""


def google_oauth_configured() -> bool:
    """Return ``True`` when Google OAuth has been configured."""
    client_id = settings.google_oauth_client_id
    client_secret = settings.google_oauth_client_secret
    return bool(client_id and client_secret)


def resolve_google_redirect_uri(request: Request) -> str:
    """Resolve the callback URI for Google OAuth."""
    configured = settings.google_oauth_redirect_uri
    if configured:
        normalized = configured.rstrip("/")
        if normalized:
            return normalized
        return configured

    backend_base = settings.backend_url or settings.backend_origin
    if backend_base:
        backend_base = backend_base.rstrip("/")
        if backend_base.endswith("/auth/google/callback"):
            return backend_base
        if backend_base.endswith("/auth/callback"):
            return backend_base
        if backend_base.endswith("/api"):
            return f"{backend_base}/auth/google/callback"
        return f"{backend_base}/api/auth/google/callback"

    return str(request.url_for(GOOGLE_CALLBACK_ROUTE_NAME))


def ensure_google_user(db: Session, profile: dict[str, Any]) -> User:
    """Create or update a user record from a Google profile payload."""
    email_raw = profile.get("email")
    if not email_raw:
        raise OAuthUserError("google_email_missing")

    email = normalize_email(email_raw)

    from .disposable_email import is_disposable_domain

    google_sub = profile.get("sub")

    # The provider must assert the email is verified (SRS 1D.1.5).
    verified_claim = profile.get("email_verified")
    email_is_verified = verified_claim is True or str(verified_claim).lower() == "true"

    user = None
    if google_sub:
        user = db.query(User).filter(User.google_sub == google_sub).first()

    if user is None:
        user = get_user_by_email(db, email)

    # Disposable-email rule (SRS 1D.2): reject NEW signups on temporary
    # domains outright. An EXISTING account is never hard-blocked from
    # logging in just because its domain was added to the blocklist later —
    # that would be an unreviewable lockout, contrary to D5's resolved
    # flag-for-review default. It is flagged for review below instead.
    if user is None and is_disposable_domain(email):
        raise OAuthUserError("disposable_email")
    # The owner's first sign-in: Google vouches for the address, it matches
    # MAIN_ADMIN_EMAIL_HASH and the site has no owner yet. Closed registration
    # must not lock the owner out of their own site.
    from ..core.admin_identity import claim_owner_seat, wants_owner_seat

    owner_candidate = email_is_verified and wants_owner_seat(db, email)

    if user is None and not owner_candidate:
        from .site_content_service import registration_open

        if not registration_open(db):
            raise OAuthUserError("registration_closed")

    created = False
    if user is None:
        user = User(
            email=email,
            provider="google",
            google_sub=google_sub,
        )
        created = True
    else:
        if google_sub and user.google_sub != google_sub:
            user.google_sub = google_sub
        if user.provider != "google":
            user.provider = "google"

    # Once the reader has completed their profile, their chosen name and
    # avatar win over whatever the provider sends on later sign-ins.
    profile_locked = bool(getattr(user, "profile_completed", False))
    name = profile.get("name") or profile.get("given_name")
    if name and not profile_locked:
        clean_name = strip_all_html(name)
        if user.name != clean_name:
            user.name = clean_name

    picture = profile.get("picture")
    if picture and not (profile_locked and user.profile_image):
        if user.profile_image != picture:
            user.profile_image = picture

    if email_is_verified and not getattr(user, "email_verified", False):
        from .auth_service import mark_email_verified

        mark_email_verified(user)

    if created:
        db.add(user)
    else:
        # Defense-in-depth for existing accounts (SRS 1H.7.1 / D5).
        from .disposable_email import flag_if_disposable

        flag_if_disposable(db, user)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        user = get_user_by_email(db, email)
        if user is None:
            raise
        if google_sub and user.google_sub != google_sub:
            user.google_sub = google_sub
        if user.provider != "google":
            user.provider = "google"
        db.add(user)
        db.commit()

    db.refresh(user)

    if owner_candidate and claim_owner_seat(db, user):
        db.commit()
        db.refresh(user)
    return user


def exchange_google_code_for_user(code: str, redirect_uri: str, db: Session) -> User:
    """Exchange the OAuth authorization code for tokens and fetch user profile."""
    client_id = settings.google_oauth_client_id
    client_secret = settings.google_oauth_client_secret

    token_payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }

    try:
        with httpx.Client(timeout=10) as client:
            token_resp = client.post(GOOGLE_TOKEN_ENDPOINT, data=token_payload)
            token_resp.raise_for_status()
            token_data = token_resp.json()

            access_token = token_data.get("access_token")
            if not access_token:
                raise OAuthExchangeError("google_access_token_missing")

            userinfo_resp = client.get(
                GOOGLE_USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_resp.raise_for_status()
            profile = userinfo_resp.json()
    except httpx.HTTPError as exc:
        raise OAuthExchangeError("google_oauth_exchange_failed") from exc

    return ensure_google_user(db, profile)
