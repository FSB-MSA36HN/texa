# Clarification benchmark revision 1

This is an append-only correction to the clarification experiment in
data/benchmark/research_v3. The prior run remains intact and its results are
not relabeled or overwritten.

The prior 15 metric ambiguity pairs asked about “customers.” That wording is
not a valid ambiguity in the current catalog: customer/person-count wording
maps to users. Revision 1 replaces those pairs with “sales” / “doanh số,”
which can reasonably mean either purchase revenue or a count of purchase
events/item lines. Each ambiguous prompt is paired with an explicit control,
and the two interpretations produce different result tables in the fixture.

The 15 missing-period pairs are preserved with the same questions, intent,
gold SQL, and expected results. They now include source_id, language, and
ui_scope: [source_id]. The selected source is supplied explicitly to Texa, so
this clarification suite does not score source guessing. The reported results
compare Texa with its ablations. Baseline is evaluated only on single questions;
no Baseline result is claimed for this clarification suite.

interactions.yaml contains 180 physical rows: the same 60 logical cases are
materialized once for each fixture world. The evaluator selects 60 rows per
world and uses that world's expected table. This prevents the perturbed
fixtures from being scored against base-world results.

The copied fixture SQL is in worlds/. gold_oracle.py and generate.py produce
expected SQL and tables without the product compiler or an LLM. Gold
generation imports the retained source-row helper at
data/benchmark/challenge_v1/generate_candidate.py; the copied fixture SQL
and their provenance are recorded in manifest.yaml.

This remains a candidate dataset. The terms “sales” and “doanh số” still need
independent human review to confirm both interpretations are natural for each
source and that the system should ask a clarification rather than select a
default. No model run or PostgreSQL execution is performed by the generator.

Execution amendment before paid runs: 60 physical model-test records on the base world; all three independent gold tables remain attached to each case and are validated offline. Counterexample worlds are not counted as extra questions or model repeats. This limits spend within the existing budget.
