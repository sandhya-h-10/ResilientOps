"""Independent checks against exported data. Exit nonzero on any failure."""
import json, sqlite3, sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
ROOT=Path(__file__).resolve().parents[1]
def main():
    manifest=json.loads((ROOT/'manifest.json').read_text()); schema=json.loads((ROOT/'schema.json').read_text())
    T={t:[json.loads(l) for l in (ROOT/'data'/f'{t}.jsonl').read_text().splitlines()] for t in schema['primary_keys']}
    idx={t:{r[schema['primary_keys'][t]]:r for r in rs} for t,rs in T.items()}
    tests=[]
    def check(name,errors,detail=''):
        tests.append({'check':name,'passed':not errors,'error_count':len(errors),'examples':errors[:5],'detail':detail})
    check('Unique primary keys',[t for t in T if len(T[t])!=len(idx[t])])
    check('Foreign key references',[f'{tb}.{f}: {r[f]}' for tb,f,pa,pf in schema['foreign_keys'] for r in T[tb] if r[f] is not None and r[f] not in set(idx[pa])])
    check('Agreed network scope',[] if (len(T['plants']),len(T['products']),len(T['materials']),len(T['suppliers']))==(3,4,30,15) else ['scope mismatch'])
    check('Five critical components',[] if sum(m['criticality']=='CRITICAL' for m in T['materials'])==5 else ['critical count'])
    check('All 30 components used by a BOM',[] if {b['material_revision_id'] for b in T['bom_lines']}==set(idx['material_revisions']) else ['unused component'])
    check('Dataset provenance',[t for t in T if any(not r['is_synthetic'] or r['dataset_version']!=manifest['dataset_version'] for r in T[t])])
    # Reconstruct material consumption from BOM, independently from exported requirement rows.
    expected={}; actual=defaultdict(int); lotmeta=idx['inventory_lots']
    for p in T['production_orders']:
        for b in T['bom_lines']:
            if b['bom_id']==p['bom_id']: expected[(p['production_order_id'],b['material_revision_id'])]=p['planned_qty']*b['quantity_per_output']
    for m in T['inventory_movements']:
        if m['movement_type']=='CONSUMPTION': actual[(m['reference_id'],lotmeta[m['lot_id']]['material_revision_id'])]+=m['quantity']
    check('Historical consumption equals BOM demand',[str(k) for k,q in expected.items() if idx['production_orders'][k[0]]['status']=='COMPLETED' and actual[k]!=q])
    req={(r['production_order_id'],r['material_revision_id']):r['required_qty'] for r in T['material_requirements']}
    check('Requirements recomputed from production and BOM',[] if req==expected else ['requirement mismatch'])
    stock=defaultdict(int)
    for o in T['opening_inventory']: stock[o['lot_id']]+=o['quantity']
    bad=[]
    for m in sorted(T['inventory_movements'],key=lambda r:(r['occurred_at_utc'],r['movement_id'])):
        stock[m['lot_id']]+=m['quantity'] if m['movement_type']=='RECEIPT' else -m['quantity']
        if stock[m['lot_id']]<0: bad.append(m['movement_id'])
    check('No negative historical lot balance',bad)
    exported={r['lot_id']:r['physical_qty'] for r in T['inventory_balances']}
    check('Current inventory reconciles to opening plus ledger',[l for l,q in stock.items() if exported.get(l,0)!=q])
    reserved=defaultdict(int)
    for r in T['inventory_reservations']: reserved[r['lot_id']]+=r['reserved_qty']
    check('Reservations fit current usable inventory',[l for l,q in reserved.items() if q>exported.get(l,0)])
    alloc=defaultdict(int); customeralloc=defaultdict(int)
    for a in T['order_allocations']:
        alloc[a['production_order_id']]+=a['allocated_qty']; customeralloc[a['customer_order_line_id']]+=a['allocated_qty']
    check('Production allocation totals',[p['production_order_id'] for p in T['production_orders'] if alloc[p['production_order_id']]!=p['planned_qty']])
    check('Customer allocation totals',[p['customer_order_line_id'] for p in T['customer_order_lines'] if customeralloc[p['customer_order_line_id']]!=p['ordered_qty']])
    capacity=defaultdict(float); intervals=defaultdict(list); bad=[]
    caps={(r['line_id'],r['product_id']):r for r in T['line_product_capabilities']}
    for p in T['production_orders']:
        cap=caps.get((p['line_id'],p['product_id'])); dur=(datetime.fromisoformat(p['scheduled_end_utc'].replace('Z','+00:00'))-datetime.fromisoformat(p['scheduled_start_utc'].replace('Z','+00:00'))).total_seconds()/3600
        if not cap or p['planned_qty']/cap['units_per_hour']+cap['setup_hours']>dur: bad.append(p['production_order_id'])
        key=(p['line_id'],p['local_date']);capacity[key]+=dur;intervals[key].append((p['scheduled_start_utc'],p['scheduled_end_utc']))
    check('Product capability and duration',bad)
    avail={(r['line_id'],r['local_date']):r['available_hours'] for r in T['line_capacity_daily']}
    check('Daily line capacity',[str(k) for k,h in capacity.items() if h>avail[k]])
    check('No line schedule overlaps',[str(k) for k,v in intervals.items() if any(a[1]>b[0] for a,b in zip(sorted(v),sorted(v)[1:]))])
    received=defaultdict(int)
    for r in T['goods_receipts']:received[r['shipment_line_id']]+=r['received_qty']
    check('Receipt quantities match received shipments',[r['shipment_line_id'] for r in T['shipment_lines'] if idx['shipments'][r['shipment_id']]['status']=='RECEIVED' and received[r['shipment_line_id']]!=r['shipped_qty']])
    check('Procurement approval and pack sizes',[r['po_line_id'] for r in T['purchase_order_lines'] if (s:=idx['sourcing_agreements'][r['sourcing_id']])['approval_status']!='APPROVED' or r['ordered_qty']<s['minimum_order_qty'] or r['ordered_qty']%s['order_multiple']])
    check('Supplier capacity not exceeded',[r['capacity_id'] for r in T['supplier_capacity_daily'] if r['committed_qty']>r['total_capacity_qty']])
    cutoff=manifest['decision_time_utc']
    check('Actual events precede decision cutoff',[r['movement_id'] for r in T['inventory_movements'] if r['occurred_at_utc']>=cutoff]+[r['completion_id'] for r in T['production_completions'] if r['completed_at_utc']>=cutoff])
    check('No actual dispatch for planned shipments',[r['shipment_id'] for r in T['shipments'] if r['status']=='PLANNED' and r['actual_dispatch_at_utc'] is not None])
    check('Forward baseline has no negative stock',[r['projection_id'] for r in T['inventory_projection_daily'] if r['projected_physical_qty']<0])
    # Independent daily aggregate rebuild validates all historical snapshots.
    agg=defaultdict(int); byday=defaultdict(list)
    for o in T['opening_inventory']:
        l=lotmeta[o['lot_id']];agg[(l['plant_id'],l['material_revision_id'])]+=o['quantity']
    offsets={'PLT_MUM':5.5,'PLT_TYO':9,'PLT_BJS':8}
    for m in T['inventory_movements']:
        l=lotmeta[m['lot_id']];d=(datetime.fromisoformat(m['occurred_at_utc'].replace('Z','+00:00'))+timedelta(hours=offsets[l['plant_id']])).date().isoformat();byday[d].append(m)
    bad=[]
    for d in sorted({r['local_date'] for r in T['inventory_daily']}):
        for m in byday[d]:
            l=lotmeta[m['lot_id']];agg[(l['plant_id'],l['material_revision_id'])]+=m['quantity'] if m['movement_type']=='RECEIPT' else -m['quantity']
        for r in (r for r in T['inventory_daily'] if r['local_date']==d):
            if agg[(r['plant_id'],r['material_revision_id'])]!=r['physical_qty']:bad.append(r['balance_id'])
    check('All daily balances independently reconstructed',bad)
    check('Scenario target IDs exist',[r['change_id'] for r in T['scenario_changes'] if r['target_id'] not in idx[r['target_type']]])
    db=sqlite3.connect(ROOT/'data'/'resilientops.sqlite');check('SQLite foreign key integrity',list(db.execute('PRAGMA foreign_key_check')));db.close()
    report={'passed':all(t['passed'] for t in tests),'checks':len(tests),'results':tests,'limitations':['Baseline is intentionally disruption-free; it cannot establish anomaly-model accuracy.','Scenario overlays are definitions, not applied outcomes or validated recovery plans.','No public/live API observations or real commercial rates are included.']}
    (ROOT/'validation_report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'passed':report['passed'],'checks':len(tests),'failed':[t for t in tests if not t['passed']]},indent=2))
    return 0 if report['passed'] else 1
if __name__=='__main__':sys.exit(main())
