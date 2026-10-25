#!/usr/bin/env bash
# One-time server preparation for a fresh Hostinger VPS (Ubuntu 22.04 / 24.04).
# Covers guide Steps 8 (update), 9 (Docker + Git), swap, Nginx install, Certbot install and firewall.
# Usage (on the VPS):   sudo bash deploy/setup-vps.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then echo "Run with sudo: sudo bash $0"; exit 1; fi
TARGET_USER="${SUDO_USER:-root}"

echo "==> Updating system"
apt update && apt upgrade -y

echo "==> Installing Git, Nginx, Certbot"
apt install -y git curl nginx certbot python3-certbot-nginx ufw

if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker (official convenience script)"
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  sh /tmp/get-docker.sh
fi
usermod -aG docker "$TARGET_USER" || true
systemctl enable --now docker
systemctl enable --now nginx

# Swap prevents "Killed" during the frontend build / embedding model download on small plans
if ! swapon --show | grep -q /swapfile; then
  echo "==> Adding 2 GB swap"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Firewall: SSH first, then Nginx (80/443)"
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
ufw status

echo
docker --version
docker compose version
git --version
echo
echo "Done. Log out and SSH back in so '$TARGET_USER' can run docker without sudo."
echo "Note: Docker-published ports bypass ufw. Also open/close ports in Hostinger hPanel > VPS > Firewall."
