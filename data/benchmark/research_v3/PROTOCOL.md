# Texa research benchmark v3 — frozen internal evaluation

This version expands evaluation coverage; it is an agent-authored synthetic candidate, not a human-reviewed sealed holdout. Do not interpret its score as production accuracy.

## Planned coverage

- 300 answerable single questions: 100 development, 200 test (40 basic, 100 compositional, 60 semantic).
- 60 clarification situations: 30 ambiguous questions and 30 matched explicit controls.
- 40 conversations with 6–12 turns each.
- 40 requests outside the supported scope, scored separately for the expected action.
- Cosmetics Shop and Olist event sources on PostgreSQL; eight catalog metrics, respecting source capabilities. Nested device/campaign values in the fixture are synthetic extensions.

## Comparison

All configurations use gpt-6-luna, the same authored questions and underlying fixtures. For every single-question case, the user-selected source ID is supplied equally to both systems, avoiding a comparison dominated by guessing source identifiers. The direct SQL baseline receives physical schema and that explicit user-selected source only; it does not receive semantic definitions. The interactive baseline additionally receives its actual chat history and may ask for clarification. Texa receives its managed catalog and its normal workflow. This compares systems with different semantic knowledge, not different models.

The single-question matrix compares schema-only LLM, Texa, Texa without retrieval and consistency, Texa with only retrieval, and Texa with only consistency. The interactive suites replace schema-only LLM with the raw-history interactive baseline. Retrieval examples remain the existing verified bank; no new test gold is added to it.

## Scoring and repetitions

Primary single-question accuracy requires the complete returned table to match independent gold values (aliases may differ); ranked outputs preserve requested ordering. Clarification reports final answer correctness separately from asking for every required field and no extra fields. Conversations report answer-slot correctness and complete-scenario success. Unsupported requests report action correctness, not SQL accuracy. Social/noise turns are not SQL answers.

Target three repeats per configuration, rotating run order. The protected cumulative gateway ledger enforces the previously authorized total USD 10 cap. Complete one full paired repeat before subsequent repeats; retain partial runs as incomplete and exclude them from headline comparisons. Report exact completed coverage and costs rather than claiming missing runs finished.

## Integrity

Freeze and commit all questions, gold, fixture snapshots, catalog, example bank, evaluator and runtime before paid test execution. Validate gold with an independent Python row oracle and PostgreSQL across three fixture worlds. The extra worlds are controlled data perturbations, not independent model repeats. Keep development/test logical overlap and family clustering visible; unique question strings alone do not establish independence. No runtime tuning on the new test results during this measurement.

Two independent human reviewers and a separately held-out dataset are still needed for confirmatory research claims.
