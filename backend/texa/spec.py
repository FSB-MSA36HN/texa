"""QuerySpec: the only thing the compiler accepts. The validator checks it against the published catalog."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .catalog import Catalog, Operator, Source

SHAPES = ("aggregate", "breakdown", "time_trend", "distinct_values")
MAX_SELECTION = 4
MAX_METRICS = 4
MAX_FILTERS = 8
MAX_DAYS = 366
SINGLE_VALUE_OPS = {"=", "!=", ">", ">=", "<", "<=", "CONTAINS"}


class SpecError(Exception):
    def __init__(self, code: str, message: str, suggestions: list[str] | None = None):
        super().__init__(message)
        self.code, self.message, self.suggestions = code, message, suggestions or []


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimeRange(Strict):
    field: Literal["event_date", "first_seen_date"] | None = None  # implied by the metric when omitted
    kind: Literal["last_n_days", "between", "all"]
    days: int | None = None
    start: date | None = None
    end: date | None = None


class Filter(Strict):
    field: str  # dimension id
    operator: Operator
    values: list[str] = Field(min_length=1, max_length=20)


class QuerySpec(Strict):
    source_ids: list[str] = Field(min_length=1, max_length=3)
    contract_version: int
    shape: Literal["aggregate", "breakdown", "time_trend", "distinct_values"]
    selection: list[str] = []
    recipe: str = ""
    metrics: list[str] = []
    filters: list[Filter] = []
    time_range: TimeRange
    limit: int = Field(default=1000, ge=1, le=2000)

    @property
    def metric_ids(self) -> list[str]:
        return [self.recipe] if self.recipe else list(self.metrics)


def validate_spec(raw: dict, cat: Catalog, sources: dict[str, Source]) -> QuerySpec:
    try:
        spec = QuerySpec.model_validate(raw)
    except ValidationError as e:
        raise SpecError("invalid_spec", "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()))

    if spec.contract_version != cat.contract_version:
        raise SpecError("stale_catalog", "The catalog changed since this question was read. Ask again.")
    for sid in spec.source_ids:
        if sid not in sources:
            raise SpecError("unknown_source", f"Unknown store {sid!r}.")
    if len(set(spec.source_ids)) != len(spec.source_ids):
        raise SpecError("invalid_spec", "Duplicate store.")

    if len(spec.selection) > MAX_SELECTION:
        raise SpecError("too_many_dimensions", f"At most {MAX_SELECTION} breakdowns per question.")
    if len(set(spec.selection)) != len(spec.selection):
        raise SpecError("invalid_spec", "Duplicate breakdown.")
    for d in spec.selection:
        if d not in cat.dims:
            raise SpecError("unknown_dimension", f"Unknown breakdown {d!r}.")

    if spec.recipe and spec.metrics:
        raise SpecError("invalid_spec", "Use recipe for one metric or metrics for 2-4, not both.")
    if spec.metrics and not 2 <= len(spec.metrics) <= MAX_METRICS:
        raise SpecError("too_many_metrics", f"Ask for 2 to {MAX_METRICS} metrics at once.")
    for m in spec.metric_ids:
        if m not in cat.mets:
            raise SpecError("unknown_metric", f"Metric {m!r} is not defined.")
    if len(set(spec.metric_ids)) != len(spec.metric_ids):
        raise SpecError("invalid_spec", "Duplicate metric.")

    if spec.shape == "distinct_values":
        if spec.metric_ids or not spec.selection:
            raise SpecError("invalid_spec", "Listing values needs breakdowns and no metric.")
    elif not spec.metric_ids:
        raise SpecError("missing_metric", "Which metric should be calculated?")
    if spec.shape == "aggregate" and spec.selection:
        raise SpecError("invalid_spec", "An aggregate has no breakdown; use breakdown or time_trend.")
    if spec.shape == "breakdown" and not spec.selection:
        raise SpecError("invalid_spec", "A breakdown needs at least one dimension.")
    if spec.shape == "time_trend" and not any(cat.dims[d].is_time for d in spec.selection):
        raise SpecError("invalid_spec", "A time trend needs a day, week or month breakdown.")

    # One period field per question: event metrics count by event day, cohort metrics by first-seen day.
    metrics = [cat.mets[m] for m in spec.metric_ids]
    periods = {m.period_field for m in metrics}
    if len(periods) > 1:
        raise SpecError("mixed_periods", "Cohort metrics (retention, repeat purchase) cannot be combined with event metrics in one question.")
    period = periods.pop() if periods else "event_date"
    if spec.time_range.field is None:
        spec.time_range.field = period
    if spec.time_range.field != period:
        raise SpecError("invalid_time_field", f"The period of this question must be on {period}.")
    for d in spec.selection:
        dim = cat.dims[d]
        if dim.is_time and dim.field != period:
            raise SpecError("mixed_periods", f"Break down by {'first seen' if period == 'first_seen_date' else 'event'} dates for this metric, not {dim.label}.")
    if period == "first_seen_date":
        for d in spec.selection:
            if cat.dims[d].kind not in ("source", "time"):
                raise SpecError("unsupported_combination", "Cohort metrics can only be broken down by store or first-seen date.")
        if spec.filters:
            raise SpecError("unsupported_combination", "Cohort metrics do not support filters yet.")

    tr = spec.time_range
    if tr.kind == "last_n_days":
        if tr.days is None or not 1 <= tr.days <= MAX_DAYS:
            raise SpecError("invalid_time_range", f"last_n_days needs days between 1 and {MAX_DAYS}.")
    elif tr.kind == "between":
        if not tr.start or not tr.end or tr.start > tr.end:
            raise SpecError("invalid_time_range", "between needs start <= end.")
        if (tr.end - tr.start).days >= MAX_DAYS:
            raise SpecError("invalid_time_range", f"A period can span at most {MAX_DAYS} days.")

    if len(spec.filters) > MAX_FILTERS:
        raise SpecError("too_many_filters", f"At most {MAX_FILTERS} filters.")
    for f in spec.filters:
        dim = cat.dims.get(f.field)
        if dim is None:
            raise SpecError("unknown_dimension", f"Unknown filter field {f.field!r}.")
        if f.operator in SINGLE_VALUE_OPS and len(f.values) != 1:
            raise SpecError("invalid_filter", f"{f.operator} takes exactly one value.")
        if f.operator in (">", ">=", "<", "<=") and dim.value_type == "text":
            raise SpecError("invalid_filter", f"{dim.label} is text; use =, IN or CONTAINS.")
        if dim.value_type == "number" and f.operator != "CONTAINS":
            for v in f.values:
                try:
                    float(v)
                except ValueError:
                    raise SpecError("invalid_filter", f"{dim.label} needs numbers, got {v!r}.")
        if dim.kind in ("time", "bucket"):
            raise SpecError("invalid_filter", f"Filter {dim.label} through the time range or a numeric field instead.")
    return spec
