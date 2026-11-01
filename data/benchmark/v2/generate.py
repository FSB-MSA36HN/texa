"""Generate frozen v2 synthetic event fixture and independently annotated cases.

Expected rows are computed in Python from source records; gold SQL is emitted from
separate declarative query specs and never uses the Texa QuerySpec/compiler.
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
SOURCE = "event_benchmark"
DEVICE = ["mobile", "desktop", "tablet", "unknown"]
CHANNEL = ["paid", "organic", "email", "referral"]
CATEGORY = ["shoes", "books", "toys", "home", "clearance"]


def make_rows():
    rows=[]
    start=date(2025,1,27)
    rng=random.Random(20250203)
    event_names=["view"]*4+["cart"]*2+["purchase"]*3+["remove_from_cart"]
    for i in range(96):
        day=start+timedelta(days=(i*7//96))
        name="view" if i==95 else rng.choice(event_names)
        user=f"u{rng.randrange(19):02d}"
        session=f"s{rng.randrange(26):02d}"
        device=rng.choice(DEVICE)
        channel=rng.choice(CHANNEL)
        category="clearance" if i==95 else rng.choice(CATEGORY[:-1])
        revenue=(0 if i%11==0 else rng.randrange(1,19)*5) if name=="purchase" else None
        # Deliberate missing JSON key and explicit JSON null; dimension extraction is SQL NULL.
        ep={"product":{"category":category}}
        if i%13: ep["device"]={"type":device}
        elif i%26==0: ep["device"]={"type":None}
        if i%17: ep["campaign"]={"channel":channel}
        elif i%34==0: ep["campaign"]={"channel":None}
        if name=="purchase" and i%5: ep["checkout"]={"amount":str(revenue)}
        rows.append(dict(event_id=f"v2_{i+1:03d}",event_date=day.isoformat(),event_name=name,user_id=user,
             session_id=session,device_type=(None if i%13==0 else device),campaign_channel=(None if i%17==0 else channel),
             item_category=category,revenue=revenue,ep=ep))
    return rows


def lit(v):
    return "NULL" if v is None else "'"+str(v).replace("'","''")+"'"


def fixture(rows):
    out=["-- v2 frozen synthetic event fixture; apply only to texa_benchmark.",
         "CREATE TABLE IF NOT EXISTS analytics.event_activity_event_benchmark PARTITION OF analytics.event_activity FOR VALUES IN ('event_benchmark');",
         "DELETE FROM analytics.event_activity WHERE source_id='event_benchmark';",
         "INSERT INTO analytics.event_activity (event_id,source_id,event_ts,event_date,event_name,user_id,session_id,first_seen_date,platform,item_category,revenue,ep,up,src_table) VALUES"]
    vals=[]
    for i,r in enumerate(rows):
        ts=r['event_date']+f" {8+i%12:02d}:{(i*13)%60:02d}+00"
        vals.append("("+",".join([lit(r['event_id']),lit(SOURCE),lit(ts),lit(r['event_date']),lit(r['event_name']),lit(r['user_id']),lit(r['session_id']),lit(r['event_date']),lit('web' if i%2 else 'ios'),lit(r['item_category']),str(r['revenue']) if r['revenue'] is not None else 'NULL',lit(json.dumps(r['ep'],separators=(',',':')))+"::jsonb", "'{}'::jsonb",lit('v2')])+")")
    out.append(",\n".join(vals)+";")
    min_date=min(r["event_date"] for r in rows); max_date=max(r["event_date"] for r in rows); users=len({r["user_id"] for r in rows})
    out += [f"INSERT INTO analytics.source_registry (source_id,label,description,currency,min_date,max_date,row_count,user_count,last_loaded_at) VALUES ('event_benchmark','Synthetic product events v2','Frozen generated {len(rows)}-row benchmark fixture','USD',{lit(min_date)},{lit(max_date)},{len(rows)},{users},now()) ON CONFLICT(source_id) DO UPDATE SET label=EXCLUDED.label,description=EXCLUDED.description,currency=EXCLUDED.currency,min_date=EXCLUDED.min_date,max_date=EXCLUDED.max_date,row_count=EXCLUDED.row_count,user_count=EXCLUDED.user_count,last_loaded_at=now();",
      "DELETE FROM analytics.vocabulary WHERE source_id='event_benchmark';",
      "INSERT INTO analytics.vocabulary (source_id,kind,field,value,event_count,last_seen) SELECT source_id,'event_name','event_name',event_name,count(*),max(event_date) FROM analytics.event_activity WHERE source_id='event_benchmark' GROUP BY source_id,event_name;",
      "INSERT INTO analytics.vocabulary (source_id,kind,field,value,event_count,last_seen) SELECT 'event_benchmark','ep_key','ep',p,96,'2025-02-02' FROM (VALUES ('device.type'),('campaign.channel'),('product.category'),('checkout.amount')) x(p);",
      "INSERT INTO analytics.vocabulary (source_id,kind,field,value,event_count,last_seen) SELECT 'event_benchmark','column','column',c,96,'2025-02-02' FROM (VALUES ('event_date'),('event_name'),('user_id'),('session_id'),('item_category'),('revenue')) x(c);"]
    return "\n".join(out)+"\n"


def sql(spec):
    m,where,group=spec
    expr={"events":"count(*)::bigint","users":"count(DISTINCT user_id)::bigint",
          "sessions":"count(DISTINCT session_id)::bigint",
          "viewers":"count(DISTINCT user_id) FILTER (WHERE event_name='view')::bigint",
          "buyers":"count(DISTINCT user_id) FILTER (WHERE event_name='purchase')::bigint",
          "purchases":"count(*) FILTER (WHERE event_name='purchase')::bigint",
          "revenue":"coalesce(sum(revenue) FILTER (WHERE event_name='purchase'),0)::numeric",
          "buyer_conversion_rate":"count(DISTINCT user_id) FILTER (WHERE event_name='purchase')::numeric / nullif(count(DISTINCT user_id),0)"}[m]
    prefix=""
    if group:
        ge={"event_date":"event_date","device_type":"ep #>> '{device,type}' AS device_type","campaign_channel":"ep #>> '{campaign,channel}' AS campaign_channel","item_category":"item_category"}[group]
        prefix=f"{ge}, "
    clauses=["source_id='event_benchmark'"]
    for clause in where:
        if clause.startswith("event_date BETWEEN"):
            clauses.append(clause); continue
        field,value=clause.split("=",1)
        field_sql={"device_type":"ep #>> '{device,type}'","campaign_channel":"ep #>> '{campaign,channel}'","item_category":"item_category","event_date":"event_date","event_name":"event_name"}.get(field,field)
        clauses.append(f"{field_sql}={value}")
    return f"SELECT {prefix}{expr} AS {m} FROM analytics.event_activity WHERE {' AND '.join(clauses)}"+(f" GROUP BY 1 ORDER BY 1" if group else "")


def evaluate(rows,spec):
    metric,where,group=spec
    def passes(r):
        for clause in where:
            if clause.startswith("event_date BETWEEN"):
                import re
                a,b=re.findall(r"'([^']+)'",clause)
                if not a<=r['event_date']<=b:return False
            elif clause.startswith("event_date="):
                if r['event_date']!=clause.split("'")[1]: return False
            elif clause.startswith("event_name="):
                if r['event_name']!=clause.split("'")[1]:return False
            elif clause.startswith("device_type="):
                if r['device_type']!=clause.split("'")[1]:return False
            elif clause.startswith("campaign_channel="):
                if r['campaign_channel']!=clause.split("'")[1]:return False
            elif clause.startswith("item_category="):
                if r['item_category']!=clause.split("'")[1]:return False
            else:
                raise ValueError(f"unsupported reference clause: {clause}")
        return True
    data=[r for r in rows if passes(r)]
    def val(rs):
        users={r['user_id'] for r in rs}; buyers={r['user_id'] for r in rs if r['event_name']=='purchase'}
        return {"events":len(rs),"users":len(users),"sessions":len({r['session_id'] for r in rs}),
          "viewers":len({r['user_id'] for r in rs if r['event_name']=='view'}),"buyers":len(buyers),
          "purchases":sum(r['event_name']=='purchase' for r in rs),"revenue":sum(r['revenue'] or 0 for r in rs if r['event_name']=='purchase'),
          "buyer_conversion_rate":(len(buyers)/len(users) if users else None)}[metric]
    if not group:return {"columns":[metric],"rows":[[val(data)]]}
    key={"event_date":"event_date","device_type":"device_type","campaign_channel":"campaign_channel","item_category":"item_category"}[group]
    all_values=sorted({r[key] for r in data},key=lambda v:(v is None,"" if v is None else str(v)))
    groups={v:[r for r in data if r[key]==v] for v in all_values}
    return {"columns":[group,metric],"rows":[[v,val(groups[v])] for v in all_values]}


def build():
    rows=make_rows(); cases=[]
    # Distinct question families by split. Dev explores date windows/filters; test
    # holds dimension breakouts and event-type conditional metrics.
    dims=[("device_type",DEVICE),("campaign_channel",CHANNEL),("item_category",CATEGORY)]
    metrics=["events","users","sessions","viewers","buyers","purchases","revenue","buyer_conversion_rate"]
    metric_vi={"events":"lượt sự kiện","users":"người dùng riêng biệt","sessions":"phiên truy cập","viewers":"người đã xem","buyers":"người mua","purchases":"lượt mua","revenue":"doanh thu từ mua hàng","buyer_conversion_rate":"tỷ lệ người mua trên người dùng"}
    dim_vi={"device_type":"loại thiết bị","campaign_channel":"kênh tiếp thị","item_category":"danh mục sản phẩm"}
    for i,m in enumerate(metrics):
        where=["event_date BETWEEN '2025-01-29' AND '2025-02-02'"]
        split="dev"; family="dev_date_window"
        cases.append(dict(id=f"v2_dev_window_{m}",split=split,family=family,question=f"Cho biết {metric_vi[m]} từ ngày 29/1 đến hết ngày 2/2/2025.",gold_sql=sql((m,where,None)),expected_result=evaluate(rows,(m,where,None)),in_scope=True))
        for j,(d,vals) in enumerate(dims):
            chosen=vals[(i+j+1)%len(vals)]
            filt=[f"{d}='{chosen}'"]
            cases.append(dict(id=f"v2_dev_filter_{m}_{d}",split="dev",family="dev_attribute_filters",question=f"Trong toàn bộ dữ liệu, cho biết {metric_vi[m]} khi {dim_vi[d]} là {chosen}.",gold_sql=sql((m,filt,None)),expected_result=evaluate(rows,(m,filt,None)),in_scope=True))
    for m in metrics:
        for d,_ in dims:
            where=[]
            cases.append(dict(id=f"v2_test_break_{m}_{d}",split="test",family=f"test_breakdown_{d}",question=f"Trong toàn bộ dữ liệu, phân tích {metric_vi[m]} theo {dim_vi[d]}.",gold_sql=sql((m,where,d)),expected_result=evaluate(rows,(m,where,d)),in_scope=True))
    # Test date-edge filters; family held out from development.
    for day in ["2025-01-27","2025-01-31","2025-02-01","2025-02-02"]:
        for m in ["events","buyers","revenue","users"]:
            w=[f"event_date='{day}'"]
            cases.append(dict(id=f"v2_test_day_{day[-2:]}_{m}",split="test",family="test_date_edges",question=f"Báo cáo {metric_vi[m]} trong ngày {int(day[-2:])}/{int(day[5:7])}/2025.",gold_sql=sql((m,w,None)),expected_result=evaluate(rows,(m,w,None)),in_scope=True))
    for name in ["view","cart","purchase","remove_from_cart"]:
        for m in ["events","users"]:
            w=[f"event_name='{name}'"]
            event_vi={"view":"xem sản phẩm","cart":"thêm vào giỏ hàng","purchase":"mua hàng","remove_from_cart":"xóa khỏi giỏ hàng"}[name]
            cases.append(dict(id=f"v2_test_event_{name}_{m}",split="test",family="test_event_conditionals",question=f"Trong toàn bộ dữ liệu, có bao nhiêu {metric_vi[m]} gắn với sự kiện {event_vi}?",gold_sql=sql((m,w,None)),expected_result=evaluate(rows,(m,w,None)),in_scope=True))
    for m in metrics:
        w=["event_date='2025-02-03'"]
        cases.append(dict(id=f"v2_test_empty_{m}",split="test",family="test_empty_aggregate",question=f"Cho biết {metric_vi[m]} ngày 3/2/2025 (ngày không có sự kiện nào).",gold_sql=sql((m,w,None)),expected_result=evaluate(rows,(m,w,None)),in_scope=True))
    for i,(d,values) in enumerate(dims):
        chosen=values[(i+1)%len(values)]
        w=["event_name='purchase'",f"{d}='{chosen}'"]
        cases.append(dict(id=f"v2_test_purchase_filter_{d}",split="test",family="test_purchase_nested_filters",question=f"Trong toàn bộ dữ liệu, có bao nhiêu người mua hàng khi {dim_vi[d]} là {chosen}?",gold_sql=sql(("buyers",w,None)),expected_result=evaluate(rows,("buyers",w,None)),in_scope=True))
    for i,m in enumerate(["revenue","buyers","events","users","revenue","buyers","events","users","revenue"]):
        d1,v1=dims[i%3]; d2,v2=dims[(i+1)%3]
        spec=[f"{d1}='{v1[(i+1)%len(v1)]}'",f"{d2}='{v2[(i+2)%len(v2)]}'"]
        cases.append(dict(id=f"v2_dev_compound_{i+1:02d}",split="dev",family="dev_compound_filters",question=f"Trong toàn bộ dữ liệu, cho biết {metric_vi[m]} với {dim_vi[d1]} là {v1[(i+1)%len(v1)]} đồng thời {dim_vi[d2]} là {v2[(i+2)%len(v2)]}.",gold_sql=sql((m,spec,None)),expected_result=evaluate(rows,(m,spec,None)),in_scope=True))
    for m,d,k in [("revenue","item_category",3),("buyers","device_type",3),("events","campaign_channel",3),("purchases","item_category",2)]:
        base_sql=sql((m,[],d))
        ranked=base_sql.replace("GROUP BY 1 ORDER BY 1",f"GROUP BY 1 ORDER BY {m} DESC, {d} ASC NULLS LAST LIMIT {k}")
        expected=evaluate(rows,(m,[],d))
        expected["rows"].sort(key=lambda row:(-(float(row[1] or 0)),row[0] is None,"" if row[0] is None else str(row[0])))
        expected["rows"]=expected["rows"][:k]
        cases.append(dict(id=f"v2_test_top_{m}_{d}",split="test",family="test_top_k_ranking",question=f"Trong toàn bộ dữ liệu, xếp hạng top {k} {dim_vi[d]} theo {metric_vi[m]} từ cao xuống thấp.",gold_sql=ranked,expected_result=expected,in_scope=True,ordered=True,top_k=k))
    # Each test family must not cross splits. All families above are split exclusive.
    for c in cases:
        c["intent"] = c["family"]
        c["difficulty"] = ("easy" if c["family"] in {"dev_date_window","test_date_edges"} else "hard" if c["family"] in {"dev_compound_filters","test_purchase_nested_filters"} else "medium")
        c["tags"] = ["event", "nested_scalar" if "device_type" in c["id"] or "campaign_channel" in c["id"] else "relational_dimension", c["split"]]
    (ROOT/"cases.yaml").write_text(yaml.safe_dump(cases,sort_keys=False,allow_unicode=True,width=110),encoding="utf-8")
    (ROOT/"fixture.sql").write_text(fixture(rows),encoding="utf-8")
    build_dialogues(cases)
    return rows,cases


def build_dialogues(cases):
    rows=make_rows()
    def answer(question,metric,time_range="all",filters=None,breakdown=None,reference=None):
        filters=filters or []; where=[]
        if isinstance(time_range,str) and time_range!="all": where.append(f"event_date='{time_range}'")
        elif isinstance(time_range,dict): where.append(f"event_date BETWEEN '{time_range['start']}' AND '{time_range['end']}'")
        for f in filters:
            key,value=next(iter(f.items())); where.append(f"{key}='{value}'")
        spec=(metric,where,breakdown)
        turn={"question":question,"action":"answer","state":{"metric":metric,"time_range":time_range,"filters":filters,"breakdown":breakdown},"gold_sql":sql(spec),"expected_result":evaluate(rows,spec)}
        if reference is not None: turn["referenced_turn"]=reference
        return turn

    dev=[
      ("dlg_v2_followup_date_filter","dev_followup_filter",[answer("Tính doanh thu mua hàng ngày 31/1/2025.","revenue","2025-01-31"),answer("Chỉ trên mobile.","revenue","2025-01-31",[{"device_type":"mobile"}],reference=1)]),
      ("dlg_v2_missing_period_clarify","dev_missing_period",[{"question":"Cho tôi doanh thu mua hàng theo từng ngày.","action":"clarify","ask_fields":["time_range"]},{**answer("Xem toàn bộ dữ liệu.","revenue","all",breakdown="event_date"),"action":"clarification_answer","oracle_answers":{"time_range":["all"]}}]),
      ("dlg_v2_noise_reuse","dev_noise_reuse",[answer("Có bao nhiêu người mua ngày 1/2/2025?","buyers","2025-02-01"),{"question":"Cảm ơn, bạn giải thích rõ rồi.","action":"conversation"},answer("Chia kết quả đó theo danh mục sản phẩm.","buyers","2025-02-01",breakdown="item_category",reference=1)]),
      ("dlg_v2_correction_date","dev_correction",[answer("Đếm phiên truy cập ngày 30/1/2025.","sessions","2025-01-30"),answer("Tôi nói nhầm, đổi sang ngày 31/1/2025.","sessions","2025-01-31",reference=1)]),
      ("dlg_v2_compound_filter","dev_compound_followup",[answer("Tổng doanh thu mua hàng toàn thời gian từ kênh paid?","revenue","all",[{"campaign_channel":"paid"}]),answer("Cộng thêm điều kiện thiết bị mobile.","revenue","all",[{"campaign_channel":"paid"},{"device_type":"mobile"}],reference=1)])]
    long8=[answer("Doanh thu mua hàng ngày 1/2/2025 là bao nhiêu?","revenue","2025-02-01"),{"question":"Chào bạn.","action":"conversation"},answer("Đếm sự kiện ngày 31/1/2025.","events","2025-01-31"),{"question":"Cảm ơn.","action":"conversation"},answer("Có bao nhiêu phiên ngày 2/2/2025?","sessions","2025-02-02"),{"question":"Đợi tôi ghi chú một chút.","action":"conversation"},answer("Số người dùng ngày 27/1/2025?","users","2025-01-27"),answer("Quay lại doanh thu câu đầu, chia theo kênh tiếp thị.","revenue","2025-02-01",breakdown="campaign_channel",reference=1)]
    dev.append(("dlg_v2_long_8","dev_long_dependency_8",long8))

    test=[
      ("dlg_v2_date_comparison","test_two_periods",[answer("Có bao nhiêu người dùng ngày 31/1/2025?","users","2025-01-31"),answer("Còn ngày 1/2/2025 thì sao?","users","2025-02-01",reference=1)]),
      ("dlg_v2_switch_return","test_topic_switch_return",[answer("Doanh thu mua hàng ngày 27/1/2025?","revenue","2025-01-27"),answer("Đếm người dùng ngày 1/2/2025.","users","2025-02-01"),answer("Quay lại doanh thu ngày đầu, phân theo danh mục.","revenue","2025-01-27",breakdown="item_category",reference=1)]),
      ("dlg_v2_explicit_range","test_inclusive_range",[answer("Đếm người mua từ 31/1 đến hết 2/2/2025.","buyers",{"kind":"between","start":"2025-01-31","end":"2025-02-02"}),answer("Và chia theo thiết bị.","buyers",{"kind":"between","start":"2025-01-31","end":"2025-02-02"},breakdown="device_type",reference=1)]),
      ("dlg_v2_out_of_scope","test_out_of_scope",[{"question":"Đếm từng phần tử trong mảng items của payload.","action":"refuse"},answer("Vậy tổng người dùng toàn bộ dữ liệu là bao nhiêu?","users","all")]),
      ("dlg_v2_nested_correction","test_nested_correction",[answer("Đếm người mua toàn thời gian từ kênh organic.","buyers","all",[{"campaign_channel":"organic"}]),answer("Sửa kênh thành referral.","buyers","all",[{"campaign_channel":"referral"}],reference=1)])]
    long10=[answer("Đếm tất cả sự kiện ngày 31/1/2025.","events","2025-01-31"),answer("Doanh thu ngày 1/2/2025?","revenue","2025-02-01"),{"question":"Xin chào.","action":"conversation"},answer("Số người dùng 2/2/2025?","users","2025-02-02"),{"question":"Cảm ơn.","action":"conversation"},answer("Đếm phiên ngày 27/1/2025.","sessions","2025-01-27"),{"question":"Để tôi đọc lại kết quả một chút.","action":"conversation"},answer("Số người mua ngày 30/1/2025?","buyers","2025-01-30"),{"question":"Rõ rồi.","action":"conversation"},answer("Quay lại lượt sự kiện câu đầu, phân theo loại thiết bị.","events","2025-01-31",breakdown="device_type",reference=1)]
    test.append(("dlg_v2_long_10","test_long_dependency_10",long10))
    scenarios=[]
    for split,items in (("dev",dev),("test",test)):
        for ident,family,turn_list in items:
            dependency=max((index-t["referenced_turn"] for index,t in enumerate(turn_list,1) if t.get("referenced_turn")),default=0)
            scenarios.append({"id":ident,"split":split,"family":family,"dependency_distance":dependency,"turns":turn_list})
    (ROOT/"dialogues.yaml").write_text(yaml.safe_dump(scenarios,sort_keys=False,allow_unicode=True,width=110),encoding="utf-8")


if __name__=="__main__":
    rr,cc=build(); print(f"generated rows={len(rr)} cases={len(cc)} dev={sum(c['split']=='dev' for c in cc)} test={sum(c['split']=='test' for c in cc)}")
