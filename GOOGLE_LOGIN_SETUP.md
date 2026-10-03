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

## Step 3 - Make your Gmail the owner

There is no admin password and no admin page. The owner is the first person to
sign in with Google using the e-mail whose hash is in `.env`:

```bash
python backend_fastapi/scripts/make_admin_hash.py --write .env
```

(Docker: the `docker run ...` line in [`TEST_COMPUTER.md` Section 6.2](TEST_COMPUTER.md#62-write-the-owner-line); for a live server, [`GUIDE.md` Section 6](GUIDE.md#6-google-sign-in-and-the-owner-e-mail).)
Type the Gmail you will sign in with. After Step 4, **Continue with Google**
with that Gmail makes your account the owner (Google must say the address is
verified, and the site must not have an owner yet). Open **Admin** next: it asks
you to set up an authenticator app, and every admin page then asks for its code.

## Step 4 - Restart and sign in

1. Load the new `.env`: `docker compose up -d --force-recreate` (a plain `restart` keeps the old settings). Without Docker, restart the backend.
2. Check `http://localhost:8000/api/auth/options`: the `providers` list should now include `"google"`.
3. Go to `http://localhost:8080/login`, click **Continue with Google**, pick the Gmail you added as test user.

## Troubleshooting

- `redirect_uri_mismatch`: the URI in Google Console differs from `GOOGLE_OAUTH_REDIRECT_URI`.
- `access_denied` / "app not verified": add your Gmail under *Test users*.
- Back on `/login?magic=oauth_error`: wrong client secret, or cookies blocked (check `FORCE_HTTPS_REDIRECTS=false` on HTTP).
- Logged in but not owner: `cli_bootstrap admin-status` says why. The `.env` line (Step 3) must be made from exactly the Gmail you sign in with, and the site must not already have an owner.
- Magic link (optional later): set `EMAIL_BACKEND=smtp` plus `SMTP_HOST/PORT/USERNAME/PASSWORD` (e.g. Gmail app password) and run the Celery worker.
