#!/usr/bin/env python3
"""Public Steam development retrieval; no labels, accuracy or causal inference."""
import argparse, collections, csv, datetime, gzip, hashlib, importlib.metadata, json, os, platform, re, sys, time
from pathlib import Path
MODEL='sentence-transformers/all-MiniLM-L6-v2'
REVISION='1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def windows(n,width=254,overlap=32):
    if n==0: return [(0,0)]
    out=[]; start=0
    while True:
        end=min(n,start+width); out.append((start,end))
        if end==n: return out
        start=end-overlap

def order(ids,scores): return sorted(range(len(ids)),key=lambda i:(-float(scores[i]),ids[i]))
def emit(p,rows,fields):
    op=gzip.open if str(p).endswith('.gz') else open
    with op(p,'wt',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def main():
    a=argparse.ArgumentParser();a.add_argument('--queries',type=Path,required=True);a.add_argument('--candidates',type=Path,required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--model-path',type=Path);a.add_argument('--methods',default='bm25,semantic,rrf');a.add_argument('--threads',type=int,default=4);a.add_argument('--batch-size',type=int,default=64);args=a.parse_args()
    methods=args.methods.split(',');assert set(methods)<={'bm25','semantic','rrf','tfidf'}
    if 'rrf' in methods: assert {'bm25','semantic'}<=set(methods)
    args.output.mkdir(parents=True,exist_ok=False)
    started=datetime.datetime.now(datetime.timezone.utc).isoformat();start=time.monotonic()
    input_hashes={str(args.queries):sha(args.queries),str(args.candidates):sha(args.candidates)}
    import numpy as np
    queries=json.loads(args.queries.read_text());queries=queries['queries'] if isinstance(queries,dict) else queries
    qmap={str(q['query_id']):q for q in queries};assert len(qmap)==len(queries)
    pools=collections.defaultdict(list);keys=set()
    for line in args.candidates.open():
        c=json.loads(line);qid=str(c['query_id']);rid=str(c['record_id']);assert qid in qmap and str(c['appid'])==str(qmap[qid]['appid']);assert (qid,rid) not in keys
        assert isinstance(c['text'],str) and c['text'].strip(), 'Blank review'
        c['record_id']=rid;keys.add((qid,rid));pools[qid].append(c)
    model=None;model_hashes={};chunk_rows=[];statuses=[];ranked=[];allrows=[]
    if 'semantic' in methods:
        import torch
        from sentence_transformers import SentenceTransformer
        assert args.model_path and args.model_path.name==REVISION
        model_hashes={str(p.relative_to(args.model_path)):sha(p) for p in args.model_path.rglob('*') if p.is_file()}
        torch.set_num_threads(args.threads);torch.manual_seed(0);np.random.seed(0)
        model=SentenceTransformer(str(args.model_path),device='cpu',local_files_only=True,trust_remote_code=False);model.eval()
        assert model.max_seq_length==256
    for q in queries:
        qid=str(q['query_id']);pool=sorted(pools[qid],key=lambda c:c['record_id']);ids=[c['record_id'] for c in pool];texts=[c['text'] for c in pool];scores={}
        if not pool:
            for method in methods:statuses.append(dict(query_id=qid,method=method,candidate_count=0,returned_count=0,status='empty_pool'))
            continue
        if 'bm25' in methods:
            from rank_bm25 import BM25Okapi
            toks=[re.findall(r'\w+',t.lower()) for t in texts]
            scores['bm25']=BM25Okapi(toks,k1=1.5,b=.75,epsilon=.25).get_scores(re.findall(r'\w+',q['quote'].lower())) if any(toks) else np.zeros(len(pool))
        if 'tfidf' in methods:
            from sklearn.feature_extraction.text import TfidfVectorizer
            try:
                v=TfidfVectorizer();mat=v.fit_transform(texts);scores['tfidf']=(mat@v.transform([q['quote']]).T).toarray().ravel()
            except ValueError:scores['tfidf']=np.zeros(len(pool))
        if model is not None:
            tok=model.tokenizer;query_ids=tok(q['quote'],add_special_tokens=True,truncation=False)['input_ids'];assert len(query_ids)<=256,'Query would truncate'
            qe=model.encode([q['quote']],normalize_embeddings=True,show_progress_bar=False)[0]
            vals=np.full(len(pool),-np.inf);winners=[None]*len(pool);features=[];owners=[];spans=[]
            def flush():
                if not features:return
                batch=tok.pad(features,padding=True,return_tensors='pt')
                with torch.inference_mode():emb=model(batch)['sentence_embedding'];emb=torch.nn.functional.normalize(emb,p=2,dim=1).cpu().numpy()
                for owner,span,score in zip(owners,spans,emb@qe):
                    if float(score)>vals[owner]:vals[owner]=float(score);winners[owner]=span
                features.clear();owners.clear();spans.clear()
            for i,text in enumerate(texts):
                token_ids=tok(text,add_special_tokens=False,truncation=False)['input_ids'];ss=windows(len(token_ids))
                for left,right in ss:
                    token_slice=tok.build_inputs_with_special_tokens(token_ids[left:right]);features.append({'input_ids':token_slice,'attention_mask':[1]*len(token_slice)});owners.append(i);spans.append((left,right))
                    if len(features)>=args.batch_size:flush()
                chunk_rows.append(dict(query_id=qid,record_id=ids[i],tokens=len(token_ids),chunks=len(ss),covered_tokens=sum(r-l for l,r in ss)-32*(len(ss)-1)))
            flush();scores['semantic']=vals
            for row,winner in zip(chunk_rows[-len(pool):],winners):row.update(winner_start=winner[0],winner_end=winner[1])
        if 'rrf' in methods:
            ranks={m:{ids[i]:r+1 for r,i in enumerate(order(ids,scores[m]))} for m in ['bm25','semantic']}
            scores['rrf']=np.array([1/(60+ranks['bm25'][rid])+1/(60+ranks['semantic'][rid]) for rid in ids])
        for method in methods:
            values=scores[method];assert np.isfinite(values).all()
            ordering=order(ids,values)
            for rank,i in enumerate(ordering,1):
                row=dict(query_id=qid,appid=q['appid'],method=method,record_id=ids[i],rank=rank,score=float(values[i]));allrows.append(row)
                if rank<=10:ranked.append(row)
            statuses.append(dict(query_id=qid,method=method,candidate_count=len(pool),returned_count=min(10,len(pool)),status='completed'))
        print(qid,len(pool),'completed',flush=True)
    assert input_hashes=={str(args.queries):sha(args.queries),str(args.candidates):sha(args.candidates)}, 'Inputs changed during run'
    fields=['query_id','appid','method','record_id','rank','score'];emit(args.output/'ranked_top10.csv',ranked,fields);emit(args.output/'all_scores.csv.gz',allrows,fields);emit(args.output/'query_status.csv',statuses,['query_id','method','candidate_count','returned_count','status'])
    if chunk_rows:emit(args.output/'chunk_coverage.csv',chunk_rows,['query_id','record_id','tokens','chunks','covered_tokens','winner_start','winner_end'])
    packages={}
    for p in ['numpy','torch','rank-bm25','sentence-transformers','transformers','scikit-learn','huggingface-hub']:
        try:packages[p]=importlib.metadata.version(p)
        except importlib.metadata.PackageNotFoundError:pass
    meta=dict(started_at=started,ended_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-start,command=sys.argv,python=sys.version,platform=platform.platform(),packages=packages,input_hashes=input_hashes,script_sha256=sha(__file__),model=MODEL,revision=REVISION,model_files_sha256=model_hashes,methods=methods,query_count=len(queries),candidate_pairs=len(keys),bm25={'k1':1.5,'b':.75,'epsilon':.25,'tokenization':'Unicode lowercase \\w+'},semantic={'window':254,'overlap':32,'aggregation':'max cosine','query_truncation':False,'review_truncation':False},rrf_k=60,tie_break='score descending then record_id lexical ascending',limitations=['Development retrieval only; no human labels or quality metrics','Longer reviews have more maximum-score opportunities','RRF retains zero/nonpositive BM25 ranks; ties lexical, not relevance','Day-only public dates; edit times and patch exposure unknown'])
    (args.output/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n')
if __name__=='__main__':main()
