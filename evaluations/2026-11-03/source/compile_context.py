#!/usr/bin/env python3
"""Validate real saved AI outputs, select fourth-arm list and build neutral union.

No predictions or human labels are produced by this script. Output files supplied
by --outputs must be actual assessor responses, not synthetic answers.
"""
import argparse
import collections
import csv
import datetime as dt
import json
from pathlib import Path
from prepare_context import digest, write_json

FIELDS = {"case_id", "query_id", "record_id", "same_specific_issue", "reported_experience", "evidence_quote", "rationale", "required_context_missing"}
EXPERIENCE = {"ongoing", "improved_or_absent", "historical", "mixed", "unclear", "not_applicable"}


def compile_outputs(args):
    prepared = args.prepared
    manifest = json.loads((prepared / "manifest.json").read_text())
    for name, expected in manifest["private_file_sha256"].items():
        if digest(prepared / name) != expected:
            raise ValueError("Prepared private input changed: " + name)
    if digest(prepared / "context-assessor-prompt.txt") != manifest["prompt_sha256"]:
        raise ValueError("Prompt changed after preparation")
    if digest(prepared / "context-output.schema.json") != manifest["schema_sha256"]:
        raise ValueError("Schema changed after preparation")
    for b in manifest["batches"]:
        if digest(b["path"]) != b["sha256"]:
            raise ValueError("Evidence batch changed")
    evidence = json.loads((prepared / "private-evidence.json").read_text())
    mapping = json.loads((prepared / "private-selection-map.json").read_text())
    baseline = json.loads((prepared / "private-baseline-lists.json").read_text())
    required = {r["case_id"] for r in mapping}
    provenance = json.loads(args.provenance.read_text())
    required_provenance = {"actual_model", "runtime", "started_at_utc", "completed_at_utc", "prompt_sha256", "outputs"}
    if not required_provenance <= set(provenance):
        raise ValueError("Missing actual model execution provenance")
    if provenance["prompt_sha256"] != manifest["prompt_sha256"]:
        raise ValueError("Execution prompt does not match frozen prompt")
    if not isinstance(provenance["actual_model"], str) or not provenance["actual_model"].strip():
        raise ValueError("Record actual model; do not invent exact snapshot if runtime does not expose it")
    if provenance["actual_model"] != manifest["actual_context_model"]:
        raise ValueError("Actual assessor model differs from frozen design")
    receipts = {str(Path(r["path"]).resolve()): r for r in provenance["outputs"]}
    labels = {}
    for path in args.outputs:
        rec = receipts.get(str(path.resolve()))
        if not rec or rec.get("sha256") != digest(path) or not rec.get("execution_reference"):
            raise ValueError("Missing/changed execution receipt for " + str(path))
        rows = json.loads(path.read_text())
        if not isinstance(rows, list):
            raise ValueError("Output must be a JSON array")
        for row in rows:
            if not isinstance(row, dict) or set(row) != FIELDS:
                raise ValueError("Unexpected fields in output row")
            cid = row["case_id"]
            if cid not in required or cid in labels:
                raise ValueError("Unknown or repeated case_id " + str(cid))
            e = evidence[cid]
            if row["query_id"] != e["query_id"] or row["record_id"] != e["record_id"]:
                raise ValueError("ID mismatch " + cid)
            same, exp = row["same_specific_issue"], row["reported_experience"]
            if same not in {"yes", "no", "uncertain"} or exp not in EXPERIENCE:
                raise ValueError("Invalid label " + cid)
            if (same == "no") != (exp == "not_applicable"):
                raise ValueError("No/not_applicable consistency violated " + cid)
            quote = row["evidence_quote"]
            if quote is not None and (not isinstance(quote, str) or not quote.strip() or quote not in e["review_text"]):
                raise ValueError("Evidence quote not an exact nonempty substring " + cid)
            if same != "no" and quote is None:
                raise ValueError("Relevant/uncertain prediction needs exact evidence " + cid)
            missing = row["required_context_missing"]
            if same == "uncertain":
                if not isinstance(missing, str) or not missing.strip():
                    raise ValueError("Uncertain prediction must explain missing context " + cid)
            elif missing is not None:
                raise ValueError("Missing context must be null unless uncertain " + cid)
            if not isinstance(row["rationale"], str) or not row["rationale"].strip():
                raise ValueError("Missing rationale " + cid)
            labels[cid] = row
    if set(labels) != required:
        raise ValueError(f"Incomplete machine predictions: {len(labels)}/{len(required)}")
    per_query = collections.defaultdict(list)
    for row in mapping:
        per_query[row["query_id"]].append(row)
    selected = []
    qstatus = []
    for qid in sorted(per_query):
        ordered = sorted(per_query[qid], key=lambda r: r["rrf_rank"])
        accepted = [r for r in ordered if labels[r["case_id"]]["same_specific_issue"] == "yes" and labels[r["case_id"]]["reported_experience"] == "ongoing"][:10]
        for rank, row in enumerate(accepted, 1):
            selected.append(dict(query_id=qid, appid=row["appid"], method="rrf_context", record_id=row["record_id"], rank=rank, case_id=row["case_id"]))
        qstatus.append(dict(query_id=qid, scanned=len(ordered), returned=len(accepted), empty_display_slots=10-len(accepted), full_abstention=not accepted))
    lists = baseline + selected
    union_ids = {r["case_id"] for r in lists}
    union = [evidence[cid] for cid in sorted(union_ids)]
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "neutral-display-union.json", union)
    write_json(args.output / "private-all-method-lists.json", lists)
    write_json(args.output / "private-machine-predictions.json", [labels[cid] for cid in sorted(labels)])
    write_json(args.output / "private-context-status.json", qstatus)
    with (args.output / "private-all-method-lists.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["query_id", "appid", "method", "record_id", "rank", "case_id"])
        writer.writeheader()
        writer.writerows(lists)
    report = dict(compiled_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                  status="validated_machine_outputs_human_reference_pending", query_count=len(per_query),
                  machine_predictions=len(labels), context_display_positions=len(selected),
                  all_method_display_positions=len(lists), distinct_human_pairs=len(union),
                  two_independent_first_ratings_required=2*len(union),
                  input_sha256={str(p.resolve()): digest(p) for p in [prepared / "manifest.json", args.provenance, *args.outputs]},
                  output_sha256={p.name: digest(p) for p in args.output.iterdir() if p.is_file()},
                  script_sha256=digest(__file__),
                  note="Exact IDs/quotes are mechanical validity, not proof of label correctness. No human judgments exist in these outputs.")
    write_json(args.output / "validation.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", required=True, type=Path)
    parser.add_argument("--outputs", required=True, type=Path, nargs="+")
    parser.add_argument("--provenance", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    print(json.dumps(compile_outputs(parser.parse_args()), indent=2))
