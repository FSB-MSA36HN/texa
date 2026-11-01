"""The deterministic half of Texa: spec -> validate -> availability -> compile -> run -> facts.
The LLM steps (interpret, insight) wrap around this in answer.py."""
import datetime as dt

from . import catalog as catalog_mod
from . import execute
from .compile import compile_spec
from .facts import compute_facts, preview_for_model
from .progress import Progress
from .sanity import check_availability
from .spec import QuerySpec, validate_spec


def resolved_period(spec: QuerySpec, sources: dict) -> dict[str, dict]:
    out = {}
    for sid in spec.source_ids:
        s = sources[sid]
        tr = spec.time_range
        if tr.kind == "between":
            start, end = str(tr.start), str(tr.end)
        elif tr.kind == "last_n_days" and s.max_date:
            end_d = dt.date.fromisoformat(s.max_date)
            start, end = str(end_d - dt.timedelta(days=tr.days - 1)), s.max_date
        else:
            start, end = s.min_date, s.max_date
        out[sid] = {"start": start, "end": end, "data_start": s.min_date, "data_end": s.max_date}
    return out


def run_spec(raw_spec: dict, cat=None, sources=None, step: Progress = Progress()) -> dict:
    cat = cat or catalog_mod.published()
    sources = sources or catalog_mod.load_sources()
    if "contract_version" not in raw_spec:
        raw_spec = {**raw_spec, "contract_version": cat.contract_version}

    with step("validate_query"):
        spec = validate_spec(raw_spec, cat, sources)
    with step("check_data") as s:
        av = check_availability(spec, cat, sources)
        s.note(", ".join(sources[x].label for x in av.sources))
    with step("compile_sql"):
        compiled = compile_spec(spec, cat, av)
        sql_text = execute.display_sql(compiled)
    with step("run_query") as s:
        result = execute.run(compiled, spec.limit)
        s.note(f"{result['row_count']} rows · {result['ms']} ms")

    period = resolved_period(spec, sources)
    warnings = list(av.warnings)
    if spec.top_k:
        warnings.append(f"This result contains the top {spec.top_k} groups; totals describe these groups only.")
    if not result["rows"]:
        spans = "; ".join(f"{sources[s].label} has data from {p['data_start']} to {p['data_end']}" for s, p in period.items())
        warnings.append(f"No rows match this question. {spans}.")
    if result["partial"]:
        warnings.append(f"Only the first {spec.limit} rows are shown; totals over the result are not computed.")
    small = sum(1 for s in result["samples"] for v in s.values() if v is not None and v < cat.policy.min_sample)
    if small:
        warnings.append(f"{small} row(s) rest on fewer than {cat.policy.min_sample} users or events; treat them as unreliable.")
    for m, reason in av.unavailable_metrics.items():
        warnings.append(f"{cat.mets[m].label} is empty where it cannot be computed: {reason}.")
    for sid, reason in av.sources_without_data.items():
        warnings.append(f"{sources[sid].label} is left out: {reason}.")

    currency_of = {s: sources[s].currency for s in av.sources}
    facts = compute_facts(result["rows"], compiled.columns, spec.shape, result["partial"], currency_of)
    preview, preview_grouped = preview_for_model(result["rows"], compiled.columns, spec.shape)
    return {
        "query_spec": spec.model_dump(mode="json"),
        "compiled_sql": sql_text,
        "columns": [c.__dict__ for c in compiled.columns],
        "rows": result["rows"],
        "row_count": result["row_count"],
        "partial": result["partial"],
        "facts": facts,
        "model_preview": preview,
        "model_preview_grouped": preview_grouped,
        "warnings": warnings,
        "unavailable_metrics": av.unavailable_metrics,
        "sources_without_data": av.sources_without_data,
        "sources": av.sources,
        "currency_of": currency_of,
        "period": period,
        "ms": result["ms"],
    }
