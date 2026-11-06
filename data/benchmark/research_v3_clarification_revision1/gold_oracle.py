"""Generate research_v3 singles over challenge_v1's three controlled worlds.

Expected results use independent Python row aggregation; the SQL writer below is
declarative and does not import Texa's compiler or call an LLM. All labels remain
candidate/unsealed until external review.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from datetime import date, timedelta
from shutil import copyfile

import yaml

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[2]
CHALLENGE_GENERATOR = PROJECT / "data/benchmark/challenge_v1/generate_candidate.py"
spec = importlib.util.spec_from_file_location("research_v3_challenge_fixture", CHALLENGE_GENERATOR)
fixture = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(fixture)
ROWS_BY_WORLD = {name: rows for name, rows in fixture.variants()}
SOURCES = ("cosmetics_shop", "olist_marketplace")
ALL_METRICS = ("events", "users", "sessions", "viewers", "purchases", "buyers", "revenue", "buyer_conversion_rate")
SOURCE_METRICS = {
    "cosmetics_shop": ALL_METRICS,
    "olist_marketplace": ("events", "users", "purchases", "buyers", "revenue", "buyer_conversion_rate"),
}
METRIC_EN = {"events":"events", "users":"distinct users", "sessions":"sessions", "viewers":"distinct viewers",
             "purchases":"purchased item lines", "buyers":"distinct buyers", "revenue":"purchase revenue",
             "buyer_conversion_rate":"buyer-to-observed-user rate"}
METRIC_VI = {"events":"lượt sự kiện", "users":"người dùng duy nhất", "sessions":"phiên truy cập",
             "viewers":"người xem sản phẩm duy nhất", "purchases":"dòng sản phẩm đã mua",
             "buyers":"người mua duy nhất", "revenue":"doanh thu từ sản phẩm đã mua",
             "buyer_conversion_rate":"tỷ lệ người mua trên người dùng quan sát được"}
DIM_EN = {"event_date":"date", "event_name":"event type", "item_category":"product category",
          "device_type":"device type", "campaign_channel":"campaign channel"}
DIM_VI = {"event_date":"ngày", "event_name":"loại sự kiện", "item_category":"danh mục sản phẩm",
          "device_type":"thiết bị", "campaign_channel":"kênh chiến dịch"}
DIM_VALUES = {"item_category":["serum","cream","mask","cleanser","toner","sunscreen"],
              "device_type":["mobile","desktop","tablet"], "campaign_channel":["paid","email"]}
FIELD_SQL = {"event_date":"event_date", "event_name":"event_name", "item_category":"item_category",
             "device_type":"ep #>> '{device,type}'", "campaign_channel":"ep #>> '{campaign,channel}'"}
PURCHASE_EVENT = {"cosmetics_shop":"purchase", "olist_marketplace":"order_purchased"}


def _rows(world="base", source=None):
    rows = ROWS_BY_WORLD[world]
    return [r for r in rows if source is None or r["source"] == source]


def sql_for(source, metric, where=None, group=None, limit=None, order_by=None):
    """Produce PostgreSQL gold SQL from explicit metric/filter/group specs."""
    if source not in SOURCES or metric not in SOURCE_METRICS[source]:
        raise ValueError(f"unsupported source/metric: {source}/{metric}")
    event = PURCHASE_EVENT[source]
    expr = {"events":"count(*)::bigint", "users":"count(DISTINCT user_id)::bigint",
            "sessions":"count(DISTINCT session_id)::bigint",
            "viewers":"count(DISTINCT user_id) FILTER (WHERE event_name='view')::bigint",
            "purchases":f"count(*) FILTER (WHERE event_name='{event}')::bigint",
            "buyers":f"count(DISTINCT user_id) FILTER (WHERE event_name='{event}')::bigint",
            "revenue":f"coalesce(sum(revenue) FILTER (WHERE event_name='{event}'),0)::numeric",
            "buyer_conversion_rate":f"count(DISTINCT user_id) FILTER (WHERE event_name='{event}')::numeric / nullif(count(DISTINCT user_id),0)"}[metric]
    clauses = [f"source_id='{source}'"]
    for condition in where or []:
        field, value = next(iter(condition.items()))
        sql_field = FIELD_SQL[field]
        if isinstance(value, dict) and "between" in value:
            lo, hi = value["between"]
            clauses.append(f"{sql_field} BETWEEN '{lo}' AND '{hi}'")
        elif isinstance(value, dict) and value.get("is_null"):
            clauses.append(f"{sql_field} IS NULL")
        else:
            literal = str(value).replace("'", "''")
            clauses.append(f"{sql_field}='{literal}'")
    if group:
        # Match the catalog metric's eligible event domain. This keeps groups with
        # zero qualifying purchase/view events out of purchase/view metrics while
        # retaining observed-user groups for the ratio.
        eligible = {"viewers": "view", "purchases": event, "buyers": event, "revenue": event}
        if metric in eligible:
            clauses.append(f"event_name='{eligible[metric]}'")
        group_sql = FIELD_SQL[group]
        tail = f" GROUP BY 1 ORDER BY {group} NULLS LAST"
        if order_by == "metric_desc":
            tail = f" GROUP BY 1 ORDER BY {metric} DESC NULLS LAST, {group} ASC NULLS LAST"
        if limit is not None:
            tail += f" LIMIT {int(limit)}"
        return f"SELECT {group_sql} AS {group}, {expr} AS {metric} FROM analytics.event_activity WHERE {' AND '.join(clauses)}{tail}"
    return f"SELECT {expr} AS {metric} FROM analytics.event_activity WHERE {' AND '.join(clauses)}"


def evaluate(source, metric, where=None, group=None, limit=None, order_by=None, world="base"):
    """Independent Python oracle over the selected immutable fixture world."""
    if source not in SOURCES or metric not in SOURCE_METRICS[source]:
        raise ValueError(f"unsupported source/metric: {source}/{metric}")
    data = _rows(world, source)
    def actual(row, field):
        if field == "device_type": return (row.get("ep") or {}).get("device", {}).get("type")
        if field == "campaign_channel": return (row.get("ep") or {}).get("campaign", {}).get("channel")
        return row["day"] if field == "event_date" else row["event"] if field == "event_name" else row["category"]
    def matches(row):
        for condition in where or []:
            field, expected = next(iter(condition.items())); value = actual(row, field)
            if isinstance(expected, dict) and "between" in expected:
                if not expected["between"][0] <= value <= expected["between"][1]: return False
            elif isinstance(expected, dict) and expected.get("is_null"):
                if value is not None: return False
            elif value != expected: return False
        return True
    purchase = PURCHASE_EVENT[source]
    rows = [r for r in data if matches(r)]
    def agg(group_rows):
        users = {r["user"] for r in group_rows}
        buyers = {r["user"] for r in group_rows if r["event"] == purchase}
        return {"events":len(group_rows), "users":len(users),
                "sessions":len({r["session"] for r in group_rows if r["session"] is not None}),
                "viewers":len({r["user"] for r in group_rows if r["event"] == "view"}),
                "purchases":sum(r["event"] == purchase for r in group_rows), "buyers":len(buyers),
                "revenue":sum((r["revenue"] or 0) for r in group_rows if r["event"] == purchase),
                "buyer_conversion_rate":len(buyers)/len(users) if users else None}[metric]
    if not group:
        return {"columns":[metric], "rows":[[agg(rows)]]}
    if metric == "viewers":
        rows = [r for r in rows if r["event"] == "view"]
    elif metric in {"purchases", "buyers", "revenue"}:
        rows = [r for r in rows if r["event"] == purchase]
    buckets = {}
    for row in rows: buckets.setdefault(actual(row, group), []).append(row)
    result = [[key, agg(value)] for key, value in buckets.items()]
    result.sort(key=lambda item:(item[0] is None, "" if item[0] is None else str(item[0])))
    if order_by == "metric_desc":
        result.sort(key=lambda item:(-(float(item[1] or 0)), item[0] is None, "" if item[0] is None else str(item[0])))
    if limit is not None: result = result[:limit]
    return {"columns":[group,metric], "rows":result}


def _date_windows(source):
    dates = sorted({r["day"] for r in _rows("base", source)})
    return dates


def _question(source, metric, where, group, limit, lang, style=0):
    label = "Cosmetics Shop" if source == "cosmetics_shop" else "Olist"
    m = METRIC_EN[metric] if lang == "en" else METRIC_VI[metric]
    cond = []
    for item in where:
        field, value = next(iter(item.items()))
        if field == "event_date":
            if isinstance(value, dict):
                phrase = f"from {value['between'][0]} through {value['between'][1]}" if lang == "en" else f"từ {value['between'][0]} đến hết {value['between'][1]}"
            else: phrase = f"on {value}" if lang == "en" else f"ngày {value}"
        elif isinstance(value, dict) and value.get("is_null"):
            phrase = f"with no recorded {DIM_EN[field]}" if lang == "en" else f"chưa ghi nhận {DIM_VI[field]}"
        else:
            dim = DIM_EN[field] if lang == "en" else DIM_VI[field]
            phrase = f"{dim} {value}" if lang == "en" else f"{dim} {value}"
        cond.append(phrase)
    scope = ", ".join(cond) if cond else ("all available dates" if lang == "en" else "toàn bộ thời gian có dữ liệu")
    if group:
        dimension = DIM_EN[group] if lang == "en" else DIM_VI[group]
        if limit:
            return (f"{label}: rank the top {limit} {dimension} by {m} for {scope}; break ties by {dimension} ascending, with missing values last."
                    if lang == "en" else f"{label}: xếp hạng {limit} {dimension} cao nhất theo {m}, {scope}; nếu bằng nhau thì xếp {dimension} tăng dần, giá trị thiếu cuối cùng.")
        return f"{label}: break down {m} by {dimension} for {scope}." if lang == "en" else f"{label}: phân tích {m} theo {dimension}, {scope}."
    prefix = ["Report", "Calculate", "Show"][style % 3] if lang == "en" else ["Báo cáo", "Tính", "Cho biết"][style % 3]
    return f"{label}: {prefix} {m} {scope}."


def build_cases():
    cases=[]; ids=set(); sqls=set(); questions=set()
    def add(split, stratum, source, ident, metric, where=(), group=None, limit=None, order_by=None, lang="vi", family=None):
        where=list(where)
        query=sql_for(source,metric,where,group,limit,order_by)
        question=_question(source,metric,where,group,limit,lang,len(cases))
        if ident in ids or query in sqls or question in questions:
            raise ValueError(f"duplicate id/question/query: {ident}; sql={query}; question={question}")
        ids.add(ident); sqls.add(query); questions.add(question)
        by_world={world:evaluate(source,metric,where,group,limit,order_by,world) for world in ROWS_BY_WORLD}
        cases.append({"id":f"rv3_{ident}", "split":split, "family":family or f"{split}_{stratum}_{source}",
                      "source_id":source, "ui_scope":[source], "language":lang, "stratum":stratum, "question":question,
                      "gold_sql":query, "expected_result":by_world["base"], "expected_results_by_world":by_world,
                      "fixture_world":"base", "in_scope":True, "ordered":bool(limit),
                      "intent":stratum, "difficulty":{"basic":"easy","compositional":"hard","semantic":"hard"}[stratum],
                      "tags":[source,stratum,lang,"synthetic"]})
    split_targets={"dev":{"basic":20,"compositional":50,"semantic":30},"test":{"basic":40,"compositional":100,"semantic":60}}
    for split, strata in split_targets.items():
        # Even source allocation keeps the evaluation multi-source without inventing Olist visitors/sessions.
        for stratum,total in strata.items():
            for source in SOURCES:
                n=total//2
                dates=_date_windows(source)
                metrics=SOURCE_METRICS[source]
                if stratum=="basic":
                    # One explicit metric and period, with disjoint date slices across splits.
                    start=0 if split=="dev" else len(dates)//2
                    for i in range(n):
                        metric=metrics[i%len(metrics)]
                        lo=date.fromisoformat(dates[start+(i//len(metrics))*3])
                        hi=min(lo+timedelta(days=12),date.fromisoformat(dates[-1]))
                        period={"between":[lo.isoformat(),hi.isoformat()]}
                        add(split,stratum,source,f"{split}_{stratum}_{source}_{i+1:03}",metric,[{"event_date":period}],lang="vi" if i%3 else "en",family="basic_metric_period")
                elif stratum=="compositional":
                    # At least two interacting constraints: time plus a supported nested or item field;
                    # some cases also group/rank, which changes the result contract.
                    dims=["device_type","campaign_channel","item_category"]
                    for i in range(n):
                        metric=metrics[(i*5+1)%len(metrics)]
                        half=len(dates)//2; base=0 if split=="dev" else half
                        lo=date.fromisoformat(dates[base+(i*7)%half])
                        hi=min(lo+timedelta(days=7 + 7*(i//half)),date.fromisoformat(dates[-1]))
                        day={"between":[lo.isoformat(),hi.isoformat()]}
                        dim=dims[i%len(dims)]
                        vals=DIM_VALUES[dim]
                        val=vals[(i//3+i+i//half)%len(vals)]
                        where=[{"event_date":day},{dim:val}]
                        group=[None,"event_name","item_category","device_type","campaign_channel"][i%5]
                        if group and source=="olist_marketplace" and group=="device_type": group="event_name"
                        if group=="campaign_channel" and source=="olist_marketplace": group="event_name"
                        top=i%4==0
                        family="grouped_or_ranked_composition" if group else "time_plus_dimension_filter"
                        add(split,stratum,source,f"{split}_{stratum}_{source}_{i+1:03}",metric,where,group,
                            limit=3 if top and group else None,order_by="metric_desc" if top and group else None,
                            lang="vi" if i%4 else "en",family=family)
                else:
                    # Semantic cases contrast row/user/purchase grain, purchase-vs-payment role,
                    # nested missing/null behavior and ratio denominator. No unsupported request is treated as answerable.
                    # Explicitly interleave semantic phenomena so the quota does not
                    # accidentally fill from the first date/event cells only.
                    pattern_families={"row_vs_user_and_purchase_grain":[],"purchase_role_vs_event_literal":[],
                                      "nested_scalar_presence":[],"eligible_group_domain_topk":[],
                                      "ratio_denominator":[],"zero_denominator":[],"null_grouping":[]}
                    sem_dates=dates[:]
                    half=len(sem_dates)//2
                    chosen_dates=sem_dates[:half] if split=="dev" else sem_dates[half:]
                    broad_ranges=[]
                    for j in range(0,len(chosen_dates)-4,5):
                        lo=date.fromisoformat(chosen_dates[j]); hi=min(lo+timedelta(days=12),date.fromisoformat(chosen_dates[-1]))
                        broad_ranges.append({"between":[lo.isoformat(),hi.isoformat()]})
                    if not broad_ranges:
                        broad_ranges=[{"between":[chosen_dates[0],chosen_dates[-1]]}]
                    # (1) event-row vs distinct-user/purchaser grain and role-vs-literal event.
                    for j,metric in enumerate(("events","users","buyers","purchases","revenue","buyer_conversion_rate")):
                        ev=PURCHASE_EVENT[source]
                        pattern_families["row_vs_user_and_purchase_grain"].append((metric,[{"event_date":broad_ranges[j%len(broad_ranges)]},{"event_name":ev}],None,None,None,"row_vs_user_and_purchase_grain"))
                    # (2) Olist payment value must not be purchase revenue; cosmetics gets view/cart role controls.
                    control_events=["payment_made","order_approved"] if source=="olist_marketplace" else ["view","cart"]
                    for j,ev in enumerate(control_events):
                        for metric in ("events","users","purchases","revenue"):
                            pattern_families["purchase_role_vs_event_literal"].append((metric,[{"event_date":broad_ranges[(j+1)%len(broad_ranges)]},{"event_name":ev}],None,None,None,"purchase_role_vs_event_literal"))
                    # (3) Nested scalar presence, explicit JSON null and absent key semantics.
                    for dim in ("device_type","campaign_channel"):
                        for val in DIM_VALUES[dim]:
                            w=[{"event_date":broad_ranges[(len(pattern_families['nested_scalar_presence']))%len(broad_ranges)]},{dim:val}]
                            for metric in ("events","users"):
                                pattern_families["nested_scalar_presence"].append((metric,w,None,None,None,"nested_scalar_presence"))
                    # (4) Metric-specific eligible group domain and top-k order.
                    for dim in ("item_category","device_type","campaign_channel"):
                        for metric in ("purchases","buyers","revenue"):
                            pattern_families["eligible_group_domain_topk"].append((metric,[{"event_date":broad_ranges[-1]},{"event_name":PURCHASE_EVENT[source]}],dim,3,"metric_desc","eligible_group_domain_topk"))
                    # (5) Ratio denominator vs zero and observed population; only a few empty-period cases.
                    pattern_families["ratio_denominator"].append(("buyer_conversion_rate",[{"event_date":broad_ranges[0]},{"item_category":"serum"}],None,None,None,"ratio_denominator"))
                    pattern_families["ratio_denominator"].append(("buyer_conversion_rate",[{"event_date":broad_ranges[min(1,len(broad_ranges)-1)]},{"device_type":"mobile"}],"item_category",None,None,"ratio_denominator_grouped"))
                    empty_year="2030" if split=="dev" else "2031"
                    pattern_families["zero_denominator"].append(("buyer_conversion_rate",[{"event_date":{"between":[f"{empty_year}-01-01",f"{empty_year}-01-07"]}},{"event_name":PURCHASE_EVENT[source]}],None,None,None,"zero_denominator"))
                    # (6) Null group rows remain visible for broad user/event metrics.
                    pattern_families["null_grouping"].append(("users",[{"event_date":broad_ranges[-1]}],"device_type",None,None,"null_grouping"))
                    family_quota=({"row_vs_user_and_purchase_grain":3,"purchase_role_vs_event_literal":3,
                                   "nested_scalar_presence":4,"eligible_group_domain_topk":3,
                                   "ratio_denominator":1,"zero_denominator":0,"null_grouping":1} if split=="dev" else
                                  {"row_vs_user_and_purchase_grain":6,"purchase_role_vs_event_literal":6,
                                   "nested_scalar_presence":8,"eligible_group_domain_topk":6,
                                   "ratio_denominator":2,"zero_denominator":1,"null_grouping":1})
                    patterns=[]
                    for family_name, quota in family_quota.items():
                        if quota == 0: continue
                        selected=[]; seen=set()
                        for candidate in pattern_families[family_name]:
                            signature=sql_for(source,candidate[0],candidate[1],candidate[2],candidate[3],candidate[4])
                            if signature in seen: continue
                            selected.append(candidate); seen.add(signature)
                            if len(selected)>=quota: break
                        if len(selected)<quota:
                            raise ValueError(f"semantic family shortage {split}/{source}/{family_name}: {len(selected)}/{quota}")
                        patterns.extend(selected)
                    idx=0
                    for metric,where,group,limit,order_by,family in patterns:
                        if sum(c["split"]==split and c["stratum"]==stratum and c["source_id"]==source for c in cases)>=n: break
                        candidate=sql_for(source,metric,where,group,limit,order_by)
                        if candidate in sqls: continue
                        add(split,stratum,source,f"{split}_{stratum}_{source}_{idx+1:03}",metric,where,group,limit,order_by,
                            lang="en" if idx%3==0 else "vi",family=family)
                        idx+=1
    expected={(sp,st):num for sp,vals in split_targets.items() for st,num in vals.items()}
    actual={(sp,st):sum(c["split"]==sp and c["stratum"]==st for c in cases) for sp,st in expected}
    if actual!=expected or len(cases)!=300:
        by_source={(sp,st,src):sum(c['split']==sp and c['stratum']==st and c['source_id']==src for c in cases)
                   for sp,st in expected for src in SOURCES}
        fam=__import__('collections').Counter((c['split'],c['source_id'],c['family']) for c in cases)
        raise ValueError(f"quota mismatch: {actual}, by_source={by_source}, families={fam}, total {len(cases)}")
    return cases


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    cases=build_cases()
    (ROOT/"cases.yaml").write_text(yaml.safe_dump(cases,sort_keys=False,allow_unicode=True,width=110),encoding="utf-8")
    manifest={"name":"Texa Research Benchmark v3 candidate","dataset_type":"challenge_candidate","version":3,
      "status":"candidate_agent_reviewed_not_sealed","engine":"PostgreSQL 16+","sources":list(SOURCES),
      "metrics":list(ALL_METRICS),"nested_scalar_paths":["ep.device.type","ep.campaign.channel"],
      "fixture":"worlds/base.sql","fixture_worlds":{
        name:{"file":f"worlds/{name}.sql","rows":len(rows),"cosmetics_rows":sum(r['source']=='cosmetics_shop' for r in rows),"olist_rows":sum(r['source']=='olist_marketplace' for r in rows)}
        for name,rows in ROWS_BY_WORLD.items()},
      "single_turn_suite":"cases.yaml","dialogue_suite":"dialogues.yaml","interaction_suite":"interactions.yaml",
      "split_policy":"300 answerable singles: 100 dev, 200 test. Test strata are 40 basic, 100 compositional, 60 semantic; dev 20/50/30. Each stratum is evenly allocated across Cosmetics Shop and Olist. Query families are labeled by phenomenon, not split prefix; template overlap is intentional and the split is not claimed to be family-disjoint. The three fixture worlds expose controlled grain/coverage changes, and every gold result is authored for each world.",
      "test_strata":{"basic":40,"compositional":100,"semantic":60},"dev_strata":{"basic":20,"compositional":50,"semantic":30},
      "source_capability_notes":{"cosmetics_shop":"challenge-only synthetic events include sessions, views, device and campaign scalar paths.",
        "olist_marketplace":"challenge-only order item/payment/approval events; no synthetic sessions or viewers. Nested device/campaign fields are declared fixture extensions, not claims about the production source."},
      "metric_semantics":"Olist users are distinct customers observed in order-lifecycle events, not all website visitors. Olist buyer_conversion_rate is buyers divided by observed event-customers; it must not be described as visitor-to-buyer conversion. Purchase revenue is item-line revenue, excluding payment_made event values.",
      "family_counts":dict(__import__('collections').Counter(c['family'] for c in cases)),
      "provenance":"Fixture records reused from challenge_v1; this generator independently authors new query specs/SQL and computes expected results in Python for every controlled world. No Texa compiler or LLM generates the gold.",
      "human_review":"pending two independent reviewers","sealed":False,"test_labels_exposed_to_author":True,
      "limitations":"Synthetic controlled worlds do not estimate accuracy on live Cosmetics Shop or Olist data. Test labels are visible to the author and the candidate must be externally reviewed and sealed before confirmatory claims.",
      "counts":{"single_total":300,"single_dev":100,"single_test":200,"clarification_total":60,"clarification_ambiguous":30,"clarification_clear_controls":30,"conversation_total":40,"unsupported_total":40}}
    (ROOT/"worlds").mkdir(exist_ok=True)
    for name in ROWS_BY_WORLD:
        copyfile(PROJECT/f"data/benchmark/challenge_v1/worlds/{name}.sql",ROOT/f"worlds/{name}.sql")
    (ROOT/"manifest.yaml").write_text(yaml.safe_dump(manifest,sort_keys=False,allow_unicode=True),encoding="utf-8")


if __name__=="__main__": main()
