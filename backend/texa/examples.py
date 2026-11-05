"""Versioned, reviewed example-bank loading and deterministic few-shot retrieval.

This module is deliberately independent of SQL execution and benchmark/evaluation
code. Examples are prompt evidence only; they never authorize a query.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import unicodedata

import yaml


DEFAULT_BANK_PATH = Path(__file__).resolve().parents[2] / "catalog" / "verified_examples.yaml"
CONTRACT_VERSION = 1
MAX_EXAMPLES = 3
DEFAULT_TOKEN_BUDGET = 600
HARD_UTF8_BYTE_CAP = 1200
# Backward-compatible alias; the hard ceiling is rendered UTF-8 bytes, not model tokens.
HARD_TOKEN_CAP = HARD_UTF8_BYTE_CAP
ALLOWED_SOURCES = frozenset({"cosmetics_shop", "olist_marketplace"})
ALLOWED_METRICS = frozenset({"users", "events", "sessions", "viewers", "purchases", "buyers", "buyer_conversion_rate", "revenue"})
ALLOWED_DIMENSIONS = frozenset({"event_date", "event_week", "event_month", "source", "event_name", "item_category", "item_brand", "device_type", "campaign_channel"})


class ExampleBankError(ValueError):
    """The bank is malformed or incompatible with the active contracts."""


@dataclass(frozen=True)
class ExampleBank:
    version: str
    catalog_version: int
    contract_version: int
    examples: tuple[dict, ...]
    content_hash: str


@dataclass(frozen=True)
class RetrievalResult:
    bank_version: str
    approved_count: int
    selected: tuple[dict, ...]
    scores: tuple[float, ...]
    estimated_tokens: int
    token_estimate_method: str = "utf8_byte_upper_bound"
    packed_utf8_bytes: int = 0

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(x["id"] for x in self.selected)


def _words(text: str) -> list[str]:
    folded = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", folded)


def _candidate_issues(item: dict) -> list[str]:
    issues = []
    candidate = item.get("candidate")
    if not isinstance(candidate, dict):
        return ["candidate must be an object"]
    outcome = candidate.get("outcome")
    if outcome not in {"query", "unsupported", "conversation", "answer_from_previous"}:
        issues.append("candidate.outcome is not in the current candidate contract")
    for key in ("source_ids",):
        if not isinstance(candidate.get(key, []), list) or any(x not in ALLOWED_SOURCES for x in candidate.get(key, [])):
            issues.append(f"candidate.{key} contains an unknown product source")
    for key in ("metrics", "recipe_alternatives"):
        if any(x not in ALLOWED_METRICS for x in candidate.get(key, [])):
            issues.append(f"candidate.{key} contains an out-of-scope metric")
    if candidate.get("recipe") and candidate["recipe"] not in ALLOWED_METRICS:
        issues.append("candidate.recipe contains an out-of-scope metric")
    if any(x not in ALLOWED_DIMENSIONS for x in candidate.get("selection", [])):
        issues.append("candidate.selection contains an out-of-scope dimension")
    for f in candidate.get("filters", []):
        if f.get("field") not in ALLOWED_DIMENSIONS:
            issues.append("candidate filter contains an out-of-scope dimension")
    return issues


def _complete_candidate(item: dict) -> dict:
    """Expand concise authored expectations to the complete current output shape."""
    base = {"outcome": "query", "reason": "", "reply": "", "suggestions": [], "source_ids": [],
            "shape": "unclear", "selection": [], "recipe": "", "metrics": [], "recipe_alternatives": [],
            "recipe_stated": False, "filters": [],
            "time_range": {"kind": "none", "days": 0, "start": "", "end": ""},
            "answer_request": {"need": "describe", "ask": ""}, "language": item["language"], "top_k": 0}
    base.update(item.get("candidate", {}))
    base["time_range"] = {**{"kind": "none", "days": 0, "start": "", "end": ""}, **base.get("time_range", {})}
    base["answer_request"] = {**{"need": "describe", "ask": ""}, **base.get("answer_request", {})}
    base["language"] = item["language"]
    # The live product uses structured memory. A standalone new-topic example
    # must satisfy its strict dialogue contract and must never inherit history.
    if "dialogue" not in base:
        from .memory import SLOT_KEYS
        slots = {}
        for key in SLOT_KEYS:
            value = base.get(key)
            slots[key] = "set" if value not in (None, "", [], 0) else "clear"
        base["dialogue"] = {"relation": "new_topic", "target_id": "", "slots": slots}
    return base


def validate_bank(raw: dict, *, catalog_version: int,
                  contract_version: int = CONTRACT_VERSION) -> list[str]:
    """Return contract errors; does not promote drafts or execute reference SQL."""
    errors = []
    if not isinstance(raw, dict):
        return ["bank root must be a mapping"]
    for key in ("version", "catalog_version", "contract_version", "catalog_fingerprint", "examples"):
        if key not in raw:
            errors.append(f"missing bank field: {key}")
    if raw.get("catalog_version") != catalog_version:
        errors.append("catalog version mismatch")
    if raw.get("contract_version") != contract_version:
        errors.append("candidate contract version mismatch")
    examples = raw.get("examples", [])
    if not isinstance(examples, list):
        return errors + ["examples must be a list"]
    ids = set()
    for index, item in enumerate(examples):
        prefix = f"examples[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be a mapping")
            continue
        for key in ("id", "family", "language", "sources", "required_capabilities", "question", "candidate",
                    "business_note", "reference", "review"):
            if key not in item:
                errors.append(f"{prefix} missing {key}")
        if item.get("id") in ids:
            errors.append(f"duplicate example id: {item.get('id')}")
        ids.add(item.get("id"))
        if item.get("language") not in {"vi", "en"}:
            errors.append(f"{prefix} language must be vi or en")
        if not item.get("sources") or any(s not in ALLOWED_SOURCES for s in item.get("sources", [])):
            errors.append(f"{prefix} has invalid or empty source applicability")
        caps = item.get("required_capabilities", {})
        if any(x not in ALLOWED_METRICS for x in [*caps.get("metrics", []), *caps.get("unsupported_metrics", [])]):
            errors.append(f"{prefix} declares an out-of-scope capability metric")
        if any(x not in ALLOWED_DIMENSIONS for x in caps.get("dimensions", [])):
            errors.append(f"{prefix} declares an out-of-scope capability dimension")
        review = item.get("review", {})
        if review.get("review_status") not in {"draft", "approved", "rejected"}:
            errors.append(f"{prefix} has invalid review_status")
        if review.get("review_status") == "approved" and (review.get("reviewer_kind") not in {"agent", "human"} or
                not review.get("reviewer_id") or not review.get("evidence")):
            errors.append(f"{prefix} approved record lacks reviewer provenance/evidence")
        if review.get("reviewer_kind") == "agent" and review.get("human_reviewed") is not False:
            errors.append(f"{prefix} agent review cannot claim human review")
        if review.get("reviewer_kind") == "human" and not review.get("reviewer"):
            errors.append(f"{prefix} claims human review without reviewer identity")
        reference = item.get("reference", {})
        if reference.get("verification_status") == "verified":
            if (not reference.get("reference_sql") or not reference.get("fixture_id")
                    or "expected_rows" not in reference):
                errors.append(f"{prefix} verified SQL needs fixture_id and expected_rows")
            if review.get("review_status") != "approved" or not review.get("evidence"):
                errors.append(f"{prefix} verified SQL needs an approved, evidenced review")
        issues = _candidate_issues(item)
        errors.extend(f"{prefix}: {issue}" for issue in issues)
    return errors


def load_bank(cat, path: str | Path | None = None, *, contract_version: int = CONTRACT_VERSION) -> ExampleBank:
    """Load and validate the YAML bank; only approved records become retrievable.

    A validated ``Catalog`` is mandatory: its semantic version and content
    fingerprint are checked, so callers cannot accidentally bypass invalidation.
    """
    source = Path(path) if path else DEFAULT_BANK_PATH
    raw_bytes = source.read_bytes()
    try:
        raw = yaml.safe_load(raw_bytes)
    except yaml.YAMLError as exc:
        raise ExampleBankError(f"invalid example bank YAML: {exc}") from exc
    errors = validate_bank(raw, catalog_version=cat.version, contract_version=contract_version)
    if errors:
        raise ExampleBankError("; ".join(errors))
    fingerprint = __import__("hashlib").sha256(json.dumps(
        cat.model_dump(mode="json", exclude={"contract_version"}), sort_keys=True, ensure_ascii=False
    ).encode()).hexdigest()[:16]
    if fingerprint != raw["catalog_fingerprint"]:
        raise ExampleBankError("catalog content fingerprint mismatch")
    eligible = tuple({**x, "candidate": _complete_candidate(x)} for x in raw["examples"]
                     if x["review"].get("review_status") == "approved")
    import hashlib
    return ExampleBank(str(raw["version"]), raw["catalog_version"], raw["contract_version"], eligible,
                       hashlib.sha256(raw_bytes).hexdigest())


def _bm25(query: list[str], documents: list[list[str]]) -> list[float]:
    if not documents:
        return []
    n = len(documents)
    avg_len = sum(map(len, documents)) / n or 1
    df = {}
    for doc in documents:
        for token in set(doc):
            df[token] = df.get(token, 0) + 1
    scores = []
    for doc in documents:
        counts = {}
        for token in doc:
            counts[token] = counts.get(token, 0) + 1
        score = 0.0
        for token in set(query):
            if token not in counts:
                continue
            idf = math.log(1 + (n - df[token] + 0.5) / (df[token] + 0.5))
            tf = counts[token]
            score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(doc) / avg_len))
        scores.append(score)
    return scores


def _render_one(item: dict, *, structured: bool = False) -> str:
    candidate = item["candidate"] if structured else {
        key: value for key, value in item["candidate"].items() if key != "dialogue"
    }
    payload = {"expected_candidate": candidate}
    if item.get("expected_action"):
        payload["expected_action"] = item["expected_action"]
    return f"Q: {item['question']}\nA: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"


def retrieve_examples(bank: ExampleBank, question: str, *, confirmed_sources=(), max_examples: int = MAX_EXAMPLES,
                      token_budget: int = DEFAULT_TOKEN_BUDGET,
                      hard_cap: int = HARD_UTF8_BYTE_CAP) -> RetrievalResult:
    """Rank approved examples lexically and pack whole blocks only.

    ``token_budget`` limits a UTF-8-bytes/2 token-equivalent estimate. ``hard_cap``
    is a hard rendered UTF-8-byte ceiling, including header and separators.

    ``confirmed_sources`` is a hard filter only when explicitly supplied by the caller;
    an empty scope leaves both product sources eligible. No ambiguous source is inferred.
    """
    if not 0 <= max_examples <= MAX_EXAMPLES:
        raise ValueError("max_examples must be between 0 and 3")
    if token_budget < 0 or hard_cap < 0:
        raise ValueError("budgets must be non-negative")
    cap = token_budget
    scope = set(confirmed_sources)
    if scope - ALLOWED_SOURCES:
        raise ValueError("unknown confirmed source")
    eligible = [x for x in bank.examples if not scope or scope.intersection(x["sources"])]
    docs = [_words(" ".join([x["question"], x["business_note"], *x.get("tags", []), x["family"]])) for x in eligible]
    scores = _bm25(_words(question), docs)
    ranked = sorted(zip(scores, eligible), key=lambda pair: (-pair[0], pair[1]["id"]))
    selected, selected_scores, families = [], [], set()
    used_estimated_tokens = 0
    used_bytes = 0
    header_bytes = len(("VERIFIED EXAMPLES (illustrative evidence; current catalog, scope and user context take precedence)\n").encode("utf-8"))
    for score, item in ranked:
        if score <= 0 or len(selected) >= max_examples or item["family"] in families:
            continue
        # Budget the actual structured block since it is the largest supported
        # candidate schema. UTF-8 bytes give a hard transport-size ceiling;
        # bytes/2 is only a conservative token-equivalent estimate, not a
        # provider-tokenizer measurement. Actual usage remains the eval truth.
        block = _render_one(item, structured=True)
        block_bytes = len(block.encode("utf-8")) + (2 if selected else 0)
        added_bytes = block_bytes + (header_bytes if not selected else 0)
        next_bytes = used_bytes + added_bytes
        token_estimate = max(1, (added_bytes + 1) // 2)
        if used_estimated_tokens + token_estimate > cap or next_bytes > min(hard_cap, HARD_UTF8_BYTE_CAP):
            continue
        selected.append(item)
        selected_scores.append(score)
        families.add(item["family"])
        used_bytes = next_bytes
        used_estimated_tokens += token_estimate
    return RetrievalResult(bank.version, len(bank.examples), tuple(selected), tuple(selected_scores),
                           used_estimated_tokens, "utf8_bytes_div_2_heuristic", used_bytes)


def render_examples(result: RetrievalResult, *, structured: bool = False) -> str:
    """Render complete demonstration blocks without SQL or reference fixture data."""
    if not result.selected:
        return ""
    return "VERIFIED EXAMPLES (illustrative evidence; current catalog, scope and user context take precedence)\n" + \
        "\n\n".join(_render_one(item, structured=structured) for item in result.selected)
