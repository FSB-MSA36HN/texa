# Oracle Cloud demo deployment

This deployment is intended for one Oracle Cloud Always Free VM. It keeps the public demo small:

- `postgres`: private database with a persistent Docker volume;
- `api`: Texa FastAPI service;
- `web`: built React frontend and Nginx reverse proxy;
- Airflow is intentionally excluded from the public runtime. Run ETL before the demo and seed PostgreSQL once.

## 1. Create the VM

In Oracle Cloud Console, create an Always Free eligible `VM.Standard.A1.Flex` instance in your home region. Use Ubuntu 22.04/24.04 ARM64, assign a public IPv4 address, select 2 OCPUs and 12 GB RAM if the quota is available, and save the SSH private key. Add inbound TCP rules for ports `22` and `80` in the VCN security list. Do not expose PostgreSQL publicly.

Oracle documents that the Always Free A1 allowance is equivalent to 2 OCPUs and 12 GB RAM for all tenancies; capacity can be temporarily unavailable in a region.

SSH into the VM, then install Docker Engine and Compose with the repository script:

```bash
ssh -i <private-key> ubuntu@<VM_PUBLIC_IP>

# On the VM, after cloning the repository:
git clone https://github.com/thanhhai12/texa.git texa
cd texa
./deploy/oracle/bootstrap_ubuntu.sh
exit
ssh -i <private-key> ubuntu@<VM_PUBLIC_IP>
```

The script follows Docker's official apt-repository installation and enables the host firewall. OCI's VCN security list must also allow TCP 22 and 80. Then create the deployment secrets:

```bash
cd ~/texa
cp .env.demo.example .env.demo
chmod 600 .env.demo
```

Fill `.env.demo` with a long database password, a random `TEXA_ADMIN_TOKEN`, `OPENAI_API_KEY`, `TEXA_BASE_URL=https://llmproxy.inwave.vn/v1`, and `TEXA_DEFAULT_MODEL=gpt-6-luna`. Keep the file out of git.

## 2. Load the demo data once

The runtime compose file initializes the schema. The ETL profile downloads the two public source datasets, loads both marts and refreshes metadata. Run it once before opening the demo:

```bash
./deploy/oracle/seed_data.sh
```

The script starts PostgreSQL, runs the one-shot ETL container, starts API/frontend, and verifies that both `cosmetics_shop` and `olist_marketplace` appear in `/api/bootstrap`. The database volume and downloaded landing files are persistent.

If the data is already loaded, skip this step and start only the demo:

```bash
./deploy/oracle/deploy.sh
```

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
