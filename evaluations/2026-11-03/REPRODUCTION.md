# Reproduce the saved analysis

From the repository root, run with Python 3.12 or newer:

```sh
python3 evaluations/2026-11-03/reproduce_analysis.py --output replay.json
```

Use a new output filename each time. No packages, credentials, network access or model downloads are required.

The command verifies 23 files against [source-manifest.json](source-manifest.json), joins 1,215 reference pairs to 1,803 returned method positions, and checks all 60 queries. It reproduces method and per-query counts, the primary sign-flip test, the paired-game bootstrap histogram, shared-pair uncertainty bounds, and the known-secondhand sensitivity using the saved analysis functions.

This checks arithmetic conditional on the saved labels. It does not recheck the labels, acquire reviews or rerun retrieval and context assessment.

The [source directory](source/) retains frozen scripts and their original relative path metadata. Several scripts depend on files or environments outside this subset. Original path and hash fields identify the research inputs; they are not additional files promised by this repository. Full source archives, returned review workbooks and model runtimes are excluded.
