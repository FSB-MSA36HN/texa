"""Context preparation (whole catalog or a shortlist) and the 'understand the question' model call."""
import json
import re
import unicodedata

from . import db, llm
from .catalog import Catalog, Source, coverage
from .prompts import CANDIDATE_SCHEMA, INTERPRET_INSTRUCTION, SELECT_INSTRUCTION, SELECT_SCHEMA

ALWAYS_INCLUDED_DIMS = {"source", "event_name"}
SHORTLIST_MAX = 80


def estimate_tokens(text: str) -> int:
    return len(text) // 4  # ponytail: chars/4 estimate; swap for the provider's count_tokens if budgets get tight


def _line(*parts) -> str:
    return " | ".join(str(p) for p in parts if p not in ("", None, [], {}))


def render_catalog(cat: Catalog, sources: dict[str, Source], ids: set[str] | None = None) -> str:
    """The static, cacheable part of the prompt (same for every question until the catalog or data changes)."""
    cov = coverage(cat, sources)
    keep = (lambda i: True) if ids is None else (lambda i: i in ids)
    out = ["STORES (id | label | description | data period | currency | cannot compute | breakdowns without data)"]
    for s in sources.values():
        c = cov[s.id]
        out.append(_line(s.id, s.label, s.description, f"{s.min_date}..{s.max_date}", s.currency,
                         "cannot compute: " + ", ".join(c["metrics_missing"]) if c["metrics_missing"] else "",
                         "no data for: " + ", ".join(c["dimensions_missing"]) if c["dimensions_missing"] else ""))
    out.append("\nMETRICS (id | label | unit | description | synonyms | when to use | ways of counting)")
    for m in cat.metrics:
        if keep(m.id):
            g = cat.variant_group_of(m.id)
            out.append(_line(m.id, m.label, m.unit, m.description, ", ".join(m.synonyms), m.when_to_use,
                             f"one way of counting '{g.label}': {', '.join(g.metrics)}" if g else ""))
    out.append("\nDIMENSIONS (id | label | kind | description | synonyms)")
    for d in cat.dimensions:
        if keep(d.id) or d.kind == "time" or d.id in ALWAYS_INCLUDED_DIMS:
            out.append(_line(d.id, d.label, d.kind if d.kind != "field" else "", d.description, ", ".join(d.synonyms)))
    if cat.glossary:
        out.append("\nGLOSSARY (id | term | meaning | synonyms | filter)")
        for t in cat.glossary:
            out.append(_line(t.id, t.label, t.description, ", ".join(t.synonyms),
                             f"filter {t.field} IN {t.values}" if t.field and t.values else ""))
    if cat.verified_questions:
        out.append("\nEXAMPLES (question -> reading)")
        for q in cat.verified_questions:
            reading = {k: v for k, v in {"shape": q.shape, "selection": q.selection, "recipe": q.recipe,
                                         "metrics": q.metrics, "filters": q.filters}.items() if v}
            out.append(f"{q.question} -> {json.dumps(reading, ensure_ascii=False)}")
    return "\n".join(out)


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _fold(text)))


def _lexical(question: str, cat: Catalog) -> list[str]:
    """Fallback ranking when the shortlist call fails: shared words between question and entry text."""
    q = _words(question)
    scored = []
    for entry in [*cat.metrics, *cat.dimensions]:
        text = " ".join([entry.id, entry.label, entry.description, *entry.synonyms])
        score = len(q & _words(text))
        if score:
            scored.append((score, entry.id))
    return [i for _, i in sorted(scored, reverse=True)][:SHORTLIST_MAX]


def shortlist(question: str, previous: dict | None, cat: Catalog, model: str | None, turn_id) -> set[str]:
    index = [f"metric {m.id}: {m.label} ({', '.join(m.synonyms)}) - {m.description[:120]}" for m in cat.metrics]
    index += [f"dimension {d.id}: {d.label} ({', '.join(d.synonyms)}) - {d.description[:120]}" for d in cat.dimensions]
    try:
        picked = llm.generate_structured(model=model, system=SELECT_INSTRUCTION, name="shortlist", turn_id=turn_id,
                                         prompt=f"INDEX\n" + "\n".join(index) + f"\n\nQUESTION\n{question}",
                                         schema=SELECT_SCHEMA, max_output_tokens=2048)["ids"]
    except llm.LLMError:
        picked = []
    ids = set(picked) | set(_lexical(question, cat))
    if previous:
        spec = previous.get("query_spec") or {}
        ids |= {spec.get("recipe", ""), *spec.get("metrics", []), *spec.get("selection", [])}
    for mid in list(ids):  # a metric brings its alternative ways of counting
        g = cat.variant_group_of(mid)
        if g:
            ids |= set(g.metrics)
    return ids


def render_previous(previous: list[dict]) -> str:
    """Last turns, newest last: question plus how it was read and what it returned."""
    lines = []
    for t in previous:
        st = t.get("state") or {}
        reading = st.get("query_spec")
        lines.append(f"Q: {t['question']}")
        if reading:
            lines.append("  reading: " + json.dumps({k: reading[k] for k in ("source_ids", "shape", "selection", "recipe",
                                                                           "metrics", "filters", "time_range") if reading.get(k)},
                                                     ensure_ascii=False, default=str))
        if st.get("insight"):
            lines.append(f"  answer: {st['insight'].get('headline', '')}")
        elif st.get("message"):
            lines.append(f"  answer: {st['message']}")
    text = "\n".join(lines)
    while estimate_tokens(text) > 6000 and lines:  # keep the newest turns within the context window
        lines = lines[2:]
        text = "\n".join(lines)
    return text


def interpret(question: str, previous: list[dict], cat: Catalog, sources: dict[str, Source], *, model: str | None,
              turn_id=None, scope: list[str] | None = None, step=None) -> dict:
    with step("prepare_context") as s:
        full = render_catalog(cat, sources)
        catalog_text = full
        if estimate_tokens(INTERPRET_INSTRUCTION + full) > db.CONTEXT_BUDGET_TOKENS:
            s.note("catalog over budget: shortlisting")
            ids = shortlist(question, previous[-1]["state"] if previous else None, cat, model, turn_id)
            catalog_text = render_catalog(cat, sources, ids)
        s.note(f"~{estimate_tokens(catalog_text):,} tokens of catalog")
    dynamic = []
    if previous:
        dynamic.append("CONVERSATION SO FAR\n" + render_previous(previous))
    if scope:
        dynamic.append(f"STORE SCOPE chosen in the app: {', '.join(scope)} (use these when the question names no store)")
    dynamic.append(f"QUESTION\n{question}")
    with step("interpret") as s:
        # Static catalog first so the provider's implicit prompt cache can reuse it across questions.
        candidate = llm.generate_structured(model=model, system=INTERPRET_INSTRUCTION, name="interpret", turn_id=turn_id,
                                            prompt="CATALOG\n" + catalog_text + "\n\n" + "\n\n".join(dynamic),
                                            schema=CANDIDATE_SCHEMA)
        s.note(candidate["outcome"])
    return candidate
