# Encryption key rotation

Two secrets encrypt data in the database. Rotate them when a key may have
leaked, when someone who knew it leaves, or on a schedule.

| Secret | Protects | Rotation variable |
| --- | --- | --- |
| `EMAIL_ENCRYPTION_KEY` | emails, OAuth tokens, admin authenticator secrets | `NEW_KEY,OLD_KEY` in the same variable |
| `INTEGRATIONS_SECRET` | stored provider and user API keys | old value in `INTEGRATIONS_SECRET_PREVIOUS` |

`SECRET_KEY`, `JWT_SECRET_KEY` and `MAGIC_LINK_SECRET` are not covered here:
changing them signs everyone out, which needs no re-encryption.

## Before you start

1. Take a database backup (`backend_fastapi/deployment/backups.md`) and check it
   restores.
2. **Pin the email lookup secret.** Emails are found through a hash that, when
   `EMAIL_HASH_SECRET` is empty, is derived from the email key. If that value
   changed, nobody could log in. Set `EMAIL_HASH_SECRET` to the *current*
   `EMAIL_ENCRYPTION_KEY` value (or, on a new install, any long random string)
   and redeploy. Do this once and never change it afterwards. The app refuses
   to start with several email keys and no `EMAIL_HASH_SECRET`.

## Steps

1. Generate a new key:
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   For the integrations secret any new long random string works.
2. Set the variables and redeploy the API and every worker:
   - `EMAIL_ENCRYPTION_KEY=<new>,<old>`
   - `INTEGRATIONS_SECRET=<new>` and `INTEGRATIONS_SECRET_PREVIOUS=<old>`

   The app now writes with the new keys and still reads old data with the old
   ones. Check that login and the admin API-management page work.
3. Re-encrypt what is stored (safe to repeat, safe to stop):
   `python -m backend_fastapi.scripts.rotate_encryption_key --dry-run`, then
   without `--dry-run`. It prints how many values it rewrote. A non-zero
   `unreadable` count (and exit code 1) means some values could not be read
   with any known key: find out why before going on (they may be old plaintext
   test data, or encrypted with a key you no longer have).
4. When `unreadable` is 0, remove the old keys: `EMAIL_ENCRYPTION_KEY=<new>`,
   clear `INTEGRATIONS_SECRET_PREVIOUS`, and redeploy. Leave `EMAIL_HASH_SECRET`
   as it is.
5. Destroy the old keys and old backups made before step 3 when policy allows;
   those backups can only be read with the old keys.

## If something goes wrong

Put the old keys back in the variables and redeploy: reading works with any key
in the list, so nothing is lost. Restore from the backup only if rows were
damaged.

## Also encrypted with `EMAIL_ENCRYPTION_KEY`

Admins who enrol an authenticator app (`/admin/security`) have their secret
stored under this key. The rotation script covers it. If the key is lost, those
admins can no longer pass the second step: clear the secret directly
(`UPDATE users SET totp_secret = NULL, totp_enabled = false WHERE id = <id>;`)
and let them enrol again. Do this only after checking who is asking.
