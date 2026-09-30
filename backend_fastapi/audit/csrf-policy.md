# CSRF Token Policy

- CSRF protection is a **double-submit cookie**, implemented entirely in
  `backend_fastapi/app/utils/csrf_middleware.py` and registered at
  `backend_fastapi/app/bootstrap/middleware.py:302`. No user record is involved.
- On any safe request (`GET`/`HEAD`/`OPTIONS`/`TRACE`) arriving without a
  `csrf_token` cookie, the middleware seeds one with `secrets.token_urlsafe(32)`.
  The cookie is deliberately **not** httponly — client JS must read it to echo it
  back — and is `samesite=lax`, `secure` when HTTPS redirects are enforced
  (`csrf_middleware.py:65-76`).
- On any state-changing request (`POST`/`PUT`/`DELETE`/`PATCH`) that authenticates
  **via the `access_token_cookie`**, the `x-csrf-token` header must be present and
  equal to the `csrf_token` cookie under `secrets.compare_digest`. Otherwise the
  request is rejected with `403 {"detail": "CSRF validation failed"}`
  (`csrf_middleware.py:41-58`).
- Requests authenticating with an `Authorization` bearer header are **exempt** —
  browsers do not attach bearer tokens automatically, so they carry no CSRF risk
  (`csrf_middleware.py:31-36`).
- Why this is safe: an attacker's cross-site request cannot read the victim's
  `csrf_token` cookie (same-origin policy) and so cannot set a matching header.
  Safety comes from the header-vs-cookie comparison — **not** from the token being
  secret in the response body. An earlier implementation checked only that *some*
  header was present and accepted any attacker-supplied value; see the module
  docstring at `csrf_middleware.py:3-7`.

> **Historical note.** An earlier version of this file described CSRF tokens being
> issued into a `user.csrf_token` database column at login. That column has never
> existed on the `User` model (`app/models/user.py`), and the write at
> `app/services/auth_service.py:294-296` is guarded by `hasattr(user, "csrf_token")`
> and therefore never executes. A fresh UUID *is* still generated at magic-link
> consumption and returned in the login payload (`auth_service.py:293,309`), and the
> frontend mirrors it to `localStorage` (`AuthContext.js:67-69`) — but the enforcement
> middleware never reads it, and `api.js:57-70` prefers the cookie, so in normal
> browser use it is never even sent. It is vestigial; do not treat it as the
> mechanism. See `docs/master-audit/pre-part-2-doc-verification.md`.
