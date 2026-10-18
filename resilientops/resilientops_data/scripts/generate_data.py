"""Reproducible synthetic operations. Python 3.10+; standard library only."""
import argparse, json, random, sqlite3, hashlib
from pathlib import Path
from datetime import date, datetime, time, timedelta, timezone
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
T = defaultdict(list)
KEYS = {}
FKS = []
ORDER = []
META = {}

def add(table, pk, **row):
    if table not in KEYS:
        KEYS[table] = pk
        ORDER.append(table)
    row.update(dataset_version=META['dataset_version'], is_synthetic=True)
    T[table].append(row)
    return row

def fk(table, field, parent, target=None):
    FKS.append((table, field, parent, target or KEYS[parent]))

def stamp(day, hour=0, offset=0):
    return (datetime.combine(day, time(hour), timezone(timedelta(hours=offset))).astimezone(timezone.utc)).isoformat().replace('+00:00','Z')

def main(seed=42, decision='2026-10-01', history_start='2024-01-01'):
    rng = random.Random(seed)
    D=date.fromisoformat(decision); start=date.fromisoformat(history_start); end=D+timedelta(days=30)
    if start>=D: raise ValueError("History start must precede decision date")
    history_days=(D-start).days; total_days=history_days+30
    days=[start+timedelta(days=i) for i in range(total_days)]
    META.update(seed=seed, decision_date=str(D), history_start=str(start), history_end_exclusive=str(D), planning_end_exclusive=str(end), history_days=history_days, planning_days=30, dataset_version=f'v2_{history_start}_{decision}_seed{seed}', decision_time_utc=stamp(D), generation_order=[])
    out=ROOT/'data'; out.mkdir(exist_ok=True)
    # 1. Network and material identities.
    plants=[('MUM','Mumbai','IN','Asia/Kolkata','INR',19.076,72.878,5.5),('TYO','Tokyo','JP','Asia/Tokyo','JPY',35.676,139.650,9),('BJS','Beijing','CN','Asia/Shanghai','CNY',39.904,116.407,8)]
    offsets={f'PLT_{p[0]}':p[7] for p in plants}
    for c,city,country,tz,cur,lat,lon,off in plants:
        add('plants','plant_id',plant_id=f'PLT_{c}',plant_name=f'Fictional {city} Electronics Plant',city=city,country_code=country,timezone=tz,local_currency=cur,latitude=lat,longitude=lon,active=True)
    names=['Control PCB','Microcontroller','Power regulator','Connector assembly','Sensor interface']
    for i in range(1,31):
        m=f'MAT_{i:03}'
        add('materials','material_id',material_id=m,material_name=names[i-1] if i<=5 else f'Component {i:03}',base_uom='EA',quantity_increment=1,criticality='CRITICAL' if i<=5 else 'STANDARD')
        add('material_revisions','material_revision_id',material_revision_id=f'{m}_A',material_id=m,revision_code='A',valid_from=str(start-timedelta(days=365)),valid_to=None,status='ACTIVE')
    prodnames=['Body control module','Vehicle control module','Power control module','Sensor control module']
    for i,n in enumerate(prodnames,1): add('products','product_id',product_id=f'PRD_{i:03}',product_name=n,base_uom='EA')
    # 48 logical BOM lines, with deliberate shared critical components and all 30 components used.
    product_bom={}
    for i in range(4):
        mats=list(range(1,6))+[6+(i*7+j)%25 for j in range(7)]
        product_bom[f'PRD_{i+1:03}']=[(f'MAT_{m:03}_A',1 if m<=5 else 1+(m%3)) for m in mats]
    capabilities=[]; bommap={}; bomlines=defaultdict(list)
    for pi,p in enumerate(T['plants']):
        plant=p['plant_id']
        for l in range(2): add('production_lines','line_id',line_id=f'{plant}_L{l+1}',plant_id=plant,line_name=f'Line {l+1}')
        products=[1,2,3] if pi==0 else ([2,3,4] if pi==1 else [1,4])
        for j,pn in enumerate(products):
            pr=f'PRD_{pn:03}'; line=f'{plant}_L{j%2+1}'; b=f'BOM_{plant}_{pr}_V1'
            cap=add('line_product_capabilities','capability_id',capability_id=f'CAP_{plant}_{pr}',line_id=line,product_id=pr,units_per_hour=50,setup_hours=0.5)
            capabilities.append((plant,pr,line,b))
            add('bom_headers','bom_id',bom_id=b,product_id=pr,plant_id=plant,version=1,output_quantity=1,valid_from=str(start),valid_to=None,status='RELEASED')
            for j,(rev,q) in enumerate(product_bom[pr],1):
                r=add('bom_lines','bom_line_id',bom_line_id=f'{b}_{j}',bom_id=b,material_revision_id=rev,quantity_per_output=q,scrap_rate=0)
                bomlines[b].append(r)
    sitecoords=[(22.54,114.06,'CN','CNY'),(34.69,135.50,'JP','JPY'),(18.52,73.86,'IN','INR')]
    for i in range(1,16):
        lat,lon,co,cu=sitecoords[(i-1)%3]
        s=f'SUP_{i:03}'; ss=f'{s}_SITE'
        add('suppliers','supplier_id',supplier_id=s,supplier_name=f'Fictional Supplier {i:03}',status='ACTIVE')
        add('supplier_sites','supplier_site_id',supplier_site_id=ss,supplier_id=s,latitude=lat+(i//3)*0.02,longitude=lon,country_code=co,currency=cu,status='ACTIVE')
    for i in range(1,13): add('customers','customer_id',customer_id=f'CUS_{i:03}',customer_name=f'Fictional Automotive Customer {i:03}',service_priority=1+(i%3))
    # 2. Routes, approvals and policies before demand or supply.
    for p in T['plants']: add('logistics_nodes','node_id',node_id=p['plant_id'],node_type='PLANT',country_code=p['country_code'],latitude=p['latitude'],longitude=p['longitude'])
    for s in T['supplier_sites']: add('logistics_nodes','node_id',node_id=s['supplier_site_id'],node_type='SUPPLIER_SITE',country_code=s['country_code'],latitude=s['latitude'],longitude=s['longitude'])
    for co,lat,lon in [('CN',22.6,114.25),('JP',35.55,139.78),('IN',19.09,72.87)]: add('logistics_nodes','node_id',node_id=f'HUB_{co}',node_type='SIMULATED_HUB',country_code=co,latitude=lat,longitude=lon)
    route_by={}
    for s in T['supplier_sites']:
        for p in T['plants']:
            rid=f'R_{s["supplier_site_id"]}_{p["plant_id"]}'; route_by[(s['supplier_site_id'],p['plant_id'])]=rid
            cross=s['country_code']!=p['country_code']
            add('transport_routes','route_id',route_id=rid,origin_node_id=s['supplier_site_id'],destination_node_id=p['plant_id'],mode='AIR' if cross else 'ROAD',active=True)
            ns=[s['supplier_site_id'],f'HUB_{s["country_code"]}',p['plant_id']]
            for k in range(2): add('route_legs','route_leg_id',route_leg_id=f'{rid}_{k}',route_id=rid,sequence_number=k+1,from_node_id=ns[k],to_node_id=ns[k+1],transit_hours=12 if cross else 6,clearance_hours=24 if cross and k==1 else 0,handling_hours=0)
    for src in T['plants']:
        for dst in T['plants']:
            if src==dst: continue
            rid=f'R_{src["plant_id"]}_{dst["plant_id"]}'
            add('transport_routes','route_id',route_id=rid,origin_node_id=src['plant_id'],destination_node_id=dst['plant_id'],mode='AIR',active=True)
            add('route_legs','route_leg_id',route_leg_id=rid+'_1',route_id=rid,sequence_number=1,from_node_id=src['plant_id'],to_node_id=dst['plant_id'],transit_hours=24,clearance_hours=24,handling_hours=0)
            for m in T['materials']:
                add('transfer_permissions','permission_id',permission_id=f'TP_{src["plant_id"]}_{dst["plant_id"]}_{m["material_id"]}',source_plant_id=src['plant_id'],destination_plant_id=dst['plant_id'],material_revision_id=m['material_id']+'_A',permitted=True,receiving_release_hours=0)
                add('transport_offers','offer_id',offer_id=f'OF_{rid}_{m["material_id"]}',route_id=rid,material_id=m['material_id'],fixed_cost='15000.00',cost_per_base_unit='35.00',currency='INR',dispatch_prep_hours=24,capacity_qty_per_day=2000)
    sources={}; prices={'INR':'120.00','JPY':'210.00','CNY':'10.00'}
    for p in T['plants']:
        for j,m in enumerate(T['materials']):
            rev=m['material_id']+'_A'
            for alt in range(2 if j<5 else 1):
                ss=T['supplier_sites'][(j+alt*5)%15]
                sid=f'SRC_{p["plant_id"]}_{rev}_{alt}'
                r=add('sourcing_agreements','sourcing_id',sourcing_id=sid,supplier_site_id=ss['supplier_site_id'],material_revision_id=rev,destination_plant_id=p['plant_id'],approval_status='APPROVED',valid_from=str(start-timedelta(days=90)),valid_to=None,unit_price=prices[ss['currency']],currency=ss['currency'],minimum_order_qty=10,order_multiple=10,processing_lead_time_days=3,route_id=route_by[(ss['supplier_site_id'],p['plant_id'])],is_primary=alt==0)
                if alt==0: sources[(p['plant_id'],rev)]=r
            add('inventory_policies','inventory_policy_id',inventory_policy_id=f'IP_{p["plant_id"]}_{rev}',plant_id=p['plant_id'],material_revision_id=rev,minimum_protected_qty=40)
    add('approval_rules','approval_rule_id',approval_rule_id='AR_001',action_type='TRANSFER',amount_from='0.00',amount_to='500000.00',currency='INR',required_role='PLANNER_MANAGER')
    add('approval_rules','approval_rule_id',approval_rule_id='AR_002',action_type='TRANSFER',amount_from='500000.00',amount_to=None,currency='INR',required_role='OPERATIONS_DIRECTOR')
    add('penalty_rules','penalty_rule_id',penalty_rule_id='PEN_001',rule_type='PER_LATE_UNIT_PER_DAY',rate='10.00',currency='INR',grace_hours=24,maximum_penalty='100000.00')
    # 3. Calendars and demand. Weekdays only; no national holidays in synthetic baseline.
    for day in days:
        for p in T['plants']:
            work=day.weekday()<5
            add('plant_calendar','calendar_id',calendar_id=f'{p["plant_id"]}_{day}',plant_id=p['plant_id'],local_date=str(day),is_working_day=work,working_hours=8 if work else 0)
            for n in [1,2]: add('line_capacity_daily','capacity_id',capacity_id=f'{p["plant_id"]}_L{n}_{day}',line_id=f'{p["plant_id"]}_L{n}',local_date=str(day),available_hours=8 if work else 0,planned_maintenance_hours=0)
        for cur,rate in [('JPY','0.560000'),('CNY','12.000000')]: add('exchange_rates','rate_id',rate_id=f'{day}_{cur}_INR',rate_date=str(day),from_currency=cur,to_currency='INR',rate=rate,rate_basis='SYNTHETIC_CONSTANT_NOT_MARKET_RATE')
    jobs_byday=defaultdict(list); requirements=defaultdict(int); serial=0; workindex=0
    for day in days:
        if day.weekday()>=5: continue
        if workindex%3==0:
            for plant,pr,line,b in capabilities:
                serial+=1; qty=rng.choice([40,50,60]); pid=f'PROD_{serial:04}'; off=offsets[plant]
                # Two products sharing line use non-overlapping three-hour slots.
                siblings=[c for c in capabilities if c[0]==plant and c[2]==line]; slot=siblings.index((plant,pr,line,b)); hr=8+slot*3
                job=add('production_orders','production_order_id',production_order_id=pid,plant_id=plant,line_id=line,product_id=pr,bom_id=b,planned_qty=qty,scheduled_start_utc=stamp(day,hr,off),scheduled_end_utc=stamp(day,hr+2,off),local_date=str(day),priority=2,status='COMPLETED' if day<D else 'PLANNED')
                jobs_byday[day].append(job)
                for split in range(2):
                    oid=f'CO_{serial:04}_{split}'; ol=oid+'_1'; created=stamp(day-timedelta(days=45),0)
                    add('customer_orders','customer_order_id',customer_order_id=oid,customer_id=f'CUS_{1+(serial+split)%12:03}',created_at_utc=created,currency='INR',status='PRODUCTION_COMPLETE' if day<D else 'OPEN')
                    add('customer_order_lines','customer_order_line_id',customer_order_line_id=ol,customer_order_id=oid,product_id=pr,ordered_qty=qty//2,due_at_utc=stamp(day+timedelta(days=4),18,off),selling_price_per_unit='8000.00',contribution_margin_per_unit='2400.00',penalty_rule_id='PEN_001',outbound_delivery_hours=48)
                    add('order_allocations','allocation_id',allocation_id='AL_'+ol,customer_order_line_id=ol,production_order_id=pid,allocated_qty=qty//2)
                for bl in bomlines[b]:
                    q=qty*bl['quantity_per_output']; requirements[(plant,bl['material_revision_id'],day)]+=q
                    add('material_requirements','requirement_id',requirement_id=f'REQ_{pid}_{bl["material_revision_id"]}',production_order_id=pid,plant_id=plant,material_revision_id=bl['material_revision_id'],required_qty=q,required_at_utc=job['scheduled_start_utc'])
        workindex+=1
    # 4. Supply planning from requirements, then actual ledger simulation.
    lots=defaultdict(list); balances={}; receipts_byday=defaultdict(list); supplies=[]; movements=[]
    def lot_new(plant,rev,lid,day,site):
        add('inventory_lots','lot_id',lot_id=lid,plant_id=plant,material_revision_id=rev,supplier_site_id=site,received_at_utc=stamp(day,6,offsets[plant]),expiry_at_utc=None)
        lots[(plant,rev)].append(lid); balances[lid]=0
    def move(lid,kind,qty,ts,ref):
        sign=1 if kind=='RECEIPT' else -1
        balances[lid]+=sign*qty
        add('inventory_movements','movement_id',movement_id=f'MOV_{len(T["inventory_movements"])+1:06}',lot_id=lid,movement_type=kind,quantity=qty,occurred_at_utc=ts,reference_id=ref)
        assert balances[lid]>=0
    for p in T['plants']:
        plant=p['plant_id']; off=offsets[plant]
        for mat in T['materials']:
            rev=mat['material_id']+'_A'; src=sources[(plant,rev)]
            opening=sum(requirements[(plant,rev,start+timedelta(days=k))] for k in range(7))+40
            lid=f'OPEN_{plant}_{rev}'; lot_new(plant,rev,lid,start-timedelta(days=1),src['supplier_site_id'])
            # Opening balance is a separate bootstrap record, not an invented historical receipt.
            balances[lid]=opening
            add('opening_inventory','opening_id',opening_id=lid,lot_id=lid,as_of_utc=stamp(start,0,off),quantity=opening)
            for wi in range(7,total_days,7):
                rd=start+timedelta(days=wi)
                needed=sum(requirements[(plant,rev,start+timedelta(days=k))] for k in range(wi,min(wi+7,total_days)))
                if not needed: continue
                # Consumption occurs in multiples of 10, satisfying sourcing pack requirements.
                n=len(T['purchase_orders'])+1; po=f'PO_{n:05}'; pol=po+'_1'; sh=f'SHIP_{n:05}'; sl=sh+'_1'
                route=src['route_id']; cross=next(s for s in T['supplier_sites'] if s['supplier_site_id']==src['supplier_site_id'])['country_code']!=p['country_code']
                transit=2 if cross else 1; dispatch=rd-timedelta(days=transit); orderday=dispatch-timedelta(days=3)
                eta=stamp(rd,6,off); dsp=stamp(dispatch,6,off)
                add('purchase_orders','po_id',po_id=po,supplier_site_id=src['supplier_site_id'],created_at_utc=stamp(orderday,6,off),status='RECEIVED' if rd<D else ('OPEN' if orderday<D else 'PLANNED'),currency=src['currency'])
                add('purchase_order_lines','po_line_id',po_line_id=pol,po_id=po,sourcing_id=src['sourcing_id'],ordered_qty=needed,cancelled_qty=0,unit_price=src['unit_price'],promised_receipt_at_utc=eta)
                add('shipments','shipment_id',shipment_id=sh,route_id=route,status='RECEIVED' if rd<D else ('IN_TRANSIT' if dispatch<D else 'PLANNED'),planned_dispatch_at_utc=dsp,actual_dispatch_at_utc=dsp if dispatch<D else None,original_eta_utc=eta)
                add('shipment_lines','shipment_line_id',shipment_line_id=sl,shipment_id=sh,po_line_id=pol,shipped_qty=needed if dispatch<D else 0,planned_qty=needed)
                if dispatch<D: add('shipment_updates','update_id',update_id=sh+'_UP1',shipment_id=sh,observed_at_utc=dsp,expected_arrival_at_utc=eta,status='DISPATCHED',reason_code='BASELINE_ON_TIME')
                receipt={'plant':plant,'rev':rev,'qty':needed,'eta':eta,'site':src['supplier_site_id'],'sl':sl,'sh':sh,'date':rd}
                supplies.append(receipt)
                receipts_byday[rd].append(receipt)
    # Actuals are limited to history. Future inventory is separately projected.
    for day in days[:history_days]:
        for rec in receipts_byday[day]:
            lid='LOT_'+rec['sl']; lot_new(rec['plant'],rec['rev'],lid,day,rec['site']); move(lid,'RECEIPT',rec['qty'],rec['eta'],rec['sl'])
            add('goods_receipts','receipt_id',receipt_id='GR_'+rec['sl'],shipment_line_id=rec['sl'],lot_id=lid,received_qty=rec['qty'],received_at_utc=rec['eta'])
        for job in jobs_byday[day]:
            for bl in bomlines[job['bom_id']]:
                need=job['planned_qty']*bl['quantity_per_output']
                for lid in lots[(job['plant_id'],bl['material_revision_id'])]:
                    take=min(need,balances[lid])
                    if take: move(lid,'CONSUMPTION',take,job['scheduled_start_utc'],job['production_order_id']); need-=take
                    if not need: break
                assert need==0,('baseline shortage',job['production_order_id'])
            add('production_completions','completion_id',completion_id='DONE_'+job['production_order_id'],production_order_id=job['production_order_id'],completed_at_utc=job['scheduled_end_utc'],good_qty=job['planned_qty'],scrap_qty=0)
        for p in T['plants']:
            for m in T['materials']:
                rev=m['material_id']+'_A'; q=sum(balances[l] for l in lots[(p['plant_id'],rev)])
                add('inventory_daily','balance_id',balance_id=f'{p["plant_id"]}_{rev}_{day}',plant_id=p['plant_id'],material_revision_id=rev,local_date=str(day),physical_qty=q,quality_hold_qty=0,other_blocked_qty=0)
    current={}
    for (plant,rev),ids in lots.items():
        current[(plant,rev)]=sum(balances[l] for l in ids)
        for lid in ids:
            if balances[lid]: add('inventory_balances','balance_id',balance_id='BAL_'+lid,lot_id=lid,as_of_utc=stamp(D),physical_qty=balances[lid],quality_hold_qty=0,other_blocked_qty=0)
    free=balances.copy()
    for job in [j for day in days[history_days:history_days+7] for j in jobs_byday[day]]:
        for bl in bomlines[job['bom_id']]:
            need=job['planned_qty']*bl['quantity_per_output']
            for lid in lots[(job['plant_id'],bl['material_revision_id'])]:
                take=min(need,free[lid])
                if take:
                    add('inventory_reservations','reservation_id',reservation_id=f'RES_{len(T["inventory_reservations"])+1:05}',lot_id=lid,production_order_id=job['production_order_id'],reserved_qty=take,required_at_utc=job['scheduled_start_utc'],status='ACTIVE'); free[lid]-=take; need-=take
                if not need: break
    projected=current.copy()
    for day in days[history_days:]:
        for rec in receipts_byday[day]: projected[(rec['plant'],rec['rev'])]+=rec['qty']
        for key in projected:
            projected[key]-=requirements[(*key,day)]
            assert projected[key]>=0
            add('inventory_projection_daily','projection_id',projection_id=f'PROJ_{key[0]}_{key[1]}_{day}',plant_id=key[0],material_revision_id=key[1],local_date=str(day),projected_physical_qty=projected[key],basis='PLANNED_RECEIPTS_AND_SCHEDULED_DEMAND')
    # 5. Shared supplier capacity derived from orders; baseline performance derived from receipts.
    commits=defaultdict(int)
    srclook={s['sourcing_id']:s for s in T['sourcing_agreements']}; polook={p['po_id']:p for p in T['purchase_orders']}
    for pol in T['purchase_order_lines']:
        s=srclook[pol['sourcing_id']]; dt=polook[pol['po_id']]['created_at_utc'][:10]
        commits[(s['supplier_site_id'],s['material_revision_id'],dt)]+=pol['ordered_qty']
    pairs=sorted(set((s['supplier_site_id'],s['material_revision_id']) for s in T['sourcing_agreements']))
    for site,rev in pairs:
        for day in days: add('supplier_capacity_daily','capacity_id',capacity_id=f'{site}_{rev}_{day}',supplier_site_id=site,material_revision_id=rev,capacity_date=str(day),total_capacity_qty=10000,committed_qty=commits[(site,rev,str(day))],capacity_basis='ORDER_RELEASE_QUANTITY_PER_UTC_DAY')
    for site in T['supplier_sites']:
        for period in range((history_days+29)//30):
            a=start+timedelta(days=30*period); z=min(a+timedelta(days=30),D)
            rr=[s for s in supplies if s['site']==site['supplier_site_id'] and a<=s['date']<z]
            add('supplier_performance','performance_id',performance_id=f'PERF_{site["supplier_site_id"]}_{period}',supplier_site_id=site['supplier_site_id'],period_start=str(a),period_end_exclusive=str(z),delivered_lines=len(rr),delivered_qty=sum(r['qty'] for r in rr),on_time_in_full_rate='1.0000' if rr else None,average_delay_days='0.00' if rr else None)
    # 6. Scenario overlays: don't corrupt baseline actuals. One target and one declared change each.
    future=[s for s in supplies if D<=s['date']<end]
    availablelots=T['inventory_balances']
    planned_ids={p['production_order_id'] for p in T['production_orders'] if p['status']=='PLANNED'}
    future_line_ids={a['customer_order_line_id'] for a in T['order_allocations'] if a['production_order_id'] in planned_ids}
    futureorders=[o for o in T['customer_order_lines'] if o['customer_order_line_id'] in future_line_ids]
    for i in range(12):
        typ=['SHIPMENT_DELAY','SUPPLIER_OUTAGE','QUALITY_HOLD','DEMAND_SURGE'][i//3]; sid=f'SCN_{i+1:03}'
        add('scenarios','scenario_id',scenario_id=sid,scenario_name=f'{typ.title()} variation {i%3+1}',scenario_type=typ,base_dataset_version=META['dataset_version'],decision_time_utc=stamp(D),random_seed=seed+i,description='Independent synthetic overlay; no external event claim.')
        if typ=='SHIPMENT_DELAY':
            rec=future[i%len(future)]; target=rec['sh']; table='shipments'; params={'delay_days':[2,5,9][i%3]}
        elif typ=='SUPPLIER_OUTAGE': table='supplier_sites';target=T[table][i%15]['supplier_site_id'];params={'capacity_multiplier':0,'duration_days':[3,7,12][i%3],'affect_unshipped_supply':True}
        elif typ=='QUALITY_HOLD': table='inventory_lots';bal=availablelots[i%len(availablelots)];target=bal['lot_id'];params={'hold_qty':bal['physical_qty'],'duration_days':5}
        else: table='customer_order_lines'; target=futureorders[i%len(futureorders)]['customer_order_line_id'];params={'additional_qty':[20,60,120][i%3],'requires_rescheduling':True}
        add('scenario_changes','change_id',change_id=sid+'_C1',scenario_id=sid,target_type=table,target_id=target,change_type=typ,effective_at_utc=stamp(D),known_at_utc=stamp(D),parameters=params)
    # FK registry is also shipped for loader/evaluation use.
    for tb,field,pa in [
        ('material_revisions','material_id','materials'),('production_lines','plant_id','plants'),('line_product_capabilities','line_id','production_lines'),('line_product_capabilities','product_id','products'),('bom_headers','product_id','products'),('bom_headers','plant_id','plants'),('bom_lines','bom_id','bom_headers'),('bom_lines','material_revision_id','material_revisions'),('supplier_sites','supplier_id','suppliers'),('sourcing_agreements','supplier_site_id','supplier_sites'),('sourcing_agreements','material_revision_id','material_revisions'),('sourcing_agreements','destination_plant_id','plants'),('sourcing_agreements','route_id','transport_routes'),('route_legs','route_id','transport_routes'),('route_legs','from_node_id','logistics_nodes'),('route_legs','to_node_id','logistics_nodes'),('transport_routes','origin_node_id','logistics_nodes'),('transport_routes','destination_node_id','logistics_nodes'),('transport_offers','route_id','transport_routes'),('transport_offers','material_id','materials'),('transfer_permissions','source_plant_id','plants'),('transfer_permissions','destination_plant_id','plants'),('transfer_permissions','material_revision_id','material_revisions'),('inventory_policies','plant_id','plants'),('inventory_policies','material_revision_id','material_revisions'),('plant_calendar','plant_id','plants'),('line_capacity_daily','line_id','production_lines'),('production_orders','plant_id','plants'),('production_orders','line_id','production_lines'),('production_orders','product_id','products'),('production_orders','bom_id','bom_headers'),('customer_orders','customer_id','customers'),('customer_order_lines','customer_order_id','customer_orders'),('customer_order_lines','product_id','products'),('customer_order_lines','penalty_rule_id','penalty_rules'),('order_allocations','production_order_id','production_orders'),('order_allocations','customer_order_line_id','customer_order_lines'),('material_requirements','production_order_id','production_orders'),('material_requirements','plant_id','plants'),('material_requirements','material_revision_id','material_revisions'),('purchase_orders','supplier_site_id','supplier_sites'),('purchase_order_lines','po_id','purchase_orders'),('purchase_order_lines','sourcing_id','sourcing_agreements'),('shipments','route_id','transport_routes'),('shipment_lines','shipment_id','shipments'),('shipment_lines','po_line_id','purchase_order_lines'),('shipment_updates','shipment_id','shipments'),('goods_receipts','shipment_line_id','shipment_lines'),('goods_receipts','lot_id','inventory_lots'),('inventory_lots','plant_id','plants'),('inventory_lots','material_revision_id','material_revisions'),('inventory_lots','supplier_site_id','supplier_sites'),('inventory_balances','lot_id','inventory_lots'),('opening_inventory','lot_id','inventory_lots'),('inventory_movements','lot_id','inventory_lots'),('inventory_reservations','lot_id','inventory_lots'),('inventory_reservations','production_order_id','production_orders'),('production_completions','production_order_id','production_orders'),('supplier_capacity_daily','supplier_site_id','supplier_sites'),('supplier_capacity_daily','material_revision_id','material_revisions'),('supplier_performance','supplier_site_id','supplier_sites'),('scenario_changes','scenario_id','scenarios')]: fk(tb,field,pa)
    # Export JSONL and a typed SQLite database. FK insertion deferred to accommodate table order.
    for tab,rows in T.items():
        (out/f'{tab}.jsonl').write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in rows),encoding='utf-8')
    schema={'primary_keys':KEYS,'foreign_keys':FKS,'tables':{t:{k:type(v).__name__ for k,v in rs[0].items()} for t,rs in T.items()}}
    (ROOT/'schema.json').write_text(json.dumps(schema,indent=2))
    dbpath=out/'resilientops.sqlite'; dbpath.unlink(missing_ok=True)
    db=sqlite3.connect(dbpath)
    for tab,rows in T.items():
        cols=list(rows[0]); defs=[]
        for c in cols:
            val=next((r[c] for r in rows if r[c] is not None),None)
            typ='INTEGER' if isinstance(val,(int,bool)) else 'REAL' if isinstance(val,float) else 'TEXT'
            defs.append(f'"{c}" {typ}'+(' PRIMARY KEY' if c==KEYS[tab] else ''))
        for tb,f,pa,pf in FKS:
            if tb==tab: defs.append(f'FOREIGN KEY ("{f}") REFERENCES "{pa}"("{pf}")')
        db.execute(f'CREATE TABLE "{tab}" ({",".join(defs)})')
        vals=[[json.dumps(r[c],sort_keys=True) if isinstance(r[c],(dict,list)) else r[c] for c in cols] for r in rows]
        db.executemany(f'INSERT INTO "{tab}" VALUES ({",".join("?" for _ in cols)})',vals)
    db.commit(); assert not list(db.execute('PRAGMA foreign_key_check')); db.close()
    META['generation_order']=['network','BOM and capabilities','sourcing and routes','calendars','customer demand','production and material requirements','procurement and shipments','historical inventory ledger','current reservations','future projections','derived supplier metrics','scenario overlays']
    META['table_counts']={t:len(r) for t,r in T.items()}; META['row_count']=sum(META['table_counts'].values())
    META['jsonl_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob('*.jsonl'))}
    (ROOT/'manifest.json').write_text(json.dumps(META,indent=2))
    print(json.dumps({'tables':len(T),'rows':META['row_count'],'counts':META['table_counts']},indent=2))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--seed',type=int,default=42);ap.add_argument('--decision-date',default='2026-10-01');ap.add_argument('--history-start',default='2024-01-01');a=ap.parse_args();main(a.seed,a.decision_date,a.history_start)
