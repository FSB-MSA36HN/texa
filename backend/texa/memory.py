"""Deterministic conversation state helpers for multi-turn analytics questions.

This module is intentionally pure: callers own persistence and may use an LLM's
interpretation to override the conservative relation decision from select_context.
"""
from __future__ import annotations

import re
import unicodedata
from copy import deepcopy
from typing import Any

SLOT_KEYS = ("source_ids", "recipe", "metrics", "selection", "filters", "time_range", "shape", "top_k")
FOLLOWUP_CUES = {
    "and", "also", "instead", "now", "what about", "same", "again", "only", "just", "then",
    "còn", "vậy", "thế", "cũng", "riêng", "chỉ", "đổi", "thay", "tiếp", "nữa", "theo tuần",
    "theo tháng", "theo ngày", "tại sao", "vì sao", "giải thích", "cụ thể hơn",
    "kết quả đó", "kết quả này", "that result", "this result", "thêm điều kiện", "add a filter", "add the filter",
}
RETURN_CUES = {"back to", "return to", "go back to", "quay lại", "trở lại", "noi lai", "nói lại", "earlier", "before"}
EXPLICIT_NEW_CUES = {"new question", "different topic", "chủ đề khác", "câu hỏi khác", "đổi chủ đề"}
EXPLANATION_CUES = {"why", "explain", "what does this mean", "tại sao", "vì sao", "giải thích", "ý nghĩa"}
BREAKDOWN_PREFIX_CUES = {"chia theo", "break down by", "broken down by", "by", "theo", "tính theo", "không,", "actually", "no,"}
STOP_WORDS = {
    "the", "a", "an", "is", "are", "of", "for", "in", "on", "by", "to", "and", "or", "what", "how",
    "show", "me", "please", "data", "all", "last", "month", "week", "day", "theo", "cua",
    "của", "cho", "toi", "tôi", "la", "là", "bao", "nhieu", "nhiều", "so", "số", "tren", "trên", "ve", "về",
}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch)).replace("đ", "d")


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_]+", _fold(text)) if len(w) > 1 and w not in STOP_WORDS}


def _state(turn: dict) -> dict:
    state = turn.get("state")
    return state if isinstance(state, dict) else turn


def _spec(turn: dict) -> dict:
    state = _state(turn)
    spec = state.get("query_spec") or state.get("spec") or {}
    return spec if isinstance(spec, dict) else {}


def _topic(turn: dict) -> set[str]:
    spec = _spec(turn)
    ids = set()
    for key in ("recipe", "source_ids", "metrics", "selection"):
        val = spec.get(key) or []
        ids.update([val] if isinstance(val, str) else val)
    for filt in spec.get("filters", []) or []:
        ids.add(filt.get("field", ""))
    question = turn.get("question", "")
    return {str(x).lower() for x in ids if x} | _words(question)


def _turn_id(turn: dict) -> str | None:
    value = turn.get("id") or turn.get("turn_id")
    return str(value) if value is not None else None


def _is_answered(turn: dict) -> bool:
    status = turn.get("status") or _state(turn).get("status")
    return status == "answered" and bool(_spec(turn))


def _has_cue(text: str, cues: set[str]) -> bool:
    folded = _fold(text)
    return any(re.search(rf"(?<![a-z0-9_]){re.escape(_fold(cue))}(?![a-z0-9_])", folded) for cue in cues)


def _starts_with_cue(text: str, cues: set[str]) -> bool:
    folded = _fold(text).lstrip()
    return any(re.match(rf"^{re.escape(_fold(cue))}(?![a-z0-9_])", folded) for cue in cues)


def _ordinal_reference(question: str, history: list[dict], usable: list[dict]) -> tuple[bool, dict | None]:
    """Resolve a stated question/result position before fuzzy topic matching.

    Question positions include social/failed questions; result positions include
    successful answers only. Never silently substitute another answer for a
    requested question that did not produce a compatible result.
    """
    q = _fold(question)
    result_matches = re.findall(r"\b(?:result|ket qua)\s+(?:number\s+|thu\s+)?(\d+)\b", q)
    question_matches = re.findall(r"\b(?:cau(?: hoi)?(?: thu)?|question(?: number)?)\s+(\d+)\b", q)
    first_result = _has_cue(q, {"first result", "kết quả đầu"})
    first_question = _has_cue(q, {"first question", "câu đầu", "câu hỏi đầu"})
    pointers = {(True, int(n) - 1) for n in result_matches} | {(False, int(n) - 1) for n in question_matches}
    if first_result:
        pointers.add((True, 0))
    if first_question:
        pointers.add((False, 0))
    if not pointers:
        return False, None
    if len(pointers) != 1:
        return True, None
    is_result, index = pointers.pop()
    candidates = usable if is_result else history
    target = candidates[index] if 0 <= index < len(candidates) else None
    return True, target if target is not None and target in usable else None


def apply_turn(committed: dict | None, turn: dict, *, catalog_version: int | None = None,
               dataset_version: str | int | None = None, source_snapshot: Any = None,
               context: dict | None = None) -> dict:
    """Return memory after a turn, keeping clarification drafts separate.

    Only answered turns commit slots. Each changed slot carries its source turn
    and question as provenance; a pending clarification never overwrites them.
    """
    memory = deepcopy(committed or {"version": 1, "topics": [], "active_topic_id": None, "pending": None})
    memory.setdefault("version", 1)
    memory.setdefault("topics", [])
    state = _state(turn)
    status = turn.get("status") or state.get("status", "")
    if status in {"needs_clarification", "running"}:
        memory["pending"] = {
            "turn_id": _turn_id(turn), "question": turn.get("question", ""),
            "candidate": deepcopy(state.get("candidate") or {}),
            "answers": deepcopy(state.get("answers") or {}),
        }
        return memory
    if status != "answered":
        return memory

    spec = deepcopy(_spec(turn))
    if not spec:
        return memory
    version = catalog_version if catalog_version is not None else spec.get("contract_version")
    dataset_version = dataset_version if dataset_version is not None else state.get("dataset_version")
    source_snapshot = source_snapshot if source_snapshot is not None else state.get("source_snapshot")
    if ((memory.get("catalog_version") not in (None, version)) or
            (dataset_version is not None and memory.get("dataset_version") not in (None, dataset_version)) or
            (source_snapshot is not None and memory.get("source_snapshot") not in (None, source_snapshot))):
        # Do not silently carry definitions across a changed semantic catalog.
        memory["topics"] = []
        memory["active_topic_id"] = None
    memory["catalog_version"] = version
    if dataset_version is not None:
        memory["dataset_version"] = dataset_version
    if source_snapshot is not None:
        memory["source_snapshot"] = deepcopy(source_snapshot)
    topic_id = _turn_id(turn) or f"topic-{len(memory['topics']) + 1}"
    refs = set((context or {}).get("references") or [])
    followup = (context or {}).get("relation") == "followup"
    prior_topic = next((t for t in reversed(memory["topics"]) if followup and (t.get("id") in refs or t.get("result_ref") in refs)), None)
    topic = deepcopy(prior_topic) if prior_topic else {
        "id": topic_id, "question": turn.get("question", ""), "slots": {},
        "result_ref": _turn_id(turn), "updated_at": turn.get("created_at"),
    }
    topic["question"] = turn.get("question", "")
    topic["result_ref"] = _turn_id(turn)
    topic["updated_at"] = turn.get("created_at")
    for key in SLOT_KEYS:
        if key not in spec:
            continue
        old = topic["slots"].get(key)
        if old is not None and old.get("value") == spec[key]:
            continue  # Preserve the turn that originally supplied an unchanged slot.
        topic["slots"][key] = {
            "value": deepcopy(spec[key]), "turn_id": _turn_id(turn),
            "question": turn.get("question", ""), "catalog_version": version,
        }
    if prior_topic:
        memory["topics"] = [t for t in memory["topics"] if t.get("id") != prior_topic.get("id")]
    memory["topics"].append(topic)
    memory["topics"] = memory["topics"][-50:]
    memory["active_topic_id"] = topic["id"]
    memory["pending"] = None
    return memory


def _score(question: str, turn: dict) -> float:
    query = _fold(question)
    for cue in sorted(RETURN_CUES | EXPLANATION_CUES | BREAKDOWN_PREFIX_CUES, key=len, reverse=True):
        query = re.sub(rf"(?<![a-z0-9_]){re.escape(_fold(cue))}(?![a-z0-9_])", " ", query)
    q = _words(query)
    t = _topic(turn)
    if not q or not t:
        return 0.0
    overlap = len(q & t)
    return overlap / max(1, len(q))


def select_context(history: list[dict], question: str, *, catalog_version: int | None = None,
                   max_turns: int = 6, ordinal_history: list[dict] | None = None) -> dict[str, Any]:
    """Select relevant conversational turns and decide whether slots may carry.

    Full history can be passed in; this function selects a bounded prompt view
    while retaining distant topic matches. Ambiguous result references are
    surfaced to the caller for a clarification question.
    """
    if max_turns < 0:
        raise ValueError("max_turns must be non-negative")
    usable = [t for t in history if _is_answered(t) and (catalog_version is None or
                                    _spec(t).get("contract_version", catalog_version) == catalog_version)]
    active = next((t for t in reversed(usable) if _is_answered(t)), None)
    q = _fold(question).strip()
    qwords = _words(question)
    explicit_new = _has_cue(q, EXPLICIT_NEW_CUES)
    returning = _has_cue(q, RETURN_CUES)
    explanation = _has_cue(q, EXPLANATION_CUES)
    breakdown_fragment = _starts_with_cue(q, BREAKDOWN_PREFIX_CUES)
    followup = (_has_cue(q, FOLLOWUP_CUES) or breakdown_fragment or len(qwords) <= 1) and not explicit_new
    ordinal_stated, ordinal_target = _ordinal_reference(question, history if ordinal_history is None else ordinal_history, usable)

    scored = sorted((( _score(question, t), i, t) for i, t in enumerate(usable)), reverse=True, key=lambda x: (x[0], x[1]))
    # Require a strong overlap: a shared store name alone must not bind a new
    # metric/dimension query to the previous result.
    relevant = [t for score, _, t in scored if score >= 0.5]
    top_score = scored[0][0] if scored else 0.0
    tied = [t for score, _, t in scored if score > 0 and score == top_score]
    # Explain/this/that and explicit returns need a unique matching result.
    answered = [t for t in usable if _is_answered(t)]
    plausible_ties = [t for score, _, t in scored if score == top_score and score > 0.5]
    ambiguous = not explicit_new and (
        (explanation and len(answered) > 1 and len(plausible_ties) != 1) or
        (returning and len(answered) > 1 and (not plausible_ties or len(plausible_ties) > 1))
    )
    if ordinal_stated and not explicit_new:
        ambiguous = ordinal_target is None

    relation = "new_topic"
    chosen = None
    if explicit_new:
        relation = "new_topic"
    elif ordinal_target is not None:
        chosen = ordinal_target
        relation = "followup"
    elif ambiguous:
        relation = "ambiguous"
    elif returning and relevant:
        chosen = scored[0][2]
        relation = "followup"
    elif explanation and relevant and top_score >= 0.5:
        chosen = scored[0][2]
        relation = "followup"
    elif explanation and len(answered) == 1:
        chosen = answered[-1]
        relation = "followup"
    elif returning and len(answered) == 1:
        chosen = answered[-1]
        relation = "followup"
    elif followup and active:
        chosen = active
        relation = "followup"

    # A terse continuation uses only the current active query. Topic lookup can
    # find older results, but must not cause unrelated active slots to leak in.
    if chosen is None and relation == "ambiguous":
        possible = plausible_ties or tied or answered
        refs = [str(_turn_id(t)) for t in possible if _turn_id(t)]
    else:
        refs = [str(_turn_id(chosen))] if chosen and _turn_id(chosen) else []
    selected = []
    if max_turns == 0:
        return {
            "turns": [], "relation": relation, "references": refs,
            "active_state": deepcopy(_spec(active)) if active else None,
            "inherited_slots": {}, "clarification_needed": ambiguous,
            "reason": "multiple plausible result references" if ambiguous else
                      ("matched prior topic" if chosen else "no confident prior-topic match"),
        }
    # A standalone, sufficiently specified query starts fresh even if it shares
    # broad words/source identifiers with older turns. Explicit topic switches
    # likewise receive no prior result text in their prompt context.
    context_candidates = relevant if relation == "followup" and (returning or explanation) and not ordinal_stated else []
    for t in (context_candidates[:max_turns] if context_candidates else ([chosen] if chosen else [])):
        if t is not None and t not in selected:
            selected.append(t)
    if chosen and chosen not in selected and len(selected) < max_turns:
        selected.append(chosen)
    selected.sort(key=lambda t: usable.index(t))
    inherited = {}
    if chosen and relation == "followup":
        for key, value in _spec(chosen).items():
            if key in SLOT_KEYS:
                inherited[key] = deepcopy(value)
    return {
        "turns": selected, "relation": relation, "references": refs,
        "active_state": deepcopy(_spec(active)) if active else None,
        "inherited_slots": inherited, "clarification_needed": ambiguous,
        "reason": "multiple plausible result references" if ambiguous else
                  ("matched prior topic" if chosen else "no confident prior-topic match"),
    }


def compatible_results(history: list[dict], catalog_version: int) -> list[dict]:
    """The complete server-owned registry; prompt eviction never changes eligibility."""
    return [t for t in history if _is_answered(t) and _spec(t).get('contract_version') == catalog_version]


def result_registry(history: list[dict], catalog_version: int, ordinal_history: list[dict] | None = None) -> list[dict]:
    usable = compatible_results(history, catalog_version)
    result_positions = {_turn_id(t): i + 1 for i, t in enumerate(t for t in (ordinal_history if ordinal_history is not None else history) if _is_answered(t))}
    positions = {_turn_id(t): i + 1 for i, t in enumerate(ordinal_history if ordinal_history is not None else history)}
    return [{'id': _turn_id(t), 'result_number': result_positions[_turn_id(t)], 'question_number': positions[_turn_id(t)], 'question': t.get('question', ''),
             'reading': {k: deepcopy(v) for k, v in _spec(t).items() if k in SLOT_KEYS}}
            for i, t in enumerate(usable)]


def reduce_candidate(candidate: dict, history: list[dict], catalog_version: int,
                     forced_reference: str | None = None) -> tuple[dict, dict]:
    """Validate the semantic resolver's pointer, then apply keep/set/clear on the server.

    The model proposes meaning; it cannot invent a reference, inherit from a stale
    snapshot, or change a kept slot by emitting different candidate values.
    Callers must pass only this conversation's current-snapshot history.
    """
    from . import llm
    decision = candidate.get('dialogue')
    if not isinstance(decision, dict):
        raise llm.LLMError('MODEL_OUTPUT_INVALID', 'Missing structured dialogue decision.')
    relation = decision.get('relation')
    if forced_reference and (relation != 'followup' or candidate.get('outcome') == 'conversation'):
        raise llm.LLMError('MODEL_OUTPUT_INVALID', 'An explicitly selected reference cannot be ignored.')
    registry = compatible_results(history, catalog_version)
    target_id = forced_reference or decision.get('target_id')
    target = next((t for t in registry if _turn_id(t) == target_id), None)
    context = {'relation': relation, 'references': [], 'inherited_slots': {}, 'clarification_needed': False}
    if forced_reference and target is not None and relation != 'social':
        relation = 'followup'
        context['relation'] = relation
    if (relation == 'ambiguous' or (relation == 'followup' and target is None)
            or (relation == 'followup' and not forced_reference and not candidate.get('_registry_complete', True))):
        context.update(relation='ambiguous', clarification_needed=True)
        return deepcopy(candidate), context
    if relation not in {'new_topic', 'followup', 'social'}:
        raise llm.LLMError('MODEL_OUTPUT_INVALID', 'Invalid dialogue relation.')
    if forced_reference and relation != 'social':
        relation = 'followup'
        context['relation'] = relation
    if relation == 'new_topic' and target_id and not forced_reference:
        raise llm.LLMError('MODEL_OUTPUT_INVALID', 'A new topic cannot inherit an earlier result.')
    inherited = _spec(target) if relation == 'followup' and target else {}
    if inherited:
        context.update(references=[_turn_id(target)], inherited_slots=deepcopy(inherited))
    defaults = {'source_ids': [], 'recipe': '', 'metrics': [], 'selection': [], 'filters': [],
                'time_range': {'kind': 'none', 'days': 0, 'start': '', 'end': ''}, 'shape': 'unclear', 'top_k': 0}
    out = deepcopy(candidate)
    operations = decision.get('slots', {})
    if relation == 'social':
        return out, context
    for key in SLOT_KEYS:
        operation = operations.get(key)
        if operation not in {'keep', 'set', 'clear'}:
            raise llm.LLMError('MODEL_OUTPUT_INVALID', f'Missing slot operation: {key}.')
        if operation == 'keep':
            if not inherited:
                raise llm.LLMError('MODEL_OUTPUT_INVALID', 'Cannot keep slots without a compatible reference.')
            value = deepcopy(inherited.get(key, defaults[key]))
            if key == 'filters':
                value = [{'field': f['field'], 'operator': f['operator'],
                          'values_mentioned': f.get('values', f.get('values_mentioned', []))} for f in value]
            if key == 'time_range':
                value = {k: v for k, v in value.items() if k in {'kind', 'days', 'start', 'end'}}
            out[key] = value if value is not None else deepcopy(defaults[key])
        elif operation == 'clear':
            out[key] = deepcopy(defaults[key])
    # Alternatives are an interpretation of the current request, not an old metric.
    if inherited and operations.get('recipe') == 'keep' and operations.get('metrics') == 'keep':
        out['recipe_alternatives'] = []
        out['recipe_stated'] = True
    context['slot_operations'] = deepcopy(operations)
    return out, context


def bounded_registry(registry: list[dict], token_budget: int) -> tuple[list[dict], bool]:
    """Bound prompt evidence without changing the complete server registry.

    If any entries are omitted, an unforced followup must ask the user to choose
    from the complete registry instead of guessing from the partial prompt view.
    Independent questions remain usable even in arbitrarily long conversations.
    """
    import json
    selected, used = [], 0
    for item in reversed(registry):
        cost = (len(json.dumps(item, ensure_ascii=False, default=str)) + 3) // 4 + 2
        if used + cost > token_budget:
            break
        selected.append(item)
        used += cost
    selected.reverse()
    return selected, len(selected) == len(registry)
