# TLS Certificate Renewal

This directory contains tooling to renew the Manga website TLS certificates via Certbot and systemd.

## Files

- `renew_certificates.sh` – stops nginx if it is running, renews certificates with Certbot, and reloads nginx. Output is appended to `/var/log/manga/renew.log`.
- `manga-certbot.service` – a `oneshot` systemd unit that runs the renewal script.
- `manga-certbot.timer` – systemd timer that triggers the service twice per day.

## Installation

Run the following steps on each production host (adjusting paths if the repository lives somewhere other than `/opt/manga`). The commands assume you are root or using `sudo`:

1. Copy the repository files into place and ensure the renewal script is executable:
   ```bash
   install -m 755 deployment/renew_certificates.sh /opt/manga/deployment/renew_certificates.sh
   install -m 644 deployment/manga-certbot.service /etc/systemd/system/manga-certbot.service
   install -m 644 deployment/manga-certbot.timer /etc/systemd/system/manga-certbot.timer
   ```
2. Reload systemd to pick up the new units:
   ```bash
   systemctl daemon-reload
   ```
3. Enable and start the timer so it runs immediately and on subsequent boots:
   ```bash
   systemctl enable --now manga-certbot.timer
   ```
4. Verify that the timer is scheduled and review the latest run output:
   ```bash
   systemctl list-timers --all | grep manga-certbot
   journalctl -u manga-certbot.service --since "-1 day"
   tail -n 50 /var/log/manga/renew.log
   ```

The timer is configured to execute twice daily (`00:00` and `12:00` server time) with up to a 30 minute randomized delay to avoid hitting Let's Encrypt rate limits when many hosts renew simultaneously.

To manually trigger a renewal run, execute:
```bash
systemctl start manga-certbot.service
```
