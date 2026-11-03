#!/usr/bin/env python3
"""Prepare rank-hidden machine evidence and a private deterministic selection map.

This does NOT make AI calls, generate predictions, or generate human labels.
It consumes the existing retrieval/run.py queries/candidates/all_scores schema.
"""
import argparse
import collections
import csv
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def case_id(qid, rid):
    h = hashlib.sha256((qid + "\x00" + rid).encode()).hexdigest()[:20]
    return "E60-" + h


def prepare(args):
    protocol = json.loads(args.protocol.read_text())
    if protocol.get("status") != "frozen_before_new_rankings":
        raise ValueError("Protocol must be frozen before rankings; retain its timestamp/receipt")
    for filename, key in [("context-assessor-prompt.txt", "prompt_sha256"), ("context-output.schema.json", "schema_sha256")]:
        if digest(HERE / filename) != protocol["context_arm"][key]:
            raise ValueError("Prompt/schema differs from frozen protocol: " + filename)
    queries = json.loads(args.queries.read_text())
    queries = queries["queries"] if isinstance(queries, dict) else queries
    qmap = {str(q["query_id"]): q for q in queries}
    if len(qmap) != len(queries):
        raise ValueError("Duplicate query_id")
    if len({str(q["appid"]) for q in queries}) != len(queries):
        raise ValueError("One query per independent game required")
    if not 1 <= len(queries) <= protocol["sampling"]["target_games"]:
        raise ValueError("Cohort outside frozen target range")
    excluded = set(map(str, protocol["sampling"]["development_game_exclusions"]))
    excluded.update(map(str, protocol["sampling"].get("excluded_non_game_appids", [])))
    if {str(q["appid"]) for q in queries} & excluded:
        raise ValueError("Development game entered new evaluation")
    candidates = {}
    pools = collections.defaultdict(set)
    pool_texts = collections.defaultdict(set)
    for line in args.candidates.open():
        c = json.loads(line)
        qid, rid = str(c["query_id"]), str(c["record_id"])
        if qid not in qmap or str(c["appid"]) != str(qmap[qid]["appid"]):
            raise ValueError("Unknown query or wrong appid")
        if (qid, rid) in candidates or not isinstance(c["text"], str) or not c["text"].strip():
            raise ValueError("Duplicate ID or blank text")
        if c["text"] in pool_texts[qid]:
            raise ValueError("Duplicate exact full text within game")
        pool_texts[qid].add(c["text"])
        candidates[qid, rid] = c
        pools[qid].add(rid)
    minimum = protocol["sampling"]["minimum_eligible_reviews"]
    if any(len(pools[qid]) < minimum for qid in qmap):
        raise ValueError("One or more pools fail preregistered minimum")
    methods = ("bm25", "semantic", "rrf")
    ranks = collections.defaultdict(list)
    opener = gzip.open if str(args.scores).endswith(".gz") else open
    with opener(args.scores, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            qid, rid, method = row["query_id"], row["record_id"], row["method"]
            if method not in methods:
                continue
            if (qid, rid) not in candidates or str(row["appid"]) != str(qmap[qid]["appid"]):
                raise ValueError("Scores reference unknown candidate or wrong appid")
            ranks[qid, method].append((int(row["rank"]), rid))
    for qid in qmap:
        for method in methods:
            ordered = sorted(ranks[qid, method])
            if [r for r, _ in ordered] != list(range(1, len(pools[qid]) + 1)):
                raise ValueError(f"Noncontiguous/full ranks {qid}/{method}")
            if {rid for _, rid in ordered} != pools[qid] or len(ordered) != len(pools[qid]):
                raise ValueError(f"Ranking universe differs {qid}/{method}")
            ranks[qid, method] = ordered
    evidence = {}
    mapping = []
    baseline_rows = []
    scan = protocol["context_arm"]["rrf_prefix"]
    for qid in sorted(qmap):
        q = qmap[qid]
        for method in methods:
            for rank, rid in ranks[qid, method][:10]:
                baseline_rows.append(dict(query_id=qid, appid=str(q["appid"]), method=method,
                                          record_id=rid, rank=rank, case_id=case_id(qid, rid)))
        # Include baseline-only rows in private evidence so the output union can be reconstructed.
        display_ids = {r["record_id"] for r in baseline_rows if r["query_id"] == qid}
        prefix_ids = [rid for _, rid in ranks[qid, "rrf"][:scan]]
        for rid in display_ids | set(prefix_ids):
            c = candidates[qid, rid]
            cid = case_id(qid, rid)
            if cid in evidence:
                raise ValueError("Case hash collision")
            evidence[cid] = dict(case_id=cid, query_id=qid, record_id=rid, appid=str(q["appid"]),
                                 game=q.get("game", ""), official_fix_quote=q["quote"],
                                 source_url=q.get("source_url"), published_at=q.get("published_at"),
                                 review_date=c.get("post_date"), review_text=c["text"],
                                 temporal_limit="Creation/publication dates are proxies; deployment, review edits, and patch exposure are unknown")
            # Keep public archive attribution for the coordinator's allowlisted reviewer adapter.
            for field in ("source_member", "source_row_1based", "source_csv_sha256"):
                evidence[cid][field] = c.get(field)
            evidence[cid]["review_text_sha256"] = hashlib.sha256(c["text"].encode()).hexdigest()
            evidence[cid]["claim_text_sha256"] = hashlib.sha256(q["quote"].encode()).hexdigest()
        for rank, rid in ranks[qid, "rrf"][:scan]:
            mapping.append(dict(case_id=case_id(qid, rid), query_id=qid, record_id=rid,
                                appid=str(q["appid"]), rrf_rank=rank))
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    (output / "batches").mkdir()
    # Hash order conceals retrieval order; this is rank-hidden AI input, not a claim of human blinding.
    ordered = sorted(mapping, key=lambda r: hashlib.sha256(("E60-context-order|" + r["case_id"]).encode()).hexdigest())
    batch_manifest = []
    for start in range(0, len(ordered), args.batch_size):
        items = [evidence[r["case_id"]] for r in ordered[start:start + args.batch_size]]
        path = output / "batches" / f"batch-{start // args.batch_size + 1:04d}.json"
        write_json(path, items)
        batch_manifest.append(dict(path=str(path.resolve()), sha256=digest(path),
                                   case_ids=[r["case_id"] for r in items], count=len(items)))
    write_json(output / "private-selection-map.json", mapping)
    write_json(output / "private-baseline-lists.json", baseline_rows)
    write_json(output / "private-evidence.json", evidence)
    (output / "context-assessor-prompt.txt").write_bytes((HERE / "context-assessor-prompt.txt").read_bytes())
    (output / "context-output.schema.json").write_bytes((HERE / "context-output.schema.json").read_bytes())
    manifest = dict(created_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                    status="prepared_inputs_only_no_predictions_no_human_labels", query_count=len(queries),
                    target_games=protocol["sampling"]["target_games"],
                    cohort_status="at_target" if len(queries) == protocol["sampling"]["target_games"] else "below_target",
                    machine_judgment_count=len(mapping), baseline_positions=len(baseline_rows), batches=batch_manifest,
                    input_sha256={str(p.resolve()): digest(p) for p in (args.protocol, args.queries, args.candidates, args.scores)},
                    prompt_sha256=digest(output / "context-assessor-prompt.txt"),
                    schema_sha256=digest(output / "context-output.schema.json"),
                    actual_context_model=protocol["context_arm"]["actual_model"],
                    private_file_sha256={name: digest(output / name) for name in ["private-selection-map.json", "private-baseline-lists.json", "private-evidence.json"]},
                    script_sha256=digest(__file__),
                    note="Keep predictions, private selection maps, ranks and scores out of human packets")
    write_json(output / "manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--scores", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--batch-size", type=int, default=30)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("batch-size must be positive")
    print(json.dumps(prepare(args), indent=2))
