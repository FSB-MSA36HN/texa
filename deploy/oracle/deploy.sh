#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

if [[ ! -f .env.demo ]]; then
  echo "Missing .env.demo. Copy .env.demo.example, fill secrets, then run again." >&2
  exit 1
fi

sudo docker compose --env-file .env.demo -f docker-compose.demo.yml up -d --build
sudo docker compose --env-file .env.demo -f docker-compose.demo.yml ps
printf '\nTexa is available at: http://%s\n' "$(hostname -I | awk '{print $1}')"
printf 'Health check: http://%s/api/health\n' "$(hostname -I | awk '{print $1}')"
