#!/usr/bin/env bash
# One-time server preparation for a Hostinger VPS (Ubuntu 22.04 / 24.04).
# Usage (on the VPS, from the project folder):   sudo bash deploy/setup-vps.sh
#
# - Updates the system, installs Git and Docker (if missing), adds 2 GB swap, enables ufw.
# - If Traefik already owns ports 80/443 (Hostinger Docker template), it does NOT install
#   Nginx/Certbot; Traefik handles HTTPS. It also restarts Traefik after a Docker upgrade
#   (otherwise Traefik keeps a dead docker.sock and serves "404 page not found").
# - On a clean server with nothing on port 80, it installs Nginx + Certbot instead
#   (use deploy/nginx-site.conf, see README "Option B").
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then echo "Run with sudo: sudo bash $0"; exit 1; fi
TARGET_USER="${SUDO_USER:-root}"
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a

echo "==> Updating system"
apt update && apt upgrade -y

echo "==> Installing Git, curl, ufw"
apt install -y git curl ufw

if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker (official convenience script)"
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  sh /tmp/get-docker.sh
fi
usermod -aG docker "$TARGET_USER" || true
systemctl enable --now docker

# ---- Reverse proxy: reuse Traefik if present, otherwise install Nginx + Certbot ----
TRAEFIK=$(docker ps --filter "ancestor=traefik" --format '{{.Names}}' | head -1 || true)
[ -z "$TRAEFIK" ] && TRAEFIK=$(docker ps --format '{{.Names}} {{.Image}}' | awk '$2 ~ /traefik/ {print $1; exit}' || true)

if [ -n "$TRAEFIK" ]; then
  echo "==> Traefik found ($TRAEFIK): using it for HTTPS, skipping Nginx/Certbot"
  if systemctl list-unit-files nginx.service >/dev/null 2>&1; then
    systemctl disable --now nginx 2>/dev/null || true
  fi
  echo "==> Restarting Traefik so it reconnects to the (possibly upgraded) Docker engine"
  docker restart "$TRAEFIK" >/dev/null
  echo "    Entrypoints / cert resolver configured in Traefik:"
  docker inspect "$TRAEFIK" --format '{{json .Config.Cmd}}' | tr ',' '\n' | grep -E 'entrypoints\.[a-z]+\.address|certificatesresolvers\.[a-z]+\.acme\.email' || true
  echo "    deploy/docker-compose.traefik.yml expects entrypoint 'websecure' and resolver 'letsencrypt'."
else
  echo "==> No Traefik found: installing Nginx + Certbot"
  apt install -y nginx certbot python3-certbot-nginx
  systemctl enable --now nginx
fi

# Swap prevents "Killed" during the frontend build / embedding model download on small plans
if ! swapon --show | grep -q /swapfile; then
  echo "==> Adding 2 GB swap"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Firewall: SSH first, then HTTP/HTTPS"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status

echo
docker --version
docker compose version
git --version
echo
if [ -f /var/run/reboot-required ]; then
  echo "NOTE: a reboot is required (kernel update). Run 'reboot' after deploying; containers restart automatically."
fi
echo "Done. Next: create backend/.env and the root .env (see README, Part 2)."
echo "Reminder: Docker-published ports bypass ufw. Also restrict ports in Hostinger hPanel > VPS > Firewall."
