"""Fail closed before running SQL: a store that never logs what a question needs is refused or named,
never reported as 0. Also normalizes filter values to what the data actually contains."""
import difflib
from dataclasses import dataclass, field

from .catalog import Catalog, Source
from .spec import QuerySpec, SpecError


@dataclass
class Availability:
    sources: list[str]                                  # stores that will be queried
    metric_sources: dict[str, list[str]]                # metric -> stores that can compute it
    unavailable_metrics: dict[str, str] = field(default_factory=dict)   # metric -> reason
    sources_without_data: dict[str, str] = field(default_factory=dict)  # store -> reason
    warnings: list[str] = field(default_factory=list)


def _metric_gaps(cat: Catalog, metric_id: str, src: Source) -> list[str]:
    gaps = [f"does not log {r.label.lower()} events ({', '.join(r.events)})" for r in cat.roles_of(metric_id) if not src.logs_role(r)]
    gaps += [f"has no {f} field" for f in cat.fields_of(metric_id) if not src.has_field(cat.mapped_field(f, src.id))]
    return gaps


def check_availability(spec: QuerySpec, cat: Catalog, sources: dict[str, Source]) -> Availability:
    av = Availability(sources=[], metric_sources={m: [] for m in spec.metric_ids})
    gaps_by_metric: dict[str, dict[str, str]] = {m: {} for m in spec.metric_ids}
    for sid in spec.source_ids:
        src = sources[sid]
        missing_dims = [cat.dims[d] for d in [*spec.selection, *(f.field for f in spec.filters)]
                        if cat.dims[d].field and not src.has_field(cat.mapped_field(cat.dims[d].field, sid))]
        filter_gaps = [cat.dims[f.field].label for f in spec.filters if cat.dims[f.field] in missing_dims]
        if filter_gaps:
            av.sources_without_data[sid] = f"{src.label} has no {', '.join(filter_gaps)} data to filter on"
            continue
        if missing_dims:
            if len(spec.source_ids) == 1:
                raise SpecError("field_not_tracked", f"{src.label} does not record {', '.join(d.label for d in missing_dims)}.")
            av.warnings.append(f"{src.label} does not record {', '.join(d.label for d in missing_dims)}; its rows show it as empty.")
        usable = []
        for m in spec.metric_ids:
            gaps = _metric_gaps(cat, m, src)
            if gaps:
                gaps_by_metric[m][sid] = f"{src.label} {'; '.join(gaps)}"
            else:
                usable.append(m)
                av.metric_sources[m].append(sid)
        if spec.metric_ids and not usable:
            av.sources_without_data[sid] = "; ".join(dict.fromkeys(gaps_by_metric[m][sid] for m in spec.metric_ids))
            continue
        av.sources.append(sid)
        # Two spellings of one action logged by one store would count it twice.
        for m in spec.metric_ids:
            for role in cat.roles_of(m):
                logged = src.logs_role(role)
                if role.alternatives and len(logged) > 1:
                    av.warnings.append(f"{src.label} logs {role.label.lower()} as both {' and '.join(logged)}; it may be counted twice.")
    # A metric is reported unavailable (NULL, never 0) for each queried store that cannot compute it.
    for m, by_source in gaps_by_metric.items():
        reasons = [r for sid, r in by_source.items() if sid in av.sources]
        if reasons:
            av.unavailable_metrics[m] = "; ".join(reasons)
    if not av.sources:
        reasons = "; ".join(av.sources_without_data.values())
        raise SpecError("not_tracked", f"This cannot be answered from the data: {reasons}.")
    if spec.metric_ids and all(not av.metric_sources[m] for m in spec.metric_ids):
        raise SpecError("not_tracked", "; ".join(r for g in gaps_by_metric.values() for r in g.values()) + ".")
    currencies = {sources[s].currency for s in av.sources}
    if len(currencies) > 1 and any(cat.mets[m].unit == "currency" and not cat.mets[m].currency for m in spec.metric_ids):
        av.warnings.append(f"Amounts are in different currencies ({', '.join(f'{sources[s].label}: {sources[s].currency}' for s in av.sources)}) and are not converted; compare trends, not totals.")
    return av


def match_values(cat: Catalog, dim_id: str, typed: list[str], sources: list[Source]) -> tuple[list[str], dict[str, list[str]]]:
    """Map typed values to exact stored values. Returns (resolved, unresolved -> close suggestions).
    Fields without a value vocabulary (too many values) pass through unchanged."""
    dim = cat.dims[dim_id]
    known: dict[str, str] = {}
    has_vocab = False
    for src in sources:
        vocab = src.values.get(cat.mapped_field(dim.field, src.id))
        if vocab is not None:
            has_vocab = True
            known |= vocab
    if not has_vocab or dim.value_type == "number":
        return typed, {}
    resolved, unresolved = [], {}
    for t in typed:
        hit = known.get(t.strip().lower())
        if hit:
            resolved.append(hit)
            continue
        close = difflib.get_close_matches(t.strip().lower(), list(known), n=6, cutoff=0.6)
        contains = [k for k in known if t.strip().lower() in k][:6]
        unresolved[t] = [known[k] for k in dict.fromkeys(contains + close)][:6]
    return resolved, unresolved
