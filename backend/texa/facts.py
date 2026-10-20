"""Numbers the insight writer may cite. Computed by code over the whole result; the model only references
them by id ([[f_total_revenue]]) and the server substitutes the formatted value."""
import re

from .compile import Column

MAX_SERIES = 10
PREVIEW_ROWS = 100


def _label(row: dict, dims: list[Column]) -> str:
    return " · ".join("(not set)" if row.get(d.name) is None else str(row[d.name]) for d in dims) or "all"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "x"


def compute_facts(rows: list[dict], columns: list[Column], shape: str, partial: bool,
                  currency_of: dict[str, str]) -> list[dict]:
    dims = [c for c in columns if c.role == "dimension"]
    metrics = [c for c in columns if c.role == "metric"]
    time_dims = [d for d in dims if d.value_type == "date"]
    other_dims = [d for d in dims if d.value_type != "date"]
    facts: list[dict] = [{"id": "f_rows", "label": "Rows in the result", "value": len(rows), "unit": "count"}]
    currencies = set(currency_of.values())

    def cur(row=None):
        if row is not None and "source" in row and row["source"] in currency_of:
            return currency_of[row["source"]]
        return next(iter(currencies)) if len(currencies) == 1 else None

    fixed = None  # set per metric: a converted metric's currency, the same for every row

    def add(fid, label, value, unit, row=None, kind="number"):
        fact = {"id": fid, "label": label, "value": value, "unit": unit if kind == "number" else "text"}
        if unit == "currency" and kind == "number":
            fact["currency"] = fixed or cur(row)
        facts.append(fact)

    for m in metrics:
        fixed = m.currency
        vals = [(r, r[m.name]) for r in rows if isinstance(r.get(m.name), (int, float))]
        if not vals:
            add(f"f_{m.name}_missing", f"{m.label}: no value in the result", "no data", m.unit, kind="text")
            continue
        if not dims or len(rows) == 1:
            add(f"f_{m.name}", m.label, vals[0][1], m.unit, vals[0][0])
            continue
        single_currency = m.unit != "currency" or len(currencies) == 1 or bool(m.currency)
        total = None
        if m.additive and not partial and single_currency:
            total = sum(v for _, v in vals)
            add(f"f_total_{m.name}", f"Total {m.label}", total, m.unit)
        hi = max(vals, key=lambda x: x[1])
        lo = min(vals, key=lambda x: x[1])
        add(f"f_max_{m.name}", f"Highest {m.label}", hi[1], m.unit, hi[0])
        add(f"f_max_{m.name}_at", f"Where {m.label} is highest", _label(hi[0], dims), m.unit, kind="text")
        add(f"f_min_{m.name}", f"Lowest {m.label}", lo[1], m.unit, lo[0])
        add(f"f_min_{m.name}_at", f"Where {m.label} is lowest", _label(lo[0], dims), m.unit, kind="text")
        if single_currency:
            add(f"f_avg_{m.name}", f"Average {m.label} per row", sum(v for _, v in vals) / len(vals), m.unit)
        if total:
            add(f"f_max_{m.name}_share", f"Share of total {m.label} at the highest row", hi[1] / total, "percent")
        if len(rows) == 2 and shape == "breakdown" and single_currency:
            (r1, v1), (r2, v2) = vals[0], vals[-1]
            add(f"f_diff_{m.name}", f"{m.label}: {_label(r1, dims)} minus {_label(r2, dims)}", v1 - v2, m.unit, r1)
            if v2:
                add(f"f_diff_{m.name}_pct", f"{m.label}: {_label(r1, dims)} vs {_label(r2, dims)} relative difference", v1 / v2 - 1, "percent")

        if shape == "time_trend" and time_dims:
            series: dict[str, list[tuple[dict, float]]] = {}
            for r, v in vals:
                series.setdefault(_label(r, other_dims), []).append((r, v))
            ranked = sorted(series.items(), key=lambda kv: -sum(abs(v) for _, v in kv[1]))[:MAX_SERIES]
            for name, points in ranked:
                if len(points) < 2:
                    continue
                points.sort(key=lambda p: tuple(str(p[0][d.name]) for d in time_dims))
                sfx = "" if len(series) == 1 else f"_{_slug(name)}"
                lbl = m.label if len(series) == 1 else f"{m.label} ({name})"
                (r_first, first), (r_last, last) = points[0], points[-1]
                when = lambda r: " ".join(str(r[d.name]) for d in time_dims)
                add(f"f_first_{m.name}{sfx}", f"{lbl} at the start ({when(r_first)})", first, m.unit, r_first)
                add(f"f_last_{m.name}{sfx}", f"{lbl} at the end ({when(r_last)})", last, m.unit, r_last)
                add(f"f_change_{m.name}{sfx}", f"Change in {lbl} from start to end", last - first, m.unit, r_last)
                if first:
                    add(f"f_change_{m.name}{sfx}_pct", f"Relative change in {lbl} from start to end", last / first - 1, "percent")
                peak = max(points, key=lambda p: p[1])
                trough = min(points, key=lambda p: p[1])
                add(f"f_peak_{m.name}{sfx}", f"Peak {lbl}", peak[1], m.unit, peak[0])
                add(f"f_peak_{m.name}{sfx}_at", f"When {lbl} peaked", when(peak[0]), m.unit, kind="text")
                add(f"f_trough_{m.name}{sfx}", f"Lowest {lbl}", trough[1], m.unit, trough[0])
                add(f"f_trough_{m.name}{sfx}_at", f"When {lbl} was lowest", when(trough[0]), m.unit, kind="text")
    return facts


def preview_for_model(rows: list[dict], columns: list[Column], shape: str) -> tuple[list[dict], bool]:
    """At most 100 rows. A larger breakdown keeps the top 99 by the first metric plus one 'Others' row
    (additive metrics summed, others left empty)."""
    if len(rows) <= PREVIEW_ROWS:
        return rows, False
    metrics = [c for c in columns if c.role == "metric"]
    if shape != "breakdown" or not metrics:
        return rows[:PREVIEW_ROWS], True
    primary = metrics[0].name
    ranked = sorted(rows, key=lambda r: (r.get(primary) is None, -(r.get(primary) or 0)))
    top, rest = ranked[:PREVIEW_ROWS - 1], ranked[PREVIEW_ROWS - 1:]
    others = {c.name: (f"Others ({len(rest)} rows)" if i == 0 else None)
              for i, c in enumerate(c for c in columns if c.role == "dimension")}
    for m in metrics:
        others[m.name] = sum(r.get(m.name) or 0 for r in rest) if m.additive else None
    return top + [others], True


def format_value(value, unit: str, currency: str | None = None, lang: str = "en") -> str:
    if value is None:
        return "no data"
    if isinstance(value, str):
        return value
    if unit == "percent":
        text = f"{value * 100:,.1f}%"
    elif unit in ("count",) or (isinstance(value, int)):
        text = f"{value:,.0f}"
    elif unit in ("score", "days", "number"):
        text = f"{value:,.2f}"
    else:
        text = f"{value:,.2f}"
    if lang.startswith("vi"):  # 1,234.5 -> 1.234,5
        text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    if unit == "currency" and currency:
        text = f"{text} {currency}"
    elif unit == "days":
        text += " days" if not lang.startswith("vi") else " ngày"
    return text
