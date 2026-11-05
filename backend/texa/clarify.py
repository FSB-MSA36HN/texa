"""Turn the model's reading (candidate) plus the user's form answers into a QuerySpec, or ask with buttons.
No model call happens here: answering a form re-runs this function only."""
import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field

from . import llm
from .catalog import Catalog, Source, display_label, display_description
from .sanity import _metric_gaps, match_values

TEXT = {
    "en": {
        "which_store": "Which store should I use?", "all_stores": "Compare all stores",
        "which_metric": "Which way of counting do you mean?", "which_period": "Which period?",
        "last_7": "Last 7 days", "last_30": "Last 30 days", "last_90": "Last 90 days", "all": "All available data",
        "of_data": "up to {end}", "which_value": "I could not find \"{value}\" in {field}. Did you mean:",
        "need_metric": "Which number should I calculate? For example:", "store": "Store", "metric": "Metric",
        "period": "Period", "no_value": "\"{value}\" does not occur in {field}. Known values include: {examples}.",
        "missing": "Please choose a {field}.", "intro": "A few details before I run this:",
    },
    "vi": {
        "which_store": "Bạn muốn xem dữ liệu của cửa hàng nào?", "all_stores": "So sánh tất cả cửa hàng",
        "which_metric": "Bạn muốn tính theo cách nào?", "which_period": "Khoảng thời gian nào?",
        "last_7": "7 ngày gần nhất", "last_30": "30 ngày gần nhất", "last_90": "90 ngày gần nhất", "all": "Toàn bộ dữ liệu",
        "of_data": "tính đến {end}", "which_value": "Không tìm thấy \"{value}\" trong {field}. Ý bạn là:",
        "need_metric": "Bạn muốn tính chỉ số nào? Ví dụ:", "store": "Cửa hàng", "metric": "Chỉ số",
        "period": "Thời gian", "no_value": "\"{value}\" không có trong {field}. Một số giá trị có: {examples}.",
        "missing": "Vui lòng chọn {field}.", "intro": "Cần làm rõ vài điểm trước khi chạy:",
    },
}
PERIOD_CHOICES = {"last_7": 7, "last_30": 30, "last_90": 90, "all": None}


def t(lang: str, key: str, **kw) -> str:
    return TEXT.get((lang or "en")[:2], TEXT["en"])[key].format(**kw)


@dataclass
class Outcome:
    kind: str                                    # spec | clarify | refuse
    spec: dict | None = None
    form: dict | None = None
    message: str = ""
    suggestions: list[str] = field(default_factory=list)
    variants: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _choice(id_, label, description=""):
    return {"id": id_, "label": label, "description": description}


def _catalog_ambiguities(cat: Catalog, question: str, sources: dict[str, Source], scope: list[str] | None,
                         candidate_sources: list[str] | None = None) -> list[str]:
    """Return answerable metrics declared for a matched ambiguous phrase, independent of LLM confidence."""
    text = _normalize(question)
    selected = scope or candidate_sources
    candidates = [sources[s] for s in selected if s in sources] if selected else list(sources.values())
    found = []
    for rule in cat.metric_ambiguities:
        if not any(re.search(rf"(?<!\w){re.escape(_normalize(phrase))}(?!\w)", text) for phrase in rule.phrases):
            continue
        available = [metric for metric in rule.metric_ids
                     if any(not _metric_gaps(cat, metric, src) for src in candidates)]
        explicit = [metric for metric, terms in rule.disambiguators.items()
                    if any(re.search(rf"(?<!\w){re.escape(_normalize(term))}(?!\w)", text) for term in terms)]
        if len(explicit) == 1:
            continue
        if len(explicit) > 1:
            available = [metric for metric in available if metric in explicit]
        if len(available) > 1:
            found.extend(available)
    return list(dict.fromkeys(found))


def _normalize(text: str) -> str:
    text = " ".join((text or "").casefold().split())
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def advance(candidate: dict, answers: dict[str, list[str]], cat: Catalog, sources: dict[str, Source],
            scope: list[str] | None = None, lang: str = "en", question: str = "") -> Outcome:
    fields, notes = [], []
    examples = [q.question for q in cat.verified_questions[:3]]

    # -- ids must exist: the model may only pick from the catalog ------------------------------------------
    metric_ids = [m for m in [candidate["recipe"], *candidate["metrics"]] if m]
    unknown = [m for m in metric_ids + candidate["recipe_alternatives"] if m not in cat.mets]
    unknown += [d for d in candidate["selection"] + [f["field"] for f in candidate["filters"]] if d not in cat.dims]
    if unknown:
        raise llm.LLMError("MODEL_OUTPUT_INVALID", f"The model used ids that are not in the catalog: {', '.join(unknown)}. Retry or rephrase.")
    if len(metric_ids) > 4:
        return Outcome("refuse", message="Mỗi câu hỏi tối đa 4 chỉ số. Hãy chia thành nhiều câu hỏi." if lang == "vi" else "Ask for at most 4 metrics at once; split the question.", suggestions=examples)

    # -- metric --------------------------------------------------------------------------------------------
    variants = []
    recipe, metrics = candidate["recipe"], list(candidate["metrics"])
    policy_ambiguities = [] if answers.get("recipe") else _catalog_ambiguities(
        cat, question, sources, scope, candidate.get("source_ids") or None)
    if policy_ambiguities:
        candidate = dict(candidate, recipe="", metrics=[], recipe_alternatives=policy_ambiguities,
                         recipe_stated=False)
        recipe, metrics = "", []
    if len(metrics) == 1:
        recipe, metrics = metrics[0], []
    if answers.get("recipe"):
        recipe, metrics = answers["recipe"][0], []
    elif recipe and candidate["recipe_alternatives"] and not candidate.get("recipe_stated"):
        alts = list(dict.fromkeys([recipe, *candidate["recipe_alternatives"]]))
        if len(alts) > 1:
            recipe, metrics = "", []
            fields.append({"id": "recipe", "label": t(lang, "which_metric"), "kind": "single_choice", "required": True,
                           "allow_other": False, "default": [],
                           "choices": [_choice(a, display_label(cat.mets[a], lang), display_description(cat.mets[a], lang)) for a in alts]})
    elif not recipe and not metrics and candidate["recipe_alternatives"]:
        alts = list(dict.fromkeys(candidate["recipe_alternatives"]))
        if len(alts) == 1:
            recipe = alts[0]
        else:
            fields.append({"id": "recipe", "label": t(lang, "which_metric"), "kind": "single_choice", "required": True,
                           "allow_other": False, "default": [],
                           "choices": [_choice(a, display_label(cat.mets[a], lang), display_description(cat.mets[a], lang)) for a in alts]})
    shape = candidate["shape"]
    selection = list(dict.fromkeys(candidate["selection"]))
    if not recipe and not metrics and shape != "distinct_values" and not any(f["id"] == "recipe" for f in fields):
        return Outcome("refuse", message=t(lang, "need_metric"), suggestions=examples)
    if recipe:
        g = cat.variant_group_of(recipe)
        if g:
            variants = [{"id": m, "label": display_label(cat.mets[m], lang), "description": display_description(cat.mets[m], lang)} for m in g.metrics]

    # -- shape follows the selection -----------------------------------------------------------------------
    if shape != "distinct_values":
        has_time = any(cat.dims[d].is_time for d in selection)
        shape = "time_trend" if has_time else ("breakdown" if selection else "aggregate")

    # -- stores --------------------------------------------------------------------------------------------
    chosen = [s for s in candidate["source_ids"] if s in sources]
    if answers.get("source"):
        chosen = list(sources) if "__all__" in answers["source"] else [s for s in answers["source"] if s in sources]
    if not chosen and scope:
        chosen = [s for s in scope if s in sources]
    if not chosen:
        candidates_ = list(sources)
        wanted = [recipe] if recipe else metrics
        if wanted:  # only stores that can compute the metric are worth asking about
            able = [s for s in sources if all(not _metric_gaps(cat, m, sources[s]) for m in wanted)]
            candidates_ = able or candidates_
        if len(candidates_) == 1:
            chosen = candidates_
            if len(sources) > 1:
                notes.append(f"Chỉ {sources[chosen[0]].label} ghi nhận dữ liệu này." if lang == "vi" else f"Only {sources[chosen[0]].label} records this.")
        else:
            fields.append({"id": "source", "label": t(lang, "which_store"), "kind": "single_choice", "required": True,
                           "allow_other": False, "default": [],
                           "choices": [_choice(s, sources[s].label, f"{sources[s].min_date} → {sources[s].max_date}")
                                       for s in candidates_] + ([_choice("__all__", t(lang, "all_stores"))] if cat.policy.max_sources > 1 else [])})
    if len(chosen) > cat.policy.max_sources:
        return Outcome("refuse", message="Mỗi câu hỏi chỉ dùng một nguồn dữ liệu." if lang == "vi" else f"Choose one dataset per question (limit: {cat.policy.max_sources}).", suggestions=examples)

    # -- period --------------------------------------------------------------------------------------------
    tr = candidate["time_range"]
    time_range = None
    if answers.get("time_range"):
        days = PERIOD_CHOICES.get(answers["time_range"][0])
        time_range = {"kind": "all"} if days is None else {"kind": "last_n_days", "days": days}
    elif tr["kind"] == "last_n_days" and tr["days"] > 0:
        time_range = {"kind": "last_n_days", "days": min(tr["days"], 366)}
    elif tr["kind"] == "between" and tr["start"] and tr["end"]:
        try:
            start, end = dt.date.fromisoformat(tr["start"]), dt.date.fromisoformat(tr["end"])
            time_range = {"kind": "between", "start": str(start), "end": str(end)}
            if (end - start).days >= 366:
                time_range = {"kind": "between", "start": str(end - dt.timedelta(days=365)), "end": str(end)}
                notes.append(f"The period was shortened to the last 366 days ({end - dt.timedelta(days=365)} → {end}).")
        except ValueError:
            time_range = None
    elif tr["kind"] == "all" or shape == "distinct_values":
        time_range = {"kind": "all"}
    if time_range is None:
        ends = sorted({sources[s].max_date for s in (chosen or sources) if sources[s].max_date})
        fields.append({"id": "time_range", "label": t(lang, "which_period"), "kind": "single_choice", "required": True,
                       "allow_other": False, "default": ["last_30"],
                       "choices": [_choice(k, t(lang, k), t(lang, "of_data", end=" / ".join(ends)) if k != "all" else "")
                                   for k in PERIOD_CHOICES]})

    # -- filters: values must exist in the data -------------------------------------------------------------
    filters = []
    target_sources = [sources[s] for s in (chosen or sources)]
    for f in candidate["filters"]:
        dim = cat.dims[f["field"]]
        fid = f"filter:{dim.id}"
        typed = [v for v in f["values_mentioned"] if v.strip()]
        if answers.get(fid):
            typed = answers[fid]
        if not typed:
            continue
        resolved, unresolved = (typed, {}) if f["operator"] == "CONTAINS" else match_values(cat, dim.id, typed, target_sources)
        for value, close in unresolved.items():
            if close:
                fields.append({"id": fid, "label": t(lang, "which_value", value=value, field=display_label(dim, lang)),
                               "kind": "multi_choice", "required": True, "allow_other": True, "default": [],
                               "choices": [_choice(c, c) for c in close]})
            else:
                known = sorted({v for s in target_sources for v in s.values.get(cat.mapped_field(dim.field, s.id), {}).values()})
                return Outcome("refuse", message=t(lang, "no_value", value=value, field=display_label(dim, lang),
                                                   examples=", ".join(known[:8]) or "—"), suggestions=examples)
        if unresolved:
            continue
        op = f["operator"]
        if op in ("=", "IN"):
            op = "IN" if len(resolved) > 1 else "="
        elif op in ("!=", "NOT IN"):
            op = "NOT IN" if len(resolved) > 1 else "!="
        else:
            resolved = resolved[:1]
        filters.append({"field": dim.id, "operator": op, "values": resolved})

    # -- policy: fields the organization always wants stated -----------------------------------------------
    for dim_id in cat.policy.ask_when_missing:
        if dim_id in selection or any(f["field"] == dim_id for f in filters):
            continue
        dim = cat.dims[dim_id]
        values = sorted({v for s in target_sources for v in s.values.get(dim.field, {}).values()})
        if answers.get(f"filter:{dim_id}"):
            filters.append({"field": dim_id, "operator": "IN", "values": answers[f"filter:{dim_id}"]})
        elif len(values) > 1:
            fields.append({"id": f"filter:{dim_id}", "label": t(lang, "missing", field=display_label(dim, lang)), "kind": "multi_choice",
                           "required": True, "allow_other": False, "default": [], "choices": [_choice(v, v) for v in values[:50]]})

    if fields:
        return Outcome("clarify", form={"message": t(lang, "intro"), "fields": fields}, variants=variants, notes=notes)

    spec = {"source_ids": chosen, "shape": shape, "selection": selection, "recipe": recipe if recipe else "",
            "metrics": metrics if not recipe else [], "filters": filters, "time_range": time_range}
    if candidate.get("top_k", 0):
        spec["top_k"] = candidate["top_k"]
    return Outcome("spec", spec=spec, variants=variants, notes=notes)
