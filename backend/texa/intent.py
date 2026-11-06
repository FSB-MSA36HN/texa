"""Reconcile the model's requested-measure assertion with its executable proposal.

This is a guardrail, not a proof of semantic understanding: the contract is model-generated.
It makes measure, grain, source and dimension mismatches explicit and fail-closed rather
than assuming that a syntactically valid QuerySpec answers the user's actual question.
"""


def metric_operation(cat, metric_ids: list[str]) -> str | None:
    if len(metric_ids) > 1:
        return "multiple"
    if len(metric_ids) != 1 or metric_ids[0] not in cat.mets:
        return None
    metric = cat.mets[metric_ids[0]]
    if metric.type == "simple":
        return metric.simple.aggregation
    if metric.type == "ratio":
        return "ratio"
    return metric.type


def metric_grain(cat, metric_ids: list[str]) -> str | None:
    if len(metric_ids) > 1:
        return "multiple"
    if len(metric_ids) != 1 or metric_ids[0] not in cat.mets:
        return None
    return cat.mets[metric_ids[0]].intent_grain or "unspecified"


def candidate_metric_ids(candidate: dict) -> list[str]:
    return [metric for metric in ([candidate.get("recipe", "")] + candidate.get("metrics", [])) if metric]


def candidate_filter_ids(candidate: dict) -> list[str]:
    return list(dict.fromkeys(f.get("field") for f in candidate.get("filters", []) if f.get("field")))


def reconcile_dimension_roles(candidate: dict, cat=None) -> dict:
    """Use the separate intent contract to repair a filter/grouping role swap.

    Only moves a catalog dimension that the intent contract explicitly requests as a
    breakdown and explicitly excludes from filters. Filter values on other fields are
    preserved byte-for-byte and still go through the normal vocabulary binder.
    """
    contract = candidate.get("intent_contract") or {}
    if contract.get("kind") != "catalog_metric":
        return candidate
    breakdowns = set(contract.get("breakdown_ids") or [])
    filter_ids = set(contract.get("filter_ids") or [])
    movable = breakdowns - filter_ids
    if not movable:
        return candidate
    current = list(candidate.get("selection") or [])
    filters = []
    moved = set()
    for item in candidate.get("filters", []):
        field = item.get("field")
        if field in movable:
            moved.add(field)
        else:
            filters.append(item)
    if not moved:
        return candidate
    candidate = dict(candidate)
    ordered = [dimension for dimension in contract.get("breakdown_ids", []) if dimension in moved]
    candidate["selection"] = list(dict.fromkeys([*current, *ordered]))
    candidate["filters"] = filters
    if candidate.get("shape") not in {"distinct_values"}:
        has_time = bool(cat and any(cat.dims.get(d) and cat.dims[d].is_time for d in candidate["selection"]))
        candidate["shape"] = "time_trend" if has_time else "breakdown"
    return candidate


def has_source_conflict(scope: list[str] | None, requested: list[str], textual: list[str], max_sources: int) -> bool:
    """Treat UI scope, semantic intent and source mentions as constraints before outcomes/votes."""
    return bool(
        len(set(requested)) > max_sources or len(set(textual)) > max_sources or
        (scope and requested and set(requested) != set(scope)) or
        (textual and requested and set(textual) != set(requested)) or
        (scope and textual and set(scope) != set(textual))
    )


def mismatch(candidate: dict, cat, *, spec: dict | None = None, allow_continuation: bool = False) -> str | None:
    """Return a stable diagnostic code if requested intent and proposal disagree."""
    contract = candidate.get("intent_contract")
    # Direct unit callers and historical persisted candidates predate the contract.
    # New live LLM responses cannot omit it because the structured output schema requires it.
    if not isinstance(contract, dict):
        return None
    kind = contract.get("kind")
    if kind == "ambiguous_metric":
        alternatives = set(candidate.get("recipe_alternatives") or [])
        intended = set(contract.get("metric_ids") or [])
        if candidate.get("outcome") != "query" or candidate_metric_ids(candidate) or not alternatives or alternatives != intended:
            return "invalid_ambiguous_metric_contract"
        return None
    if kind in {"derived_measure", "unsupported_measure"}:
        return "non_catalog_measure"
    if kind == "continuation":
        if not allow_continuation:
            return "unbound_continuation"
        return None
    if kind == "dimension_query":
        if candidate.get("outcome") != "query" or candidate.get("shape") != "distinct_values":
            return "dimension_query_shape_mismatch"
        dims = set(contract.get("breakdown_ids") or [])
        proposed = set((spec or {}).get("selection", []) if spec else candidate.get("selection", []))
        if not dims or dims != proposed:
            return "dimension_query_dimension_mismatch"
        return None
    if kind == "non_metric":
        return "non_metric_query" if candidate.get("outcome") == "query" else None
    if kind not in {"catalog_metric", "presentation_arithmetic"}:
        return "invalid_intent_kind"

    intent_metrics = contract.get("metric_ids") or []
    if not intent_metrics or any(metric not in cat.mets for metric in intent_metrics):
        return "intent_metric_not_catalogued"
    operation = metric_operation(cat, intent_metrics)
    grain = metric_grain(cat, intent_metrics)
    expected_operation = "presentation_arithmetic" if kind == "presentation_arithmetic" else operation
    if expected_operation != contract.get("operation"):
        return "intent_operation_mismatch"
    if kind == "presentation_arithmetic" and not (candidate.get("answer_request") or {}).get("ask"):
        return "arithmetic_without_request"
    if grain != (contract.get("grain") or "unspecified"):
        return "intent_grain_mismatch"

    proposed_metrics = candidate_metric_ids(spec) if spec else candidate_metric_ids(candidate)
    if set(intent_metrics) != set(proposed_metrics):
        return "intent_metric_mismatch"
    if (contract.get("source_ids") and
            set(contract["source_ids"]) != set((spec or {}).get("source_ids") or candidate.get("source_ids", []))):
        return "intent_source_mismatch"
    requested_breakdowns = set(contract.get("breakdown_ids") or [])
    proposed_breakdowns = set((spec or {}).get("selection", []) if spec else candidate.get("selection", []))
    if requested_breakdowns != proposed_breakdowns:
        return "intent_breakdown_mismatch"
    requested_filters = set(contract.get("filter_ids") or [])
    proposed_filters = set((f.get("field") for f in (spec or {}).get("filters", []))) if spec else set(candidate_filter_ids(candidate))
    if requested_filters != proposed_filters:
        return "intent_filter_mismatch"
    return None


def materialize_catalog_intent(candidate: dict, cat) -> dict | None:
    """Complete only omitted metric/source/group slots from an explicit catalog contract.

    Filter values remain exclusively from the user-facing candidate; this never invents them.
    """
    contract = candidate.get("intent_contract") or {}
    if contract.get("kind") != "catalog_metric":
        return None
    metrics = contract.get("metric_ids") or []
    if not metrics or any(metric not in cat.mets for metric in metrics):
        return None
    if metric_operation(cat, metrics) != contract.get("operation"):
        return None
    out = dict(candidate)
    if not candidate_metric_ids(out):
        out["recipe"] = metrics[0] if len(metrics) == 1 else ""
        out["metrics"] = metrics if len(metrics) > 1 else []
    if not out.get("source_ids") and contract.get("source_ids"):
        out["source_ids"] = list(contract["source_ids"])
    if not out.get("selection") and contract.get("breakdown_ids"):
        out["selection"] = list(contract["breakdown_ids"])
    if set(contract.get("filter_ids") or []) != set(candidate_filter_ids(out)):
        return None
    if mismatch(out, cat):
        return None
    return out


def resolve_ambiguous_contract(candidate: dict, selected_metric: str, cat, *, offered_metrics=()) -> dict:
    """Bind explicit user intent from model alternatives or a server-issued form.

    The server policy can discover ambiguity the model missed. Its actual offered
    choices are authoritative; an arbitrary caller-supplied metric cannot replace
    a non-catalog measure or silently change a previously confirmed request.
    """
    contract = candidate.get("intent_contract") or {}
    alternatives = set(candidate.get("recipe_alternatives") or [])
    permitted = (contract.get("kind") == "ambiguous_metric" and selected_metric in alternatives) or (
        contract.get("kind") == "catalog_metric" and selected_metric in offered_metrics)
    if not permitted or selected_metric not in cat.mets:
        return candidate
    metric = cat.mets[selected_metric]
    operation = metric_operation(cat, [selected_metric])
    updated = dict(candidate)
    updated["intent_contract"] = contract | {"kind": "catalog_metric", "metric_ids": [selected_metric],
                                             "operation": operation,
                                             "grain": metric.intent_grain or "unspecified"}
    return updated
