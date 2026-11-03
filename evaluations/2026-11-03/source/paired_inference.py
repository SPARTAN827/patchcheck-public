"""Frozen query-level inference machinery; this module contains no study results.

Call only with complete, genuinely human-referenced per-game confirmed counts.
It cannot establish label provenance or create/adjudicate reference judgments.
"""
import math
import numpy as np


def analyze(context_counts, rrf_counts):
    c=np.asarray(context_counts);r=np.asarray(rrf_counts)
    if c.ndim!=1 or r.ndim!=1 or len(c)!=len(r) or not 2<=len(c)<=60:
        raise ValueError('Require2–60 complete paired game/query units')
    if not(np.isfinite(c).all() and np.isfinite(r).all()):
        raise ValueError('No missing/nonfinite game counts')
    if not(np.equal(c,c.astype(int)).all() and np.equal(r,r.astype(int)).all() and (c>=0).all() and (r>=0).all() and (c<=10).all() and (r<=10).all()):
        raise ValueError('Confirmed counts must be integers0–10, not percentages or rating totals')
    # Integer differences preserve exact equality at permutation boundaries.
    d=c.astype(np.int64)-r.astype(np.int64);n=len(d);nonzero=d[d!=0];m=len(nonzero)
    observed=abs(int(d.sum()));extreme=0
    if m==0:
        pvalue=1.0;method='all_zero';draws=1;extreme=1
    elif m<=20:
        draws=2**m;bits=np.arange(m,dtype=np.uint64)
        for start in range(0,draws,4096):
            masks=np.arange(start,min(draws,start+4096),dtype=np.uint64)
            signs=2*((masks[:,None]>>bits)&1).astype(np.int64)-1
            extreme+=int(np.count_nonzero(np.abs(signs@nonzero)>=observed))
        pvalue=extreme/draws;method='exhaustive_nonzero_signs'
    else:
        draws=100000;rng=np.random.default_rng(20261102)
        for start in range(0,draws,5000):
            signs=2*rng.integers(0,2,size=(min(5000,draws-start),m),dtype=np.int64)-1
            extreme+=int(np.count_nonzero(np.abs(signs@nonzero)>=observed))
        pvalue=(1+extreme)/(1+draws);method='monte_carlo_sign_flip_plus_one'
    rng=np.random.default_rng(20261103);boot=np.empty(100000)
    for start in range(0,len(boot),5000):
        indices=rng.integers(0,n,size=(min(5000,len(boot)-start),n))
        boot[start:start+len(indices)]=d[indices].mean(axis=1)/10
    ci=np.quantile(boot,[.025,.975],method='linear').tolist()
    mean=float(d.mean()/10);degenerate=bool(np.all(d==d[0]));radius=math.sqrt(2*math.log(40)/n)
    return {'game_query_n':n,'nonzero_difference_n':m,'mean_yield_difference':mean,'percentage_point_difference':100*mean,'extra_confirmed_items_per10':10*mean,'paired_count_differences':d.tolist(),'win_tie_loss':{'context_higher':int((d>0).sum()),'tie':int((d==0).sum()),'context_lower':int((d<0).sum())},'two_sided_sign_flip':{'p_value':pvalue,'method':method,'sign_vectors':draws,'extreme_vectors':extreme,'seed_if_monte_carlo':20261102 if m>20 else None},'percentile_game_bootstrap_95':{'interval':ci,'resamples':100000,'seed':20261103,'degenerate_empirical_interval':degenerate},'bounded_mean_95_if_degenerate':[max(-1,mean-radius),min(1,mean+radius)] if degenerate else None,'assumptions':['Game units are independent; source frame is a fixed convenience frame, not a probability sample of all games.','Sign-flip inference assumes sign exchangeability/symmetry under the null; no randomized treatment assignment occurred.','Bootstrap resamples paired game differences, not individual texts or duplicated ratings.','Nonsignificance or a degenerate interval does not establish equivalence.','This function verifies arithmetic only; caller must separately validate genuine human references, completeness and provenance.']}
