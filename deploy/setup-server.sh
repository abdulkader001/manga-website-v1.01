#!/bin/bash
set -euo pipefail

echo "🔧 Updating system..."
apt-get update && apt-get upgrade -y

echo "🐳 Installing Docker and Docker Compose..."
apt-get install -y docker.io docker-compose-plugin curl fail2ban
systemctl enable docker
systemctl start docker

echo "📂 Setting up project directory..."
mkdir -p /var/www/manga/logs
cd /var/www/manga

# ------------------------------
# Environment file
# ------------------------------
if [ ! -f /var/www/manga/.env ]; then
  echo "⚠️ Missing /var/www/manga/.env."
  if [ -f /var/www/manga/.env.example ]; then
    echo "   Copy the template and fill the placeholder values (e.g. <generate-…>) before starting services:"
    echo "     cp .env.example .env"
    echo "     cp backend_fastapi/.env.example backend_fastapi/.env"
    echo "     cp frontend/.env.example frontend/.env.local"
  else
    echo "   Create one manually following the secret checklist in README.md#secret-management-and-rotation."
  fi
  echo "   Aborting setup so secrets can be provisioned safely."
  exit 1
else
   echo "🔑 Found existing .env. Review the secrets and rotate them manually per README.md#secret-management-and-rotation."
fi

# ------------------------------
# Systemd service for docker compose
# ------------------------------
echo "⚙️ Installing systemd service..."
cat <<EOF > /etc/systemd/system/manga-compose.service
[Unit]
Description=Manga Website (Docker Compose)
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/var/www/manga
ExecStart=/usr/bin/docker compose --env-file /var/www/manga/.env up -d
ExecStop=/usr/bin/docker compose --env-file /var/www/manga/.env down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable manga-compose
systemctl start manga-compose

# ------------------------------
# SSH hardening
# ------------------------------
echo "🔒 Hardening SSH..."
SSHD_CFG="/etc/ssh/sshd_config"
sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin no/' "$SSHD_CFG"
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' "$SSHD_CFG"
sed -i 's/^#\?ChallengeResponseAuthentication .*/ChallengeResponseAuthentication no/' "$SSHD_CFG"
sed -i 's/^#\?UsePAM .*/UsePAM yes/' "$SSHD_CFG"
systemctl restart ssh || systemctl restart sshd

# ------------------------------
# Fail2ban setup
# ------------------------------
echo "🛡️ Configuring fail2ban..."
cat >/etc/fail2ban/jail.d/sshd.local <<'JAIL'
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 5
findtime = 10m
bantime = 24h
JAIL
systemctl enable --now fail2ban

# ------------------------------
# Firewall
# ------------------------------
if command -v ufw >/dev/null 2>&1; then
  echo "🔒 Configuring firewall (UFW)..."
  ufw allow OpenSSH
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
fi

echo "🚀 Setup complete. Your site should be available at https://manga.example.com/"
