# November 3, 2026 results

Status: saved exploratory comparison. Model outputs were frozen at 01:32:21 UTC; final reference codes arrived at 09:26:20 UTC. The procedure statement was recorded at 09:48 UTC.

| Method | Returned items | Target-labeled items | Games with no returned items |
|---|---:|---:|---:|
| BM25 | 600 | 2 | 0 |
| Semantic | 600 | 1 | 0 |
| RRF | 600 | 1 | 0 |
| RRF + context | 3 | 2 | 57 |

Each method has 600 possible display slots across 60 games. A target-labeled item has both `same_issue = yes` and `experience = ongoing` in the saved reference.

For context versus RRF, the mean difference is +0.167 percentage points, the paired sign-flip p-value is 1.0, and the empirical paired-game bootstrap interval is [0, +0.500] percentage points. One game contributes the observed difference. The shared-pair uncertainty analysis ranges from -15.000 to +0.333 percentage points under the experience-compatible scenario. These results do not establish superiority or equivalence.

## Files

- [Reproduction instructions](REPRODUCTION.md)
- [Reference provenance](REFERENCE-PROVENANCE.md)
- [Method summary](results/method-summary.csv) and [per-query results](results/per-query-method.csv)
- [Primary inference](results/original-primary-conditional-inference.json) and [uncertainty bounds](results/shared-pair-uncertainty-bounds.csv)
- [Input and source checksums](source-manifest.json)

The [cohort summary](../2026-11-02/evidence/cohort-summary.json) records 657,375 raw review rows, 303,692 English-screened rows and 39,944 eligible pairs. Its human-label count and the [execution summary](../2026-11-02/evidence/machine-execution-summary.json)'s human-label count describe their creation time, before final labels arrived. The cohort summary's provenance paths were made project-relative; measurements are unchanged.
