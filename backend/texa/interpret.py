"""Context preparation (whole catalog or a shortlist) and the 'understand the question' model call."""
import json
from copy import deepcopy
import os
import re
import unicodedata

from . import db, llm, memory, examples, consistency, intent
from .catalog import Catalog, Source, coverage, mentioned_sources
from .prompts import CANDIDATE_SCHEMA, INTERPRET_INSTRUCTION, SELECT_INSTRUCTION, SELECT_SCHEMA, DIALOGUE_INSTRUCTION, structured_candidate_schema
from .progress import Progress

ALWAYS_INCLUDED_DIMS = {"source", "event_name"}
SHORTLIST_MAX = 80


def candidate_schema(cat: Catalog, *, structured: bool) -> dict:
    """Constrain semantic identifiers to the current governed catalog.

    Grain is an identifier, not prose to be string-compared after generation.
    Uncatalogued requested entities can still be described in the entity field.
    Copy the schema so one catalog cannot mutate another request's constraints.
    """
    schema = structured_candidate_schema() if structured else deepcopy(CANDIDATE_SCHEMA)
    contract = schema["properties"]["intent_contract"]["properties"]
    contract["grain"]["enum"] = sorted({"", "multiple", "unspecified", "uncatalogued"} |
                                         {m.intent_grain for m in cat.metrics if m.intent_grain})
    contract["operation"]["enum"] = sorted({"", "multiple", "uncatalogued", "presentation_arithmetic"} |
                                             {intent.metric_operation(cat, [m.id]) for m in cat.metrics})
    return schema


def estimate_tokens(text: str) -> int:
    return len(text) // 4  # ponytail: chars/4 estimate; swap for the provider's count_tokens if budgets get tight


def _line(*parts) -> str:
    return " | ".join(str(p) for p in parts if p not in ("", None, [], {}))


def count_measure_options(cat: Catalog, source: Source, available_metric_ids=None) -> list[dict]:
    """Derive source-supported row/user counts over catalog event roles without mutating either input."""
    available = (set(available_metric_ids) if available_metric_ids is not None else
                 set(coverage(cat, {source.id: source})[source.id]["metrics_ok"]))
    event_name = next((d for d in cat.dimensions if d.field == "event_name" and
                       source.has_field(cat.mapped_field(d.field, source.id))), None)
    options = []
    for role in cat.event_roles:
        tracked_values = source.logs_role(role)
        if not tracked_values:
            continue
        for operation, entity in (("count_events", "event_occurrences"),
                                  ("count_users", "distinct_users")):
            exact = sorted(m.id for m in cat.metrics if m.id in available and m.type == "simple" and
                           m.simple.aggregation == operation and m.simple.event_role == role.id and
                           not m.simple.field and not m.simple.conditions)
            if exact:
                base_metric = exact[0]
                required_filters = []
            else:
                # Compose from a broader catalog count measure and a declared, source-observed
                # event-name dimension. Never invent event literals.
                if event_name is None:
                    continue
                bases = []
                for metric in cat.metrics:
                    if (metric.id not in available or metric.type != "simple" or
                            metric.simple.aggregation != operation or metric.simple.field or
                            metric.simple.conditions):
                        continue
                    base_role = cat.roles[metric.simple.event_role]
                    base_values = set(source.logs_role(base_role))
                    if set(tracked_values) <= base_values:
                        bases.append((len(base_values), metric.id))
                if not bases:
                    continue
                base_metric = min(bases)[1]
                required_filters = [{"field_id": event_name.id, "operator": "IN",
                                     "values": list(tracked_values)}]
            options.append({"operation": operation, "counting_entity": entity,
                            "event_role_id": role.id, "base_metric_id": base_metric,
                            "required_filters": required_filters})
    return options


def _shortlist_count_roles(cat: Catalog, ids: set[str] | None) -> set[str] | None:
    if ids is None:
        return None
    roles = set()
    for metric_id in ids:
        if metric_id not in cat.mets:
            continue
        roles.update(role.id for role in cat.roles_of(metric_id))
    # A shortlisted population also makes its catalog-declared subpopulations relevant.
    selected_events = [set(cat.roles[role_id].events) for role_id in roles if role_id in cat.roles]
    for event_set in selected_events:
        roles.update(r.id for r in cat.event_roles if set(r.events) <= event_set)
    return roles


def render_catalog(cat: Catalog, sources: dict[str, Source], ids: set[str] | None = None) -> str:
    """The static, cacheable part of the prompt (same for every question until the catalog or data changes)."""
    cov = coverage(cat, sources)
    relevant_roles = _shortlist_count_roles(cat, ids)
    options_by_source = {}
    option_metric_ids = set()
    for source in sources.values():
        options = count_measure_options(cat, source, cov[source.id]["metrics_ok"])
        if relevant_roles is not None:
            options = [o for o in options if o["event_role_id"] in relevant_roles or o["base_metric_id"] in ids]
        options_by_source[source.id] = options
        option_metric_ids.update(o["base_metric_id"] for o in options)
    keep = (lambda i: True) if ids is None else (lambda i: i in ids or i in option_metric_ids)
    out = ["STORES (id | label | description | data period | currency | cannot compute | breakdowns without data)"]
    for s in sources.values():
        c = cov[s.id]
        out.append(_line(s.id, s.label, ", ".join(cat.source_aliases.get(s.id, [])), s.description, f"{s.min_date}..{s.max_date}", s.currency,
                         "cannot compute: " + ", ".join(c["metrics_missing"]) if c["metrics_missing"] else "",
                         "no data for: " + ", ".join(c["dimensions_missing"]) if c["dimensions_missing"] else ""))
    out.append("\nSOURCE CAPABILITIES (authoritative profiler/catalog evidence; availability is not a query answer)")
    for source in sources.values():
        out.append(json.dumps({
            "source_id": source.id,
            "available_metric_ids": cov[source.id]["metrics_ok"],
            "unavailable_metric_reasons": cov[source.id]["metrics_missing"],
            "tracked_event_roles": {role.id: source.logs_role(role) for role in cat.event_roles
                                    if source.logs_role(role)},
            "count_measure_options": options_by_source[source.id],
            "available_dimension_ids": [d.id for d in cat.dimensions
                                        if not d.field or source.has_field(cat.mapped_field(d.field, source.id))],
        }, ensure_ascii=False, sort_keys=True))
    out.append("\nMETRICS (id | label | unit | grain | description | synonyms | when to use | ways of counting)")
    for m in cat.metrics:
        if keep(m.id):
            g = cat.variant_group_of(m.id)
            if m.type == "simple":
                signature = _line("semantic operation=" + m.simple.aggregation,
                                  "event_role=" + m.simple.event_role,
                                  "field=" + m.simple.field if m.simple.field else "")
            elif m.type == "ratio":
                signature = f"semantic operation=ratio numerator={m.ratio.numerator} denominator={m.ratio.denominator}"
            else:
                signature = "semantic operation=" + m.type
            out.append(_line(m.id, m.label, m.unit, m.intent_grain, m.description, ", ".join(m.synonyms), m.when_to_use,
                             signature, f"one way of counting '{g.label}': {', '.join(g.metrics)}" if g else ""))
    out.append("\nDIMENSIONS (id | label | kind | description | synonyms | path | value type)")
    for d in cat.dimensions:
        if keep(d.id) or d.kind == "time" or d.id in ALWAYS_INCLUDED_DIMS:
            out.append(_line(d.id, d.label, d.kind if d.kind != "field" else "", d.description, ", ".join(d.synonyms),
                             d.field, d.value_type))
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
    notes = [note for note in cat.data_notes if note.get("source") in sources and note.get("message")]
    if notes:
        out.append("\nSOURCE LIMITATIONS\n" + "\n".join(json.dumps(note, ensure_ascii=False) for note in notes))
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


def render_previous(previous: list[dict], budget: int = 6000) -> str:
    """Last turns, newest last: question plus how it was read and what it returned."""
    blocks = []
    for t in previous:
        lines = [f"TURN {t.get('id', '')}"]
        st = t.get("state") or {}
        reading = st.get("query_spec")
        lines.append(f"Q: {t['question']}")
        if reading:
            lines.append("  reading: " + json.dumps({k: reading[k] for k in ("source_ids", "shape", "selection", "recipe",
                                                                           "metrics", "filters", "time_range", "top_k") if reading.get(k)},
                                                     ensure_ascii=False, default=str))
        if st.get("insight"):
            lines.append(f"  answer: {st['insight'].get('headline', '')}")
        elif st.get("message"):
            lines.append(f"  answer: {st['message']}")
        blocks.append("\n".join(lines))
    # Drop whole turns, never a question independently of its reading.
    while blocks and estimate_tokens("\n\n".join(blocks)) > budget:
        blocks.pop(0)
    return "\n\n".join(blocks)


def interpret(question: str, previous: list[dict], cat: Catalog, sources: dict[str, Source], *, model: str | None,
              turn_id=None, scope: list[str] | None = None, step=None, context: dict | None = None, normalize=None, cancelled=lambda: False) -> dict:
    step = step or Progress()
    with step("prepare_context") as s:
        full = render_catalog(cat, sources)
        catalog_text = full
        if estimate_tokens(INTERPRET_INSTRUCTION + full) > db.CONTEXT_BUDGET_TOKENS:
            s.note("catalog over budget: shortlisting")
            ids = shortlist(question, previous[-1]["state"] if previous else None, cat, model, turn_id)
            catalog_text = render_catalog(cat, sources, ids)
        s.note(f"~{estimate_tokens(catalog_text):,} tokens of catalog")
    structured = bool(context and context.get("structured_memory"))
    instruction = INTERPRET_INSTRUCTION + (DIALOGUE_INSTRUCTION if structured else "")
    schema = candidate_schema(cat, structured=structured)
    if structured and context.get("forced_reference"):
        schema["properties"]["dialogue"]["properties"]["relation"]["enum"] = ["followup"]
        schema["properties"]["dialogue"]["properties"]["target_id"]["enum"] = [context["forced_reference"]]
        schema["properties"]["outcome"]["enum"] = ["query", "answer_from_previous", "unsupported"]
    dynamic = []
    if context and context.get("validation_feedback"):
        dynamic.append("SEMANTIC VALIDATION FEEDBACK (one bounded re-resolution of the original request)\n" +
                       json.dumps(context["validation_feedback"], ensure_ascii=False))
    registry_complete = True
    if structured:
        static_cost = estimate_tokens(instruction + catalog_text + question + json.dumps(
            context.get("inherited_slots", {}), default=str))
        registry_budget = max(0, min(db.CONTEXT_BUDGET_TOKENS // 3, db.CONTEXT_BUDGET_TOKENS - static_cost - 2048))
        registry_view, registry_complete = memory.bounded_registry(context.get("registry", []), registry_budget)
        dynamic.append("RESULT REGISTRY\n" + json.dumps(registry_view, ensure_ascii=False, default=str))
        if not registry_complete:
            dynamic.append("Registry evidence is incomplete. Use ambiguous for references unless forced_reference is supplied. New independent questions may proceed without inheritance.")
        if context.get("forced_reference"):
            dynamic.append("forced_reference: " + context["forced_reference"])
    if context:
        dynamic.append("DIALOGUE STATE\n" + json.dumps({k: context.get(k) for k in
                       ("relation", "references", "inherited_slots")}, ensure_ascii=False, default=str))
    remaining = db.CONTEXT_BUDGET_TOKENS - estimate_tokens(instruction + catalog_text + question + "\n".join(dynamic)) - 1024
    if remaining < 0:
        raise llm.LLMError("CONTEXT_TOO_LARGE", "The schema and active query exceed the context budget. Narrow the catalog or question.")
    if previous:
        dynamic.append("RELEVANT PRIOR TURNS (evidence only)\n" + render_previous(previous, min(6000, remaining)))
    if scope:
        dynamic.append(f"STORE SCOPE chosen in the app: {', '.join(scope)} (constraint; conflicting text must be resolved before querying)")
    dynamic.append(f"QUESTION\n{question}")
    retrieval_trace = {"enabled": os.getenv("TEXA_EXAMPLE_RETRIEVAL", "0") == "1"}
    example_text = ""
    if retrieval_trace["enabled"]:
        # Registry and prior-turn evidence are packed first. Demonstrations only
        # consume remaining space; a UI/text conflict is not a confirmed source.
        budget = max(0, min(600, db.CONTEXT_BUDGET_TOKENS - estimate_tokens(
            instruction + catalog_text + "\n\n".join(dynamic)) - 1024))
        mentions = set(mentioned_sources(cat, sources, question))
        confirmed = scope if scope and (not mentions or mentions == set(scope)) else ()
        try:
            bank = examples.load_bank(cat)
        except examples.ExampleBankError as exc:
            raise llm.LLMError("EXAMPLE_BANK_INVALID", "The example bank does not match the active catalog.") from exc
        # Evaluation may freeze a shared SQL-verified demonstration subset so
        # the direct-SQL control and Texa receive the same eligible examples.
        policy = os.getenv("TEXA_EXAMPLE_POLICY", "approved")
        if policy == "sql_verified":
            from dataclasses import replace
            bank = replace(bank, examples=tuple(x for x in bank.examples if
                x.get("reference", {}).get("verification_status") == "verified" and
                x.get("reference", {}).get("reference_sql")))
        elif policy != "approved":
            raise llm.LLMError("EXAMPLE_BANK_INVALID", "Unknown example eligibility policy.")
        retrieval_trace["eligibility_policy"] = policy
        retrieved = examples.retrieve_examples(bank, question, confirmed_sources=confirmed, token_budget=budget)
        example_text = examples.render_examples(retrieved, structured=structured)
        retrieval_trace.update(bank_version=bank.version, bank_hash=bank.content_hash, ids=list(retrieved.ids),
                               scores=list(retrieved.scores), estimated_tokens=retrieved.estimated_tokens,
                               token_estimate_method=getattr(retrieved, "token_estimate_method", "unknown"),
                               packed_utf8_bytes=getattr(retrieved, "packed_utf8_bytes", None))
    prompt = "CATALOG\n" + catalog_text + "\n\n" + example_text + "\n\n" + "\n\n".join(dynamic)
    def sample():
        result = llm.generate_structured(model=model, system=instruction, name="interpret", turn_id=turn_id,
                                         prompt=prompt, schema=schema)
        if structured:
            result["_registry_complete"] = registry_complete
        return result
    primary_error = None
    with step("interpret") as s:
        # Static catalog first so the provider's implicit prompt cache can reuse it across questions.
        try:
            candidate = sample()
        except llm.LLMError as exc:
            if exc.code != "MODEL_OUTPUT_INVALID" or normalize is None or os.getenv("TEXA_CONSISTENCY", "0") != "1":
                raise
            primary_error = exc.code
            candidate = {"outcome": "unresolved", "language": (context or {}).get("language", "en")}
        s.note(candidate["outcome"])
    trace = {"retrieval": retrieval_trace, "consistency": {"enabled": False}}
    if os.getenv("TEXA_CONSISTENCY", "0") == "1" and normalize is not None:
        with step("consistency_selection"):
            candidate, trace["consistency"] = consistency.select(candidate, sample, normalize, cancelled=cancelled, primary_error=primary_error)
    candidate["_accuracy"] = trace
    return candidate
