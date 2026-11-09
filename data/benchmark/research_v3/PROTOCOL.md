# Texa research benchmark v3 — frozen internal evaluation

This version expands evaluation coverage; it is an agent-authored synthetic candidate, not a human-reviewed sealed holdout. Do not interpret its score as production accuracy.

## Coverage

- 300 answerable single questions: 100 development, 200 test (40 basic, 100 compositional, 60 semantic).
- 60 clarification situations: 30 ambiguous questions and 30 matched explicit controls.
- 40 conversations with 6–12 turns each.
- 40 requests outside the supported scope, scored separately for the expected action.
- Cosmetics Shop and Olist event sources on PostgreSQL; eight catalog metrics, respecting source capabilities. Nested device/campaign values in the fixture are synthetic extensions.

## Comparison

All configurations use gpt-6-luna, the same authored questions and underlying fixtures. For every single-question case, the user-selected source ID is supplied equally to both systems. Baseline receives the question, physical PostgreSQL schema, explicit source selection and the same business definitions supplied to Texa, rendered as text. It generates SQL directly and may repair it once if execution fails, using only a sanitized error category. It does not receive gold answers and does not use Texa's QuerySpec, compiler, semantic validation, retrieval or consistency.

The single-question matrix compares Baseline, Texa, Texa without retrieval and consistency, Texa with only retrieval, and Texa with only consistency. Baseline is evaluated only on single questions. Conversation, clarification and unsupported-request results report Texa and its ablations; these suites do not establish a Baseline comparison. Retrieval examples remain the existing verified bank; no test gold is added to it.

## Scoring and repetitions

Primary single-question accuracy requires the complete returned table to match independent gold values (aliases may differ); ranked outputs preserve requested ordering. Clarification reports final answer correctness separately from asking for every required field and no extra fields. Conversations report answer-slot correctness and complete-scenario success. Unsupported requests report action correctness, not SQL accuracy. Social/noise turns are not SQL answers.

The reported single-question comparison has two completed repeats per configuration: 200 unique test cases and 400 executions. Baseline scores 356/400 (89.00%) and Texa scores 365/400 (91.25%). Repeats measure model variation and do not double the number of independent questions. The protected cumulative gateway ledger enforces the authorized total USD 150 cap. Retain partial runs as incomplete and exclude them from headline comparisons; report exact completed coverage and costs.

## Integrity

Freeze and commit all questions, gold, fixture snapshots, catalog, example bank, evaluator and runtime before paid test execution. Validate gold with an independent Python row oracle and PostgreSQL across three fixture worlds. The extra worlds are controlled data perturbations, not independent model repeats. Keep development/test logical overlap and family clustering visible; unique question strings alone do not establish independence. No runtime tuning on the new test results during this measurement.

Two independent human reviewers and a separately held-out dataset are still needed for confirmatory research claims.

## Execution partitioning

Independent scenarios may run in deterministic round-robin shards for throughput. A conversation remains intact within one shard. A full result is merged only when all shard indices are complete, scenario IDs are disjoint, their union exactly matches the frozen suite, and metadata/provenance match. Raw shard files and SHA-256 audit links are retained. Partial pilot runs before this execution improvement are excluded from the final comparison.
