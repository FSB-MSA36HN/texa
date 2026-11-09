# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Texa: a text-to-analytics app for non-SQL PMs/POs. Users ask e-commerce questions (Vietnamese or English); the system answers from PostgreSQL. Scope, supported metrics and benchmark evidence are in [docs/PRODUCT_SCOPE.md](docs/PRODUCT_SCOPE.md) (written in Vietnamese; much of the docs, comments and `run.sh` output are too).

Components: `backend/` (FastAPI + Python ≥3.12, managed with `uv`), `web/` (React 19 + Vite + Tailwind 4), `pipeline/` (ETL + Airflow DAGs), `catalog/` (semantic YAML), `data/` (landing data + benchmark datasets), `docs/`.

## Commands

Everything at once (Postgres + Airflow in Docker, API on :18000, web on :15173; Ctrl-C or `./run.sh stop` tears down):
```
./run.sh
```
Ports are non-default: Postgres 15432, API 18000, web 15173, Airflow 18080.

Backend (run from `backend/`):
```
uv sync
uv run uvicorn texa.main:app --port 18000
uv run pytest                                  # all tests (testpaths = tests)
uv run pytest tests/test_flow.py::test_name    # single test
uv run texa catalog publish|check|coverage     # catalog CLI
uv run texa query spec.json                    # run a QuerySpec without the LLM
uv run texa ask "question" [--model M] [--answers '{"source":["olist_marketplace"]}']
```
Web (run from `web/`): `npm run dev`, `npm run build` (tsc + vite), `npm run lint`. E2E: `npm run test:e2e` requires `TEXA_E2E_TEST_DSN=1` and an isolated benchmark Postgres on port 15433 (the Playwright config refuses to run otherwise; it starts `tests.e2e_server` on :18001).

ETL (from `pipeline/`): `python -m texa_etl.run <source_id> [step ...]` with sources `cosmetics_shop`, `olist_marketplace`, plus `fx_rates`. Steps such as `load_mart`, `refresh_metadata`. Revenue in USD needs `fx_rates` loaded and stores reloaded (run.sh prints the exact commands if missing).

Config comes from `.env` (copied from `.env.example` by run.sh): `TEXA_SECRET_KEY` (Fernet key encrypting the stored LLM key), optional provider keys, `TEXA_BASE_URL` gateway, concurrency limits, and ablation toggles `TEXA_EXAMPLE_RETRIEVAL`, `TEXA_CONSISTENCY`, `TEXA_EXAMPLE_POLICY`.

## Architecture

**The LLM never writes SQL in the product pipeline.** Flow (see `backend/texa/answer.py` for orchestration, `pipeline.py` for the deterministic half):

question + chosen source → retrieve verified SQL examples (`examples.py`) → LLM proposes intent (`interpret.py`/`intent.py`, with conditional self-consistency in `consistency.py`) → binder/clarification (`clarify.py`) → `QuerySpec` validated against the catalog (`spec.py`) → availability/capability check (`sanity.py`) → Python compiler emits parameterized SQL (`compile.py`) → executed on a **read-only** reader connection (`execute.py`, `db.py`) → facts with provenance (`facts.py`) → LLM insight with placeholder checking (`insight.py`).

Key ideas:
- `QuerySpec` is the single contract between LLM and compiler; `spec.py` validation is the safety boundary. One metric-set per query, one source per query (no cross-source joins).
- The semantic **catalog** (`catalog/product_events.yaml`, the current one; `ecommerce.yaml` is legacy) defines metrics, dimensions, event roles, source aliases, per-source availability and data notes. It is versioned: `texa catalog publish` stores a version in the app DB and the runtime reads the *published* catalog (`catalog.published()`), so edit YAML then republish. Missing field/event means "unavailable", never zero.
- Two DB roles: app owner (writes `app.*`, schema in `backend/texa/schema.sql`) and `texa_reader` (reads `analytics.*` only). Single table `analytics.event_activity` holds event rows from all sources; ETL adapters in `pipeline/` map each raw dataset into it.
- Each question is a "turn" run in a background thread; progress steps stream to the web via SSE (`/api/turns/{id}/stream`). Run registry is in-process, so the API assumes a single worker. Bounded admission for runs/LLM calls is in `runtime_guard.py`.
- Multi-turn context lives in `memory.py`: results referenced by ID and QuerySpec slots inherited/changed/cleared server-side after validation; follow-ups that can't be resolved trigger clarification instead of guessing.
- `llm.py` abstracts Gemini/Anthropic/OpenAI (+ custom gateway); the API key is stored encrypted in the DB and configurable in the UI. `gateway_budget.py` is an optional shared guard.
- API surface is in `backend/texa/main.py` (`/api/questions`, `/api/turns/*`, `/api/conversations/*`, `/api/model-connection`, ...); frontend client in `web/src/api.ts`.

## Evaluation / benchmarks

`backend/eval/` holds runners and reports (golden set, ablation, accuracy study, research v3 matrix, dataset validators); datasets live in `data/benchmark/*` (each with cases/dialogues/fixture SQL/manifest, and gold SQL validated on multiple "worlds"). Results are written to `backend/eval/results/` (gitignored) and `data/benchmark/results/`. `texa/ablation.py` implements the component toggles. `catalog/verified_examples.yaml` is the example bank used for retrieval; `TEXA_EXAMPLE_POLICY` selects `approved` vs `sql_verified`.

## Docs

`docs/` contains the product scope, remediation/accuracy plans, and the final presentation script/deck (the git history is mostly presentation edits). Keep claims in docs consistent with the benchmark report cited in PRODUCT_SCOPE.md.
