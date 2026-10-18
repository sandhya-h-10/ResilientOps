"""Rebuild year coverage, source gaps and documentation from the delivered files."""
import json
from pathlib import Path
from datetime import date,timedelta
R=Path(__file__).resolve().parents[1]
def rows(p):return [json.loads(x) for x in (R/p).read_text().splitlines() if x]
m=json.loads((R/'manifest.json').read_text());w=rows('public_data/weather_reference/observations.jsonl');n=rows('public_data/news/curated_evidence.jsonl');mp=json.loads((R/'public_data/noaa_reference_station_mapping.json').read_text());stations=sorted({x['station_id'] for x in mp});idx={(x['station_id'],x['observation_date']):x['observation_id'] for x in w}
start=date.fromisoformat(m['history_start']);end=date.fromisoformat(m['history_end_exclusive']);summary=[];gaps=[]
for year in range(start.year,end.year+1):
 a=max(start,date(year,1,1));z=min(end,date(year+1,1,1))
 if a>=z:continue
 wx=[x for x in w if x['observation_date'][:4]==str(year)];news=[x for x in n if x['event_year']==year]
 summary.append({'year':year,'start':str(a),'end_inclusive':str(z-timedelta(days=1)),'history_days':(z-a).days,'weather_expected_station_days':len(stations)*(z-a).days,'weather_observed_station_days':len(wx),'weather_missing_station_days':len(stations)*(z-a).days-len(wx),'weather_first_observation':min((x['observation_date'] for x in wx),default=None),'weather_last_observation':max((x['observation_date'] for x in wx),default=None),'curated_news_records':len(news),'news_coverage':'SELECTED_EXAMPLES_NOT_EXHAUSTIVE'})
 for station in stations:
  for i in range((z-a).days):
   d=str(a+timedelta(days=i))
   if (station,d) not in idx:gaps.append({'station_id':station,'observation_date':d,'status':'MISSING_PUBLIC_OBSERVATION','temperature_c':None,'wind_speed_ms':None,'precipitation_mm':None,'record_kind':'COVERAGE_PLACEHOLDER_NOT_OBSERVATION'})
(R/'period_coverage.json').write_text(json.dumps(summary,indent=2));(R/'public_data/weather_reference/missing_station_days.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in gaps))
(R/'DATA_INVENTORY.md').write_text('# Dataset inventory\n\nHistory: '+str(start)+' through '+str(end-timedelta(days=1))+'. Planning: '+str(end)+' through '+str(date.fromisoformat(m['planning_end_exclusive'])-timedelta(days=1))+'.\n\n| Table | Rows |\n|---|---:|\n'+''.join(f'| {k} | {v:,} |\n' for k,v in m['table_counts'].items())+f'\nTotal: {m["row_count"]:,} synthetic rows across {len(m["table_counts"])} tables. Public observations and documents are counted separately in period_coverage.json and knowledge/validation.json.\n')
print(json.dumps(summary,indent=2))
