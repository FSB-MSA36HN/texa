# Ablation study suite v1

See the [canonical evaluation status](../../../docs/EVALUATION.md) and [ablation run instructions](../../../backend/eval/ABLATION_README.md). This fixture is synthetic, not Olist data or Olist accuracy. Product scope remains Cosmetics + Olist, one source, eight metrics, nested scalar paths up to two keys. Exploratory dev model checks exist; the controlled full F/M6/M0/C0 test matrix with repeats remains pending.

This suite supports controlled tests of Texa's memory and clarification components. It has 24 dialogue scenarios (12 dev / 12 test) covering short follow-ups, corrections, irrelevant social turns, topic switches and returns, long references (8, 10 and 12 turns), ambiguous references, and a new independent query that must not inherit old filters. It also has 20 ambiguous one-turn requests paired with 20 explicit controls. Sixteen ambiguous requests omit the period; four use a deliberately broad customer-count phrase whose intended distinction is users versus buyers.

The suite uses a deterministic 96-event synthetic fixture spread over 50 days. The wider date range makes the system-supported `last_7` and `all` period choices distinguishable. Every answer-bearing turn and interaction includes gold SQL plus literal expected columns/rows, computed from source records using the independent Python reference aggregator. This is a diagnostic synthetic dataset; memory phenomenon labels overlap dev/test, and human product-owner review is pending.

`fixture_rows.json` stores the expected canonical source projection (event ID, event date/name, user/session, product category, revenue and nested `ep`). The manifest's `source_digest` is SHA-256 of that exact compact UTF-8 JSON. Before scoring, compare this projection against the rows actually loaded in PostgreSQL; matching file hashes alone cannot detect a stale or different database fixture.

`cases.yaml` is intentionally an empty list. Use the unchanged single-turn cases in `../v2/cases.yaml` for the direct-LLM-vs-Texa system comparison. This suite focuses on component ablations and must be run with its own fixture loaded in the isolated `texa_benchmark` database. Loading its fixture replaces the `event_benchmark` source partition. Reload v2 before running v2 checks.

The `interactions.yaml` gold state records the user's intended answer, not information available to every system. A simulator may provide an oracle value to full Texa only after Texa asks for the exact annotated field. C0 must never receive hidden intent. A missing or incorrect question, form field, or answer remains in the scenario denominator. Before counting a broad metric prompt as a valid clarification trigger, verify on dev that the actual resolver asks the expected `recipe` field; if it does not, keep and report it as a trigger failure or revise the question during dev, then freeze before test.

Regenerate deterministically:

```sh
backend/.venv/bin/python data/benchmark/ablation_v1/generate.py
```

The dataset integrity checker should be run before loading. Execute gold SQL on the isolated PostgreSQL benchmark database and compare every returned table to its literal expected result. A gold pass validates annotations and fixture consistency; it does not measure any model or system accuracy.
