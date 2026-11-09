"""QuerySpec -> parameterized PostgreSQL. Identifiers come only from the catalog whitelist; every literal is a
bound parameter. Formulas are typed definitions, never text from the model."""
from dataclasses import dataclass, field

from psycopg import sql

from .catalog import COLUMNS, Catalog, Condition, Dimension, EventRole, Metric, nested_field_parts
from .sanity import Availability
from .spec import QuerySpec

T = "analytics.event_activity"


@dataclass
class Column:
    name: str
    label: str
    role: str                 # dimension | metric
    unit: str = ""
    additive: bool = False
    value_type: str = "text"
    currency: str | None = None    # fixed currency of a converted money metric; None = the store's own


@dataclass
class Compiled:
    query: sql.Composed
    params: dict
    columns: list[Column]
    order_hint: str
    hidden: list[str] = field(default_factory=list)


class _Builder:
    def __init__(self, cat: Catalog, spec: QuerySpec, av: Availability):
        self.cat, self.spec, self.av = cat, spec, av
        self.params: dict = {}

    def bind(self, value) -> sql.Composable:
        name = f"p{len(self.params)}"
        self.params[name] = value
        return sql.Placeholder(name)

    # ---- fields -------------------------------------------------------------
    def raw_field(self, f: str, alias: str = "e") -> sql.Composable:
        if f in COLUMNS:
            return sql.SQL("{}.{}").format(sql.Identifier(alias), sql.Identifier(f))
        parts = nested_field_parts(f)
        if parts is None:
            raise ValueError(f"field is not a permitted catalog path: {f!r}")
        side, keys = parts
        expr = sql.SQL("{}.{} ").format(sql.Identifier(alias), sql.Identifier(side))
        for key in keys[:-1]:
            expr += sql.SQL("-> {}").format(sql.Literal(key))
        return sql.SQL("({} ->> {})").format(expr, sql.Literal(keys[-1]))

    def field(self, f: str, number: bool = False, alias: str = "e") -> sql.Composable:
        """A catalog field, resolved to the physical column/path each store maps it to."""
        mapped = {s: self.cat.mapped_field(f, s) for s in self.av.sources}
        if len(set(mapped.values())) == 1:
            expr = self.raw_field(next(iter(mapped.values())), alias)
            numeric_column = next(iter(mapped.values())) in COLUMNS and COLUMNS[next(iter(mapped.values()))] == "number"
        else:
            whens = sql.SQL(" ").join(
                sql.SQL("WHEN {} THEN ({})::text").format(sql.Literal(s), self.raw_field(m, alias)) for s, m in mapped.items())
            expr = sql.SQL("(CASE {}.source_id {} END)").format(sql.Identifier(alias), whens)
            numeric_column = False
        if number and not numeric_column:
            return sql.SQL("analytics.try_numeric({})").format(expr)
        return expr

    def condition(self, c: Condition) -> sql.Composable:
        number = c.operator in (">", ">=", "<", "<=") or any(
            d.field == c.field and d.value_type == "number" for d in self.cat.dimensions)
        if c.operator == "CONTAINS":
            number = False
        x = self.field(c.field, number=number)
        values = [float(v) for v in c.values] if number else c.values
        if c.operator == "IN":
            return sql.SQL("{} = ANY({})").format(x, self.bind(values))
        if c.operator == "NOT IN":
            return sql.SQL("({} IS NULL OR {} <> ALL({}))").format(x, x, self.bind(values))
        if c.operator == "CONTAINS":
            return sql.SQL("strpos(lower({}::text), lower({})) > 0").format(x, self.bind(c.values[0]))
        if c.operator == "!=":
            return sql.SQL("{} IS DISTINCT FROM {}").format(x, self.bind(values[0]))
        value = values[0]
        return sql.SQL("{} {} {}").format(x, sql.SQL(c.operator), self.bind(value))

    def role_filter(self, role: EventRole) -> sql.Composable:
        parts = [sql.SQL("e.event_name = ANY({})").format(self.bind(role.events))]
        for event, conds in role.event_conditions.items():
            inner = sql.SQL(" AND ").join(self.condition(c) for c in conds)
            parts.append(sql.SQL("(e.event_name <> {} OR ({}))").format(self.bind(event), inner))
        return sql.SQL("(") + sql.SQL(" AND ").join(parts) + sql.SQL(")")

    # ---- dimensions ---------------------------------------------------------
    def dim(self, d: Dimension, alias: str = "e") -> tuple[sql.Composable, sql.Composable | None]:
        """Returns (value expression, sort expression or None)."""
        a = sql.Identifier(alias)
        if d.kind == "time":
            if d.grain == "day":
                return sql.SQL("{}.{}").format(a, sql.Identifier(d.field)), None
            return sql.SQL("date_trunc({}, {}.{})::date").format(sql.Literal(d.grain), a, sql.Identifier(d.field)), None
        if d.kind == "source":
            return sql.SQL("{}.source_id").format(a), None
        if d.kind == "user_type":
            return sql.SQL("CASE WHEN {a}.event_date = {a}.first_seen_date THEN 'new' ELSE 'returning' END").format(a=a), None
        if d.kind == "days_since":
            return sql.SQL("({a}.event_date - {a}.first_seen_date)").format(a=a), None
        if d.kind == "bucket":
            v = self.field(d.field, number=True, alias=alias)
            fmt = lambda x: f"{x:g}"
            whens = [sql.SQL("WHEN {} < {} THEN {}").format(v, sql.Literal(d.edges[0]), sql.Literal(f"< {fmt(d.edges[0])}"))]
            for lo, hi in zip(d.edges, d.edges[1:]):
                whens.append(sql.SQL("WHEN {} < {} THEN {}").format(v, sql.Literal(hi), sql.Literal(f"{fmt(lo)}–{fmt(hi)}")))
            label = sql.SQL("CASE WHEN {} IS NULL THEN NULL {} ELSE {} END").format(
                v, sql.SQL(" ").join(whens), sql.Literal(f"≥ {fmt(d.edges[-1])}"))
            sort = sql.SQL("width_bucket({}, {}::numeric[])").format(v, sql.Literal(d.edges))
            return label, sort
        return self.field(d.field, number=d.cast == "number", alias=alias), None

    # ---- base relation ------------------------------------------------------
    def where(self, period: str) -> sql.Composable:
        parts = [sql.SQL("e.source_id = ANY({})").format(self.bind(self.av.sources))]
        tr = self.spec.time_range
        col = sql.Identifier(period)
        if tr.kind == "last_n_days":
            # Relative periods end at each store's latest data day, not today: the datasets are historical.
            parts.append(sql.SQL("e.{c} > sr.max_date - {n}::int AND e.{c} <= sr.max_date").format(c=col, n=self.bind(tr.days)))
        elif tr.kind == "between":
            parts.append(sql.SQL("e.{c} BETWEEN {s} AND {e}").format(c=col, s=self.bind(tr.start), e=self.bind(tr.end)))
        for f in self.spec.filters:
            d = self.cat.dims[f.field]
            parts.append(self.condition(Condition(field=d.field, operator=f.operator, values=f.values))
                         if d.kind == "field" else self._kind_filter(d, f))
        return sql.SQL(" AND ").join(parts)

    def _kind_filter(self, d: Dimension, f) -> sql.Composable:
        expr, _ = self.dim(d)
        if f.operator in ("IN", "NOT IN"):
            op = sql.SQL("= ANY({})" if f.operator == "IN" else "<> ALL({})")
            return sql.SQL("{} ").format(expr) + op.format(self.bind(f.values))
        value = float(f.values[0]) if d.value_type == "number" else f.values[0]
        return sql.SQL("{} {} {}").format(expr, sql.SQL(f.operator if f.operator != "CONTAINS" else "="), self.bind(value))

    # ---- metrics ------------------------------------------------------------
    def metric_support(self, m: Metric) -> sql.Composable:
        """Rows eligible for a simple metric, independent of their numeric value."""
        s = m.simple
        cond = self.role_filter(self.cat.roles[s.event_role])
        if s.conditions:
            cond = cond + sql.SQL(" AND ") + sql.SQL(" AND ").join(self.condition(c) for c in s.conditions)
        return cond

    def simple(self, m: Metric) -> sql.Composable:
        s = m.simple
        cond = self.metric_support(m)
        if s.aggregation == "count_events":
            return sql.SQL("count(*) FILTER (WHERE {})").format(cond)
        if s.aggregation == "count_users":
            return sql.SQL("count(DISTINCT e.user_id) FILTER (WHERE {})").format(cond)
        if s.aggregation == "count_distinct":
            return sql.SQL("count(DISTINCT {}) FILTER (WHERE {})").format(self.field(s.field), cond)
        agg = sql.SQL("{}({}) FILTER (WHERE {})").format(sql.SQL(s.aggregation), self.field(s.field, number=True), cond)
        # The store logs this role (checked in sanity), so an empty sum is a true 0.
        return sql.SQL("coalesce({}, 0)").format(agg) if s.aggregation == "sum" else agg

    def available(self, metric_id: str, expr: sql.Composable) -> sql.Composable:
        """NULL (never 0) for stores that cannot compute the metric."""
        ok = self.av.metric_sources[metric_id]
        if set(ok) == set(self.av.sources):
            return expr
        if not ok:
            return sql.SQL("NULL::numeric")
        return sql.SQL("CASE WHEN e.source_id = ANY({}) THEN {} END").format(self.bind(ok), expr)


def compile_spec(spec: QuerySpec, cat: Catalog, av: Availability) -> Compiled:
    b = _Builder(cat, spec, av)
    selection = list(spec.selection)
    if len(av.sources) > 1 and "source" not in selection and "source" in cat.dims:
        selection.insert(0, "source")
    dims = [cat.dims[d] for d in selection]
    metrics = [cat.mets[m] for m in spec.metric_ids]
    period = metrics[0].period_field if metrics else "event_date"
    columns = [Column(d.id, d.label, "dimension", value_type=d.value_type) for d in dims]
    hidden: list[str] = []
    order_hint = "time" if spec.shape == "time_trend" else "metric_desc"

    if metrics and metrics[0].type == "cohort":
        return _compile_cohort(b, spec, cat, dims, metrics, columns, av)

    dim_exprs = [b.dim(d) for d in dims]
    select = [sql.SQL("{} AS {}").format(e, sql.Identifier(d.id)) for d, (e, _) in zip(dims, dim_exprs)]
    for d, (_, sort) in zip(dims, dim_exprs):
        if sort is not None:
            select.append(sql.SQL("min({}) AS {}").format(sort, sql.Identifier(f"__sort_{d.id}")))
            hidden.append(f"__sort_{d.id}")
    where = b.where(period)
    if dims and metrics and all(m.group_domain == "metric_support" for m in metrics):
        # Groups come from eligible event rows, not from whether the final value
        # happens to be nonzero. Ratios retain support for BOTH numerator and
        # denominator, so a visitor-only group still yields a valid zero rate.
        support_metrics = {leaf.id: leaf for m in metrics for leaf in cat.base_simple_metrics(m.id)}
        support = sql.SQL(" OR ").join(b.metric_support(m) for m in support_metrics.values())
        where += sql.SQL(" AND ({})").format(support)
    base = sql.SQL("FROM {} e JOIN analytics.source_registry sr ON sr.source_id = e.source_id WHERE {}").format(sql.SQL(T), where)
    group = sql.SQL(" GROUP BY {}").format(sql.SQL(", ").join(sql.Literal(i + 1) for i in range(len(dims)))) if dims else sql.SQL("")

    if spec.shape == "distinct_values":
        select.append(sql.SQL("count(*) AS events"))
        columns.append(Column("events", "Events", "metric", "count", additive=True, value_type="number"))
        q = sql.SQL("SELECT {} {}{}").format(sql.SQL(", ").join(select), base, group)
        return _finish(b, q, columns, hidden, spec, dims, "events", "metric_desc")

    per_day = [m for m in metrics if m.type == "per_day"]
    if per_day:
        # Per-day metrics: aggregate per (dims, day) first, then average/sum over days.
        inner_select = [sql.SQL("{} AS {}").format(e, sql.Identifier(d.id)) for d, (e, _) in zip(dims, dim_exprs)]
        inner_select.append(sql.SQL("e.event_date AS __day"))
        needed = {b2.id: b2 for m in metrics for b2 in cat.base_simple_metrics(m.id)}
        for mid, bm in needed.items():
            inner_select.append(sql.SQL("{} AS {}").format(b.simple(bm), sql.Identifier(mid)))
        inner_group = sql.SQL(" GROUP BY {}").format(sql.SQL(", ").join(sql.Literal(i + 1) for i in range(len(dims) + 1)))
        daily = sql.SQL("SELECT {} {}{}").format(sql.SQL(", ").join(inner_select), base, inner_group)
        outer = [sql.SQL("d.{0} AS {0}").format(sql.Identifier(d.id)) for d in dims]
        for m in metrics:
            if m.type == "per_day":
                expr = sql.SQL("{}(d.{})").format(sql.SQL(m.per_day.statistic), sql.Identifier(m.per_day.metric))
            elif m.type == "simple":
                if m.simple.aggregation not in ("count_events", "sum"):
                    from .spec import SpecError
                    raise SpecError("unsupported_combination", f"{m.label} cannot be combined with per-day averages.")
                expr = sql.SQL("sum(d.{})").format(sql.Identifier(m.id))
            else:
                n, dn = sql.Identifier(m.ratio.numerator), sql.Identifier(m.ratio.denominator)
                expr = sql.SQL("sum(d.{})::numeric / NULLIF(sum(d.{}), 0)").format(n, dn)
            outer.append(sql.SQL("{} AS {}").format(expr, sql.Identifier(m.id)))
            columns.append(Column(m.id, m.label, "metric", m.unit, cat.is_additive(m.id), "number", m.currency))
        q = sql.SQL("SELECT {} FROM ({}) d{}").format(
            sql.SQL(", ").join(outer), daily, group if not dims else sql.SQL(" GROUP BY {}").format(
                sql.SQL(", ").join(sql.Identifier(d.id) for d in dims)))
        return _finish(b, q, columns, hidden, spec, dims, metrics[0].id, order_hint)

    for m in metrics:
        if m.type == "simple":
            expr = b.simple(m)
        else:
            num, den = b.simple(cat.mets[m.ratio.numerator]), b.simple(cat.mets[m.ratio.denominator])
            expr = sql.SQL("({})::numeric / NULLIF({}, 0)").format(num, den)
            if m.ratio.form == "complement":
                expr = sql.SQL("1 - ") + expr
            select.append(sql.SQL("{} AS {}").format(b.available(m.id, den), sql.Identifier(f"__sample_{m.id}")))
            hidden.append(f"__sample_{m.id}")
        select.append(sql.SQL("{} AS {}").format(b.available(m.id, expr), sql.Identifier(m.id)))
        columns.append(Column(m.id, m.label, "metric", m.unit, cat.is_additive(m.id), "number", m.currency))
    q = sql.SQL("SELECT {} {}{}").format(sql.SQL(", ").join(select), base, group)
    return _finish(b, q, columns, hidden, spec, dims, metrics[0].id, order_hint)


def _compile_cohort(b, spec, cat, dims, metrics, columns, av) -> Compiled:
    m = metrics[0]
    if len(metrics) > 1:
        from .spec import SpecError
        raise SpecError("unsupported_combination", "Ask for one cohort metric at a time.")
    c = m.cohort
    tr = spec.time_range
    cohort_where = [sql.SQL("e.source_id = ANY({})").format(b.bind(av.sources)),
                    # Only users whose whole window lies inside the data, or late cohorts would look like churn.
                    sql.SQL("e.first_seen_date <= sr.max_date - {}::int").format(b.bind(c.day))]
    if tr.kind == "last_n_days":
        cohort_where.append(sql.SQL("e.first_seen_date > sr.max_date - {n}::int AND e.first_seen_date <= sr.max_date").format(n=b.bind(tr.days)))
    elif tr.kind == "between":
        cohort_where.append(sql.SQL("e.first_seen_date BETWEEN {} AND {}").format(b.bind(tr.start), b.bind(tr.end)))
    window = (sql.SQL("(e.event_date - e.first_seen_date) = {}").format(b.bind(c.day)) if c.window == "on_day"
              else sql.SQL("(e.event_date - e.first_seen_date) BETWEEN 1 AND {}").format(b.bind(c.day)))
    dim_select = [sql.SQL("{} AS {}").format(b.dim(d, alias="c")[0], sql.Identifier(d.id)) for d in dims]
    group = sql.SQL(" GROUP BY {}").format(sql.SQL(", ").join(sql.Literal(i + 1) for i in range(len(dims)))) if dims else sql.SQL("")
    q = sql.SQL(
        "WITH c AS (SELECT DISTINCT e.source_id, e.user_id, e.first_seen_date FROM {t} e "
        "JOIN analytics.source_registry sr ON sr.source_id = e.source_id WHERE {cw}), "
        "r AS (SELECT DISTINCT e.source_id, e.user_id FROM {t} e WHERE e.source_id = ANY({src}) AND {role} AND {window}) "
        "SELECT {sel}count(r.user_id)::numeric / NULLIF(count(*), 0) AS {mid}, count(*) AS __sample_{mid_raw} "
        "FROM c LEFT JOIN r ON r.source_id = c.source_id AND r.user_id = c.user_id{group}"
    ).format(
        t=sql.SQL(T), cw=sql.SQL(" AND ").join(cohort_where), src=b.bind(av.sources), role=b.role_filter(cat.roles[c.event_role]),
        window=window, sel=sql.SQL(", ").join(dim_select) + (sql.SQL(", ") if dim_select else sql.SQL("")),
        mid=sql.Identifier(m.id), mid_raw=sql.SQL(m.id), group=group)
    columns.append(Column(m.id, m.label, "metric", m.unit, False, "number", m.currency))
    return _finish(b, q, columns, [f"__sample_{m.id}"], spec, dims, m.id,
                   "time" if spec.shape == "time_trend" else "metric_desc")


def _finish(b, q, columns, hidden, spec, dims, primary, order_hint) -> Compiled:
    if dims:
        order = []
        if order_hint == "time":
            order += [sql.SQL("{} ASC").format(sql.Identifier(d.id)) for d in dims if d.is_time]
            order += [sql.SQL("{} ASC NULLS LAST").format(sql.Identifier(f"__sort_{d.id}" if d.kind == "bucket" else d.id))
                      for d in dims if not d.is_time]
        else:
            if not spec.top_k:
                order += [sql.SQL("{} ASC").format(sql.Identifier(f"__sort_{d.id}")) for d in dims if d.kind == "bucket"]
            order += [sql.SQL("{} DESC NULLS LAST").format(sql.Identifier(primary))]
            order += [sql.SQL("{} ASC NULLS LAST").format(sql.Identifier(d.id)) for d in dims if d.kind != "bucket"]
            if spec.top_k:
                order += [sql.SQL("{} ASC").format(sql.Identifier(f"__sort_{d.id}")) for d in dims if d.kind == "bucket"]
        q = sql.SQL("SELECT * FROM ({}) q ORDER BY {}").format(q, sql.SQL(", ").join(order))
    # Requested top-k belongs to query semantics, separate from the safety row cap.
    q = q + sql.SQL(" LIMIT {}").format(b.bind(min(spec.top_k, spec.limit + 1) if spec.top_k else spec.limit + 1))
    return Compiled(q, b.params, columns, order_hint, hidden)
