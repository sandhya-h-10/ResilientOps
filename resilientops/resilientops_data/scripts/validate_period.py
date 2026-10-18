"""Checks specific to the requested January 2024–September 2026 revision."""
import json,hashlib
from pathlib import Path
from datetime import date,timedelta
R=Path(__file__).resolve().parents[1]
def rows(p):return [json.loads(x) for x in (R/p).read_text().splitlines() if x]
m=json.loads((R/'manifest.json').read_text());checks=[]
def check(name,value):checks.append({'check':name,'passed':bool(value)})
start=date(2024,1,1);cutoff=date(2026,10,1);dates={str(start+timedelta(days=i)) for i in range((cutoff-start).days)}
hist=rows('data/inventory_daily.jsonl');future=rows('data/inventory_projection_daily.jsonl');aud=json.loads((R/'knowledge/document_catalog.json').read_text());gaps=rows('public_data/weather_reference/missing_station_days.jsonl');w=rows('public_data/weather_reference/observations.jsonl')
check('History is 1004 days including leap day',m['history_days']==1004 and '2024-02-29' in dates)
check('Every historical date has 90 plant-material balances',len(hist)==1004*90 and {x['local_date'] for x in hist}==dates and len({(x['plant_id'],x['material_revision_id'],x['local_date']) for x in hist})==len(hist))
check('Planning dates are separate October 1–30',len(future)==2700 and all('2026-10-01'<=x['local_date']<'2026-10-31' for x in future))
check('Audits unavailable before decision date',all(x['effective_from']=='2026-10-01' for x in aud if x['document_type']=='SUPPLIER_AUDIT'))
obs={(x['station_id'],x['observation_date']) for x in w};missing={(x['station_id'],x['observation_date']) for x in gaps}
check('Weather gaps reconcile without invented observations',not obs&missing and len(obs|missing)==7*1004 and all(x['temperature_c'] is None and x['record_kind']=='COVERAGE_PLACEHOLDER_NOT_OBSERVATION' for x in gaps))
check('All operational file hashes match manifest',all(hashlib.sha256((R/'data'/k).read_bytes()).hexdigest()==v for k,v in m['jsonl_sha256'].items()))
windows=json.loads((R/'public_data/news/gdelt_backfill_windows.json').read_text())
check('News backfill windows cover range with no gaps',windows[0]['start_inclusive']=='2024-01-01' and windows[-1]['end_exclusive']=='2026-10-01' and all(a['end_exclusive']==b['start_inclusive'] for a,b in zip(windows,windows[1:])))
result={'passed':all(x['passed'] for x in checks),'checks':checks};(R/'period_validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)
