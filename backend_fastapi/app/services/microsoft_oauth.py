"""Sign in with Microsoft (personal, work and school accounts) via OpenID
Connect authorization-code flow with PKCE."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from typing import Any

import httpx
from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.settings import settings
from ..models import User
from ..utils.sanitizer import strip_all_html
from .auth_service import get_user_by_email, normalize_email

MICROSOFT_STATE_COOKIE = "microsoft_oauth_state"
MICROSOFT_STATE_TTL = 600
MICROSOFT_SCOPES = "openid email profile"
MICROSOFT_CALLBACK_ROUTE_NAME = "microsoft_oauth_callback"
USERINFO_ENDPOINT = "https://graph.microsoft.com/oidc/userinfo"
# Tenant id Microsoft uses for personal (outlook.com / hotmail / live)
# accounts. Only there is the email claim a verified, non-reassignable address.
CONSUMER_TENANT_ID = "9188040d-6c67-4c5b-b112-36a304b66dad"


class MicrosoftOAuthError(Exception):
    """Raised with a short status key the login page can explain."""


def configured() -> bool:
    return bool(settings.microsoft_oauth_client_id and settings.microsoft_oauth_client_secret)


def _tenant() -> str:
    tenant = (settings.microsoft_oauth_tenant or "common").strip() or "common"
    return tenant if tenant.replace("-", "").replace(".", "").isalnum() else "common"


def authorize_endpoint() -> str:
    return f"https://login.microsoftonline.com/{_tenant()}/oauth2/v2.0/authorize"


def token_endpoint() -> str:
    return f"https://login.microsoftonline.com/{_tenant()}/oauth2/v2.0/token"


def redirect_uri(request: Request) -> str:
    if settings.microsoft_oauth_redirect_uri:
        return settings.microsoft_oauth_redirect_uri
    return str(request.url_for(MICROSOFT_CALLBACK_ROUTE_NAME))


def new_state_and_challenge() -> tuple[str, str, str]:
    """Return ``(state, verifier, challenge)`` for one login attempt."""

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    return state, verifier, challenge


def _unverified_claims(id_token: str | None) -> dict[str, Any]:
    """Claims of an ID token received directly from Microsoft's token endpoint
    over TLS in exchange for our client secret (OIDC Core 3.1.3.7 permits
    skipping signature validation in exactly this case)."""

    if not id_token or id_token.count(".") != 2:
        return {}
    payload = id_token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
        return {}


def exchange_code_for_user(
    code: str, verifier: str, callback_uri: str, db: Session
) -> User:
    data = {
        "client_id": settings.microsoft_oauth_client_id,
        "client_secret": settings.microsoft_oauth_client_secret,
        "code": code,
        "redirect_uri": callback_uri,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
        "scope": MICROSOFT_SCOPES,
    }
    try:
        with httpx.Client(timeout=10) as client:
            token_resp = client.post(token_endpoint(), data=data)
            token_resp.raise_for_status()
            tokens = token_resp.json()
            access_token = tokens.get("access_token")
            if not access_token:
                raise MicrosoftOAuthError("oauth_error")
            info_resp = client.get(
                USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"}
            )
            info_resp.raise_for_status()
            profile = info_resp.json()
    except httpx.HTTPError as exc:
        raise MicrosoftOAuthError("oauth_error") from exc

    claims = _unverified_claims(tokens.get("id_token"))
    return _ensure_user(db, profile, claims)


def _ensure_user(db: Session, profile: dict[str, Any], claims: dict[str, Any]) -> User:
    sub = profile.get("sub") or claims.get("sub")
    tenant_id = claims.get("tid")
    email_raw = profile.get("email") or claims.get("email") or claims.get("preferred_username")
    if not sub:
        raise MicrosoftOAuthError("oauth_error")
    if not email_raw or "@" not in str(email_raw):
        raise MicrosoftOAuthError("email_missing")
    email = normalize_email(str(email_raw))
    # Namespace the subject by tenant: ``sub`` is only unique per tenant.
    stable_sub = f"{tenant_id or 'unknown'}:{sub}"

    user = db.query(User).filter(User.microsoft_sub == stable_sub).first()
    if user is None:
        existing = get_user_by_email(db, email)
        if existing is not None:
            if tenant_id != CONSUMER_TENANT_ID:
                # Work/school directories let their admins set the email
                # claim to any address, so it cannot prove ownership of an
                # existing account here.
                raise MicrosoftOAuthError("account_exists")
            existing.microsoft_sub = stable_sub
            user = existing
        else:
            from .disposable_email import is_disposable_domain

            if is_disposable_domain(email):
                raise MicrosoftOAuthError("disposable_email")
            from .site_content_service import registration_open

            if not registration_open(db):
                raise MicrosoftOAuthError("registration_closed")
            user = User(email=email, provider="microsoft", microsoft_sub=stable_sub)
            name = profile.get("name") or claims.get("name")
            if name:
                user.name = strip_all_html(str(name))[:150]
            user.username = email.split("@")[0][:150]
            if tenant_id == CONSUMER_TENANT_ID:
                from .auth_service import mark_email_verified

                mark_email_verified(user)
            db.add(user)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        user = db.query(User).filter(User.microsoft_sub == stable_sub).first()
        if user is None:
            raise MicrosoftOAuthError("oauth_error")
    db.refresh(user)
    return user
