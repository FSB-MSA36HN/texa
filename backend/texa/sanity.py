"""Fail closed before running SQL: a store that never logs what a question needs is refused or named,
never reported as 0. Also normalizes filter values to what the data actually contains."""
import difflib
import unicodedata
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
    warning_details: list[dict] = field(default_factory=list)


def _warning(av: Availability, code: str, message: str, **params) -> None:
    """Keep the legacy prose while exposing typed, locale-safe warning parameters."""
    av.warnings.append(message)
    av.warning_details.append({"code": code, "message": message, "params": params})


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
                raise SpecError("field_not_tracked", f"{src.label} does not record {', '.join(d.label for d in missing_dims)}.",
                                params={"source_id": sid, "field_ids": [d.id for d in missing_dims],
                                        "fields": [d.label for d in missing_dims]})
            _warning(av, "availability_missing_fields",
                     f"{src.label} does not record {', '.join(d.label for d in missing_dims)}; its rows show it as empty.",
                     source_id=sid, field_ids=[d.id for d in missing_dims])
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
                    _warning(av, "availability_duplicate_event_role",
                             f"{src.label} logs {role.label.lower()} as both {' and '.join(logged)}; it may be counted twice.",
                             source_id=sid, role_id=role.id, event_names=logged)
    # A metric is reported unavailable (NULL, never 0) for each queried store that cannot compute it.
    for m, by_source in gaps_by_metric.items():
        reasons = [r for sid, r in by_source.items() if sid in av.sources]
        if reasons:
            av.unavailable_metrics[m] = "; ".join(reasons)
    if not av.sources:
        reasons = "; ".join(av.sources_without_data.values())
        raise SpecError("not_tracked", f"This cannot be answered from the data: {reasons}.",
                        params={"source_ids": spec.source_ids, "metric_ids": spec.metric_ids,
                                "unavailable": av.sources_without_data})
    if spec.metric_ids and all(not av.metric_sources[m] for m in spec.metric_ids):
        raise SpecError("not_tracked", "; ".join(r for g in gaps_by_metric.values() for r in g.values()) + ".",
                        params={"source_ids": spec.source_ids, "metric_ids": spec.metric_ids,
                                "unavailable": gaps_by_metric})
    currencies = {sources[s].currency for s in av.sources}
    if len(currencies) > 1 and any(cat.mets[m].unit == "currency" and not cat.mets[m].currency for m in spec.metric_ids):
        source_currencies = {sid: sources[sid].currency for sid in av.sources}
        _warning(av, "availability_mixed_currencies",
                 f"Amounts are in different currencies ({', '.join(f'{sources[s].label}: {sources[s].currency}' for s in av.sources)}) and are not converted; compare trends, not totals.",
                 source_currencies=source_currencies)
    return av


def match_values(cat: Catalog, dim_id: str, typed: list[str], sources: list[Source]) -> tuple[list[str], dict[str, list[str]]]:
    """Bind display/business values to physical values for the selected sources.

    ETL-emitted low-cardinality vocabularies are complete; missing vocabulary means
    open/high-cardinality or unknown, so a literal may pass only for a present field.
    """
    dim = cat.dims[dim_id]
    field = dim.field
    known: dict[str, str] = {}
    complete = field == "event_name"
    for src in sources:
        physical = cat.mapped_field(field, src.id)
        vocab = src.values.get(physical, {})
        known.update(vocab)
        if physical in src.value_vocab_fields:
            complete = True
        if field == "event_name":
            known.update({v.casefold(): v for v in src.events})
    if dim.value_type == "number":
        return typed, {}

    def norm(value: str) -> str:
        text = " ".join(value.casefold().split())
        return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")

    resolved, unresolved = [], {}
    for t in typed:
        text = t.strip()
        semantic = []
        for concept in cat.semantic_values:
            if concept.field != field:
                continue
            aliases = [concept.id, concept.label, *concept.synonyms]
            if norm(text) in {norm(a) for a in aliases}:
                semantic.append(concept)
        concept_ids = {c.id for c in semantic}
        if len(concept_ids) > 1:
            unresolved[t] = [c.label for c in semantic]
            continue
        if semantic:
            concept = semantic[0]
            translated = []
            for src in sources:
                values = concept.source_values.get(src.id, [])
                physical = cat.mapped_field(field, src.id)
                available = src.events if field == "event_name" else src.values.get(physical, {})
                if field == "event_name":
                    translated.extend(v for v in values if v in available)
                elif physical in src.value_vocab_fields:
                    translated.extend(v for v in values if v.casefold() in available)
                elif src.has_field(physical):
                    # Open vocabulary: keep the curated physical value from the semantic contract.
                    translated.extend(values)
            if translated:
                resolved.extend(dict.fromkeys(translated))
            else:
                unresolved[t] = []
            continue
        hit = known.get(text.casefold())
        if hit:
            resolved.append(hit)
            continue
        if not complete:
            resolved.append(text)
            continue
        close = difflib.get_close_matches(t.strip().lower(), list(known), n=6, cutoff=0.6)
        contains = [k for k in known if text.casefold() in k][:6]
        unresolved[t] = [known[k] for k in dict.fromkeys(contains + close)][:6]
    return resolved, unresolved
