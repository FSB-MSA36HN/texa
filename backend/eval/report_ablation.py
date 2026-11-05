"""Summarize paired, repeated Texa ablation runs from JSONL without model calls.

Every input file represents exactly one variant/repeat. The runner writes a
manifest first, one scenario record per frozen scenario, and a completion record
last. Repeats are averaged within scenario; bootstrap resamples scenario clusters,
never turns or repeated calls as if they were independent examples.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PRIMARY = {"memory": ("F", "M6")}
ALLOWED = {"memory": {"F", "M6", "M0"}, "clarification": {"F", "C0"},
           "single": {"F", "B0"}}


def project_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError(f"input/output paths must stay under {ROOT}") from exc
    return path


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered)-1, math.ceil(fraction * len(ordered))-1)]


def _read_run(path: Path) -> dict[str, Any]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(records) < 3 or records[0].get("type") != "run_manifest" or records[-1].get("type") != "run_complete":
        raise ValueError(f"{path}: expected manifest first, scenarios, then run_complete")
    manifest = records[0]
    required = ("variant", "suite", "split", "repeat", "model", "provenance", "expected_ids")
    if any(k not in manifest for k in required):
        raise ValueError(f"{path}: run_manifest missing one of {', '.join(required)}")
    variant, suite = manifest["variant"], manifest["suite"]
    if variant not in ALLOWED.get(suite, set()):
        raise ValueError(f"{path}: variant {variant!r} is not valid for suite {suite!r}")
    if manifest["split"] not in {"dev", "test"} or not isinstance(manifest["repeat"], int) or manifest["repeat"] < 1:
        raise ValueError(f"{path}: invalid split/repeat")
    provenance = manifest["provenance"]
    for key in ("dataset_hashes", "catalog_hash", "prompt_hashes", "source_digest", "effective_model_config", "commit"):
        if key not in provenance:
            raise ValueError(f"{path}: provenance missing {key}")
    if "implementation_hashes" in provenance and provenance.get("source_profile") != "evaluation":
        raise ValueError(f"{path}: implementation hash lock requires the evaluation source profile")
    scenarios = records[1:-1]
    if not scenarios or any(row.get("type") != "scenario" for row in scenarios):
        raise ValueError(f"{path}: only scenario rows are allowed between manifest and completion")
    ids = [str(row.get("id", "")) for row in scenarios]
    expected = manifest["expected_ids"]
    if not isinstance(expected, list) or not expected or len(expected) != len(set(expected)):
        raise ValueError(f"{path}: invalid expected_ids")
    if len(ids) != len(set(ids)) or set(ids) != set(map(str, expected)):
        raise ValueError(f"{path}: scenario IDs do not exactly match expected_ids")
    complete = records[-1]
    if complete.get("scenarios") != len(scenarios):
        raise ValueError(f"{path}: run_complete scenario count mismatch")
    for row in scenarios:
        for key in ("cluster_id", "group", "success", "latency_ms", "usage"):
            if key not in row:
                raise ValueError(f"{path}: scenario {row.get('id')} missing {key}")
        if not isinstance(row["success"], bool) or not isinstance(row["usage"], dict):
            raise ValueError(f"{path}: malformed scenario {row['id']}")
        if not isinstance(row.get("usage_complete", True), bool):
            raise ValueError(f"{path}: usage_complete must be boolean in {row['id']}")
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0
               for value in row["usage"].values()):
            raise ValueError(f"{path}: usage counters must be non-negative numbers in {row['id']}")
        if row.get("answer_count", 0) < 0 or row.get("answer_correct", 0) < 0 or row.get("answer_correct", 0) > row.get("answer_count", 0):
            raise ValueError(f"{path}: invalid answer counts in {row['id']}")
    return {"path": path, "manifest": manifest, "scenarios": {str(r["id"]): r for r in scenarios}}


def _provenance_key(run: dict[str, Any]) -> tuple:
    m = run["manifest"]
    p = m["provenance"]
    # implementation_hashes cover prompts plus semantic/runtime/scoring code;
    # rendered prompts remain separately hashed in each scenario's trace.
    # Variant/repeat and output file deliberately excluded; shared experimental
    # inputs that could explain a quality difference must be held fixed.
    return (m["suite"], m["split"], m["model"], json.dumps(p, sort_keys=True, separators=(",", ":")),
            json.dumps(m.get("effective_model_config", {}), sort_keys=True, separators=(",", ":")))


def _validate_pair(left_runs: list[dict], right_runs: list[dict]) -> tuple[list[int], list[str]]:
    if not left_runs or not right_runs:
        raise ValueError("both variants need at least one run")
    lm, rm = left_runs[0]["manifest"], right_runs[0]["manifest"]
    if lm["suite"] != rm["suite"] or lm["split"] != rm["split"]:
        raise ValueError("paired variants must use the same suite and split")
    if (lm["variant"], rm["variant"]) not in ({("F", "M6"), ("F", "M0"), ("F", "C0"), ("F", "B0")}):
        raise ValueError("report only paired F-vs-one-ablation/baseline comparisons")
    if lm["variant"] not in ALLOWED[lm["suite"]] or rm["variant"] not in ALLOWED[rm["suite"]]:
        raise ValueError("variant/suite mismatch")
    if any(_provenance_key(r) != _provenance_key(left_runs[0]) for r in left_runs + right_runs):
        raise ValueError("paired runs differ in model, suite, split, or experimental provenance/config")
    left_by_repeat = {r["manifest"]["repeat"]: r for r in left_runs}
    right_by_repeat = {r["manifest"]["repeat"]: r for r in right_runs}
    if len(left_by_repeat) != len(left_runs) or len(right_by_repeat) != len(right_runs):
        raise ValueError("duplicate variant/repeat run")
    if set(left_by_repeat) != set(right_by_repeat):
        raise ValueError("paired variants must have exactly the same repeat numbers")
    ids = set(left_runs[0]["scenarios"])
    if any(set(r["scenarios"]) != ids for r in left_runs + right_runs):
        raise ValueError("all paired repeats must contain identical scenario IDs")
    for sid in ids:
        ref = left_runs[0]["scenarios"][sid]
        expected_answers = ref.get("answer_count", 0)
        for r in left_runs + right_runs:
            row = r["scenarios"][sid]
            if row["cluster_id"] != ref["cluster_id"] or row["group"] != ref["group"]:
                raise ValueError(f"scenario {sid} has inconsistent cluster/group labels")
            if row.get("answer_count", 0) != expected_answers:
                raise ValueError(f"scenario {sid} has mismatched answer_count across paired variants/repeats")
    return sorted(left_by_repeat), sorted(ids)


def _validate_variant_repeats(runs: list[dict]) -> None:
    """Validate F-only (or any unpaired) groups as strictly as comparison groups."""
    if not runs:
        raise ValueError("variant has no runs")
    repeats = [run["manifest"]["repeat"] for run in runs]
    if len(repeats) != len(set(repeats)):
        raise ValueError("duplicate variant/repeat run")
    if any(_provenance_key(run) != _provenance_key(runs[0]) for run in runs):
        raise ValueError("repeats differ in model, suite, split, or experimental provenance/config")
    ids = set(runs[0]["scenarios"])
    for run in runs[1:]:
        if set(run["scenarios"]) != ids:
            raise ValueError("all repeats of a variant must contain identical scenario IDs")
    for sid in ids:
        reference = runs[0]["scenarios"][sid]
        for run in runs[1:]:
            row = run["scenarios"][sid]
            if row["cluster_id"] != reference["cluster_id"] or row["group"] != reference["group"]:
                raise ValueError(f"scenario {sid} has inconsistent cluster/group labels across repeats")
            if row.get("answer_count", 0) != reference.get("answer_count", 0):
                raise ValueError(f"scenario {sid} has mismatched answer_count across repeats")


def _cluster_bootstrap(left_runs: list[dict], right_runs: list[dict], repeats: list[int], ids: list[str],
                       *, metric: str, group: str | None = None, iterations: int = 5000,
                       seed: int = 731904) -> dict[str, Any]:
    """Paired bootstrap over scenario clusters, retaining all paired repeats."""
    left = {r["manifest"]["repeat"]: r["scenarios"] for r in left_runs}
    right = {r["manifest"]["repeat"]: r["scenarios"] for r in right_runs}

    clusters: dict[str, list[str]] = defaultdict(list)
    for sid in ids:
        if group is None or left[repeats[0]][sid]["group"] == group:
            clusters[left[repeats[0]][sid]["cluster_id"]].append(sid)
    clusters = {key: values for key, values in clusters.items() if values}
    if not clusters:
        return {"delta": None, "ci95_low": None, "ci95_high": None, "clusters": 0, "iterations": 0}

    def delta(sample_clusters: list[list[str]]) -> float:
        lvals, rvals, lcorrect, rcorrect, lcount, rcount = [], [], 0, 0, 0, 0
        for cluster in sample_clusters:
            for sid in cluster:
                for rep in repeats:
                    lr, rr = left[rep][sid], right[rep][sid]
                    if metric == "success":
                        lvals.append(float(lr["success"]))
                        rvals.append(float(rr["success"]))
                    else:
                        # Micro-average answer-bearing turns within each paired
                        # cluster sample; scenarios with no SQL answer add no denominator.
                        lcount += int(lr.get("answer_count", 0))
                        rcount += int(rr.get("answer_count", 0))
                        lcorrect += int(lr.get("answer_correct", 0))
                        rcorrect += int(rr.get("answer_correct", 0))
        if metric == "success":
            return statistics.mean(lvals) - statistics.mean(rvals) if lvals else float("nan")
        if not lcount or not rcount:
            return float("nan")
        return lcorrect / lcount - rcorrect / rcount

    cluster_values = list(clusters.values())
    observed = delta(cluster_values)
    rng = random.Random(seed)
    samples = [delta([rng.choice(cluster_values) for _ in cluster_values]) for _ in range(iterations)]
    samples = sorted(v for v in samples if math.isfinite(v))
    if not samples:
        return {"delta": observed if math.isfinite(observed) else None, "ci95_low": None, "ci95_high": None, "clusters": len(clusters)}
    return {"delta": observed, "ci95_low": samples[max(0, math.floor(.025 * len(samples)))],
            "ci95_high": samples[min(len(samples)-1, math.ceil(.975 * len(samples))-1)],
            "clusters": len(clusters), "iterations": len(samples)}


def _summarize(runs: list[dict], repeats: list[int], ids: list[str]) -> dict[str, Any]:
    by_repeat = {r["manifest"]["repeat"]: r["scenarios"] for r in runs}
    successes, correctness, strict_correctness, contract_correctness, latency = [], [], [], [], []
    slice_counts: dict[str, dict[str, dict[str, int]]] = {
        "source_id": defaultdict(lambda: {"correct": 0, "answers": 0}),
        "language": defaultdict(lambda: {"correct": 0, "answers": 0}),
    }
    usage_totals: dict[str, list[float]] = defaultdict(list)
    group_vals: dict[str, list[bool]] = defaultdict(list)
    tp = fp = fn = rounds = 0
    usage_incomplete = usage_rows = 0
    slots: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
    activation = {"turn_observations": 0, "clarification_requested": 0, "guess_invoked": 0}
    activation_reasons, memory_relations = defaultdict(int), defaultdict(int)
    for rep in repeats:
        scenarios = by_repeat[rep]
        for sid in ids:
            row = scenarios[sid]
            successes.append(float(row["success"]))
            group_vals[str(row["group"])].append(row["success"])
            if row.get("output_contract_compliant") is not None:
                contract_correctness.append(bool(row["output_contract_compliant"]))
            strict_value = row.get("strict_result_correct", row.get("result_correct"))
            if strict_value is not None:
                strict_correctness.append(bool(strict_value))
            n = row.get("answer_count", 0)
            if n:
                correctness.extend([True] * row.get("answer_correct", 0))
                correctness.extend([False] * (n-row.get("answer_correct", 0)))
                for key in slice_counts:
                    label = row.get(key)
                    if label:
                        slice_counts[key][str(label)]["correct"] += int(row.get("answer_correct", 0))
                        slice_counts[key][str(label)]["answers"] += int(n)
            elif row.get("business_result_correct") is not None:
                correctness.append(bool(row["business_result_correct"]))
            elif row.get("result_correct") is not None:
                correctness.append(bool(row["result_correct"]))
            if row.get("latency_ms") is not None:
                latency.append(float(row["latency_ms"]))
            for key, value in row.get("usage", {}).items():
                if isinstance(value, (float, int)):
                    usage_totals[key].append(float(value))
            usage_rows += 1
            usage_incomplete += int(not row.get("usage_complete", True))
            counts = row.get("clarification_counts", {})
            tp += int(counts.get("tp", 0)); fp += int(counts.get("fp", 0)); fn += int(counts.get("fn", 0))
            rounds += int(row.get("clarification_rounds", 0))
            observed_turns = {}
            for turn in row.get("turns", []):
                observation = turn.get("trace") or {}
                if observation.get("id"):
                    observed_turns[observation["id"]] = observation
                for slot, passed in (turn.get("slot_checks") or {}).items():
                    slots[slot]["total"] += 1
                    slots[slot]["correct"] += int(bool(passed))
            for observation in observed_turns.values():
                component = observation.get("ablation") or {}
                activation["turn_observations"] += 1
                activation["clarification_requested"] += int(bool(component.get("clarification_requested")))
                activation["guess_invoked"] += int(bool(component.get("clarification_invoked")))
                activation_reasons[component.get("clarification_reason", "unknown")] += 1
                memory_relations[(observation.get("context") or {}).get("relation", "unknown")] += 1
    # result_correct may be a scenario-only flag when answer_count is absent;
    # when answer_count exists it is the more granular gold-turn accounting.
    accuracy = sum(correctness) / len(correctness) if correctness else None
    per_repeat_success = {
        str(rep): statistics.mean(float(by_repeat[rep][sid]["success"]) for sid in ids)
        for rep in repeats
    }
    repeat_means = list(per_repeat_success.values())
    return {"scenario_success_mean": statistics.mean(successes) if successes else None,
            "scenario_success_sd": statistics.stdev(successes) if len(successes) > 1 else 0.0 if successes else None,
            "per_repeat_scenario_success": per_repeat_success,
            "repeat_success_sd": statistics.stdev(repeat_means) if len(repeat_means) > 1 else 0.0 if repeat_means else None,
            "result_accuracy": accuracy, "result_count": len(correctness),
            "strict_result_accuracy": (sum(strict_correctness) / len(strict_correctness)
                                       if strict_correctness else None),
            "strict_result_count": len(strict_correctness),
            "output_contract_compliance": (sum(contract_correctness) / len(contract_correctness)
                                           if contract_correctness else None),
            "output_contract_count": len(contract_correctness),
            "business_accuracy_by_source": {label: {**counts, "accuracy": counts["correct"] / counts["answers"]}
                                            for label, counts in sorted(slice_counts["source_id"].items())
                                            if counts["answers"]},
            "business_accuracy_by_language": {label: {**counts, "accuracy": counts["correct"] / counts["answers"]}
                                               for label, counts in sorted(slice_counts["language"].items())
                                               if counts["answers"]},
            "per_group_success": {k: {"n_run_scenarios": len(v), "mean": statistics.mean(v)} for k, v in sorted(group_vals.items())},
            "per_group_result_accuracy": {
                group: {"answer_count": sum(by_repeat[rep][sid].get("answer_count", 0) for rep in repeats for sid in ids
                                              if str(by_repeat[rep][sid]["group"]) == group),
                        "accuracy": (sum(by_repeat[rep][sid].get("answer_correct", 0) for rep in repeats for sid in ids
                                         if str(by_repeat[rep][sid]["group"]) == group) /
                                     sum(by_repeat[rep][sid].get("answer_count", 0) for rep in repeats for sid in ids
                                         if str(by_repeat[rep][sid]["group"]) == group))
                                     if sum(by_repeat[rep][sid].get("answer_count", 0) for rep in repeats for sid in ids
                                            if str(by_repeat[rep][sid]["group"]) == group) else None}
                for group in sorted(group_vals)},
            "clarification": {"tp": tp, "fp": fp, "fn": fn,
                "precision": tp/(tp+fp) if tp+fp else None, "recall": tp/(tp+fn) if tp+fn else None,
                "rounds": rounds},
            "latency_ms": {"n": len(latency), "mean": statistics.mean(latency) if latency else None,
                           "p50": _percentile(latency, .50), "p95": _percentile(latency, .95)},
            "usage_mean": {key: statistics.mean(vals) for key, vals in sorted(usage_totals.items()) if vals},
            "usage_completeness": {"scenarios": usage_rows, "incomplete_scenarios": usage_incomplete,
                "complete": usage_rows > 0 and usage_incomplete == 0,
                "interpretation": "complete totals" if usage_rows > 0 and usage_incomplete == 0 else "lower bound; failed calls may not report tokens"},
            "component_activation": activation | {"guess_reasons": dict(activation_reasons), "memory_relations": dict(memory_relations)},
            "slot_accuracy": {key: {"correct": val["correct"], "total": val["total"],
                                    "accuracy": val["correct"]/val["total"] if val["total"] else None}
                              for key, val in sorted(slots.items())},
            "repeats": len(repeats), "scenarios": len(ids), "run_observations": len(successes)}


def build_report(paths: list[Path], *, iterations: int = 5000, seed: int = 731904) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("iterations must be positive")
    runs = [_read_run(path) for path in paths]
    if not runs:
        raise ValueError("no input runs")
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for run in runs:
        m = run["manifest"]
        grouped[(m["suite"], m["split"], m["variant"])].append(run)
    comparisons = []
    all_summaries = {}
    for (suite, split, variant), variant_runs in sorted(grouped.items()):
        variant_runs.sort(key=lambda r: r["manifest"]["repeat"])
        _validate_variant_repeats(variant_runs)
        repeats = [r["manifest"]["repeat"] for r in variant_runs]
        ids = sorted(variant_runs[0]["scenarios"])
        all_summaries[f"{suite}/{split}/{variant}"] = _summarize(variant_runs, repeats, ids)
    for (suite, split, variant), left_runs in sorted(grouped.items()):
        control_variant = "F"
        if variant == control_variant:
            continue
        f_runs = grouped.get((suite, split, control_variant))
        if not f_runs:
            raise ValueError(f"{suite}/{split}/{variant} requires matching F runs")
        repeats, ids = _validate_pair(f_runs, left_runs)
        f_runs.sort(key=lambda r: r["manifest"]["repeat"])
        left_runs.sort(key=lambda r: r["manifest"]["repeat"])
        result = {"suite": suite, "split": split, "control": "F", "variant": variant,
                  "primary": PRIMARY.get(suite) == ("F", variant), "repeats": repeats, "scenarios": len(ids),
                  "control_summary": all_summaries[f"{suite}/{split}/F"],
                  "variant_summary": all_summaries[f"{suite}/{split}/{variant}"]}
        result["delta_control_minus_variant_success"] = _cluster_bootstrap(f_runs, left_runs, repeats, ids,
                                                    metric="success", iterations=iterations, seed=seed)
        result["delta_control_minus_variant_result_accuracy"] = _cluster_bootstrap(f_runs, left_runs, repeats, ids,
                                                    metric="result_accuracy", iterations=iterations, seed=seed + 1)
        groups_in_suite = sorted({str(f_runs[0]["scenarios"][sid]["group"]) for sid in ids})
        result["per_group_delta_control_minus_variant"] = {
            group: {
                "success": _cluster_bootstrap(f_runs, left_runs, repeats, ids, metric="success", group=group,
                                              iterations=iterations, seed=seed + 2 + index),
                "result_accuracy": _cluster_bootstrap(f_runs, left_runs, repeats, ids, metric="result_accuracy", group=group,
                                                       iterations=iterations, seed=seed + 20 + index),
            } for index, group in enumerate(groups_in_suite)}
        comparisons.append(result)
    return {"type": "ablation_report", "comparisons": comparisons, "summaries": all_summaries,
            "warnings": ["Repeated runs are averaged within scenario; bootstrap clusters are scenarios, not repeats.",
                         "A single repeat gives descriptive results only; it does not demonstrate run-to-run stability.",
                         "Synthetic benchmark results do not establish production generalization.",
                         "Usage totals are lower bounds if a provider call failed before usage was recorded."]}


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Ablation evaluation report", "", "This report summarizes completed runs only. Repeats are not counted as independent scenarios.", "",
             "| Suite | Split | Comparison | Scenario success (F / variant) | Result accuracy (F / variant) | F − variant (scenario; 95% CI) | Repeats |",
             "|---|---|---|---:|---:|---:|---:|"]
    for row in report["comparisons"]:
        a, b = row["control_summary"], row["variant_summary"]
        interval = row["delta_control_minus_variant_success"]
        delta = interval["delta"]
        ci = f"[{interval['ci95_low']*100:.1f}, {interval['ci95_high']*100:.1f}] pp" if interval["ci95_low"] is not None else "N/A"
        fmt = lambda x: "N/A" if x is None else f"{x:.1%}"
        lines.append(f"| {row['suite']} | {row['split']} | F vs {row['variant']} | {fmt(a['scenario_success_mean'])} / {fmt(b['scenario_success_mean'])} | {fmt(a['result_accuracy'])} / {fmt(b['result_accuracy'])} | {delta*100:+.1f} pp {ci} | {row['repeats']} |")
    lines.extend(["", "## Limits", ""])
    lines.extend(f"- {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--output", required=True, help="Project-relative JSON report path; must not already exist")
    parser.add_argument("--markdown", help="Optional project-relative Markdown report path")
    parser.add_argument("--iterations", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=731904)
    args = parser.parse_args()
    try:
        inputs = [project_path(p) for p in args.inputs]
        output = project_path(args.output)
        markdown = project_path(args.markdown) if args.markdown else None
        if output.exists() or (markdown and markdown.exists()):
            raise ValueError("refusing to overwrite an existing report")
        report = build_report(inputs, iterations=args.iterations, seed=args.seed)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if markdown:
            markdown.parent.mkdir(parents=True, exist_ok=True)
            markdown.write_text(render_markdown(report), encoding="utf-8")
        print(json.dumps({"comparisons": len(report["comparisons"]), "output": str(output.relative_to(ROOT)),
                          "markdown": str(markdown.relative_to(ROOT)) if markdown else None}, ensure_ascii=False))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"report error: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
