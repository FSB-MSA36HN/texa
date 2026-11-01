# Product events benchmark v2

This frozen expansion keeps the original pilot intact. It contains 104 single-turn questions (41 dev / 63 test), 12 annotated dialogues (including 8- and 10-turn retrieval probes), and 96 deterministic synthetic event rows spanning 27 January–2 February 2025. Eight held-out empty-day questions additionally test aggregate zero and NULL behavior on 3 February; nine development examples test compound attribute filters; four test questions exercise deterministic top-k ranking and tie-breaking.

The fixture deliberately includes repeated users and sessions, month-boundary dates, several event types, zero-revenue purchases, missing or explicit-null nested scalar keys, and a category with observed events but no purchases. This category makes zero-revenue/zero-buyer groups testable. Arrays and arbitrary schemas remain outside the product scope. The source is generated from the readable deterministic rules in `generate.py`; `cases.yaml` contains literal expected columns and rows for every single-turn item and `dialogues.yaml` does the same for every answer action. The generator computes references with Python row aggregation and emits SQL from separate declarative query specs; it does not call Texa's query compiler.

Single-turn dev/test labels are disjoint by scenario family. The test set is a **template-family holdout only**: it does not establish generalization to unseen metrics or primitives. Dialogue cases are diagnostic: conversational patterns and query primitives overlap across splits, despite distinct scenario labels, and probe topic noise, clarifications, reference return, and dependencies longer than six turns. The data is synthetic and does not establish production accuracy or user fit. Gold validation proves only that the authored SQL agrees with the separately computed fixture expectations.

To regenerate the checked-in fixture and annotations:

```sh
backend/.venv/bin/python data/benchmark/v2/generate.py
```

Load only into the isolated `texa_benchmark` database. With the dataset-aware runner:

```sh
cd backend
uv run python eval/setup_benchmark.py --initialize --dataset-dir ../data/benchmark/v2 --dsn 'postgresql://.../texa_benchmark'
uv run python eval/run_benchmark.py --dataset-dir ../data/benchmark/v2 --method gold --split dev
uv run python eval/run_benchmark.py --dataset-dir ../data/benchmark/v2 --method gold --split test
uv run python eval/run_benchmark.py --dataset-dir ../data/benchmark/v2 --method gold --dialogues
```

For direct or Texa runs, supply the dedicated read-only benchmark DSN and explicitly select a model. These runs can incur model usage; generating and validating gold data does not call a model. Human product-owner review of business semantics is still needed before using the benchmark as a final claim.

Gold verification on isolated PostgreSQL 16.2: **41/41 dev**, **63/63 test**, and **30/30 answer-bearing dialogue turns** matched the independently computed literal result tables. This checks SQL/results only; clarification, refusal and memory actions still require live rollout evaluation. No model calls were made.

`validation.json` freezes SHA-256 hashes and annotation counts. Run `backend/.venv/bin/python backend/eval/validate_dataset.py data/benchmark/v2` from the project root to inspect integrity. Regeneration does not update the lock automatically; only refresh it with `--write-lock` after reviewing and revalidating changes. Each benchmark run records dataset version and content hashes. Both versions use the same source partition, so loading v2 replaces pilot event rows in the isolated database; reload the pilot before running pilot-specific integration tests.
