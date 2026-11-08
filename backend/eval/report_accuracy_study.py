"""Summarize complete accuracy-study run files without pooling partial runs."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from .check_world_robustness import (C19_CASES_SHA256, C19_ID, DATA as CHALLENGE_DATA,
                                        _effective_contract, _load_cases)
except ImportError:
    from check_world_robustness import (C19_CASES_SHA256, C19_ID, DATA as CHALLENGE_DATA,
                                       _effective_contract, _load_cases)

try:
    from .accuracy_study import confirmatory_eligibility, validate_coverage
except ImportError:
    from accuracy_study import confirmatory_eligibility, validate_coverage


V3_INPUT_POLICIES = {
    "B0": "schema_only_direct_sql",
    "B0R": "schema_plus_verified_retrieved_examples",
    "B0G": "schema_plus_catalog_definitions_direct_sql",
    "B0GR": "schema_plus_catalog_definitions_direct_sql_one_sql_retry",
    "B1": "schema_only_raw_history_clarification_and_one_sql_retry",
    "T00": "texa_semantic_catalog_and_compiler",
    "T10": "texa_semantic_catalog_and_compiler",
    "T01": "texa_semantic_catalog_and_compiler",
    "T11": "texa_semantic_catalog_and_compiler",
    "F": "texa_semantic_catalog_and_compiler",
    "M6": "texa_semantic_catalog_and_compiler",
    "M0": "texa_semantic_catalog_and_compiler",
    "C0": "texa_semantic_catalog_and_compiler",
}
V3_PROTOCOL = "v3_schema_only_full_table"


def _validate_input_policy(manifest: dict[str, Any]) -> None:
    """Reject mislabeled v3 prompt protocols while retaining legacy artifacts."""
    provenance = manifest.get("provenance") or {}
    protocol = provenance.get("evaluation_protocol")
    if protocol is None:
        return  # historical runs predate explicit evaluation protocol metadata
    if protocol != V3_PROTOCOL:
        raise ValueError(f"unsupported evaluation protocol: {protocol}")
    expected = V3_INPUT_POLICIES.get(manifest.get("variant"))
    if expected is None:
        raise ValueError(f"v3 input policy is undefined for variant {manifest.get('variant')!r}")
    if manifest.get("input_policy") != expected:
        raise ValueError(f"{manifest.get('variant')}: input_policy does not match the frozen v3 protocol")
    if not provenance.get("baseline_schema_hash"):
        raise ValueError("v3 run manifest lacks the shared baseline schema hash")


def read_run(path: Path) -> dict[str, Any]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(records) < 3 or records[0].get("type") != "run_manifest" or records[-1].get("type") != "run_complete":
        raise ValueError(f"{path}: incomplete run; partial records are not pooled")
    manifest = records[0]
    _validate_input_policy(manifest)
    rows = records[1:-1]
    validate_coverage(rows, manifest.get("expected_ids"), variant=manifest.get("variant"), suite=manifest.get("suite"))
    if records[-1].get("scenarios") != len(rows):
        raise ValueError(f"{path}: completion count mismatch")
    return {"manifest": manifest, "rows": rows, "path": path}


def apply_annotation_erratum(runs: list[dict[str, Any]], annotation_erratum: str | None,
                              *, dataset_dir: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Overlay the pinned C19 prose-contract correction without mutating source runs."""
    if annotation_erratum is None:
        return runs, None
    if annotation_erratum != "c19-prose-contract-v1":
        raise ValueError(f"unknown annotation erratum: {annotation_erratum}")
    cases_path = (dataset_dir or CHALLENGE_DATA) / "cases.yaml"
    if not cases_path.is_file():
        raise ValueError(f"dataset cases.yaml not found: {cases_path}")
    cases_hash = hashlib.sha256(cases_path.read_bytes()).hexdigest()
    if cases_hash != C19_CASES_SHA256:
        raise ValueError("annotation erratum refused: cases.yaml hash does not match frozen C19 dataset")
    cases = _load_cases(cases_path)
    case = cases.get(C19_ID)
    if case is None:
        raise ValueError(f"annotation erratum refused: frozen dataset lacks {C19_ID}")
    # Reuse the robustness checker's exact opt-in contract/hash gate.
    if _effective_contract(C19_ID, case, erratum=annotation_erratum, case_hash=cases_hash) is not None:
        raise ValueError("annotation erratum refused: C19 annotation does not match frozen prose contract")

    overlays = []
    corrections = []
    run_file_hashes = {}
    for run in runs:
        manifest = run["manifest"]
        if manifest.get("suite") != "single":
            raise ValueError("C19 annotation erratum is restricted to single-suite runs")
        declared_hash = (manifest.get("provenance") or {}).get("dataset_hashes", {}).get("cases.yaml")
        if declared_hash != C19_CASES_SHA256:
            raise ValueError("annotation erratum refused: run manifest cases.yaml hash mismatch")
        for row in run["rows"]:
            if row.get("id") not in cases:
                raise ValueError(f"annotation erratum refused: unknown case ID {row.get('id')!r}")

        overlay = {key: value for key, value in run.items() if key != "rows"}
        overlay["rows"] = []
        for original in run["rows"]:
            row = copy.deepcopy(original)
            if row.get("id") == C19_ID:
                old = {key: row.get(key) for key in ("business_result_correct", "answer_correct", "success")}
                turns = row.get("turns")
                if isinstance(turns, list) and any(isinstance(turn, dict) and "result_correct" in turn for turn in turns):
                    for turn in turns:
                        if isinstance(turn, dict) and "result_correct" in turn:
                            turn["business_result_correct"] = bool(turn["result_correct"])
                    raw_values = [bool(turn.get("result_correct")) for turn in turns
                                  if isinstance(turn, dict) and "result_correct" in turn]
                    corrected_count = sum(raw_values)
                    row["answer_correct"] = corrected_count
                    row["business_result_correct"] = bool(raw_values) and all(raw_values)
                else:
                    row["business_result_correct"] = bool(row.get("result_correct", False))
                    row["answer_correct"] = int(row["business_result_correct"])
                row["success"] = bool(row["business_result_correct"])
                new = {key: row.get(key) for key in ("business_result_correct", "answer_correct", "success")}
                corrections.append({"variant": manifest.get("variant"), "split": manifest.get("split"),
                    "repeat": manifest.get("repeat"), "id": C19_ID, "old": old, "new": new})
            overlay["rows"].append(row)
        overlays.append(overlay)
        path = run.get("path")
        if path is not None and Path(path).is_file():
            run_file_hashes[str(path)] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    metadata = {"name": annotation_erratum, "case_id": C19_ID,
        "cases_sha256": cases_hash, "cases_path": str(cases_path),
        "corrections": corrections, "original_run_file_sha256": run_file_hashes}
    return overlays, metadata


def _component_traces(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Return per-decision traces, using the singular field only for legacy rows."""
    traces = row.get("texa_accuracy_traces") if "texa_accuracy_traces" in row else [row.get("texa_accuracy_trace")]
    return [trace for trace in (traces or []) if isinstance(trace, dict)]


def summarize(runs: list[dict[str, Any]], *, confirmatory: bool = False) -> dict[str, Any]:
    if not runs:
        raise ValueError("no runs supplied")
    for run in runs:
        _validate_input_policy(run["manifest"])
    pair = {(run["manifest"].get("suite"), run["manifest"].get("split"), run["manifest"].get("variant")) for run in runs}
    if len(pair) != 1:
        raise ValueError("one report group must contain one suite/split/variant")
    if any(run["manifest"].get("provenance") != runs[0]["manifest"].get("provenance") for run in runs):
        raise ValueError("runs differ in frozen provenance")
    ids = set(runs[0]["manifest"]["expected_ids"])
    if any(set(run["manifest"]["expected_ids"]) != ids for run in runs):
        raise ValueError("runs have different frozen scenario pools")
    suite = runs[0]["manifest"]["suite"]
    result_rows = [row for run in runs for row in run["rows"]]
    answers = [row for row in result_rows if row.get("answer_count", 0) > 0]
    total = sum(int(row.get("answer_count", 0)) for row in result_rows)
    correct = sum(int(row.get("answer_correct", 0)) for row in result_rows)
    eligibility, reason = confirmatory_eligibility(runs[0]["manifest"].get("dataset", {}))
    if confirmatory and not eligibility:
        raise ValueError(f"confirmatory report refused: {reason}")
    return {"variant": runs[0]["manifest"]["variant"], "suite": suite,
            "split": runs[0]["manifest"]["split"], "runs": len(runs),
            "scenario_count_per_run": len(ids), "answer_count": total,
            "business_accuracy": correct / total if total else None,
            "unsupported_diagnostics": sum(int(row.get("unsupported_turn_count", 0)) for row in result_rows),
            "confirmatory_eligible": eligibility, "confirmatory_status": reason}


def compare(runs: list[dict[str, Any]], *, iterations: int = 3000) -> dict[str, Any]:
    """Matched scenario comparison, with scenario-cluster bootstrap and no incomplete pooling."""
    if not runs:
        raise ValueError("no runs supplied")
    for run in runs:
        _validate_input_policy(run["manifest"])
        declared_counts = run["manifest"].get("expected_answer_counts")
        if declared_counts is not None:
            if set(declared_counts) != {row["id"] for row in run["rows"]} or any(
                    row.get("answer_count") != declared_counts[row["id"]] for row in run["rows"]):
                raise ValueError("answer denominator differs from frozen authored answer slots")
        eligible, reason = confirmatory_eligibility(run["manifest"].get("dataset", {}))
        if run["manifest"].get("confirmatory_requested") and not eligible:
            raise ValueError(f"confirmatory comparison refused: {reason}")
    manifests = [r["manifest"] for r in runs]
    shared = [(m.get("suite"), m.get("split"), m.get("model"),
               json.dumps({k: v for k, v in (m.get("provenance") or {}).items()
                           if k not in {"feature_config", "public_context_hash"}}, sort_keys=True))
              for m in manifests]
    if len(set(shared)) != 1:
        raise ValueError("comparison runs differ in suite, split, model, or frozen shared inputs")
    by_variant: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        by_variant[run["manifest"]["variant"]].append(run)
    world_pools = manifests[0].get("world_pool_ids") or {}
    required_worlds = set(world_pools)
    if not required_worlds:
        raise ValueError("run manifests lack frozen world_pool_ids")
    expected_ids = set().union(*(set(ids) for ids in world_pools.values()))
    run_keys_by_variant = {}
    for variant, variant_runs in by_variant.items():
        keys = [(r["manifest"].get("repeat"), r["manifest"].get("fixture_world")) for r in variant_runs]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate variant/repeat/world run")
        repeats = {repeat for repeat, _ in keys}
        if any({world for rep, world in keys if rep == repeat} != required_worlds for repeat in repeats):
            raise ValueError("missing fixture world for one or more repeats")
        run_keys_by_variant[variant] = {key: run for key, run in zip(keys, variant_runs)}
        for run in variant_runs:
            world = run["manifest"].get("fixture_world")
            expected_world_ids = set(world_pools.get(world, []))
            if set(run["manifest"]["expected_ids"]) != expected_world_ids:
                raise ValueError(f"{variant}: run has incomplete/mismatched coverage for fixture world {world}")
    world_hashes = {}
    for run in runs:
        key = (run["manifest"].get("repeat"), run["manifest"].get("fixture_world"))
        world_hashes.setdefault(key, set()).add(run["manifest"].get("fixture_hash"))
    if any(len(values) != 1 or None in values for values in world_hashes.values()):
        raise ValueError("paired variants differ in fixture-world hash or omit it")
    run_key_sets = [set(keys) for keys in run_keys_by_variant.values()]
    if any(keys != run_key_sets[0] for keys in run_key_sets[1:]):
        raise ValueError("paired variants must have identical repeat/world blocks")
    context_hashes = defaultdict(set)
    for manifest in manifests:
        context_hashes[manifest.get("fixture_world")].add((manifest.get("provenance") or {}).get("public_context_hash"))
    if any(len(values) != 1 for values in context_hashes.values()):
        raise ValueError("public context differs across paired fixture worlds")
    rows_by_variant = {}
    summaries = {}
    for variant, variant_runs in by_variant.items():
        ids_to_rows: dict[str, list[dict]] = defaultdict(list)
        for run in variant_runs:
            for row in run["rows"]:
                ids_to_rows[row["id"]].append(row)
        rows_by_variant[variant] = ids_to_rows
        answer_total = sum(int(row.get("answer_count", 0)) for values in ids_to_rows.values() for row in values)
        answer_correct = sum(int(row.get("answer_correct", 0)) for values in ids_to_rows.values() for row in values)
        latencies = [float(row.get("latency_ms", 0)) for values in ids_to_rows.values() for row in values]
        tokens = sum(float((row.get("usage") or {}).get("input_tokens", 0)) +
                     float((row.get("usage") or {}).get("output_tokens", 0)) for values in ids_to_rows.values() for row in values)
        cost = sum(float(row.get("cost_estimated_usd", 0)) for values in ids_to_rows.values() for row in values)
        # The plural field is emitted by multi-turn runs; the singular field is
        # retained for older/single-turn records. Count component decisions per
        # trace, but scenario activation once if any decision activated it.
        trace_values = []
        retrieval_scenarios = 0
        for values in ids_to_rows.values():
            for row in values:
                traces = _component_traces(row)
                trace_values.extend(traces)
                if bool(row.get("retrieval_activated")) or any(
                        bool((trace.get("retrieval") or {}).get("ids")) for trace in traces):
                    retrieval_scenarios += 1
        retrieval_decisions = sum(bool((trace.get("retrieval") or {}).get("ids"))
                                  for trace in trace_values)
        consistency_scheduled_samples = sum(
            int((trace.get("consistency") or {}).get("scheduled", 0)) for trace in trace_values)
        consistency_completed_samples = sum(
            int((trace.get("consistency") or {}).get("completed", 0)) for trace in trace_values)
        consistency_scheduled_decisions = sum(
            int((trace.get("consistency") or {}).get("scheduled", 0)) > 1 for trace in trace_values)
        consistency_completed_decisions = sum(
            int((trace.get("consistency") or {}).get("completed", 0)) > 1 for trace in trace_values)
        consistency_scheduled_scenarios = sum(
            any(int((trace.get("consistency") or {}).get("scheduled", 0)) > 1
                for trace in _component_traces(row))
            for values in ids_to_rows.values() for row in values)
        consistency_completed_scenarios = sum(
            any(int((trace.get("consistency") or {}).get("completed", 0)) > 1
                for trace in _component_traces(row))
            for values in ids_to_rows.values() for row in values)
        diagnostic_rows = [row for values in ids_to_rows.values() for row in values if row.get("action_scorable")]
        summaries[variant] = {"runs": len(variant_runs), "answer_count": answer_total,
            "business_accuracy": answer_correct / answer_total if answer_total else None,
            "latency_ms_p50": statistics.median(latencies) if latencies else None,
            "latency_ms_p95": sorted(latencies)[min(len(latencies)-1, math.ceil(.95*len(latencies))-1)] if latencies else None,
            "tokens": tokens, "cost_estimated_usd": cost,
            "diagnostic_action_accuracy": sum(bool(row.get("action_correct")) for row in diagnostic_rows) / len(diagnostic_rows) if diagnostic_rows else None,
            "usage_incomplete_scenarios": sum(not row.get("usage_complete", False) for values in ids_to_rows.values() for row in values),
            "retrieval_activated_scenarios": retrieval_scenarios,
            "retrieval_activated_decisions": retrieval_decisions,
            "component_decision_count": len(trace_values),
            "consistency_scheduled_decisions": consistency_scheduled_decisions,
            "consistency_completed_decisions": consistency_completed_decisions,
            "consistency_scheduled_samples": consistency_scheduled_samples,
            "consistency_completed_samples": consistency_completed_samples,
            "consistency_scheduled_scenarios": consistency_scheduled_scenarios,
            # Retained for existing consumers, now genuinely means completed.
            "consistency_completed_scenarios": consistency_completed_scenarios,
            "unsupported_diagnostics": sum(int(row.get("unsupported_turn_count", 0)) for values in ids_to_rows.values() for row in values)}
    if manifests[0]["suite"] == "diagnostic":
        return {"suite": "diagnostic", "split": manifests[0]["split"], "variants": summaries,
                "paired_comparisons": {}, "factorial_effects": None,
                "interpretation": "Observable action diagnostics only; injection and explanation rubrics require manual review. Not SQL result accuracy."}
    names = sorted(by_variant)
    pairs = {}
    rng = random.Random(731904)
    for i, left_name in enumerate(names):
        for right_name in names[i+1:]:
            left_runs, right_runs = by_variant[left_name], by_variant[right_name]
            left_runs_by_key = run_keys_by_variant[left_name]
            right_runs_by_key = run_keys_by_variant[right_name]
            common_keys = sorted(set(left_runs_by_key) & set(right_runs_by_key))
            if not common_keys:
                continue
            diffs, b_diffs, discordant_left, discordant_right = [], [], 0, 0
            clusters = defaultdict(list)
            for sid in expected_ids:
                source = left_runs_by_key[common_keys[0]]["rows"]
                ref = next((x for x in source if x["id"] == sid), None)
                if ref is None:
                    ref = next(x for run in left_runs for x in run["rows"] if x["id"] == sid)
                clusters[ref.get("cluster_id", sid)].append(sid)
            cluster_diff = {}
            for cluster, sids in clusters.items():
                delta = 0
                observed = 0
                for key in common_keys:
                    lmap = {r["id"]: r for r in left_runs_by_key[key]["rows"]}
                    rmap = {r["id"]: r for r in right_runs_by_key[key]["rows"]}
                    for sid in sids:
                        if sid not in lmap or sid not in rmap:
                            continue
                        observed += 1
                        l, r = lmap[sid], rmap[sid]
                        lc, rc = int(l.get("answer_correct", 0)), int(r.get("answer_correct", 0))
                        ln, rn = max(1, int(l.get("answer_count", 0))), max(1, int(r.get("answer_count", 0)))
                        l_ok, r_ok = lc / ln, rc / rn
                        diffs.append(r_ok-l_ok)
                        delta += r_ok-l_ok
                        if bool(l.get("success")) and not bool(r.get("success")):
                            discordant_left += 1
                        if bool(r.get("success")) and not bool(l.get("success")):
                            discordant_right += 1
                cluster_diff[cluster] = (delta, observed)
            point = statistics.mean(diffs) if diffs else None
            values = list(cluster_diff.values())
            boot = []
            if values:
                for _ in range(iterations):
                    draw = [rng.choice(values) for _ in values]
                    boot.append(sum(value for value, _ in draw) / max(1, sum(count for _, count in draw)))
                boot.sort()
            discordant = discordant_left + discordant_right
            exact_p = min(1.0, 2 * sum(math.comb(discordant, k) for k in range(min(discordant_left, discordant_right) + 1)) / (2 ** discordant)) if discordant else 1.0
            pairs[f"{left_name}_vs_{right_name}"] = {"paired_accuracy_delta_right_minus_left": point,
                "estimand": "mean scenario answer fraction; cluster-resampled families",
                "mcnemar_exact_p_diagnostic": exact_p,
                "cluster_bootstrap_ci95": [boot[int(.025*(iterations-1))], boot[int(.975*(iterations-1))]] if boot else None,
                "clusters": len(values), "matched_run_blocks": common_keys,
                "mcnemar_discordant_left_only": discordant_left, "mcnemar_discordant_right_only": discordant_right}
    factorial = None
    t_names = {"T00", "T10", "T01", "T11"}
    if t_names <= set(summaries):
        a = {k: summaries[k]["business_accuracy"] for k in t_names}
        if all(v is not None for v in a.values()):
            factorial = {"retrieval_main_effect": ((a["T10"]+a["T11"])-(a["T00"]+a["T01"])) / 2,
                         "consistency_main_effect": ((a["T01"]+a["T11"])-(a["T00"]+a["T10"])) / 2,
                         "interaction": a["T11"]-a["T10"]-a["T01"]+a["T00"]}
    return {"suite": manifests[0]["suite"], "split": manifests[0]["split"], "variants": summaries,
            "paired_comparisons": pairs, "factorial_effects": factorial,
            "interpretation": "diagnostic exploratory candidate results; not confirmatory human-reviewed holdout evidence"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--confirmatory", action="store_true")
    parser.add_argument("--compare", action="store_true", help="compare matched complete variant runs")
    parser.add_argument("--annotation-erratum", choices=("c19-prose-contract-v1",),
                        help="apply a hash-pinned correction to the C19 business-contract annotation")
    parser.add_argument("--dataset-dir", type=Path,
                        help="challenge dataset directory containing the frozen cases.yaml")
    args = parser.parse_args(argv)
    parsed = [read_run(path) for path in args.runs]
    parsed, erratum_metadata = apply_annotation_erratum(parsed, args.annotation_erratum,
                                                         dataset_dir=args.dataset_dir)
    if args.confirmatory:
        for run in parsed:
            eligible, reason = confirmatory_eligibility(run["manifest"].get("dataset", {}))
            if not eligible:
                raise ValueError(f"confirmatory report refused: {reason}")
    result = compare(parsed) if args.compare else summarize(parsed, confirmatory=args.confirmatory)
    if erratum_metadata is not None:
        result["annotation_erratum"] = erratum_metadata
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
