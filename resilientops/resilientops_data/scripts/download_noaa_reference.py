"""Fetch selected NOAA stations for every year in the operational history. Preserve failures."""
import csv,io,json,urllib.request,hashlib
from pathlib import Path
from datetime import datetime,timezone,date
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[1]
def main():
 out=ROOT/'public_data/weather_reference';out.mkdir(parents=True,exist_ok=True)
 mappings=json.loads((ROOT/'public_data/noaa_reference_station_mapping.json').read_text())
 # Same defaults as the generator, configurable by its manifest once available.
 meta=json.loads((ROOT/'manifest.json').read_text()); start=date.fromisoformat(meta['history_start']); end=date.fromisoformat(meta['history_end_exclusive'])
 def fetch(pair):
  s,year=pair;url=f'https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/{year}/{s}.csv'
  try:
   with urllib.request.urlopen(url,timeout=20) as response:b=response.read()
   rows=list(csv.DictReader(io.StringIO(b.decode('utf-8-sig'))))
   if not rows or 'TEMP' not in rows[0]:raise ValueError('Unexpected source schema')
   (out/f'{s}_{year}.csv').write_bytes(b)
   return {'station_id':s,'year':year,'status':'DOWNLOADED','url':url,'rows':len(rows),'sha256':hashlib.sha256(b).hexdigest(),'retrieved_at_utc':datetime.now(timezone.utc).isoformat()}
  except Exception as e:
   return {'station_id':s,'year':year,'status':'FAILED','url':url,'error':str(e),'attempted_at_utc':datetime.now(timezone.utc).isoformat()}
 tasks=[(s,y) for s in sorted({m['station_id'] for m in mappings}) for y in range(start.year,end.year+1)]
 with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(fetch,tasks))
 (out/'download_status.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
if __name__=='__main__':main()
