# Implementation and verification — 01/11/2026

Branch: `codex/event-conversational-qa`. All project changes and temporary verification artifacts stay under `Final`. No external project was accessed, no application warehouse was modified, and no provider calls were made during verification.

## Commit milestones

| Commit | Milestone |
|---|---|
| `103b3ba` | Persona/scope contract and 8-metric catalog |
| `b3b1215` | Bounded nested fields and source limits |
| `ac42fac` | Persistent structured memory and clarification |
| `83d088f` | Visible metric definitions and query scope |
| `7c94513` | ETL nested metadata and PostgreSQL integration checks |
| `144649c` | SQL evaluator, pilot and baseline/dialogue runners |
| `5789cea` | Active-topic selection and stale-result guards |
| `7c4f9c0` | Explicit top-k semantics and deterministic ties |

The handover documentation is committed after these milestones. The verification PostgreSQL server was stopped after checks; the application was not deployed or started against the user's existing warehouse.

## Implemented

| Plan area | Implementation |
|---|---|
| Scope/persona | Product contract and separate 8-metric `product_events.yaml`; legacy catalog retained for regression. Default path points to the product catalog; existing DBs require an explicit publish. |
| Nested schema/compiler | Catalog-approved object paths under ep/up, at most two keys; explicit numeric declaration for nested numeric aggregations; numeric filtering handles numeric text, missing/null and malformed values. Arrays are excluded. |
| Source limits | Catalog source allowlist and max_sources; source scoping applies to API context and QuerySpec validation. Product queries use one source. |
| Top-k | Explicit requested top-k for one metric/non-time breakdown, with deterministic ties; full-result reruns preserve it independently of resource row caps. |
| Conversation state | Additive memory column migration; successful query slots, topic/result references and provenance persisted. Pending clarification is separate. Replay rebuilds memory after retries, edits and metric switches. |
| Context selection | Structured state with relevant result references; explicit return to older topics; noise does not commit query state. Ambiguous references ask the user to select a result. Context is token bounded and removes whole turns. |
| Metric resolution | Ambiguous metric alternatives ask for selection, including alternatives in the same variant group. User choices rerun deterministic clarification without another interpretation call. |
| Dataset changes | Snapshot/catalog compatibility checks before follow-up, clarification, variant switch and full-result reruns. Metadata refresh changes snapshot identity. Legacy turns without a snapshot remain visible in chat but are excluded from inheritance. |
| Metadata/profile | Nested scalar key discovery at ETL time; low-cardinality value vocabulary uses composed SQL. Discovery samples at most 10,000 rows; rare paths may be absent. No event-table profiling scan per user query. |
| UX | Metric definitions, source/time/filter scope, inherited question and data-version identifier visible without opening SQL. Existing fact-grounded answers retained. |
| Evaluation tools | Independent frozen SQL/results, direct prompting baseline, full-result comparison, dialogue rollout and memory-mode ablation tooling; details in the benchmark README. |

## Verification performed

- Pure unit and scripted-model tests cover state, long history, new topics, clarification and snapshot invalidation.
- Isolated PostgreSQL integration verifies nested SQL, numeric nested filters and a 12-turn conversation with 10 intervening social turns. It asserts persisted slot provenance after reading state back from DB.
- Metadata integration deletes nested vocabulary, refreshes it and checks regenerated paths within one transaction, then rolls back.
- Frontend production build and ESLint pass.
- Final backend run: **93 passed, 19 skipped** with metadata/product integration enabled. The skipped tests require the original two-source warehouse.
- SQL gold verification checks annotated expected results against the fixed fixture. This is evaluator/fixture validation, **not** measured LLM accuracy.

Local integration used PostgreSQL 16.2, installed temporarily under `.runtime` because Docker was not running. Container configuration still targets PostgreSQL 17; repeat DB checks on 17 before reporting version-specific compatibility. Runtime files, downloaded verification binaries and raw result logs are ignored by Git.

Legacy numeric/flow integration tests require both original Cosmetics and Olist warehouses. They skip on the isolated product fixture; they are not counted as passed. New product integration tests run separately with explicit opt-in configuration.

## Reproducing tests

Pure checks (DB integration skips unless explicitly configured):

```sh
backend/.venv/bin/python -m pytest backend/tests/test_units.py backend/tests/test_memory.py backend/tests/test_context_flow.py backend/tests/test_nested.py backend/tests/test_evaluation.py -q
cd web
npm run build
npm run lint
```

To exercise integration, initialize the schemas and fixture in a separate database named `texa_benchmark`, publish `catalog/product_events.yaml`, then set these variables **only for the test process**:

```sh
export TEXA_DB_DSN='postgresql://OWNER@127.0.0.1:PORT/texa_benchmark'
export TEXA_READER_DSN='postgresql://texa_reader:PASSWORD@127.0.0.1:PORT/texa_benchmark'
export TEXA_METADATA_TEST_DSN="$TEXA_DB_DSN"
export TEXA_PRODUCT_TEST_DSN=1
backend/.venv/bin/python -m pytest backend/tests -q
```

Do not point these tests at a normal application database. They use the project-owned benchmark partition and temporary application conversations.

## Still requiring empirical or manual work

1. Benchmark v2 now contains 104 single-turn cases (41 dev / 63 test), 12 diagnostic dialogues and a deterministic 96-event fixture; the original 24-case pilot remains available. All 104 single-turn and 30 answer-bearing dialogue gold queries match independent Python result tables on PostgreSQL 16.2. Annotation hashes are frozen. This is smaller than the initially proposed 120-case/24-dialogue target; the cases are generated from bounded templates and need external/human validation before research conclusions. See `data/benchmark/v2/README.md`.
2. Persona walkthroughs and independent gold review have not been performed. The persona and benchmark validity remain hypotheses with documented limits.
3. No real-model B0/B1/S1 runs or cost/latency comparison has been performed. Model credentials and a chosen model are required for the provided live commands. No 90% accuracy claim is made.
4. Retrieval currently uses deterministic cues and lexical topic matching. The tests validate selected behaviors, not general conversational understanding. Evaluate and tune only on dev.
5. Arrays, DuckDB, AST-based free SQL generation and self-correction remain optional P1 scope, intentionally excluded from this implementation.

## Dataset v2 expansion

Added inclusive cross-month windows, independent dimension assignments, nested missing/JSON-null fields, no-purchase groups, zero-revenue purchases, empty populations, compound filters and deterministic top-k. Dialogues cover slot correction, social noise, topic changes and return after 7/9 intervening turn positions. Each answer carries literal expected results; clarification/refusal actions are scored only in live rollouts, not counted in SQL gold accuracy.

The runner selects versioned data/manifest together, records content hashes and validates dialogue gold without provider calls. The integrity checker verifies IDs, result shapes, split labels, duplicate cross-split SQL and valid prior-turn references. Dialogue patterns overlap across splits and remain diagnostic; do not claim unseen conversational-family generalization.

Expansion verification: focused evaluator/dataset tests **18 passed**; default full backend tests **93 passed, 24 skipped** (DB opt-ins absent). No frontend changes or model calls. Full backend verification with metadata/product integration enabled against the restored pilot: **99 passed, 19 skipped**. The remaining skips require the original two-source warehouse.
