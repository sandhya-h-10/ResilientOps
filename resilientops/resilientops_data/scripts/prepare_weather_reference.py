"""Normalize downloaded NOAA GSOD without changing source dates or filling gaps."""
import csv,json,hashlib,math
from datetime import date,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def num(v,missing,scale=1,sub=0):
 try:n=float(v)
 except (ValueError,TypeError):return None
 return None if not math.isfinite(n) or n==missing else round((n-sub)*scale,4)
def main():
 out=ROOT/'public_data/weather_reference';mp=json.loads((ROOT/'public_data/noaa_reference_station_mapping.json').read_text());dl=json.loads((out/'download_status.json').read_text())
 meta=json.loads((ROOT/'manifest.json').read_text());start=date.fromisoformat(meta['history_start']);end=date.fromisoformat(meta['history_end_exclusive']);expected=(end-start).days;records=[]
 for status in dl:
  station=status['station_id'];year=status['year']
  if status['status']!='DOWNLOADED':continue
  path=out/f'{station}_{year}.csv';assert hashlib.sha256(path.read_bytes()).hexdigest()==status['sha256']
  for row in csv.DictReader(path.open()):
   if not str(start)<=row['DATE']<str(end):continue
   prcp=num(row['PRCP'],99.99,25.4);flag=row['PRCP_ATTRIBUTES'].strip()
   records.append({'observation_id':f'NOAA_{station}_{row["DATE"]}','station_id':station,'observation_date':row['DATE'],'latitude':float(row['LATITUDE']),'longitude':float(row['LONGITUDE']),'temperature_c':num(row['TEMP'],9999.9,5/9,32),'wind_speed_ms':num(row['WDSP'],999.9,0.514444),'reported_precipitation_mm':prcp,'precipitation_flag':flag,'daily_precipitation_mm_for_analysis':prcp if flag=='G' else None,'precipitation_review_required':flag!='G' or prcp is None,'source_url':status['url'],'source_provider':'NOAA NCEI','acquisition_channel':'DIRECT_NOAA_ARCHIVE_NOT_BIGQUERY','source_is_synthetic':False,'retrieved_at_utc':status['retrieved_at_utc'],'available_at_utc':status['retrieved_at_utc'],'publication_time_utc':None,'usage':'HISTORICAL_REFERENCE_NOT_ASOF_VERIFIED'})
 links=[];coverage=[]
 for e in mp:
  rr=[r for r in records if r['station_id']==e['station_id']]
  for r in rr:links.append({'observation_id':r['observation_id'],'entity_id':e['entity_id'],'distance_km':e['distance_km'],'entity_is_synthetic':True,'association_type':'NEAREST_STATION_REFERENCE_NOT_CONFIRMED_EXPOSURE'})
  coverage.append({**e,'expected_days':expected,'observed_days':len(rr),'missing_days':expected-len(rr),'temperature_present_days':sum(r['temperature_c'] is not None for r in rr),'wind_present_days':sum(r['wind_speed_ms'] is not None for r in rr),'unambiguous_daily_rain_days':sum(r['daily_precipitation_mm_for_analysis'] is not None for r in rr)})
 assert len({r['observation_id'] for r in records})==len(records)
 assert all(r['daily_precipitation_mm_for_analysis'] is None or r['daily_precipitation_mm_for_analysis']>=0 for r in records)
 for fn,rows in [('observations.jsonl',records),('entity_links.jsonl',links)]: (out/fn).write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in rows))
 (out/'coverage.json').write_text(json.dumps(coverage,indent=2))
 report={'passed':True,'source_stations':len({x['station_id'] for x in dl}), 'station_year_downloads':len(dl),'unique_observations':len(records),'entity_observation_links':len(links),'entities':len(mp),'window_start':str(start),'window_end_exclusive':str(end),'checks':['Source download hashes match','Unique station-day observations','Source dates preserved','Missing sentinels converted to null','Coverage gaps reported without imputation','Ambiguous precipitation flags excluded from daily rainfall feature']}
 (out/'validation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':main()
