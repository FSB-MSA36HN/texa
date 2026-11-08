# Oracle Cloud demo deployment

This deployment is intended for one Oracle Cloud Always Free VM. It keeps the public demo small:

- `postgres`: private database with a persistent Docker volume;
- `api`: Texa FastAPI service;
- `web`: built React frontend and Nginx reverse proxy;
- Airflow is intentionally excluded from the public runtime. Run ETL before the demo and seed PostgreSQL once.

## 1. Create the VM

Create an Ubuntu 22.04/24.04 ARM64 VM in Oracle Cloud Always Free. Open inbound TCP ports `22` and `80` in the Oracle security list and the VM firewall. Do not expose PostgreSQL publicly.

Install Docker Engine and Compose plugin using Docker's official Ubuntu instructions, then clone this repository:

```bash
git clone <repository-url> texa
cd texa
cp .env.demo.example .env.demo
chmod 600 .env.demo
```

Fill `.env.demo` with a long database password, a random `TEXA_ADMIN_TOKEN`, and the LLM gateway key. Keep the file out of git.

## 2. Load the demo data once

The runtime compose file initializes the schema. Load the prepared event fixtures/ETL data before opening the demo to students. The exact ETL commands depend on the available fixture and source files; verify that both `cosmetics_shop` and `olist_marketplace` are present in `/api/bootstrap` before continuing.

The database volume is persistent, so restarting the VM does not delete loaded data.

## 3. Start the demo

```bash
./deploy/oracle/deploy.sh
```

Useful checks:

```bash
docker compose --env-file .env.demo -f docker-compose.demo.yml ps
curl http://127.0.0.1/api/health
curl http://127.0.0.1/api/bootstrap
```

Open `http://<VM_PUBLIC_IP>/` in the browser. The frontend and API share one origin, so no public API port is required.

## 4. Stop/restart without deleting data

```bash
docker compose --env-file .env.demo -f docker-compose.demo.yml stop
docker compose --env-file .env.demo -f docker-compose.demo.yml start
```

Do not use `down -v`; the `pgdata` volume contains the demo database.

## 5. Operational limits

This is a class-demo deployment, not a production SLA. Keep one API worker because Texa keeps active run state in the API process. Limit simultaneous questions, keep the LLM key server-side, and monitor gateway spend. If the VM is under memory pressure, stop ETL/Airflow processes and keep only PostgreSQL, API and web running.
