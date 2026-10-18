"""Export bounded NOAA GSOD data from BigQuery. SQL generation needs only stdlib."""
import argparse, json, math
from pathlib import Path
from datetime import date, datetime, timezone
ROOT=Path(__file__).resolve().parents[1]

def clean(value, sentinel, multiplier=1, subtract=0):
    if value is None: return None
    try: n=float(value)
    except (TypeError,ValueError): return None
    if not math.isfinite(n) or n==sentinel:return None
    return round((n-subtract)*multiplier,4)

def normalize(row, retrieved):
    out=dict(row)
    out.update(temperature_c=clean(row.get('temp'),9999.9,5/9,32),wind_speed_ms=clean(row.get('wdsp'),999.9,0.514444),precipitation_mm=clean(row.get('prcp'),99.99,25.4),source_provider='NOAA',source_platform='Google BigQuery',source_dataset='bigquery-public-data.noaa_gsod',source_record_is_synthetic=False,entity_is_synthetic=True,retrieved_at_utc=retrieved,available_at_utc=retrieved,source_publication_time_utc=None)
    return out

def build_sql(start,end):
    # Literal year bounds allow wildcard pruning; daily bounds are parameters.
    return f'''-- NOAA observations mapped to fictional sites; this mapping does not prove disruption.
WITH entities AS (
 SELECT JSON_VALUE(e, '$.entity_id') entity_id,
 SAFE_CAST(JSON_VALUE(e, '$.latitude') AS FLOAT64) latitude,
 SAFE_CAST(JSON_VALUE(e, '$.longitude') AS FLOAT64) longitude
 FROM UNNEST(JSON_QUERY_ARRAY(@entities_json)) e
), stations AS (
 SELECT CAST(usaf AS STRING) usaf, CAST(wban AS STRING) wban, name,
 SAFE_CAST(lat AS FLOAT64) latitude, SAFE_CAST(lon AS FLOAT64) longitude
 FROM `bigquery-public-data.noaa_gsod.stations`
), nearest AS (
 SELECT e.entity_id, s.usaf, s.wban, s.name station_name,
 ST_DISTANCE(SAFE.ST_GEOGPOINT(e.longitude,e.latitude), SAFE.ST_GEOGPOINT(s.longitude,s.latitude))/1000 distance_km
 FROM entities e CROSS JOIN stations s
 WHERE s.latitude BETWEEN -90 AND 90 AND s.longitude BETWEEN -180 AND 180
 AND ST_DWITHIN(SAFE.ST_GEOGPOINT(e.longitude,e.latitude), SAFE.ST_GEOGPOINT(s.longitude,s.latitude), @radius_km * 1000)
 QUALIFY ROW_NUMBER() OVER(PARTITION BY e.entity_id ORDER BY distance_km,usaf,wban) <= 5
), observations AS (
 SELECT CAST(stn AS STRING) stn, CAST(wban AS STRING) wban,
 SAFE_CAST(CONCAT(year,'-',mo,'-',da) AS DATE) observation_date,
 temp, wdsp, prcp, flag_prcp
 FROM `bigquery-public-data.noaa_gsod.gsod*`
 WHERE _TABLE_SUFFIX BETWEEN '{start.year}' AND '{end.year}'
 AND SAFE_CAST(CONCAT(year,'-',mo,'-',da) AS DATE) BETWEEN @start_date AND @end_date
), candidate_data AS (
 SELECT n.*, o.observation_date,o.temp,o.wdsp,o.prcp,o.flag_prcp
 FROM nearest n JOIN observations o ON n.usaf=o.stn AND n.wban=o.wban
), ranked AS (
 SELECT entity_id,usaf,wban,COUNT(*) reporting_days,MIN(distance_km) distance_km
 FROM candidate_data GROUP BY entity_id,usaf,wban
 QUALIFY ROW_NUMBER() OVER(PARTITION BY entity_id ORDER BY reporting_days DESC,distance_km,usaf,wban)=1
)
SELECT c.* FROM candidate_data c JOIN ranked r USING(entity_id,usaf,wban)
ORDER BY entity_id,observation_date
'''

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project'); ap.add_argument('--execute',action='store_true');ap.add_argument('--max-bytes',type=int,default=2_000_000_000);ap.add_argument('--radius-km',type=float,default=100)
    a=ap.parse_args()
    if a.radius_km<=0 or a.max_bytes<=0:ap.error('radius and byte budget must be positive')
    m=json.loads((ROOT/'manifest.json').read_text());start=date.fromisoformat(m['history_start']);end=date.fromisoformat(m['history_end_exclusive'])
    from datetime import timedelta
    end-=timedelta(days=1)
    entities=[]
    for tab,key in [('plants','plant_id'),('supplier_sites','supplier_site_id')]:
        for line in (ROOT/'data'/f'{tab}.jsonl').read_text().splitlines():
            r=json.loads(line);entities.append({'entity_id':r[key],'latitude':r['latitude'],'longitude':r['longitude']})
    out=ROOT/'public_data';out.mkdir(exist_ok=True)
    sql=build_sql(start,end);(out/'noaa_weather.sql').write_text(sql)
    (out/'query_parameters.json').write_text(json.dumps({'start_date':str(start),'end_date':str(end),'radius_km':a.radius_km,'entities_json':json.dumps(entities)},indent=2))
    if not a.execute:
        print('SQL and parameters prepared. No cloud query executed. Add --project PROJECT_ID --execute after local authentication.');return
    if not a.project:ap.error('--project is required with --execute')
    try:from google.cloud import bigquery
    except ImportError:raise SystemExit('Install google-cloud-bigquery from requirements-public-data.txt first.')
    client=bigquery.Client(project=a.project)
    params=[bigquery.ScalarQueryParameter('entities_json','STRING',json.dumps(entities)),bigquery.ScalarQueryParameter('start_date','DATE',start),bigquery.ScalarQueryParameter('end_date','DATE',end),bigquery.ScalarQueryParameter('radius_km','FLOAT64',a.radius_km)]
    dry=client.query(sql,job_config=bigquery.QueryJobConfig(query_parameters=params,dry_run=True,use_query_cache=False),location='US')
    print('Estimated bytes scanned:',dry.total_bytes_processed)
    if dry.total_bytes_processed>a.max_bytes:raise SystemExit('Estimate exceeds --max-bytes. No execution performed.')
    job=client.query(sql,job_config=bigquery.QueryJobConfig(query_parameters=params,maximum_bytes_billed=a.max_bytes),location='US')
    raw=[dict(r) for r in job.result()];retrieved=datetime.now(timezone.utc).isoformat()
    # Serialize dates explicitly; preserve source values and precipitation flags.
    raw=json.loads(json.dumps(raw,default=str))
    normalized=[normalize(r,retrieved) for r in raw]
    keys=[(r['entity_id'],r['usaf'],r['wban'],r['observation_date']) for r in normalized]
    if len(keys)!=len(set(keys)):raise SystemExit('Duplicate station dates returned; investigate before import.')
    for name,rows in [('noaa_raw.jsonl',raw),('weather_observations.jsonl',normalized)]:
        tmp=out/(name+'.tmp');tmp.write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in rows));tmp.replace(out/name)
    coverage={e['entity_id']:sum(r['entity_id']==e['entity_id'] for r in normalized) for e in entities}
    status={'status':'IMPORTED' if raw else 'EMPTY','source':'bigquery-public-data.noaa_gsod','job_id':job.job_id,'retrieved_at_utc':retrieved,'rows':len(raw),'coverage_days':coverage,'expected_days_per_entity':(end-start).days+1,'entities_without_observations':[k for k,v in coverage.items() if not v],'replay_warning':'First availability is retrieval time. These historical observations are not proof of information available at the earlier simulation decision time.'}
    (out/'import_status.json').write_text(json.dumps(status,indent=2));print(json.dumps(status,indent=2))
if __name__=='__main__':main()
