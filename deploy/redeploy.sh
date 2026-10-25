#!/usr/bin/env bash
# The redeploy loop (Part 3 of the guide). Run on the VPS from the project folder:
#   bash deploy/redeploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
git pull
docker compose up --build -d
docker image prune -f >/dev/null
docker ps
