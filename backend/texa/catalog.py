"""Semantic catalog: typed definitions, cross-reference validation, publish, and what each source logs."""
import hashlib
import json
import re
import math
import os
import time
from functools import cached_property
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import db

Operator = Literal["=", "!=", "IN", "NOT IN", ">", ">=", "<", "<=", "CONTAINS"]

# Physical columns of analytics.event_activity. ep.* / up.* fields are text unless a definition casts them.
COLUMNS = {
    "source_id": "text", "event_ts": "timestamp", "event_date": "date", "event_name": "text", "user_id": "text",
    "session_id": "text", "first_seen_date": "date", "platform": "text", "country": "text", "region": "text",
    "city": "text", "item_id": "text", "item_category": "text", "item_brand": "text", "item_price": "number",
    "quantity": "number", "revenue": "number", "revenue_usd": "number", "currency": "text",
}
ALWAYS_FILLED = {"source_id", "event_ts", "event_date", "event_name", "user_id", "first_seen_date", "currency"}
ADDITIVE = {"count_events", "sum"}
_NESTED_FIELD = re.compile(r"^(ep|up)\.([a-zA-Z0-9_]+)(?:\.([a-zA-Z0-9_]+))?$")


def nested_field_parts(field: str) -> tuple[str, tuple[str, ...]] | None:
    """Parse a bounded JSON object path (one or two keys) rooted at ep/up."""
    match = _NESTED_FIELD.fullmatch(field)
    if not match:
        return None
    side, first, second = match.groups()
    return side, (first,) if second is None else (first, second)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Condition(Strict):
    field: str
    operator: Operator
    values: list[str] = Field(min_length=1, max_length=20)


class EventRole(Strict):
    id: str
    label: str
    description: str = ""
    events: list[str] = Field(min_length=1)
    synonyms: list[str] = []
    alternatives: bool = False
    event_conditions: dict[str, list[Condition]] = {}


class Dimension(Strict):
    id: str
    label: str
    description: str = ""
    labels: dict[str, str] = {}
    descriptions: dict[str, str] = {}
    synonyms: list[str] = []
    kind: Literal["field", "time", "source", "bucket", "user_type", "days_since"] = "field"
    field: str = ""
    cast: Literal["text", "number"] = "text"
    grain: Literal["day", "week", "month"] = "day"
    edges: list[float] = []

    @property
    def is_time(self) -> bool:
        return self.kind == "time"

    @property
    def value_type(self) -> str:
        if self.kind in ("days_since",) or self.cast == "number":
            return "number"
        if self.kind == "time":
            return "date"
        return "text"


class Simple(Strict):
    aggregation: Literal["count_events", "count_users", "count_distinct", "sum", "avg", "max", "min"]
    event_role: str
    field: str = ""
    conditions: list[Condition] = []


class Ratio(Strict):
    numerator: str
    denominator: str
    form: Literal["ratio", "complement"] = "ratio"


class Cohort(Strict):
    event_role: str
    day: int = Field(ge=1, le=180)
    window: Literal["on_day", "within"]


class PerDay(Strict):
    metric: str
    statistic: Literal["avg", "sum"]


class Metric(Strict):
    id: str
    label: str
    description: str = ""
    labels: dict[str, str] = {}
    descriptions: dict[str, str] = {}
    synonyms: list[str] = []
    when_to_use: str = ""
    unit: Literal["count", "number", "percent", "currency", "days", "score"]
    # A money metric that is already converted (e.g. revenue_usd) has one currency for every store.
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    type: Literal["simple", "ratio", "cohort", "per_day"]
    simple: Simple | None = None
    ratio: Ratio | None = None
    cohort: Cohort | None = None
    per_day: PerDay | None = None

    @model_validator(mode="after")
    def _one_body(self):
        if getattr(self, self.type) is None:
            raise ValueError(f"metric {self.id}: type {self.type} needs a `{self.type}` block")
        return self

    @property
    def period_field(self) -> str:
        return "first_seen_date" if self.type == "cohort" else "event_date"


class VariantGroup(Strict):
    id: str
    label: str
    metrics: list[str] = Field(min_length=2, max_length=4)


class FieldMapping(Strict):
    field: str
    source: str
    to: str


class GlossaryTerm(Strict):
    id: str
    label: str
    description: str = ""
    synonyms: list[str] = []
    field: str = ""          # dimension id; with values this term is a trusted filter
    values: list[str] = []


class SemanticValue(Strict):
    """A business concept whose stored spelling varies by source."""
    id: str
    field: str
    label: str
    synonyms: list[str] = []
    source_values: dict[str, list[str]]


class MetricAmbiguity(Strict):
    """Catalog-owned phrase whose valid metric interpretations are genuinely distinct."""
    id: str
    phrases: list[str] = Field(min_length=1)
    metric_ids: list[str] = Field(min_length=2)
    disambiguators: dict[str, list[str]] = {}


class VerifiedQuestion(Strict):
    id: str
    question: str
    shape: str
    selection: list[str] = []
    recipe: str = ""
    metrics: list[str] = []
    filters: list[dict] = []


class Policy(Strict):
    min_sample: int = 30
    ask_when_missing: list[str] = []
    max_sources: int = Field(default=3, ge=1, le=3)


class Catalog(Strict):
    version: int
    table: str
    allowed_sources: list[str] = []
    evaluation_sources: list[str] = []
    event_roles: list[EventRole]
    dimensions: list[Dimension]
    metrics: list[Metric]
    variant_groups: list[VariantGroup] = []
    field_mappings: list[FieldMapping] = []
    glossary: list[GlossaryTerm] = []
    semantic_values: list[SemanticValue] = []
    metric_ambiguities: list[MetricAmbiguity] = []
    verified_questions: list[VerifiedQuestion] = []
    data_notes: list[dict] = []
    policy: Policy = Policy()
    contract_version: int = 0  # set when loaded from app.catalog_versions

    @cached_property
    def roles(self) -> dict[str, EventRole]:
        return {r.id: r for r in self.event_roles}

    @cached_property
    def dims(self) -> dict[str, Dimension]:
        return {d.id: d for d in self.dimensions}

    @cached_property
    def mets(self) -> dict[str, Metric]:
        return {m.id: m for m in self.metrics}

    def variant_group_of(self, metric_id: str) -> VariantGroup | None:
        return next((g for g in self.variant_groups if metric_id in g.metrics), None)

    def mapped_field(self, field: str, source_id: str) -> str:
        return next((m.to for m in self.field_mappings if m.field == field and m.source == source_id), field)

    def sources_for_profile(self, profile: str | None = None) -> list[str]:
        profile = profile or os.environ.get("TEXA_SOURCE_PROFILE", "demo")
        return list(dict.fromkeys(self.allowed_sources + (self.evaluation_sources if profile == "evaluation" else [])))
    def base_simple_metrics(self, metric_id: str) -> list[Metric]:
        """Simple metrics a metric is computed from (itself, ratio parts, or the per-day inner metric)."""
        m = self.mets[metric_id]
        if m.type == "simple":
            return [m]
        if m.type == "ratio":
            return [self.mets[m.ratio.numerator], self.mets[m.ratio.denominator]]
        if m.type == "per_day":
            return self.base_simple_metrics(m.per_day.metric)
        return []

    def roles_of(self, metric_id: str) -> list[EventRole]:
        m = self.mets[metric_id]
        if m.type == "cohort":
            return [self.roles[m.cohort.event_role]]
        return [self.roles[b.simple.event_role] for b in self.base_simple_metrics(metric_id)]

    def fields_of(self, metric_id: str) -> list[str]:
        fields = []
        for b in self.base_simple_metrics(metric_id):
            if b.simple.field:
                fields.append(b.simple.field)
            fields += [c.field for c in b.simple.conditions]
        for role in self.roles_of(metric_id):
            fields += [c.field for conds in role.event_conditions.values() for c in conds]
        return fields

    def is_additive(self, metric_id: str) -> bool:
        m = self.mets[metric_id]
        return m.type == "simple" and m.simple.aggregation in ADDITIVE


def display_label(item: Dimension | Metric, locale: str = "en") -> str:
    return item.labels.get((locale or "en").split("-")[0].lower(), item.label)


def display_description(item: Dimension | Metric, locale: str = "en") -> str:
    return item.descriptions.get((locale or "en").split("-")[0].lower(), item.description)


def field_type(field: str, cast: str = "text") -> str:
    if field in COLUMNS:
        return COLUMNS[field]
    if nested_field_parts(field):
        return "number" if cast == "number" else "text"
    return "number" if cast == "number" else "text"


def validate_catalog(raw: dict) -> Catalog:
    """Schema + cross-reference checks. Raises ValueError listing every problem."""
    cat = Catalog.model_validate(raw)
    errors = []

    def check_field(where, field):
        if field in COLUMNS:
            return
        if nested_field_parts(field):
            return
        errors.append(f"{where}: unknown field {field!r} (use a column of {cat.table} or ep.<key>/up.<key>)")

    for kind, items in (("event role", cat.event_roles), ("dimension", cat.dimensions), ("metric", cat.metrics),
                        ("variant group", cat.variant_groups), ("glossary term", cat.glossary),
                        ("semantic value", cat.semantic_values), ("metric ambiguity", cat.metric_ambiguities)):
        ids = [i.id for i in items]
        for dup in {i for i in ids if ids.count(i) > 1}:
            errors.append(f"duplicate {kind} id {dup!r}")
    if len(set(cat.allowed_sources)) != len(cat.allowed_sources) or any(not s for s in cat.allowed_sources):
        errors.append("allowed_sources must contain unique non-empty source ids")
    if len(set(cat.evaluation_sources)) != len(cat.evaluation_sources) or set(cat.allowed_sources) & set(cat.evaluation_sources):
        errors.append("evaluation_sources must be unique and disjoint from demo allowed_sources")
    for value in cat.semantic_values:
        check_field(f"semantic value {value.id}", value.field)
        if not value.source_values or any(not vals for vals in value.source_values.values()):
            errors.append(f"semantic value {value.id}: each source needs at least one physical value")
        if set(value.source_values) - set(cat.sources_for_profile("evaluation")):
            errors.append(f"semantic value {value.id}: references a source outside demo/evaluation scope")
    for ambiguity in cat.metric_ambiguities:
        missing = set(ambiguity.metric_ids) - set(cat.mets)
        if missing:
            errors.append(f"metric ambiguity {ambiguity.id}: unknown metrics {sorted(missing)}")
        if len(set(ambiguity.metric_ids)) != len(ambiguity.metric_ids):
            errors.append(f"metric ambiguity {ambiguity.id}: duplicate metric ids")
        if set(ambiguity.disambiguators) - set(ambiguity.metric_ids):
            errors.append(f"metric ambiguity {ambiguity.id}: disambiguators reference a non-member metric")
    for role in cat.event_roles:
        for event, conds in role.event_conditions.items():
            if event not in role.events:
                errors.append(f"event role {role.id}: condition on {event!r} which is not one of its events")
            for c in conds:
                check_field(f"event role {role.id}", c.field)
    for d in cat.dimensions:
        if d.kind in ("field", "time", "bucket"):
            check_field(f"dimension {d.id}", d.field)
        if d.kind == "time" and field_type(d.field) != "date":
            errors.append(f"dimension {d.id}: time dimension needs a date field")
        if d.kind == "bucket" and (len(d.edges) < 1 or d.edges != sorted(d.edges)):
            errors.append(f"dimension {d.id}: bucket needs ascending edges")
        if d.cast == "number" and nested_field_parts(d.field) and not all(math.isfinite(v) for v in d.edges):
            errors.append(f"dimension {d.id}: numeric nested field cast requires finite values")
    for m in cat.metrics:
        where = f"metric {m.id}"
        if m.currency and m.unit != "currency":
            errors.append(f"{where}: currency {m.currency} is only for unit currency")
        if m.type == "ratio" and m.unit == "currency":
            # A money ratio keeps its numerator's currency; one store-currency part makes the whole thing per store.
            parts = [cat.mets[p] for p in (m.ratio.numerator, m.ratio.denominator) if p in cat.mets]
            money = {p.currency for p in parts if p.unit == "currency"}
            if money != {m.currency}:
                errors.append(f"{where}: currency {m.currency or 'per store'} differs from its parts ({', '.join(sorted(map(str, money)))})")
        if m.type == "simple":
            s = m.simple
            if s.event_role not in cat.roles:
                errors.append(f"{where}: unknown event role {s.event_role!r}")
            if s.aggregation in ("sum", "avg", "max", "min", "count_distinct") and not s.field:
                errors.append(f"{where}: {s.aggregation} needs a field")
            if s.field:
                check_field(where, s.field)
                if s.aggregation in ("sum", "avg") and s.field in COLUMNS and COLUMNS[s.field] != "number":
                    errors.append(f"{where}: {s.aggregation} needs a numeric field, {s.field} is {COLUMNS[s.field]}")
                path = nested_field_parts(s.field)
                if s.aggregation in ("sum", "avg") and path and len(path[1]) == 2:
                    declared = any(d.kind == "field" and d.field == s.field and d.cast == "number" for d in cat.dimensions)
                    if not declared:
                        errors.append(f"{where}: nested {s.aggregation} field {s.field} needs a numeric dimension declaration with cast: number")
            for c in s.conditions:
                check_field(where, c.field)
        elif m.type == "ratio":
            for part in (m.ratio.numerator, m.ratio.denominator):
                if part not in cat.mets:
                    errors.append(f"{where}: unknown metric {part!r}")
                elif cat.mets[part].type != "simple":
                    errors.append(f"{where}: ratio parts must be simple metrics, {part} is {cat.mets[part].type}")
        elif m.type == "cohort":
            if m.cohort.event_role not in cat.roles:
                errors.append(f"{where}: unknown event role {m.cohort.event_role!r}")
        elif m.type == "per_day":
            inner = cat.mets.get(m.per_day.metric)
            if inner is None or inner.type != "simple":
                errors.append(f"{where}: per_day needs a simple metric, got {m.per_day.metric!r}")
    for g in cat.variant_groups:
        for mid in g.metrics:
            if mid not in cat.mets:
                errors.append(f"variant group {g.id}: unknown metric {mid!r}")
        others = [o.id for o in cat.variant_groups if o.id != g.id and set(o.metrics) & set(g.metrics)]
        if others:
            errors.append(f"variant group {g.id}: shares metrics with {others}")
    for fm in cat.field_mappings:
        check_field("field mapping", fm.field)
        check_field("field mapping", fm.to)
    for t in cat.glossary:
        if t.field and t.field not in cat.dims:
            errors.append(f"glossary {t.id}: unknown dimension {t.field!r}")
    for q in cat.verified_questions:
        for ref in [q.recipe, *q.metrics]:
            if ref and ref not in cat.mets:
                errors.append(f"verified question {q.id}: unknown metric {ref!r}")
        for ref in q.selection:
            if ref not in cat.dims:
                errors.append(f"verified question {q.id}: unknown dimension {ref!r}")
    for ask in cat.policy.ask_when_missing:
        if ask not in cat.dims:
            errors.append(f"policy.ask_when_missing: unknown dimension {ask!r}")
    if errors:
        raise ValueError("catalog is invalid:\n- " + "\n- ".join(errors))
    return cat


# ---------------------------------------------------------------------------
# What each source logs (from analytics.vocabulary / source_registry)
# ---------------------------------------------------------------------------
class Source(BaseModel):
    id: str
    label: str
    description: str
    currency: str | None
    min_date: str | None
    max_date: str | None
    row_count: int
    user_count: int
    snapshot_version: str = ""
    events: set[str] = set()
    ep_keys: set[str] = set()
    up_keys: set[str] = set()
    columns: set[str] = set()
    values: dict[str, dict[str, str]] = {}  # field -> lowercased value -> exact value
    value_vocab_fields: set[str] = set()  # ETL writes complete low-cardinality vocabularies; absence is open/unknown

    def has_field(self, field: str) -> bool:
        if field in ALWAYS_FILLED:
            return True
        if field in COLUMNS:
            return field in self.columns
        path = nested_field_parts(field)
        if path:
            side, keys = path
            known = self.ep_keys if side == "ep" else self.up_keys
            # A profiler may represent nested paths as dotted keys. Accept legacy root keys
            # only for one-level paths; never infer arbitrary descendants from a parent key.
            return ".".join(keys) in known or (len(keys) == 1 and keys[0] in known)
        return False

    def value_vocabulary_status(self, field: str) -> str:
        """Return complete (closed enum), open (field exists, values not enumerated), or absent."""
        if field == "event_name":
            return "complete" if self.events else "absent"
        if field in self.value_vocab_fields:
            return "complete"
        return "open" if self.has_field(field) else "absent"

    def logs_role(self, role: EventRole) -> list[str]:
        return [e for e in role.events if e in self.events]


_sources_cache: tuple[float, dict[str, Source]] | None = None


def load_sources(max_age: float = 300) -> dict[str, Source]:
    global _sources_cache
    if _sources_cache and time.monotonic() - _sources_cache[0] < max_age:
        return _sources_cache[1]
    with db.reader_conn() as conn:
        regs = conn.execute("SELECT * FROM analytics.source_registry ORDER BY source_id").fetchall()
        vocab = conn.execute("SELECT source_id, kind, field, value FROM analytics.vocabulary").fetchall()
    sources = {
        r["source_id"]: Source(
            id=r["source_id"], label=r["label"], description=r["description"], currency=r["currency"],
            min_date=str(r["min_date"]) if r["min_date"] else None, max_date=str(r["max_date"]) if r["max_date"] else None,
            row_count=r["row_count"] or 0, user_count=r["user_count"] or 0,
            snapshot_version=str(r.get("last_loaded_at") or ""))
        for r in regs
    }
    for v in vocab:
        s = sources.get(v["source_id"])
        if s is None:
            continue
        if v["kind"] == "event_name":
            s.events.add(v["value"])
        elif v["kind"] == "ep_key":
            s.ep_keys.add(v["value"])
        elif v["kind"] == "up_key":
            s.up_keys.add(v["value"])
        elif v["kind"] == "column":
            s.columns.add(v["value"])
        else:
            s.values.setdefault(v["field"], {})[v["value"].lower()] = v["value"]
            s.value_vocab_fields.add(v["field"])
    _sources_cache = (time.monotonic(), sources)
    return sources


def scoped_sources(cat: Catalog, sources: dict[str, Source]) -> dict[str, Source]:
    """Expose demo sources by default; evaluation fixtures require an explicit profile."""
    allowed = cat.sources_for_profile()
    if not allowed:
        return sources
    return {sid: source for sid, source in sources.items() if sid in allowed}


# ---------------------------------------------------------------------------
# Publish / load
# ---------------------------------------------------------------------------
def fingerprint(raw: dict) -> str:
    return hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()[:16]


def check_against_sources(cat: Catalog, sources: dict[str, Source]) -> list[str]:
    """Require each role to be observed, not every optional event alias in a snapshot."""
    visible = {sid: src for sid, src in sources.items() if sid in cat.sources_for_profile("evaluation")}
    logged = set().union(*(s.events for s in visible.values())) if visible else set()
    errors = [f"event role {r.id}: no in-scope source logs any of {r.events!r}"
              for r in cat.event_roles if not logged.intersection(r.events)]
    for concept in cat.semantic_values:
        for sid, expected in concept.source_values.items():
            src = sources.get(sid)
            if src is None:
                errors.append(f"semantic value {concept.id}: source {sid!r} has no metadata")
                continue
            field = cat.mapped_field(concept.field, sid)
            available = src.events if concept.field == "event_name" else src.values.get(field, {})
            if concept.field != "event_name" and not src.has_field(field):
                errors.append(f"semantic value {concept.id}: source {sid!r} has no field {field!r}")
            elif (concept.field == "event_name" or field in src.value_vocab_fields) and any(
                    value.casefold() not in {v.casefold() for v in available} for value in expected):
                missing = [v for v in expected if v.casefold() not in {v.casefold() for v in available}]
                errors.append(f"semantic value {concept.id}: source {sid!r} is missing physical values {missing!r}")
    return errors


def publish(path=db.CATALOG_PATH) -> int:
    raw = yaml.safe_load(open(path, encoding="utf-8"))
    cat = validate_catalog(raw)
    problems = check_against_sources(cat, load_sources(max_age=0))
    if problems:
        raise ValueError("catalog does not match the data:\n- " + "\n- ".join(problems))
    fp = fingerprint(raw)
    with db.app_conn() as conn:
        row = conn.execute("SELECT version, fingerprint FROM app.catalog_versions ORDER BY version DESC LIMIT 1").fetchone()
        if row and row["fingerprint"] == fp:
            return row["version"]
        version = conn.execute(
            "INSERT INTO app.catalog_versions (fingerprint, catalog) VALUES (%s, %s) RETURNING version",
            (fp, json.dumps(raw)),
        ).fetchone()["version"]
    global _published
    _published = None
    return version


_published: Catalog | None = None


def published() -> Catalog:
    global _published
    with db.app_conn() as conn:
        row = conn.execute("SELECT version, catalog FROM app.catalog_versions ORDER BY version DESC LIMIT 1").fetchone()
    if row is None:
        raise LookupError("No catalog is published. Run: texa catalog publish")
    if _published is None or _published.contract_version != row["version"]:
        cat = validate_catalog(row["catalog"])
        cat.contract_version = row["version"]
        _published = cat
    return _published


def coverage(cat: Catalog, sources: dict[str, Source]) -> dict[str, dict]:
    """Per source: which metrics/dimensions it can answer, and why not."""
    out = {}
    for s in sources.values():
        ok, missing = [], {}
        for m in cat.metrics:
            reasons = [f"no {r.id} events ({', '.join(r.events)})" for r in cat.roles_of(m.id) if not s.logs_role(r)]
            reasons += [f"no field {f}" for f in cat.fields_of(m.id) if not s.has_field(cat.mapped_field(f, s.id))]
            if reasons:
                missing[m.id] = reasons
            else:
                ok.append(m.id)
        dims_missing = [d.id for d in cat.dimensions if d.field and not s.has_field(cat.mapped_field(d.field, s.id))]
        out[s.id] = {"metrics_ok": ok, "metrics_missing": missing, "dimensions_missing": dims_missing,
                     "metric_coverage": round(len(ok) / len(cat.metrics), 3)}
    return out
