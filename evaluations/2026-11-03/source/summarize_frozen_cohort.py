"""Descriptive cohort counts only; no relevance or human effectiveness results."""
import collections,csv,datetime as dt,hashlib,json,statistics
from pathlib import Path
BASE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def summary(v):
    q=statistics.quantiles(v,n=4,method='inclusive')
    return dict(n=len(v),total=sum(v),minimum=min(v),q1=q[0],median=statistics.median(v),q3=q[2],maximum=max(v),mean=statistics.mean(v),sample_sd=statistics.stdev(v))
queries=json.loads((BASE/'prepared/queries.json').read_text())
pools={r['query_id']:r for r in json.loads((BASE/'prepared/query-pools.json').read_text())}
chars=collections.defaultdict(list)
for line in (BASE/'prepared/candidates.jsonl').open():
    c=json.loads(line);chars[c['query_id']].append(len(c['text']))
rows=[]
for q in queries:
    s=json.loads((BASE/'screened'/f"{q['appid']}.summary.json").read_text());n=pools[q['query_id']]['candidate_pairs']
    assert n==len(chars[q['query_id']])
    rows.append(dict(query_id=q['query_id'],appid=q['appid'],game=q['game'],raw_rows=s['source_rows'],english_screened_rows=s['counts']['english_rows'],window_unique_candidates=n,mean_candidate_characters=statistics.mean(chars[q['query_id']]),announcement_published_at=q['published_at']))
out=BASE/'descriptive';out.mkdir(exist_ok=False)
with (out/'cohort-by-game.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
result={'created_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'unit':'60 frozen game/query pools; candidate texts are not human labels','queries':len(rows),'distributions':{k:summary([r[k] for r in rows]) for k in ['raw_rows','english_screened_rows','window_unique_candidates']},'human_judgments_received':0,'input_sha256':{str(p):sha(p) for p in [BASE/'prepared/queries.json',BASE/'prepared/query-pools.json',BASE/'prepared/candidates.jsonl']},'script_sha256':sha(Path(__file__)),'limitations':['Language is model-screened, not human certified.','Window and deduplication counts describe eligibility, not relevance or matching accuracy.','Expansion cohort is separate from the original100-game corpus.']}
(out/'cohort-summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k in ['queries','distributions','human_judgments_received']},indent=2))
