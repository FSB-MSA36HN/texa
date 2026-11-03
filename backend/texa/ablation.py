"""Offline-only component variants for controlled evaluation experiments."""
from __future__ import annotations

import os

from . import llm

VARIANTS = {"F", "M6", "M0", "C0"}
VARIANT_ENV = "TEXA_ABLATION_VARIANT"
LEGACY_MEMORY_ENV = "TEXA_MEMORY_MODE"


def variant() -> str:
    """Return the validated study variant; the product default remains full Texa."""
    explicit = VARIANT_ENV in os.environ
    selected = os.environ.get(VARIANT_ENV, "F").upper()
    legacy = os.environ.get(LEGACY_MEMORY_ENV)
    if not explicit and legacy == "window6":
        return "M6"
    if selected not in VARIANTS:
        raise llm.LLMError("BAD_ABLATION_VARIANT", f"{VARIANT_ENV} must be one of {', '.join(sorted(VARIANTS))}.")
    if legacy not in (None, "structured", "window6"):
        raise llm.LLMError("BAD_LEGACY_MEMORY_MODE", f"{LEGACY_MEMORY_ENV} must be structured or window6.")
    expected = "window6" if selected == "M6" else "structured"
    if explicit and legacy is not None and legacy != expected:
        raise llm.LLMError("ABLATION_CONFIG_CONFLICT",
                           f"{VARIANT_ENV}={selected} conflicts with {LEGACY_MEMORY_ENV}={legacy!r}; "
                           f"expected {expected!r} or unset {LEGACY_MEMORY_ENV}.")
    return selected


def memory_mode(selected: str | None = None) -> str:
    selected = selected or variant()
    return "window6" if selected == "M6" else "structured"


def memory_disabled(selected: str | None = None) -> bool:
    return (selected or variant()) == "M0"


def initial_trace(selected: str) -> dict:
    return {"variant": selected, "clarification_requested": False, "clarification_eligible": False,
            "clarification_invoked": False, "clarification_field": None, "clarification_choice_id": None,
            "clarification_choices": [], "clarification_choice_count": 0,
            "clarification_reason": "not_applicable"}


def resolve_clarification(candidate: dict, form: dict, question: str, *, model: str | None,
                          turn_id: str | None) -> tuple[dict, dict]:
    """Select only among allowed choices for supported business ambiguities.

    Returns validated form answers plus a compact trace. No answer or hidden gold
    target is supplied to the selector.
    """
    fields = list(form.get("fields") or [])
    permitted = {"time_range", "recipe"}
    targets = [field for field in fields if field.get("id") in permitted]
    if not targets:
        return {}, {"variant": "C0", "activated": False, "field": None, "choice_id": None,
                    "choices": [], "choice_count": 0, "reason": "no_supported_ambiguity"}
    # Keep the initial treatment narrow: one missing reporting period OR one
    # ambiguous metric. Compound/unsupported forms remain ordinary clarification.
    if len(targets) != 1 or len(fields) != 1:
        return {}, {"variant": "C0", "activated": False, "field": None, "choice_id": None,
                    "choices": [], "choice_count": 0, "reason": "compound_form_out_of_scope"}
    field = targets[0]
    choices = field.get("choices") or []
    if field.get("kind") != "single_choice" or field.get("allow_other") or not choices or len(choices) > 20:
        return {}, {"variant": "C0", "activated": False, "field": field["id"], "choice_id": None,
                    "choices": [], "choice_count": len(choices), "reason": "invalid_choice_set"}
    offered = [{"id": str(choice["id"]), "label": str(choice.get("label", "")),
                "description": str(choice.get("description", ""))[:300]} for choice in choices]
    system = ("Choose one option for the missing business detail in an analytics question. "
              "Select only an offered id. If the question provides no basis to choose, return an empty id.")
    prompt = (f"QUESTION\n{question}\n\n"
              f"AMBIGUOUS FIELD\n{field.get('id')}\n{field.get('label', '')}\n\n"
              f"OFFERED OPTIONS\n" + "\n".join(f"{item['id']} | {item['label']} | {item['description']}" for item in offered))
    try:
        response = llm.generate_structured(
            model=model, system=system, prompt=prompt,
            schema={"type": "object", "additionalProperties": False, "required": ["choice_id"],
                    "properties": {"choice_id": {"type": "string"}}},
            name="ablation_guess", turn_id=turn_id, max_output_tokens=120,
        )
    except llm.LLMError:
        return {}, {"variant": "C0", "activated": True, "field": field["id"], "choice_id": None,
                    "choices": [item["id"] for item in offered], "choice_count": len(offered), "reason": "guess_call_failed"}
    selected_id = response.get("choice_id")
    allowed = {item["id"] for item in offered}
    if not isinstance(selected_id, str) or selected_id not in allowed:
        return {}, {"variant": "C0", "activated": True, "field": field["id"], "choice_id": None,
                    "choices": [item["id"] for item in offered], "choice_count": len(offered),
                    "reason": "guess_not_in_offered_choices"}
    return {field["id"]: [selected_id]}, {"variant": "C0", "activated": True, "field": field["id"],
                                         "choice_id": selected_id, "choices": [item["id"] for item in offered],
                                         "choice_count": len(offered), "reason": "selected"}
