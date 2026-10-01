# Google sign-in setup (local, http://localhost:8080)

## Why the other options fail

| Option | Why it fails |
|---|---|
| Magic link | `EMAIL_BACKEND=console` (the default) only *prints* the link in the backend/worker log. The page still says "Sent!", but no email leaves the server. It also needs a Celery worker running. |
| Microsoft | `?error=microsoft_not_configured`: the Microsoft client ID/secret are not set. |
| Google | `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` are empty in `.env.example`, so `/api/auth/google` returns "not configured". |
| Password | Only works for an account that already has a password. |

## Step 1 - Create Google OAuth credentials

1. Open https://console.cloud.google.com/ and select project `manga-website-474002` (or your own).
2. **APIs & Services -> OAuth consent screen**: choose *External*, fill app name and your email, save.
   Under **Test users**, add the Gmail address you will sign in with (required while the app is in "Testing").
3. **APIs & Services -> Credentials -> Create credentials -> OAuth client ID**:
   - Application type: **Web application**
   - Authorized JavaScript origins: `http://localhost:8080`
   - Authorized redirect URIs: `http://localhost:8000/api/auth/google/callback`
     (must match `GOOGLE_OAUTH_REDIRECT_URI` exactly, including port and path)
4. Copy the **Client ID** and **Client secret**.

## Step 2 - Configure the backend

```bash
cp .env.example .env
cp backend_fastapi/.env.example backend_fastapi/.env
```

In `.env` (and `backend_fastapi/.env` if you run uvicorn directly) set:

```
GOOGLE_OAUTH_CLIENT_ID=<client id>
GOOGLE_OAUTH_CLIENT_SECRET=<client secret>
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
FRONTEND_URL=http://localhost:8080
FORCE_HTTPS_REDIRECTS=false   # local plain-HTTP only, otherwise cookies are not stored
```

## Step 3 - Make your Gmail the admin

`MAIN_ADMIN_EMAIL_HASH` holds an Argon2id hash of the admin email (lowercase):

```bash
python -c "import os;from cryptography.hazmat.primitives.kdf.argon2 import Argon2id;print(Argon2id(salt=os.urandom(16),length=32,iterations=3,lanes=4,memory_cost=65536).derive_phc_encoded(b'abdulkaderjaliny702@gmail.com'))"
```

Put the output in `.env` **inside single quotes** (it contains `$`):

```
MAIN_ADMIN_EMAIL_HASH='$argon2id$v=19$...'
MAIN_ADMIN_AUTO_PROMOTE_ENABLED=true
```

After your first successful login, set `MAIN_ADMIN_AUTO_PROMOTE_ENABLED=false` again.

## Step 4 - Restart and sign in

1. Restart the backend (and `docker compose up -d` if you use Docker) so the new env is loaded.
2. Check `http://localhost:8000/api/auth/options`: the `providers` list should now include `"google"`.
3. Go to `http://localhost:8080/login`, click **Continue with Google**, pick the Gmail you added as test user.

## Troubleshooting

- `redirect_uri_mismatch`: the URI in Google Console differs from `GOOGLE_OAUTH_REDIRECT_URI`.
- `access_denied` / "app not verified": add your Gmail under *Test users*.
- Back on `/login?magic=oauth_error`: wrong client secret, or cookies blocked (check `FORCE_HTTPS_REDIRECTS=false` on HTTP).
- Logged in but not admin: the hash was made from a different email/case, or auto-promote is still `false`.
- Magic link (optional later): set `EMAIL_BACKEND=smtp` plus `SMTP_HOST/PORT/USERNAME/PASSWORD` (e.g. Gmail app password) and run the Celery worker.
