#!/usr/bin/env bash
# The redeploy loop. Run on the VPS from the project folder:
#   bash deploy/redeploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "WARNING: root .env missing - Traefik labels will NOT be applied. Run: cp .env.example .env"
fi

git pull
docker compose up --build -d
docker image prune -f >/dev/null
docker compose ps

echo
echo "Health:"
curl -fsS http://127.0.0.1:3000/api/health && echo
