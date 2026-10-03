"""Set (or clear) the website domain from the server, without logging in.

For the day the old domain is gone and nobody can reach the admin panel: run
this on the server, and the site's address, allowed origins, e-mail login
links and sign-in callbacks all follow the new domain.

    docker compose exec backend python -m backend_fastapi.scripts.set_site_domain new-domain.com
    docker compose exec backend python -m backend_fastapi.scripts.set_site_domain --clear

It writes the same encrypted vault row the admin panel does, so the panel shows
the change. Running processes pick it up within ~30 seconds (or on restart).
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("domain", nargs="?", help="new public domain, e.g. example.com")
    parser.add_argument("--clear", action="store_true", help="remove the vault domain and fall back to .env")
    args = parser.parse_args(argv)
    if bool(args.domain) == bool(args.clear):
        parser.error("give a domain, or --clear (not both)")

    from ..app.core.db import SessionLocal
    from ..app.services import secret_vault as vault
    from ..app.vault_keys import derived_from_domain

    with SessionLocal() as db:
        try:
            if args.clear:
                vault.remove(db, "SITE_DOMAIN")
                print("Vault domain removed; the site address comes from .env again.")
                return 0
            domain = vault.store(db, "SITE_DOMAIN", args.domain, actor_id=None)
        except vault.VaultError as exc:
            print(f"Refused: {exc}", file=sys.stderr)
            return 2
        except vault.VaultUnavailable as exc:
            print(f"Cannot write the vault: {exc}", file=sys.stderr)
            return 3
    print(f"Site domain is now {domain}. Addresses derived from it:")
    for key, value in derived_from_domain(domain).items():
        print(f"  {key} = {value}")
    print("\nNext: point DNS at this server and make sure HTTPS works for the new domain (GUIDE.md, \"HTTPS with Caddy\").")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
