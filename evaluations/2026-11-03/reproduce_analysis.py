#!/usr/bin/env python3
"""Reproduce the conditional comparison from the published, reduced inputs.

No network, model inference, new labels, source QA or input edits. Uses only
Python 3.12+ standard library. This is a new portable adapter, not a rewrite of
the frozen analysis. The original analysis functions and their bytes are retained.
"""
from pathlib import Path
from collections import Counter, defaultdict
import argparse, csv, hashlib, importlib.util, json, math, sys

BASE=Path(__file__).resolve().parent

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='A NEW output JSON filename; never overwrite frozen evidence')
    args=parser.parse_args()
    if args.output.exists(): parser.error('Output already exists; choose a fresh filename')
    if sys.version_info < (3,12): parser.error('Python 3.12 or newer is required')
    manifest=json.loads((BASE/'source-manifest.json').read_text())
    repo=BASE.parents[1]
    for rec in manifest['records']:
        p=repo/rec['path']
        assert p.stat().st_size==rec['bytes'],rec['path']
        assert hashlib.sha256(p.read_bytes()).hexdigest()==rec['sha256'],rec['path']
    spec=importlib.util.spec_from_file_location('frozen_analysis',BASE/'source/frozen_analyze_reference.py')
    frozen=importlib.util.module_from_spec(spec); spec.loader.exec_module(frozen)
    rows=read_csv(BASE/'inputs/reference-codes.csv')
    labels={r['pair_id']:r for r in rows}
    queries=json.loads((BASE/'inputs/queries.json').read_text())
    rankings=json.loads((BASE/'inputs/method-rankings.json').read_text())
    order=[q['query_id'] for q in queries]
    assert len(labels)==len(rows)==1215 and len(set(order))==60
    assert Counter(r['same_issue'] for r in rows)=={'no':997,'uncertain':214,'yes':4}
    grouped=defaultdict(list)
    for row in rankings:
        assert row['case_id'] in labels
        assert labels[row['case_id']]['query_id']==row['query_id']
        grouped[row['query_id'],row['method']].append(row)
    lists={}
    per_query={}
    for q in order:
        for method in frozen.METHODS:
            ranked=sorted(grouped[q,method],key=lambda r:r['rank'])
            assert [r['rank'] for r in ranked]==list(range(1,len(ranked)+1))
            ids=[r['case_id'] for r in ranked]
            assert len(ids)==len(set(ids))<=10
            assert len(ids)==10 or method=='rrf_context'
            lists[q,method]=ids
            per_query[q,method]=frozen.counts(ids,labels)
    assert set(labels)=={i for ids in lists.values() for i in ids}
    methods=[]
    for method in frozen.METHODS:
        vals=[per_query[q,method] for q in order]
        rec={'method':method,'queries':60,'fixed_display_slots':600,
             **{key:sum(v[key] for v in vals) for key in vals[0]}}
        rec['empty_slots']=600-rec['returned']
        rec['full_abstention_queries']=sum(v['returned']==0 for v in vals)
        rec['submitted_target_yield_at10']=rec['submitted_target_yes_ongoing']/600
        methods.append(rec)
    original=read_csv(BASE/'results/method-summary.csv')
    for current,expected in zip(methods,original):
        for key,value in current.items():
            assert (value==expected[key] if isinstance(value,str) else math.isclose(value,float(expected[key]),abs_tol=1e-14)),(key,value,expected[key])
    for row in read_csv(BASE/'results/per-query-method.csv'):
        for key,value in per_query[row['query_id'],row['method']].items():
            assert value==int(row[key]),(row['query_id'],key)
    differences=[per_query[q,'rrf_context']['submitted_target_yes_ongoing']-per_query[q,'rrf']['submitted_target_yes_ongoing'] for q in order]
    primary=frozen.paired_inference(differences)
    original_primary=json.loads((BASE/'results/original-primary-conditional-inference.json').read_text())
    assert json.loads(json.dumps(primary))==original_primary,'Frozen numeric replay differs'
    bounds={scenario:frozen.summarize_bound(frozen.bound_rows(order,lists,labels,scenario)) for scenario in frozen.SCENARIOS}
    original_bounds=read_csv(BASE/'results/shared-pair-uncertainty-bounds.csv')
    for scenario in frozen.SCENARIOS:
        expected=[r for r in original_bounds if r['scenario']==scenario]
        actual=frozen.bound_rows(order,lists,labels,scenario)
        for a,e in zip(actual,expected):
            for key,value in a.items():
                assert (value==e[key] if isinstance(value,str) else math.isclose(value,float(e[key]),abs_tol=1e-14)),(scenario,key)
    secondhand=[{'method':m,'targets_excluding_known_secondhand':sum(frozen.target(labels[i]) and i!=frozen.SECONDHAND for q in order for i in lists[q,m])} for m in frozen.METHODS]
    assert [r['targets_excluding_known_secondhand'] for r in secondhand]==[1,1,1,2]
    output={'status':'pass','scope':'Numeric replay only; not source/semantic re-review, new model execution, or independent-human validation',
            'reference_status':'Mixed-provenance developmental reference; 306 submitter-reported human reviews then AI re-review, plus 909 carried records',
            'source_files_verified':len(manifest['records']),'pairs':1215,'game_queries':60,'methods':methods,
            'primary':{'percentage_point_difference':primary['percentage_point_difference'],'p_value':primary['two_sided_sign_flip']['p_value'],
                       'bootstrap_95_percentage_points':[100*x for x in primary['percentile_game_bootstrap_95']['interval']],
                       'bootstrap_histogram_matches_original':True,'win_tie_loss':primary['win_tie_loss']},
            'shared_pair_scenario_bounds':bounds,'known_secondhand_sensitivity':secondhand,
            'warning':'The old function embeds its earlier procedure-unconfirmed status. This adapter reports current provenance separately; numerical equality does not reinstate that historical wording.'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as f: json.dump(output,f,indent=2); f.write('\n')
    print(json.dumps({'status':'pass','pairs':1215,'games':60,'files_verified':len(manifest['records']),'output':str(args.output)}))

if __name__=='__main__': main()
