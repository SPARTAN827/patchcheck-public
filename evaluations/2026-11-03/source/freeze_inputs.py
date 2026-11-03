"""Freeze eligible source-linked inputs before any new ranking/model outcomes."""
import argparse, collections, datetime as dt, gzip, hashlib, json
from pathlib import Path

BASE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')

def main():
    a=argparse.ArgumentParser();a.add_argument('--selected',type=Path,required=True);a.add_argument('--protocol',type=Path,required=True);a.add_argument('--output',type=Path,required=True);args=a.parse_args()
    protocol=json.loads(args.protocol.read_text());selected=json.loads(args.selected.read_text())
    exclusions=set(map(str,protocol['sampling']['development_game_exclusions']))
    semantic={}
    for name in ['semantic-provisional-passes.json','semantic-B-provisional-passes.json','semantic-C-provisional-passes.json']:
        for r in json.loads((BASE/'source-inventory'/name).read_text()):semantic[r['fix_id']]=r
    chosen=[];seen_games=set()
    for r in sorted(selected,key=lambda r:(r['game_order_sha256'],str(r['appid']))):
        aid=str(r['appid']);assert aid not in seen_games;seen_games.add(aid)
        assert aid not in exclusions and aid not in {'1325400','1812620','1364390','1787090'}
        assert r['fix_id'] in semantic,'Source decision superseded; reverify current selection'
        assert r['claim_quote']==semantic[r['fix_id']]['claim_quote']
        v=r['source_verification'];assert v['status']=='verified_current_source'
        assert v.get('target_quote_present') is True and v.get('target_publication_matches_archived') is True,'Need target-event-bound verification'
        assert r['window']['candidate_pairs']>=20
        chosen.append(r)
    if len(chosen)<60:raise ValueError(f'Only {len(chosen)} validated eligible games; cannot manufacture target')
    chosen=chosen[:60];args.output.mkdir(parents=True,exist_ok=False)
    queries=[];pool_stats=[];candidates=[]
    for index,r in enumerate(chosen,1):
        aid=str(r['appid']);qid=f'E60-Q{index:03d}';v=r['source_verification']
        q={'query_id':qid,'appid':aid,'game':r['game'],'quote':r['claim_quote'],'published_at':r['published_at_utc'],'source_url':v.get('canonical_url') or v['final_url'],'current_official_url':v['final_url'],'archived_source_url':r['source_url'],'source_snapshot_id':r['update_snapshot_id'],'fix_id':r['fix_id'],'source_body_sha256':r['body_sha256'],'quote_start':r['quote_start'],'quote_end_exclusive':r['quote_end_exclusive'],'source_modified_at':r.get('source_modified_at_utc') or None,'historical_quote_presence':'unknown','deployment_time':None,'source_verification':v,'selection_order_sha256':r['game_order_sha256'],'source_scope':'Windows/PC source-content screening; snapshot-text announcement proxy, not strict temporal qualification'}
        queries.append(q);seen=set();pool=[]
        begin=dt.date.fromisoformat(q['published_at'][:10]);end=begin+dt.timedelta(days=90)
        with gzip.open(BASE/'screened'/f'{aid}.english.jsonl.gz','rt',encoding='utf-8') as f:
            for line in f:
                c=json.loads(line);day=dt.date.fromisoformat(c['post_date'])
                if not begin<day<=end or c['text_sha256'] in seen:continue
                assert c['source_csv_sha256']==r['raw_csv_sha256']
                assert c['language_prediction']=='__label__en' and c['language_score']>=.8
                assert hashlib.sha256(c['text'].encode()).hexdigest()==c['text_sha256']
                seen.add(c['text_sha256']);pool.append(dict(c,query_id=qid))
        assert len(pool)==r['window']['candidate_pairs'] and len(pool)>=20
        candidates.extend(pool)
        pool_stats.append({'query_id':qid,'appid':aid,'game':r['game'],'candidate_pairs':len(pool),**r['window'],'source_latest_review_date':r['source_latest_review_date']})
    write(args.output/'queries.json',queries);write(args.output/'query-pools.json',pool_stats)
    with (args.output/'candidates.jsonl').open('w') as f:
        for c in sorted(candidates,key=lambda x:(x['query_id'],x['record_id'])):f.write(json.dumps(c,ensure_ascii=False)+'\n')
    write(args.output/'source-roster.frozen.json',chosen)
    sources=[args.protocol,args.selected,BASE/'source-inventory/candidate-member-manifest.json',BASE/'source-inventory/source-claim-leads.json',BASE/'protocol/development-exclusions.frozen.json']
    for name in ['semantic-decisions.json','semantic-B-decisions.json','semantic-C-decisions.json']:
        sources.append(BASE/'source-inventory'/name)
    receipt={'frozen_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'status':'60_new_source_qualified_snapshot_query_pools_frozen_before_retrieval','query_count':len(queries),'distinct_games':len({q['appid'] for q in queries}),'candidate_pairs':len(candidates),'source_frame_sha256':{str(p):sha(p) for p in sources},'output_sha256':{p.name:sha(p) for p in args.output.iterdir() if p.is_file()},'script_sha256':sha(__file__),'human_labels':0,'limitations':['Nonexhaustive historical source-lead sampling frame','Source current official text verified; original-day wording, deployment, review edits and played build unknown','Main100 corpus unchanged; expansion is a separate evaluation cohort','No model effectiveness or inferential result exists before actual human judgments']}
    write(args.output/'freeze-receipt.json',receipt)
    print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
