# Texa research benchmark v4 — real data, independent oracle

Replaces the weakest parts of v3 for the single-question suite. It is still an unsealed candidate until two
independent humans have reviewed it (`REVIEW_GUIDE.md`, `AUDIT_A.csv`, `AUDIT_B.csv`); its score must be described as
exploratory.

## What changed from v3

| Weakness in v3 | v4 |
|---|---|
| Gold SQL and its "oracle" written by one author from one spec (`research_v3/generate.py`) | Expected tables come from `backend/eval/oracle_csv.py`: DuckDB on the raw CSV files, definitions in `GLOSSARY.md`; shares no code with the mart, catalog or v3 |
| ~120-row hand-built fixtures | Real data: Cosmetics Shop (6,200 events) and Olist (99,441 orders, 609,800 event rows) loaded by the production ETL |
| 164/200 test cases shared a SQL template with dev; 11 families | Family = (source, metric, shape); every family is wholly dev or test (96 families, 0 overlap) |
| 20 empty and 10 `[[0]]` golds; many repeated tables | Empty/all-zero gold rejected; all 300 result tables distinct |
| Nothing checked that the answer could differ under a wrong reading | Each gold must differ from two wrong readings (sibling metric, all-time scope) |
| No human review | Blind two-reviewer sheets with agreement statistics (kappa, Wilson); not yet filled in |

## How the gold is verified

`python backend/eval/validate_research_v4.py --dsn <warehouse>` checks, for all 300 cases: stored table = fresh oracle
table; gold SQL on the ETL warehouse = oracle table; dev/test families disjoint; unique ids, questions, SQL and tables.
With `--load-world` it first replays `worlds/real.sql` (see `export_world.py`) into `texa_benchmark`.
`backend/tests/test_oracle_csv.py` hand-computes the definitions on a tiny dataset and checks metamorphic relations
(windows add up, breakdowns sum to the total, filters give subsets, buyers <= purchases <= events) on the real files.

## Comparison and scoring

Scoring is by result table, never by SQL text: `benchmark.results_equal` compares complete tables (same column count
and order; aliases ignored; rows as a multiset, or in order for top-k; numbers within 1e-6). Systems and baselines are
those of `run_accuracy_study.py` (baseline ladder: B0 schema only; B0R + verified examples; B0G + the same business definitions Texa receives, as plain text; B0GR = B0G plus one SQL repair; then the Texa variants).

Run: `python backend/eval/run_research_matrix.py --dataset-dir data/benchmark/research_v4 --worlds real --suites single --variants ...`
after `python data/benchmark/research_v4/export_world.py`.

## Known limits

- Questions are templated (three phrasings per shape, two languages); family-disjointness removes shared phenomena, not
  shared sentence shapes. Human paraphrases are the next step.
- Cosmetics Shop has exactly 100 events per day, so "events on one day" cannot be tested there (dropped by the gates).
- Gold encodes the glossary's conventions, e.g. Olist lifecycle events form a NULL category group, and Olist purchases
  include canceled orders. Reviewers are asked to challenge these.
- Only the single-question suite exists in v4; clarification, conversation and unsupported suites remain v3.
