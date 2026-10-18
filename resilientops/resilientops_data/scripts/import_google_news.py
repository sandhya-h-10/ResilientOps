"""Prepare/run a bounded GDELT BigQuery candidate-evidence query; never fetch article bodies."""
import argparse,json,hashlib
from datetime import date,datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SQL="""SELECT GKGRECORDID, CAST(DATE AS STRING) AS gdelt_date,
DocumentIdentifier AS source_url, SourceCommonName AS publisher,
V2Themes AS themes, V2Locations AS locations
FROM `gdelt-bq.gdeltv2.gkg_partitioned`
WHERE _PARTITIONTIME >= TIMESTAMP(@start_date)
AND _PARTITIONTIME < TIMESTAMP(@end_date)
AND REGEXP_CONTAINS(LOWER(IFNULL(V2Locations,'')), @location_pattern)
AND REGEXP_CONTAINS(LOWER(CONCAT(IFNULL(V2Themes,''),' ',IFNULL(DocumentIdentifier,''))), @topic_pattern)
AND STARTS_WITH(DocumentIdentifier,'http')
QUALIFY ROW_NUMBER() OVER(PARTITION BY DocumentIdentifier ORDER BY DATE DESC, GKGRECORDID)=1
ORDER BY DATE DESC, GKGRECORDID
LIMIT @max_records
"""
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--project');ap.add_argument('--execute',action='store_true');ap.add_argument('--start',default='2025-09-22');ap.add_argument('--end',default='2025-09-26');ap.add_argument('--max-bytes',type=int,default=2_000_000_000);ap.add_argument('--max-records',type=int,default=100)
 a=ap.parse_args();start=date.fromisoformat(a.start);end=date.fromisoformat(a.end)
 if not 0<(end-start).days<=7:ap.error('Use a positive window of at most 7 days; end date is exclusive.')
 if not 1<=a.max_records<=1000 or a.max_bytes<=0:ap.error('Invalid limit or byte budget')
 params={'start_date':str(start),'end_date':str(end),'location_pattern':'mumbai|bombay|tokyo|beijing|peking|shenzhen|osaka|pune|hong kong|guangdong','topic_pattern':'flood|typhoon|cyclone|earthquake|strike|port.closure|factory.fire|power.outage|transport|sanction|tariff|border|conflict|inflation|commodity|exchange.rate|labor|labour|protest|public.health|holiday|festival|shutdown|outage|cyber|ransomware|export.control|customs|compliance','max_records':a.max_records}
 out=ROOT/'public_data/news';out.mkdir(parents=True,exist_ok=True);(out/'gdelt_query.sql').write_text(SQL);(out/'gdelt_parameters.json').write_text(json.dumps(params,indent=2))
 if not a.execute:print('Query prepared; public BigQuery import not executed.');return
 if not a.project:ap.error('--project required with --execute')
 from google.cloud import bigquery
 client=bigquery.Client(project=a.project)
 qp=[bigquery.ScalarQueryParameter(k,'INT64' if k=='max_records' else 'DATE' if k.endswith('_date') else 'STRING',v) for k,v in params.items()]
 dry=client.query(SQL,job_config=bigquery.QueryJobConfig(query_parameters=qp,dry_run=True,use_query_cache=False),location='US');print('Estimated bytes:',dry.total_bytes_processed)
 if dry.total_bytes_processed>a.max_bytes:raise SystemExit('Scan exceeds budget. Narrow dates or explicitly adjust --max-bytes after review.')
 job=client.query(SQL,job_config=bigquery.QueryJobConfig(query_parameters=qp,maximum_bytes_billed=a.max_bytes),location='US')
 retrieved=datetime.now(timezone.utc).isoformat();records=[]
 for r in job.result():
  raw=dict(r);url=raw['source_url']
  records.append({'evidence_id':'GDELT_'+hashlib.sha256(url.encode()).hexdigest()[:20],**raw,'source_is_synthetic':False,'evidence_status':'CANDIDATE_METADATA_NOT_VERIFIED','source_dataset':'gdelt-bq.gdeltv2.gkg_partitioned','retrieved_at_utc':retrieved,'available_at_utc':retrieved,'publication_time_utc':None,'event_time_utc':None,'linked_entity_ids':[],'note':'GDELT timestamp is ingestion metadata, not proven publication/event time. Geographic mentions do not establish supplier impact.'})
 (out/'gdelt_candidates.jsonl').write_text(''.join(json.dumps(r,default=str,sort_keys=True)+'\n' for r in records))
 (out/'gdelt_import_status.json').write_text(json.dumps({'status':'IMPORTED' if records else 'EMPTY','rows':len(records),'job_id':job.job_id,'retrieved_at_utc':retrieved,'coverage':'Bounded keyword sample; not exhaustive; LIMIT does not cap scanned bytes.'},indent=2));print('Candidates exported:',len(records))
if __name__=='__main__':main()
