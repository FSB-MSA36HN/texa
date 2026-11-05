"""Bounded same-model consistency selection over validated semantic resolutions.

No execution results or benchmark annotations participate in selection. Optional
samples use the identical prompt and provider defaults; diversity is measured,
not assumed. Only the selected proposal reaches the normal durable answer path.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait
from contextvars import copy_context
from copy import deepcopy
import hashlib
import json
import threading
import time

from . import llm
from .progress import Cancelled
from .spec import SpecError

_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="texa-consistency")
_EXPANSION = threading.BoundedSemaphore(1)
DEADLINE_S = 95


def fingerprint(bundle):
    """Normalize AND-filter order, preserving dimensions, types, NULL and operations."""
    bundle = deepcopy(bundle)
    spec = bundle.get("spec", {})
    if "filters" in spec:
        spec["filters"] = sorted(spec["filters"], key=lambda x: json.dumps(x, sort_keys=True, default=str))
    encoded = json.dumps(bundle, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def trigger(candidate, bundle):
    if bundle.get("kind") == "unsupported" and bundle.get("supported_proposal"):
        return "catalog_supported_refusal"
    if bundle.get("kind") != "spec":
        return None  # Missing user information must be asked, never majority-guessed.
    filters = bundle["spec"].get("filters", [])
    if len(filters) >= 2:
        return "composed_filters"
    if filters and bundle["spec"].get("recipe") == "buyer_conversion_rate":
        return "filtered_ratio"
    decision = candidate.get("dialogue", {})
    if decision.get("relation") == "followup" and sum(v == "set" for v in decision.get("slots", {}).values()) >= 2:
        return "multi_slot_followup"
    return None


def select(primary, sample, normalize, *, cancelled=lambda: False, timeout=DEADLINE_S, primary_error=None):
    """Return (whole proposal, privacy-safe trace); normalize is a pure read-only callback.

    At most one request may expand at a time per process. Each child call still
    independently uses provider admission and the existing cost guard.
    """
    trace = {"enabled": True, "scheduled": 1, "completed": 1, "errors": 0,
             "sampling": "independent_identical_prompt_provider_defaults", "selected": 0}
    try:
        if primary_error:
            raise llm.LLMError(primary_error, "The initial structured interpretation was invalid.")
        first = normalize(deepcopy(primary))
        reason = trigger(primary, first)
    except (llm.LLMError, SpecError) as exc:
        first, reason = None, "invalid_interpretation"
        trace["primary_error"] = exc.code
        trace["errors"] = 1
    if not reason:
        return primary, trace | {"trigger": None, "fallback": "not_eligible"}
    trace["trigger"] = reason
    if cancelled():
        raise Cancelled()
    if not _EXPANSION.acquire(blocking=False):
        return primary, trace | {"fallback": "sampling_capacity"}
    futures = []
    try:
        for _ in range(2):
            ctx = copy_context()
            futures.append(_POOL.submit(ctx.run, sample))
        trace["scheduled"] = 3
        pending = set(futures)
        deadline = time.monotonic() + timeout
        while pending and not cancelled():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            _, pending = wait(pending, timeout=min(0.1, remaining))
        proposals, bundles = [primary], [first]
        fatal = None
        for future in futures:
            if future in pending:
                future.cancel()
                proposals.append(None)
                bundles.append(None)
                trace["errors"] += 1
                continue
            trace["completed"] += 1
            try:
                proposal = future.result()
                bundle = normalize(deepcopy(proposal))
                proposals.append(proposal)
                bundles.append(bundle)
            except Exception as exc:
                proposals.append(None)
                bundles.append(None)
                trace["errors"] += 1
                if not isinstance(exc, (llm.LLMError, SpecError)) or getattr(exc, "code", "") in {
                    "BUDGET_EXHAUSTED", "AUTH", "NO_KEY", "BAD_MODEL"}:
                    fatal = exc
        # In-flight calls may settle usage after timeout, but never mutate a turn.
        if pending:
            outstanding = set(pending)
            lock = threading.Lock()
            def release(future):
                with lock:
                    outstanding.discard(future)
                    if not outstanding:
                        _EXPANSION.release()
            for future in pending:
                future.add_done_callback(release)
            futures = None  # callbacks own expansion lease until every request exits
        if cancelled():
            raise Cancelled()
        if fatal is not None:
            raise fatal
        keys = [fingerprint(b) if b is not None and b.get("kind") == "spec" else None for b in bundles]
        counts = Counter(k for k in keys if k is not None)
        trace.update(fingerprints=keys, vote_counts=sorted(counts.values(), reverse=True),
                     distinct_valid=len(counts))
        winner = next((k for k, count in counts.items() if count >= 2), None)
        if winner:
            index = keys.index(winner)
            return proposals[index], trace | {"selected": index, "fallback": None}
        # Agreement cannot fill missing information. Preserve an actual ask if one arose.
        for proposal, bundle in zip(proposals, bundles):
            if bundle and bundle.get("kind") == "clarify":
                return proposal, trace | {"selected": proposals.index(proposal), "fallback": "clarification_required"}
        out = deepcopy(primary)
        out.update(_consistency_unresolved=True, outcome="unsupported", reason=(
            "Chưa xác định chắc cách hiểu câu hỏi. Bạn hãy nêu rõ chỉ số, nguồn, thời gian và điều kiện lọc."
            if primary.get("language") == "vi" else
            "I could not resolve this request reliably. Please specify the metric, source, period and filters."))
        return out, trace | {"selected": None, "fallback": "no_semantic_majority"}
    finally:
        if futures is not None:
            _EXPANSION.release()
