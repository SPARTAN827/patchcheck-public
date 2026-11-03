"""Whole-text language screening and date-window counts; no relevance judgments."""
import argparse, collections, csv, datetime as dt, gzip, hashlib, json
from pathlib import Path
import fasttext

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[1]
MODEL=ROOT/'experiments/cleaning-2026-09-21/resources/lid.176.bin'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--start',type=int,default=0);ap.add_argument('--stop',type=int,default=211);args=ap.parse_args()
    members=json.loads((BASE/'source-inventory/candidate-member-manifest.json').read_text())[args.start:args.stop]
    leads=json.loads((BASE/'source-inventory/source-claim-leads.json').read_text());bygame=collections.defaultdict(list)
    for lead in leads:bygame[str(lead['appid'])].append(lead)
    out=BASE/'screened';out.mkdir(exist_ok=True);model=fasttext.load_model(str(MODEL));csv.field_size_limit(10000000)
    for number,m in enumerate(members,1):
        aid=str(m['appid']);target=out/f'{aid}.summary.json'
        if target.exists():print(number,aid,'existing',flush=True);continue
        receipt=BASE/'acquisition'/f'{aid}.json'
        if not receipt.exists():print(number,aid,'not_acquired',flush=True);continue
        rec=json.loads(receipt.read_text())
        if rec['status'] not in ('verified_existing','acquired_crc_length_verified'):continue
        path=Path(rec['path']);assert sha(path)==rec['sha256']
        rows=list(csv.DictReader(path.open(encoding='utf-8-sig',newline='')))
        dates=[];passing=[];stats=collections.Counter();seen_global=set()
        tmp=out/f'{aid}.english.jsonl.gz.tmp'
        with gzip.open(tmp,'wt',encoding='utf-8') as f:
            for start in range(0,len(rows),512):
                batch=rows[start:start+512]
                labs,scores=model.predict([' '.join(r['review'].splitlines()) or ' ' for r in batch],k=1)
                for off,(row,lab,score) in enumerate(zip(batch,labs,scores)):
                    ix=start+off+1;text=row['review'];day=dt.datetime.strptime(row['post_date'],'%B %d, %Y').date()
                    dates.append(day);stats['raw_rows']+=1
                    if not text.strip():stats['empty']+=1;continue
                    if lab[0]!='__label__en' or float(score[0])<.8:stats['language_excluded']+=1;continue
                    digest=hashlib.sha256(text.encode()).hexdigest();stats['english_rows']+=1
                    if digest not in seen_global:stats['english_unique']+=1;seen_global.add(digest)
                    record={'record_id':f'mend-v2-{aid}-r{ix:06d}-{digest[:12]}','appid':aid,'source_member':m['name'],'source_csv_sha256':rec['sha256'],'source_row_1based':ix,'text_sha256':digest,'post_date':day.isoformat(),'language_prediction':lab[0],'language_score':float(score[0]),'text':text,'temporal_status':'coarse_creation_date_only;modified_unknown'}
                    f.write(json.dumps(record,ensure_ascii=False)+'\n');passing.append((day,digest))
        tmp.replace(out/f'{aid}.english.jsonl.gz')
        bydate={}
        for lead in bygame[aid]:
            anchor=lead['published_at_utc'][:10]
            if anchor in bydate:continue
            begin=dt.date.fromisoformat(anchor);end=begin+dt.timedelta(days=90)
            hashes={digest for day,digest in passing if begin<day<=end}
            bydate[anchor]={'candidate_pairs':len(hashes),'window_start_exclusive':str(begin),'window_end_inclusive':str(end),'observed_tail_reaches_endpoint':max(dates)>=end,'full_window_coverage':'unknown; tail alone does not prove completeness'}
        summary={'appid':aid,'game':m['game'],'source_member':m['name'],'source_csv_sha256':rec['sha256'],'source_rows':len(rows),'counts':dict(stats),'earliest_source_date':min(dates).isoformat(),'latest_source_date':max(dates).isoformat(),'windows_by_publication_date':bydate,'created_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'language_rule':'fastText lid176 full-text top en >= .80; within-window exact text dedup for counts','input_manifest_sha256':sha(BASE/'source-inventory/candidate-member-manifest.json'),'no_relevance_labels':True}
        dump(target,summary)
        print(number,'/',len(members),aid,len(rows),'rows',sum(x['candidate_pairs']>=20 for x in bydate.values()),'dates_with_20',flush=True)
    dump(out/f'run-{args.start:03d}-{args.stop:03d}.json',{'completed_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'model_sha256':sha(MODEL),'range':[args.start,args.stop],'script_sha256':sha(Path(__file__))})

if __name__=='__main__':main()
