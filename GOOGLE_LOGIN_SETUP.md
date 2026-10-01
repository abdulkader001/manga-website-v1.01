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

Your Gmail alone never makes an account admin, so a stolen inbox can't either.
The owner becomes admin once, through the one-time Admin sign-in, using the
same Gmail address: follow Steps 6-7 of your install guide in
[`guide/`](guide/README.md). After that, **Continue with Google** with that
Gmail signs you into the admin account, and admin pages ask for your
authenticator code.

## Step 4 - Restart and sign in

1. Load the new `.env`: `docker compose up -d --force-recreate` (a plain `restart` keeps the old settings). Without Docker, restart the backend.
2. Check `http://localhost:8000/api/auth/options`: the `providers` list should now include `"google"`.
3. Go to `http://localhost:8080/login`, click **Continue with Google**, pick the Gmail you added as test user.

## Troubleshooting

- `redirect_uri_mismatch`: the URI in Google Console differs from `GOOGLE_OAUTH_REDIRECT_URI`.
- `access_denied` / "app not verified": add your Gmail under *Test users*.
- Back on `/login?magic=oauth_error`: wrong client secret, or cookies blocked (check `FORCE_HTTPS_REDIRECTS=false` on HTTP).
- Logged in but not admin: do the one-time Admin sign-in first (Step 3), with the same Gmail you use for Google.
- Magic link (optional later): set `EMAIL_BACKEND=smtp` plus `SMTP_HOST/PORT/USERNAME/PASSWORD` (e.g. Gmail app password) and run the Celery worker.
