# Synthetic event benchmark pilot

See [the evaluation status and measured-model results](../../docs/EVALUATION.md). These pilot/v2/ablation datasets are synthetic event fixtures, not Olist data; their accuracy must not be described as accuracy measured on Olist. The configured product scope is Cosmetics + Olist, one source, eight metrics, and nested scalar paths up to two keys.

The expanded [v2 dataset](v2/README.md) contains 104 single-turn cases, 12 dialogues and a richer 96-event fixture. Select it explicitly with `--dataset-dir ../data/benchmark/v2` from `backend`; default commands below preserve pilot regression behavior.

This pilot contains 24 single-turn questions (12 dev, 12 test), six annotated dialogue scenarios, and a deterministic 12-row event fixture. It exercises evaluator behavior and elementary event/nested-path distinctions; it is not evidence of broad product accuracy or a substitute for a larger held-out evaluation.

The fixture uses the project's fixed `analytics.event_activity` table and one `event_benchmark` partition. Load it only into an isolated database named `texa_benchmark` after applying the normal project database bootstrap:

```sh
cd backend
uv run python eval/setup_benchmark.py --initialize --dsn 'postgresql://benchmark_admin:...@localhost:5432/texa_benchmark'
```

Use a non-superuser read-only role for query execution and set `TEXA_BENCHMARK_DSN` to that role's connection string. The direct baseline uses the configured provider through the existing LLM API and incurs normal model usage/cost. No live model call is made by setup or tests.

```sh
cd backend
TEXA_BENCHMARK_DSN='postgresql://benchmark_reader:...@localhost:5432/texa_benchmark' \
  uv run python eval/run_benchmark.py --split dev --model MODEL --method direct
```

`--method texa` runs the existing conversational QuerySpec/compiler flow on the same questions. For that mode, configure the app and warehouse DSNs to this isolated database as well, and publish a catalog that includes `event_benchmark`. The runner appends raw SQL/status/result records to JSONL. Keep test data out of prompt tuning; evaluate dev first. Test runs are explicit and may make provider calls.

The result comparator checks output columns, NULLs, duplicate rows, unordered row multisets, and numeric tolerance; cases marked `ordered` preserve rank order. Queries run in read-only transactions with timeouts, a row cap, and a database-name guard. The role itself must remain non-superuser and read-only.

Gold validation ran against the isolated local PostgreSQL **16.2** fixture: 12/12 dev gold queries matched their separately annotated result rows, and 12/12 test gold queries matched. This checks the frozen SQL, expected columns/rows, and fixture; it is not an LLM or Texa accuracy result. The project container targets PostgreSQL 17, so the runner records the actual server version on each run.

The `dev_checkout_sum` case directly tests numeric extraction from `ep.checkout.amount`; that path is not a supported metric in the current Texa catalog. A Texa run may refuse it under the present contract; report coverage/refusal separately from the direct SQL baseline. Live direct, Texa, dialogue, and memory-ablation runs have not been made in this pilot verification.

## Rollouts and paired runs

Set app/reader DSNs to the isolated database and publish the product catalog before Texa runs. SQL gold can be verified without a model:

```sh
uv run python eval/run_benchmark.py --method gold --split dev
uv run python eval/run_benchmark.py --method gold --split test
uv run texa catalog publish ../catalog/product_events.yaml
```

These commands make provider calls and should use a selected model. Direct and Texa receive the same schema, metric definitions and output-alias contract. Run each repeat to a different output file; select model/settings on dev, then freeze them before test.

```sh
uv run python eval/run_benchmark.py --method direct --split dev --model MODEL --dialogues --output eval/results/direct-1.jsonl
uv run python eval/run_benchmark.py --method texa --split dev --model MODEL --dialogues --memory-mode window6 --output eval/results/window6-1.jsonl
uv run python eval/run_benchmark.py --method texa --split dev --model MODEL --dialogues --memory-mode structured --output eval/results/structured-1.jsonl
uv run python eval/run_benchmark.py --compare-results eval/results/window6-1.jsonl eval/results/structured-1.jsonl
```

Comparison requires exactly the same case/dialogue IDs in each file. It resamples whole scenario-family clusters (single turn) or whole dialogues. The tiny pilot gives weak statistical evidence; confidence intervals must not be presented as broad generalization.

The standalone cases are split by disjoint scenario families. Dialogues are a diagnostic suite with overlapping query primitives across dev/test, **not** proof of unseen-template generalization. The split and annotations were corrected and frozen before any live model run.

For breakdowns the common contract includes all dimension values observed after question filters, including zero qualifying events. Gold uses conditional aggregates for this behavior. All ordinary breakdowns are unordered; rank order must be requested explicitly before an ordered comparator is used. The single-turn runner reports both full workload and `in_scope` counts; the checkout diagnostic is outside the current eight-metric product scope.

Gold SQL has also been executed for all 22 answer-bearing dialogue turns. Unlike single-turn cases, dialogue gold currently lacks independently annotated literal result tables; executing those queries proves validity, not that their business interpretation is correct. Independent review remains required.

## Component ablation study

The versioned `ablation_v1` suite isolates memory and clarification, with a separate 50-day fixture. See [run instructions](../../backend/eval/ABLATION_README.md). The new runner defaults to dry-run; live test requires an explicit model, call budget, and frozen protocol. The pilot and v2 remain unchanged. Gold verification and scripted tests are not measured model accuracy.
