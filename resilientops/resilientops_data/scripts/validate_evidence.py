"""Offline integrity checks for the evidence starter. Does not certify live cloud SQL."""
import json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[1]
def rows(p):return [json.loads(x) for x in (R/p).read_text().splitlines() if x.strip()]
w=rows('public_data/weather_reference/observations.jsonl');links=rows('public_data/weather_reference/entity_links.jsonl');n=rows('public_data/news/curated_evidence.jsonl');c=rows('knowledge/rag_chunks.jsonl')
checks=[]
def check(label,condition):
 checks.append({'check':label,'passed':bool(condition)})
check('Unique weather keys',len({x['observation_id'] for x in w})==len(w))
check('Historical weather dates unchanged',all('2024-01-01'<=x['observation_date']<'2026-10-01' for x in w))
check('Entity links resolve to observations',all(x['observation_id'] in {y['observation_id'] for y in w} for x in links))
check('Ambiguous rain excluded from daily analysis',all(x['daily_precipitation_mm_for_analysis'] is None or x['precipitation_flag']=='G' for x in w))
check('Public records labeled observed',all(x['source_is_synthetic'] is False for x in w+n))
check('News URLs unique',len({x['source_url'] for x in n})==len(n))
check('No unverified operational impact links',all(x['linked_entity_ids']==[] for x in n))
check('Short paraphrases only',all(len(x['claim_summary'].split())<75 for x in n))
check('News temporal boundaries explicit',all(x['usage']=='HISTORICAL_REFERENCE_NOT_ASOF_VERIFIED' for x in n))
check('Chunks unique and synthetic',len({x['chunk_id'] for x in c})==len(c) and all(x['is_synthetic'] for x in c))
check('Chunk documents exist',all((R/'knowledge'/x['path']).is_file() for x in c))
check('Chunk checksums match',all(hashlib.sha256(x['text'].encode()).hexdigest()==x['content_sha256'] for x in c))
result={'passed':all(x['passed'] for x in checks),'checks':checks,'counts':{'weather_observations':len(w),'entity_links':len(links),'news_summaries':len(n),'knowledge_chunks':len(c)},'limits':['No live Google query executed','No embeddings generated','No confirmed supplier impacts inferred']}
(R/'evidence_validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)
