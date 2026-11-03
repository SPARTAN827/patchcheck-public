# Pipeline

1. Select a specific, dated fix statement from an official game announcement.
2. Keep English-screened reviews dated after the announcement through day 90, then remove exact duplicate texts within each query.
3. Rank candidates with BM25 and MiniLM semantic similarity. Combine their ranks with RRF (k = 60).
4. Apply the frozen context prompt to each query's top 50 RRF results, or all candidates when fewer are available. Keep only `same_specific_issue = yes` and `reported_experience = ongoing`, in RRF order, up to 10 results.
5. Compare the displayed results with the saved reference codes. Each method has 10 display slots per query; empty slots contribute zero target-labeled items.

The context assessment covered 2,899 full statement-review pairs. MiniLM used 254-token chunks with a 32-token overlap; each review's semantic score was its highest chunk score.

## Source code

All paths below are under [evaluations/2026-11-03/source/](../evaluations/2026-11-03/source/).

| Stage | Files |
|---|---|
| Source checks and acquisition | `verify_sources.py`, `acquire_reviews.py` |
| Screening and frozen inputs | `screen_reviews.py`, `freeze_inputs.py`, `summarize_frozen_cohort.py` |
| Retrieval | `retrieval-run.py`, `retrieval-metadata.json` |
| Context assessment | `prepare_context.py`, `validate_context_batch.py`, `compile_context.py` |
| Analysis | `frozen_analyze_reference.py`, `paired_inference.py` |

These files preserve the executed source. Several require the original working directories, source archives or model environment. Use [reproduce_analysis.py](../evaluations/2026-11-03/reproduce_analysis.py) for the portable saved-data replay.

The [frozen protocol](../evaluations/2026-11-02/evidence/protocol-v3.frozen.json) records the planned procedure. The [reference provenance](../evaluations/2026-11-03/REFERENCE-PROVENANCE.md) describes the labels actually received.
