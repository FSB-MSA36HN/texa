#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

if [[ ! -f .env.demo ]]; then
  echo "Missing .env.demo. Copy .env.demo.example and fill it first." >&2
  exit 1
fi

# Start only PostgreSQL; the ETL profile is a one-shot job and is not kept running.
sudo docker compose --env-file .env.demo -f docker-compose.demo.yml up -d postgres
sudo docker compose --env-file .env.demo -f docker-compose.demo.yml run --rm etl python -m texa_etl.run fx_rates
sudo docker compose --env-file .env.demo -f docker-compose.demo.yml run --rm etl python -m texa_etl.run cosmetics_shop
sudo docker compose --env-file .env.demo -f docker-compose.demo.yml run --rm etl python -m texa_etl.run olist_marketplace

sudo docker compose --env-file .env.demo -f docker-compose.demo.yml up -d api web
printf '\nSeed complete. Checking the public API...\n'
curl --fail --retry 20 --retry-delay 2 http://127.0.0.1/api/bootstrap >/tmp/texa-bootstrap.json
python3 - <<'PY'
import json
p=json.load(open('/tmp/texa-bootstrap.json'))
ids=[x['id'] for x in p.get('sources', [])]
print('sources:', ', '.join(ids) if ids else '<none>')
if not {'cosmetics_shop','olist_marketplace'}.issubset(ids):
    raise SystemExit('Both expected sources are not available in /api/bootstrap')
PY
