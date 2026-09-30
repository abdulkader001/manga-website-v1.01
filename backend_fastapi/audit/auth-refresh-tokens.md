# Refresh Token Lifetime, Rotation, and Revocation

## Lifetime

Refresh-token lifetime comes from `auth_service.get_session_expiry_days(db)` — read
from `system_settings.session_expiry_days`, clamped to 1–30 days, **default 14**. The
`REFRESH_TOKEN_EXPIRE_DAYS = 7` constant in `backend_fastapi/app/core/security.py` is
only a fallback for callers that supply no value, which the live refresh path never
does. Expect 14 days by default.

Both auth cookies carry a `Max-Age` matching their token's real TTL, so the
admin-configured session length applies to browser-persisted sessions too.

## Rotation

`POST /api/v1/auth/refresh` mints a new access **and** refresh token, and
**consumes the refresh token it was given** — that token is added to the
`revoked_tokens` denylist and will not work again.

The refresh token is read from the `refresh_token_cookie` when no JSON body is
supplied. An explicit body is still accepted for non-browser clients.

### Reuse detection

Presenting an already-consumed refresh token means one of two things: a replay, or
the legitimate client and an attacker both hold the same token and one got there
first. There is no way to tell which, so the response is to revoke **every** session
on that account (`sessions_revoked_before`) and log
`refresh_token_reuse_detected`. Both parties have to log in again.

This is what limits the damage from a stolen refresh token: its useful life is one
round trip, and using it announces the theft.

## Revocation

Access and refresh tokens are stateless JWTs — signed, self-contained, and valid
until they expire. Two mechanisms make them revocable:

| Mechanism | Table / column | Used by | Cost |
|---|---|---|---|
| Per-token denylist | `revoked_tokens.jti` | logout, refresh rotation | one indexed lookup per authenticated request |
| Per-account cutoff | `users.sessions_revoked_before` | sign out everywhere, admin revocation | free — the users row is already loaded |

Every token carries a unique `jti`, plus an `iat_ms` claim (millisecond-resolution
issue time). `iat_ms` exists because the standard `iat` is whole seconds, which
cannot distinguish "minted just before a sign-out-everywhere" from "minted just
after" — at second resolution the check either refuses the user's immediate
re-login or lets a token minted in the revocation second survive.

### Entry points

- `POST /api/v1/auth/logout` — revokes the access and refresh tokens presented with
  the request, then clears the cookies.
- `POST /api/v1/auth/logout?all=true` — additionally sets the account's cutoff,
  ending every other session. Surfaced in the UI as **Settings → Security → Sign out
  of all devices**.
- `POST /api/v1/admin/users/{id}/revoke-sessions` — administrative revocation, gated
  on the `revoke_user_sessions` permission (admin + secondary by default, SRS 1F.7).
  Use when an account is believed compromised: unlike deactivating the account, the
  user can log in again immediately; only the existing sessions end.
- Deactivating an account (`is_active = False`) still revokes its sessions
  indirectly — `_resolve_user` re-reads the user row on every authenticated request.

### Housekeeping

Denylist rows are pointless once the token they name has expired — the signature
check refuses it anyway. `audit_tasks.purge_expired_revoked_tokens` runs daily from
Celery Beat and deletes them, so the table does not grow without bound.

### Tokens issued before this feature existed

They carry no `jti` and cannot be individually revoked; they expire on their own.
`sessions_revoked_before` covers them in the meantime, and a token with no `iat` at
all is refused outright once a cutoff is set.
