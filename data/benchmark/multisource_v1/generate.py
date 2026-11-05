"""Freeze the small, explicitly synthetic multi-source diagnostic fixture."""
from pathlib import Path
import yaml

OUT = Path(__file__).parent
ROWS = {
    "cosmetics_shop": [
        ("c1", "2019-12-01", "purchase", "u1", "s1", "101", "skin", 10, "USD"),
        ("c2", "2019-12-01", "view", "u2", "s2", "102", "hair", None, "USD"),
        ("c3", "2019-12-02", "purchase", "u1", "s1", "103", "skin", 20, "USD"),
        ("c4", "2019-12-02", "cart", "u3", "s3", "104", "hair", None, "USD"),
        ("c5", "2019-12-03", "view", "u3", "s4", "105", "skin", None, "USD"),
        ("c6", "2019-12-03", "purchase", "u4", "s5", "106", "makeup", 30, "USD"),
        ("c7", "2019-12-04", "purchase", "u2", "s2", "107", "hair", 0, "USD"),
        ("c8", "2019-12-04", "view", "u5", "s6", "108", "makeup", None, "USD"),
    ],
    "olist_marketplace": [
        ("o1", "2019-12-01", "order_purchased", "u1", None, "101", "skin", 10, "BRL"),
        ("o2", "2019-12-01", "payment_made", "u1", None, None, None, 15, "BRL"),
        ("o3", "2019-12-01", "order_approved", "u1", None, None, None, None, "BRL"),
        ("o4", "2019-12-02", "order_purchased", "u2", None, "102", "hair", 20, "BRL"),
        ("o5", "2019-12-02", "payment_made", "u2", None, None, None, 25, "BRL"),
        ("o6", "2019-12-03", "order_delivered", "u1", None, None, None, None, "BRL"),
        ("o7", "2019-12-03", "order_purchased", "u3", None, "103", "skin", 30, "BRL"),
        ("o8", "2019-12-04", "payment_made", "u3", None, None, None, 30, "BRL"),
    ],
}

def q(s): return "'" + str(s).replace("'", "''") + "'"
def result(cols, rows): return {"columns": cols, "rows": [list(r) for r in rows]}

def main():
    sql = ["-- Diagnostic fixture: synthetic rows only; never remove pre-existing source rows.",
           "DO $$ BEGIN IF current_database() <> 'texa_benchmark' THEN RAISE EXCEPTION 'wrong database'; END IF;",
           "IF EXISTS (SELECT 1 FROM analytics.event_activity WHERE source_id IN ('cosmetics_shop','olist_marketplace')) THEN RAISE EXCEPTION 'refusing existing cosmetics/olist rows'; END IF; END $$;"]
    for source, rows in ROWS.items():
        sql.append("INSERT INTO analytics.event_activity (event_id,source_id,event_ts,event_date,event_name,user_id,session_id,first_seen_date,item_id,item_category,revenue,currency,ep,up,src_table) VALUES")
        values=[]
        for eid, day, ev, user, sess, item, cat, rev, cur in rows:
            values.append("("+",".join([q("msv1_"+eid),q(source),q(day+" 12:00:00+00"),q(day),q(ev),q(user),q(sess) if sess else "NULL",q(day),q(item) if item else "NULL",q(cat) if cat else "NULL",str(rev) if rev is not None else "NULL",q(cur),"'{}'::jsonb","'{}'::jsonb",q("multisource_v1")])+")")
        sql.append(",\n".join(values)+";")
        users=len({r[3] for r in rows}); sql.append(f"INSERT INTO analytics.source_registry(source_id,label,description,currency,min_date,max_date,row_count,user_count,last_loaded_at) VALUES ({q(source)}, {q('Synthetic diagnostic '+source)}, 'Synthetic diagnostic rows only; not a real warehouse', {q(rows[0][8])}, '2019-12-01','2019-12-04',{len(rows)},{users},now());")
        for ev in sorted({r[2] for r in rows}):
            n=sum(r[2]==ev for r in rows); sql.append(f"INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ({q(source)},'event_name','event_name',{q(ev)},{n},'2019-12-04');")
    (OUT/'fixture.sql').write_text("\n".join(sql)+"\n")
    cases=[]
    def add(source, suffix, question, query, cols, vals, family):
        cases.append(dict(id=f"msv1_{source}_{suffix}", split="dev", family=family,
          question=question, gold_sql=query, expected_result=result(cols, vals), ordered="ORDER BY" in query.upper(), in_scope=True,
          intent=family, difficulty="easy", tags=["synthetic",source,"diagnostic"]))
    for src, rows in ROWS.items():
        # Each diagnostic query uses a single source and the product metric contract.
        label="cosmetics shop" if src=="cosmetics_shop" else "Olist marketplace"
        add(src,"users",f"How many distinct users in {label} during 2019-12-01 through 2019-12-04?",f"SELECT count(DISTINCT user_id)::bigint AS users FROM analytics.event_activity WHERE source_id='{src}' AND event_date BETWEEN '2019-12-01' AND '2019-12-04'",["users"],[(len({r[3] for r in rows}),)],"users_total")
        for day in sorted({r[1] for r in rows}):
            add(src,"users_"+day[-2:],f"How many distinct users in {label} on {day}?",f"SELECT count(DISTINCT user_id)::bigint AS users FROM analytics.event_activity WHERE source_id='{src}' AND event_date='{day}'",["users"],[(len({r[3] for r in rows if r[1]==day}),)],"users_day")
        cats=sorted({r[6] for r in rows if r[6]})
        add(src,"users_by_category",f"Show the top 3 non-null product categories by distinct recorded users in {label} for December 1–4, 2019.",f"SELECT item_category, count(DISTINCT user_id)::bigint AS users FROM analytics.event_activity WHERE source_id='{src}' AND event_date BETWEEN '2019-12-01' AND '2019-12-04' AND item_category IS NOT NULL GROUP BY 1 ORDER BY 2 DESC,1 LIMIT 3",["item_category","users"],[(c,len({r[3] for r in rows if r[6]==c})) for c in sorted(cats,key=lambda c:(-len({r[3] for r in rows if r[6]==c}),c))[:3]],"top_users_category")
        for cat in cats:
            n=len({r[3] for r in rows if r[6]==cat})
            add(src,"category_"+cat,f"How many distinct users had recorded events in category {cat} in {label} from 2019-12-01 through 2019-12-04?",f"SELECT count(DISTINCT user_id)::bigint AS users FROM analytics.event_activity WHERE source_id='{src}' AND item_category='{cat}' AND event_date BETWEEN '2019-12-01' AND '2019-12-04'",["users"],[(n,)],"category_users")
        role_event="purchase" if src=="cosmetics_shop" else "order_purchased"
        rev=sum(r[7] or 0 for r in rows if r[2]==role_event)
        add(src,"revenue",f"What is total purchase value in {label}, 2019-12-01 through 2019-12-04?",f"SELECT coalesce(sum(revenue),0)::numeric AS revenue FROM analytics.event_activity WHERE source_id='{src}' AND event_name='{role_event}' AND event_date BETWEEN '2019-12-01' AND '2019-12-04'",["revenue"],[(rev,)],"revenue_total")
        add(src,"empty_users",f"How many users did {label} have on 2020-01-01?",f"SELECT count(DISTINCT user_id)::bigint AS users FROM analytics.event_activity WHERE source_id='{src}' AND event_date='2020-01-01'",["users"],[(0,)],"empty_date")
        add(src,"daily_purchases",f"Show each date with purchase-role rows and its count in {label} from 2019-12-01 through 2019-12-04.",f"SELECT event_date, count(*)::bigint AS purchases FROM analytics.event_activity WHERE source_id='{src}' AND event_name='{role_event}' AND event_date BETWEEN '2019-12-01' AND '2019-12-04' GROUP BY 1 ORDER BY 1",["event_date","purchases"],[(d,sum(r[1]==d and r[2]==role_event for r in rows)) for d in sorted({r[1] for r in rows}) if sum(r[1]==d and r[2]==role_event for r in rows)],"daily_purchases")
    add("olist_marketplace","purchases","How many purchase-role rows did Olist record between 2019-12-01 and 2019-12-04?", "SELECT count(*)::bigint AS purchases FROM analytics.event_activity WHERE source_id='olist_marketplace' AND event_name='order_purchased' AND event_date BETWEEN '2019-12-01' AND '2019-12-04'",["purchases"],[(3,)],"olist_purchases")
    (OUT/'cases.yaml').write_text(yaml.safe_dump(cases,sort_keys=False,allow_unicode=True))
    dialogue=[
      {"id":"msv1_missing_period","split":"dev","family":"missing_period","dependency_distance":0,"turns":[{"question":"Show users in cosmetics_shop.","action":"clarify","ask_fields":["time_range"]},{"question":"Use all available dates in cosmetics_shop.","action":"clarification_answer","state":{"metric":"users","source_ids":["cosmetics_shop"],"time_range":"all","filters":[],"breakdown":None},"gold_sql":"SELECT count(DISTINCT user_id)::bigint AS users FROM analytics.event_activity WHERE source_id='cosmetics_shop'","expected_result":result(["users"],[(5,)]),"oracle_answers":{"time_range":["all"]}}]},
      {"id":"msv1_cross_source","split":"dev","family":"cross_source_refusal","dependency_distance":0,"turns":[{"question":"Compare revenue across cosmetics_shop and olist_marketplace for 2019-12-01 through 2019-12-04.","action":"refuse"}]},
      {"id":"msv1_olist_payment_grain","split":"dev","family":"olist_payment_grain","dependency_distance":0,"turns":[{"question":"How much Olist payment value, deduplicated to orders, was collected from 2019-12-01 through 2019-12-04?","action":"refuse"}]},
      {"id":"msv1_olist_sessions","split":"dev","family":"unsupported_sessions","dependency_distance":0,"turns":[{"question":"How many sessions did Olist have between 2019-12-01 and 2019-12-04?","action":"refuse"}]},
      {"id":"msv1_array_refusal","split":"dev","family":"unsupported_array","dependency_distance":0,"turns":[{"question":"For cosmetics_shop, break revenue down by each entry in an event array field for 2019-12-01 through 2019-12-04.","action":"refuse"}]},
      {"id":"msv1_source_memory","split":"dev","family":"source_switch","dependency_distance":1,"turns":[{"question":"How many users in cosmetics_shop on 2019-12-01?","action":"answer","state":{"metric":"users","source_ids":["cosmetics_shop"],"time_range":"2019-12-01","filters":[],"breakdown":None},"gold_sql":"SELECT count(DISTINCT user_id)::bigint AS users FROM analytics.event_activity WHERE source_id='cosmetics_shop' AND event_date='2019-12-01'","expected_result":result(["users"],[(2,)])},{"question":"And for Olist on that same day?","action":"answer","state":{"metric":"users","source_ids":["olist_marketplace"],"time_range":"2019-12-01","filters":[],"breakdown":None},"gold_sql":"SELECT count(DISTINCT user_id)::bigint AS users FROM analytics.event_activity WHERE source_id='olist_marketplace' AND event_date='2019-12-01'","expected_result":result(["users"],[(1,)],),"referenced_turn":1}]}
    ]
    (OUT/'dialogues.yaml').write_text(yaml.safe_dump(dialogue,sort_keys=False,allow_unicode=True))
    manifest={"name":"multisource-v1-diagnostic","version":1,"engine":"PostgreSQL 16+","source_id":["cosmetics_shop","olist_marketplace"],"timezone":"UTC","date_semantics":"event_date UTC inclusive dates","grain":"Synthetic diagnostics only: cosmetics rows are events; Olist rows are lifecycle events including one item-row per order item and payment rows.","fixture_rows":16,"schema":"analytics.event_activity: source_id text, event_id text, event_date date, event_name text, user_id text, session_id text, item_id text, item_category text, revenue numeric, currency text, ep jsonb. Filter to exactly one named source in every query. Synthetic fixture labels are not real warehouses; the existing source identifiers are reused only to exercise catalog behavior.","metric_definitions":"Only existing eight catalog metrics may be requested: events=count event rows; users=distinct user_id; sessions=distinct non-null session_id; viewers=distinct users with view event; buyers=distinct users with purchase-role event; purchases=count purchase-role rows; revenue=sum source-native revenue on purchase-role order item rows (USD cosmetics; BRL Olist order_purchased only, never payment_made); buyer_conversion_rate=buyers/users, zero denominator NULL. Olist item rows are not orders; payment-row/order-deduplicated metrics are unsupported. Olist has no sessions or views; refuse. Do not compare/combine sources or currencies.","output_aliases":{"metrics":{"events":"events","users":"users","sessions":"sessions","viewers":"viewers","buyers":"buyers","purchases":"purchases","revenue":"revenue","buyer_conversion_rate":"buyer_conversion_rate"},"dimensions":{"event_date":"event_date","device_type":"device_type","campaign_channel":"campaign_channel","item_category":"item_category"}},"interaction_policy":"Development-only diagnostic, no held-out/test split or benchmark claim. Select one explicit source; clarify missing dates; refuse cross-source questions and unsupported Olist sessions/views/payment deduplication.","result_policy":{"row_order":"ordered where SQL explicitly orders","numeric_absolute_tolerance":1e-6,"numeric_relative_tolerance":1e-6},"limitations":"Small deterministic synthetic diagnostic fixtures, not production data or a representative benchmark. No live-model accuracy implied.","provenance":"generate.py computes expected tables from source records using Python aggregates; fixture rows explicitly synthetic.","case_counts":{"single_turn_total":len(cases),"dev":len(cases),"test":0,"dialogues":len(dialogue),"dialogue_longest_turns":max(len(d['turns']) for d in dialogue)}}
    (OUT/'manifest.yaml').write_text(yaml.safe_dump(manifest,sort_keys=False,allow_unicode=True))

if __name__ == '__main__': main()
