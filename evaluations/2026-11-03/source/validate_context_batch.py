"""Mechanical validation of actual machine responses; never assigns judgments."""
import argparse,hashlib,json
from pathlib import Path
from compile_context import FIELDS,EXPERIENCE
p=argparse.ArgumentParser();p.add_argument('--batch',type=Path,required=True);p.add_argument('--response',type=Path,required=True);a=p.parse_args()
evidence=json.loads(a.batch.read_text());rows=json.loads(a.response.read_text())
assert isinstance(rows,list)
expected={e['case_id']:e for e in evidence};seen=set()
for r in rows:
    assert isinstance(r,dict) and set(r)==FIELDS,'Wrong fields'
    cid=r['case_id'];assert cid in expected and cid not in seen,'Unknown or repeated case ID';seen.add(cid);e=expected[cid]
    assert r['query_id']==e['query_id'] and r['record_id']==e['record_id'],'ID mismatch'
    s=r['same_specific_issue'];x=r['reported_experience'];assert s in {'yes','no','uncertain'} and x in EXPERIENCE,'Invalid category'
    assert (s=='no')==(x=='not_applicable'),'No/not_applicable inconsistency'
    q=r['evidence_quote'];assert q is None or isinstance(q,str) and q.strip() and q in e['review_text'],'Quote not exact'
    assert s=='no' or q is not None,'Missing quote'
    m=r['required_context_missing'];assert isinstance(m,str) and m.strip() if s=='uncertain' else m is None,'Missing-context field'
    assert isinstance(r['rationale'],str) and r['rationale'].strip(),'Missing rationale'
assert seen==set(expected),'Incomplete batch'
print(json.dumps({'status':'mechanical_validity_passed_not_label_correctness','count':len(rows),'response_sha256':hashlib.sha256(a.response.read_bytes()).hexdigest()}))
