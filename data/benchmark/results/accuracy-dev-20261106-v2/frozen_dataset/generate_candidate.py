"""Independent fixture authoring utility; contains no product compiler imports."""
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
CATS = ['serum', 'cream', 'mask', 'cleanser', 'toner', 'sunscreen']
DEV = ['mobile', 'desktop', 'tablet']
CHANNEL = ['paid', 'email']

def cosmetics():
    rows=[]
    start=date(2025,1,1)
    # Designed row archetypes: 24 purchases, 24 views, 12 carts; repeated buyers and visitors-only users.
    for i in range(60):
        day=start+timedelta(days=(i*3)%70)
        if i<24:
            event='purchase'; user=f'buyer{(i%9)+1}'; cat=CATS[(i//2)%6]
            revenue=[0,12,18,25,31,44,None][i%7]
        elif i<48:
            event='view'; user=f'visitor{(i%12)+1}'; cat=CATS[(i//3)%6]; revenue=None
        else:
            event='cart'; user=f'buyer{(i%9)+1}'; cat=CATS[(i-48)%6]; revenue=None
        dev=DEV[i%3]; channel=CHANNEL[(i//2)%2]
        ep={'device':{'type':dev},'campaign':{'channel':channel}}
        if i in (13,37): ep.pop('device')
        if i==18: ep['device']['type']=None
        if i==22: ep.pop('campaign')
        rows.append(dict(source='cosmetics_shop',id=f'cc{i+1:03}',day=day.isoformat(),event=event,user=user,session=f'cs{i//2+1:02}',category=cat,revenue=revenue,ep=ep))
    return rows

def olist():
    rows=[]; start=date(2018,1,1)
    # 30 item lines (two rows for each of 15 orders), 18 payment facts, 12 view rows.
    for i in range(60):
        day=start+timedelta(days=(i*2)%63)
        if i<30:
            event='order_purchased'; order=i//2; user=f'cust{order%10+1}'; cat=CATS[(i//2)%6]
            revenue=[0,15,22,35,None][i%5]
            session=None
        elif i<48:
            event='payment_made'; order=(i-30)//2; user=f'cust{order%10+1}'; cat=None
            revenue=[18,40,62][i%3]; session=None
        else:
            event='order_approved'; user=f'cust{(i-48)%10+1}'; cat=None; revenue=None; session=None
        ep={'device':{'type':DEV[i%3]},'campaign':{'channel':CHANNEL[(i//3)%2]}}
        if i==9: ep.pop('device')
        if i==12: ep['device']['type']=None
        if i==15: ep['campaign']['channel']=None
        rows.append(dict(source='olist_marketplace',id=f'oc{i+1:03}',day=day.isoformat(),event=event,user=user,session=session,category=cat,revenue=revenue,ep=ep))
    return rows

def variants():
    base=cosmetics()+olist()
    yield 'base',base
    grain=[dict(r,ep=dict(r['ep'])) for r in base]
    # A deliberate extra item-line twin makes item versus order grain observable.
    x=next(r for r in grain if r['source']=='olist_marketplace' and r['id']=='oc001')
    twin=dict(x,id='oc061',session='order01')
    grain.append(twin)
    yield 'grain_counterexample',grain
    edge=[dict(r,ep=dict(r['ep'])) for r in base if r['id'] not in {'cc024','oc030'}]
    # Perturbation: remove one eligible zero-price purchase and one nullable item row.
    yield 'coverage_edge',edge

def sql_for(name,rows):
    out=[f'-- Independently authored synthetic challenge world: {name}. Apply only in isolated texa_benchmark.',
         "DELETE FROM analytics.event_activity WHERE source_id IN ('cosmetics_shop','olist_marketplace');",
         "DELETE FROM analytics.vocabulary WHERE source_id IN ('cosmetics_shop','olist_marketplace');"]
    for r in rows:
        ep=json.dumps(r['ep'],separators=(',',':')).replace("'","''")
        rev='NULL' if r['revenue'] is None else str(r['revenue'])
        cat='NULL' if r['category'] is None else "'"+r['category']+"'"
        session='NULL' if r['session'] is None else "'"+r['session'].replace("'","''")+"'"
        out.append("INSERT INTO analytics.event_activity(event_id,source_id,event_ts,event_date,event_name,user_id,session_id,first_seen_date,platform,item_category,revenue,ep,up,src_table) VALUES ("+
          f"'{r['id']}','{r['source']}','{r['day']} 12:00+00','{r['day']}','{r['event']}','{r['user']}',{session},'{r['day']}','web',{cat},{rev},'{ep}'::jsonb,'{{}}'::jsonb,'challenge_v1');")
    for source,label,currency in [('cosmetics_shop','Challenge Cosmetics Shop','USD'),('olist_marketplace','Challenge Olist Marketplace','BRL')]:
        own=[r for r in rows if r['source']==source]
        out.append("INSERT INTO analytics.source_registry(source_id,label,description,currency,min_date,max_date,row_count,user_count,last_loaded_at) VALUES "+
          f"('{source}','{label}','Synthetic challenge_v1 world {name}','{currency}','{min(r['day'] for r in own)}','{max(r['day'] for r in own)}',{len(own)},{len({r['user'] for r in own})},now()) ON CONFLICT(source_id) DO UPDATE SET label=EXCLUDED.label,description=EXCLUDED.description,currency=EXCLUDED.currency,min_date=EXCLUDED.min_date,max_date=EXCLUDED.max_date,row_count=EXCLUDED.row_count,user_count=EXCLUDED.user_count,last_loaded_at=now();")
        for ev in sorted({r['event'] for r in own}):
            n=sum(r['event']==ev for r in own); d=max(r['day'] for r in own if r['event']==ev)
            out.append(f"INSERT INTO analytics.vocabulary VALUES ('{source}','event_name','event_name','{ev}',{n},'{d}') ON CONFLICT DO NOTHING;")
        for col in ('session_id','item_category','revenue'):
            n=sum(r['session'] is not None if col=='session_id' else r['category'] is not None if col=='item_category' else r['revenue'] is not None for r in own)
            if n: out.append(f"INSERT INTO analytics.vocabulary VALUES ('{source}','column','column','{col}',{n},NULL) ON CONFLICT DO NOTHING;")
        for path,expr in [('device.type',"ep #>> '{device,type}'"),('campaign.channel',"ep #>> '{campaign,channel}'")]:
            out.append(f"INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) SELECT '{source}','ep_key','ep','{path}',count(*),max(event_date) FROM analytics.event_activity WHERE source_id='{source}' AND {expr} IS NOT NULL ON CONFLICT(source_id,kind,field,value) DO UPDATE SET event_count=excluded.event_count,last_seen=excluded.last_seen;")
            out.append(f"INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) SELECT '{source}','value','ep.{path}',{expr},count(*),max(event_date) FROM analytics.event_activity WHERE source_id='{source}' AND {expr} IS NOT NULL GROUP BY 4 ON CONFLICT DO NOTHING;")
        for field in ('item_category',):
            out.append(f"INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) SELECT '{source}','value','{field}',{field},count(*),max(event_date) FROM analytics.event_activity WHERE source_id='{source}' AND {field} IS NOT NULL GROUP BY 4 ON CONFLICT DO NOTHING;")
    return '\n'.join(out)+'\n'

if __name__=='__main__':
    d=ROOT/'worlds'; d.mkdir(exist_ok=True)
    for name,rows in variants():
        (d/f'{name}.sql').write_text(sql_for(name,rows))
        print(name, len(rows), {s:sum(r['source']==s for r in rows) for s in ('cosmetics_shop','olist_marketplace')})
