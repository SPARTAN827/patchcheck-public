#!/usr/bin/env python3
"""Conditional arithmetic on preserved submitted codes; not human-reference validation.

Run from any directory with Python 3.12+. Outputs stay beside this script.
Only input hashes and arithmetic/join invariants are checked; the completed intake
and 306-pair source/semantic QA are NOT repeated. No label is changed.
The frozen paired_inference.py has a human-reference-only call contract, so this
separate implementation applies the same formulas without calling that function.
NumPy was unavailable in this runtime. The standard-library bootstrap therefore
uses Python random.Random (MT19937), not NumPy PCG64; both implement the frozen
100,000 whole-game resamples and seed 20261103. The RNG is an implementation
choice made for this analysis, not a new claim about the frozen protocol.
Exact draws are recorded here.
"""
from collections import Counter, defaultdict
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import platform
import random
import sys

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
E60 = "tasks/evaluation60-2026-11-02/"
RESULTS = "tasks/evaluation60-results-2026-11-03/"
INPUTS = {
    RESULTS + "resolution306-2026-11-03/submitted-code-projection-1215.csv": "99b429328384d5609450a7e113137c4a412e5d811725d93022a46bba16a7cc76",
    E60 + "protocol/protocol-v3.frozen.json": "ad3afdc9fc695dacf97e833357ee6c1ed8491d3d54f11ab3174f46895c0c214c",
    E60 + "compiled/private-all-method-lists.json": "775a4564a1c4f064677e8977e45de60321272b706891bc6b3a57bc5146ea2daf",
    E60 + "prepared/queries.json": "9e80c048164aea95a8d3d478a8a0b740b1ea485ad2d88a1e212fb254585d517b",
    RESULTS + "revision-ac-2026-11-03/analysis/duplicate-check.json": "d553d7b62ab599afce4ed74a393740e3d8a1d6c804b64004a22a399b69f6f7ce",
    E60 + "protocol/paired_inference.py": "843ec1e4ce49ed6f8bb02b0dea1426b4a83f144a01b56bd300c543711906caec",
}
METHODS = ("bm25", "semantic", "rrf", "rrf_context")
SCENARIOS = ("experience_compatible", "historical_relaxed", "all_uncertain_maximum_relaxation")
SECONDHAND = "E60-7d1aa61d8cc4f8752b95"
ROW185 = "E60-50f55481a4f270c5f8c0"
ROW210 = "E60-181549f930ba9499374a"
STATUS = "conditional_exploratory_submitted_codes_not_independent_human_gold"
FILES = []


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_inputs():
    actual = {p: digest(ROOT / p) for p in INPUTS}
    if actual != INPUTS:
        raise ValueError("Frozen input changed; do not silently regenerate with a new label layer")
    return actual


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    FILES.append(name)


def write_csv(name, rows):
    assert rows
    with (OUT / name).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    FILES.append(name)


def read_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def target(row):
    return row["same_issue"] == "yes" and row["experience"] == "ongoing"


def non_target(row):
    return row["same_issue"] == "no" or (
        row["same_issue"] == "yes" and row["experience"] in {"improved_or_absent", "historical"})


def potential(row, scenario):
    """Possible additional targets only; established submitted targets excluded."""
    if target(row) or row["same_issue"] == "no":
        return False
    if scenario == "all_uncertain_maximum_relaxation":
        return row["same_issue"] == "uncertain" or row["experience"] in {"mixed", "unclear"}
    if scenario == "experience_compatible":
        return row["same_issue"] in {"yes", "uncertain"} and row["experience"] in {"ongoing", "mixed", "unclear"}
    if scenario == "historical_relaxed":
        return row["same_issue"] in {"yes", "uncertain"} and row["experience"] in {"ongoing", "mixed", "unclear", "historical"}
    raise ValueError(scenario)


def counts(ids, labels):
    selected = [labels[x] for x in ids]
    t = sum(map(target, selected))
    nt = sum(map(non_target, selected))
    result = {
        "returned": len(selected),
        "submitted_target_yes_ongoing": t,
        "submitted_non_target": nt,
        "unresolved": len(selected) - t - nt,
        "same_issue_yes_only": sum(x["same_issue"] == "yes" for x in selected),
        "same_issue_uncertain": sum(x["same_issue"] == "uncertain" for x in selected),
        "potential_target_experience_compatible": sum(potential(x, "experience_compatible") for x in selected),
        "potential_target_historical_relaxed": sum(potential(x, "historical_relaxed") for x in selected),
        "potential_target_all_uncertain_maximum_relaxation": sum(potential(x, "all_uncertain_maximum_relaxation") for x in selected),
    }
    assert result["submitted_target_yes_ongoing"] + result["submitted_non_target"] + result["unresolved"] == len(selected)
    return result


def linear_quantile(sorted_values, p):
    position = (len(sorted_values) - 1) * p
    lo = math.floor(position)
    hi = math.ceil(position)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (position - lo)


def paired_inference(count_differences):
    """Frozen formula, but only a conditional mathematical calculation here."""
    d = count_differences
    assert 2 <= len(d) <= 60 and all(isinstance(x, int) and -10 <= x <= 10 for x in d)
    n = len(d)
    nonzero = [x for x in d if x]
    m = len(nonzero)
    observed = abs(sum(d))
    if m == 0:
        draws = extreme = 1
        p_value = 1.0
        method = "all_zero"
    elif m <= 20:
        draws = 2 ** m
        extreme = sum(abs(sum(s * x for s, x in zip(signs, nonzero))) >= observed
                      for signs in itertools.product((-1, 1), repeat=m))
        p_value = extreme / draws
        method = "exhaustive_nonzero_signs"
    else:
        draws = 100000
        sign_rng = random.Random(20261102)
        extreme = sum(abs(sum((2 * sign_rng.randrange(2) - 1) * x for x in nonzero)) >= observed
                      for _ in range(draws))
        p_value = (1 + extreme) / (1 + draws)
        method = "monte_carlo_sign_flip_plus_one"
    rng = random.Random(20261103)
    bootstrap_sums = Counter(sum(d[rng.randrange(n)] for _ in range(n)) for _ in range(100000))
    boot = sorted(value / (10 * n) for value, frequency in bootstrap_sums.items() for _ in range(frequency))
    mean = sum(d) / (10 * n)
    degenerate = len(set(d)) == 1
    radius = math.sqrt(2 * math.log(40) / n)
    return {
        "status": STATUS,
        "reference_procedure_confirmed": False,
        "formal_human_reference_inference": "NOT_ESTABLISHED",
        "game_query_n": n,
        "nonzero_difference_n": m,
        "mean_yield_difference": mean,
        "percentage_point_difference": 100 * mean,
        "extra_submitted_target_items_per10": 10 * mean,
        "paired_count_differences": d,
        "win_tie_loss": {"context_higher": sum(x > 0 for x in d), "tie": d.count(0), "context_lower": sum(x < 0 for x in d)},
        "two_sided_sign_flip": {"p_value": p_value, "method": method, "sign_vectors": draws, "extreme_vectors": extreme, "seed_if_monte_carlo": 20261102 if m > 20 else None},
        "percentile_game_bootstrap_95": {
            "interval": [linear_quantile(boot, 0.025), linear_quantile(boot, 0.975)],
            "resamples": 100000, "seed": 20261103, "rng": "Python random.Random MT19937, randrange(n) for each of n game indices per resample",
            "quantile": "linear interpolation (type 7), matching the existing helper's NumPy quantile(method=linear); protocol itself specifies percentile bootstrap",
            "degenerate_empirical_interval": degenerate,
            "sum_count_difference_histogram": dict(sorted(bootstrap_sums.items())),
        },
        "bounded_mean_95_if_degenerate": [max(-1, mean - radius), min(1, mean + radius)] if degenerate else None,
        "assumptions_and_limits": [
            "Conditional on supplied codes; this calculation does not verify authorship, personal confirmation, reference independence or AI assistance.",
            "One equally weighted game/query per paired difference; all 60 enter n including zero differences.",
            "Sign exchangeability/symmetry under the null is required; method assignment was not randomized.",
            "Paired-game bootstrap requires defensibly independent game units; convenience frame is not a probability sample of all games or players.",
            "Only one nonzero game makes the discrete percentile interval unstable as a population-uncertainty summary; labels are held fixed, not resampled.",
            "This is not an equivalence test, superiority finding, repair-effect estimate, recall estimate or whole-corpus prevalence estimate.",
            "No secondary inferential contrasts or secondary p-values are calculated.",
        ],
    }


def bound_rows(query_order, lists, labels, scenario, forced_possible=frozenset()):
    rows = []
    for q in query_order:
        c, r = set(lists[q, "rrf_context"]), set(lists[q, "rrf"])
        c_only, r_only = c - r, r - c
        lower = lambda i: int(target(labels[i]))
        upper = lambda i: int(target(labels[i]) or potential(labels[i], scenario) or i in forced_possible)
        lower_difference = sum(lower(i) for i in c_only) - sum(upper(i) for i in r_only)
        upper_difference = sum(upper(i) for i in c_only) - sum(lower(i) for i in r_only)
        rows.append({
            "scenario": scenario, "query_id": q, "shared_pair_count_cancelled": len(c & r),
            "context_only_pairs": len(c_only), "rrf_only_pairs": len(r_only),
            "context_only_possible_additional_targets": sum(upper(i) - lower(i) for i in c_only),
            "rrf_only_possible_additional_targets": sum(upper(i) - lower(i) for i in r_only),
            "difference_count_lower": lower_difference, "difference_count_upper": upper_difference,
            "difference_yield_lower": lower_difference / 10, "difference_yield_upper": upper_difference / 10,
        })
    return rows


def summarize_bound(rows):
    lo = sum(x["difference_count_lower"] for x in rows)
    hi = sum(x["difference_count_upper"] for x in rows)
    denominator = len(rows) * 10
    return {"count_difference_lower": lo, "count_difference_upper": hi,
            "fixed_display_slots_per_method": denominator,
            "mean_difference_lower": lo / denominator, "mean_difference_upper": hi / denominator,
            "percentage_point_lower": 100 * lo / denominator, "percentage_point_upper": 100 * hi / denominator,
            "shared_pair_count_cancelled": sum(x["shared_pair_count_cancelled"] for x in rows),
            "not_confidence_interval": True}


def main():
    verify_inputs()
    with (ROOT / (RESULTS + "resolution306-2026-11-03/submitted-code-projection-1215.csv")).open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    labels = {x["pair_id"]: x for x in rows}
    queries = read_json(E60 + "prepared/queries.json")
    query_order = [x["query_id"] for x in queries]
    query_info = {x["query_id"]: x for x in queries}
    rankings = read_json(E60 + "compiled/private-all-method-lists.json")
    protocol = read_json(E60 + "protocol/protocol-v3.frozen.json")
    duplicates = read_json(RESULTS + "revision-ac-2026-11-03/analysis/duplicate-check.json")
    assert len(rows) == len(labels) == 1215 and len(queries) == len(set(query_order)) == 60
    assert len({x["appid"] for x in queries}) == 60
    assert protocol["primary_analysis"]["contrast"] == "rrf_context minus rrf"
    ranked = defaultdict(list)
    for row in rankings:
        assert row["case_id"] in labels and labels[row["case_id"]]["query_id"] == row["query_id"]
        assert row["method"] in METHODS and row["appid"] == query_info[row["query_id"]]["appid"]
        ranked[row["query_id"], row["method"]].append(row)
    lists = {}
    for q in query_order:
        for method in METHODS:
            values = sorted(ranked[q, method], key=lambda x: x["rank"])
            assert [x["rank"] for x in values] == list(range(1, len(values) + 1))
            ids = [x["case_id"] for x in values]
            assert len(ids) == len(set(ids)) <= 10
            assert len(ids) == 10 or method == "rrf_context"
            lists[q, method] = ids
    assert set(labels) == {x for ids in lists.values() for x in ids}
    per_query = []
    by_query_method = {}
    for q in query_order:
        for method in METHODS:
            item = {"status": STATUS, "query_id": q, "game": query_info[q]["game"], "method": method,
                    "fixed_display_slots": 10, **counts(lists[q, method], labels)}
            item["empty_slots"] = 10 - item["returned"]
            item["submitted_target_yield_at10"] = item["submitted_target_yes_ongoing"] / 10
            item["same_issue_only_yield_at10"] = item["same_issue_yes_only"] / 10
            item["submitted_target_fraction_returned"] = item["submitted_target_yes_ongoing"] / item["returned"] if item["returned"] else None
            for scenario in SCENARIOS:
                item["possible_target_upper_count_" + scenario] = item["submitted_target_yes_ongoing"] + item["potential_target_" + scenario]
                item["possible_target_upper_yield_at10_" + scenario] = item["possible_target_upper_count_" + scenario] / 10
            per_query.append(item)
            by_query_method[q, method] = item
    write_csv("per-query-method.csv", per_query)
    method_rows = []
    count_keys = list(counts([], labels))
    for method in METHODS:
        selected = [by_query_method[q, method] for q in query_order]
        summary = {"status": STATUS, "method": method, "queries": 60, "fixed_display_slots": 600,
                   **{key: sum(x[key] for x in selected) for key in count_keys}}
        summary["empty_slots"] = 600 - summary["returned"]
        summary["full_abstention_queries"] = sum(x["returned"] == 0 for x in selected)
        summary["full_abstention_fraction"] = summary["full_abstention_queries"] / 60
        summary["submitted_target_yield_at10"] = summary["submitted_target_yes_ongoing"] / 600
        summary["same_issue_only_yield_at10"] = summary["same_issue_yes_only"] / 600
        summary["submitted_target_fraction_returned"] = summary["submitted_target_yes_ongoing"] / summary["returned"] if summary["returned"] else None
        for scenario in SCENARIOS:
            summary["possible_target_upper_count_" + scenario] = summary["submitted_target_yes_ongoing"] + summary["potential_target_" + scenario]
            summary["possible_target_upper_yield_at10_" + scenario] = summary["possible_target_upper_count_" + scenario] / 600
        method_rows.append(summary)
    write_csv("method-summary.csv", method_rows)
    primary_rows = []
    for q in query_order:
        c, r = [by_query_method[q, method]["submitted_target_yes_ongoing"] for method in ("rrf_context", "rrf")]
        primary_rows.append({"status": STATUS, "query_id": q, "game": query_info[q]["game"],
                             "context_submitted_targets": c, "rrf_submitted_targets": r,
                             "count_difference": c - r, "yield_difference": (c - r) / 10})
    write_csv("primary-query-differences.csv", primary_rows)
    inference = paired_inference([x["count_difference"] for x in primary_rows])
    write_json("primary-conditional-inference.json", inference)
    bounds = []
    bounds_summary = {}
    for scenario in SCENARIOS:
        scenario_rows = bound_rows(query_order, lists, labels, scenario)
        bounds += scenario_rows
        bounds_summary[scenario] = summarize_bound(scenario_rows)
    write_csv("shared-pair-uncertainty-bounds.csv", bounds)
    matched = []
    for q in query_order:
        k = len(lists[q, "rrf_context"])
        item = {"status": STATUS, "query_id": q, "game": query_info[q]["game"], "k_context_returned": k,
                "returned_fractions_defined": bool(k)}
        for side, ids in (("context", lists[q, "rrf_context"]), ("rrf_prefix", lists[q, "rrf"][:k])):
            c = counts(ids, labels)
            for key in ("submitted_target_yes_ongoing", "submitted_non_target", "unresolved", "potential_target_experience_compatible"):
                item[side + "_" + key] = c[key]
            item[side + "_submitted_target_fraction"] = c["submitted_target_yes_ongoing"] / k if k else None
            item[side + "_submitted_non_target_fraction"] = c["submitted_non_target"] / k if k else None
        matched.append(item)
    write_csv("matched-k-query-counts.csv", matched)
    matched_summary = {
        "status": STATUS, "comparison": "Context list vs first k_q RRF entries, where k_q is context return count",
        "queries": 60, "nonempty_queries": sum(x["k_context_returned"] > 0 for x in matched),
        "zero_k_queries_undefined_not_perfect": sum(x["k_context_returned"] == 0 for x in matched),
        "matched_returned_per_side": sum(x["k_context_returned"] for x in matched),
        "counts": {key: sum(x[key] for x in matched) for key in matched[0] if key.startswith(("context_", "rrf_prefix_")) and not key.endswith("fraction")},
        "nonempty_query_rows": [x for x in matched if x["k_context_returned"]],
        "interpretation": "Submitted targets, submitted non-targets and unresolved assessments are separate. Uncertain/historical remains unresolved for same issue but cannot be ongoing if its submitted experience is held fixed. Rankers select texts; their non-target retrievals are not model assertions of ongoing problems. No secondary p-value or superiority claim.",
    }
    write_json("matched-k-summary.json", matched_summary)
    secondhand_methods = []
    for method in METHODS:
        occurrences = sum(SECONDHAND in lists[q, method] for q in query_order)
        base = next(x for x in method_rows if x["method"] == method)
        remaining = base["submitted_target_yes_ongoing"] - occurrences
        secondhand_methods.append({"method": method, "known_secondhand_target_occurrences_excluded": occurrences,
                                   "target_count_as_submitted": base["submitted_target_yes_ongoing"],
                                   "target_count_excluding_known_secondhand": remaining,
                                   "fixed_slots_unchanged": 600, "returned_unchanged": base["returned"],
                                   "yield_at10_excluding_known_secondhand": remaining / 600,
                                   "label_and_same_issue_yes_count_unchanged": True})
    row185_membership = [x for x in rankings if x["case_id"] == ROW185]
    hypothetical_bounds = {scenario: summarize_bound(bound_rows(query_order, lists, labels, scenario, frozenset({ROW185})))
                           for scenario in bounds_summary}
    write_json("sensitivity-summary.json", {
        "status": STATUS,
        "known_secondhand_exclusion": {"pair_id": SECONDHAND, "submitted_label": [labels[SECONDHAND]["same_issue"], labels[SECONDHAND]["experience"]],
                                      "rule": "Remove only this known secondhand ID from target numerator; preserve record, label, rank, returned denominator and empty-slot convention. This is not a verified all-firsthand subset.",
                                      "methods": secondhand_methods, "primary_context_minus_rrf_unchanged": True},
        "row185_hypothetical_not_actual_relabel": {
            "pair_id": ROW185, "query_id": labels[ROW185]["query_id"], "actual_label": [labels[ROW185]["same_issue"], labels[ROW185]["experience"]],
            "membership": row185_membership,
            "scenario": "Treat this disputed no/not_applicable as unresolved potentially-target [0,1] solely for sensitivity; do not infer a submitted experience correction or modify source codes.",
            "target_numerators_and_primary_point_test_bootstrap_unchanged": True,
            "uncertain_counts_would_increase_by_one": ["bm25", "semantic", "rrf"],
            "unmatched_rrf_possible_target_reduces_lower_contrast_bound_by": 1 / 600,
            "hypothetical_bounds": hypothetical_bounds,
            "leave_query_out": "Not run: retaining all games and widening the disputed-row bound avoids post-result deletion of Q034.",
        },
        "row210_rationale_only": {"pair_id": ROW210, "submitted_label": [labels[ROW210]["same_issue"], labels[ROW210]["experience"]],
                                  "membership": [x for x in rankings if x["case_id"] == ROW210],
                                  "effect_of_rationale_only_correction": "No numerical effect; uncertainty and all label codes retained."},
    })
    write_json("analysis-summary.json", {
        "status": STATUS, "protocol_id": protocol["protocol_id"],
        "reference_procedure_personal_confirmation_and_AI_assistance": "UNKNOWN; no human-gold or independent-reference promotion",
        "formal_human_reference_inference": "NOT_ESTABLISHED; conditional arithmetic only",
        "source_label_layer": "306 submitted final assessments plus 909 prior concordant no/not_applicable pairs, not 1215 newly adjudicated pairs",
        "pairs": len(labels), "queries": len(query_order),
        "unique_pair_same_issue_counts": dict(Counter(x["same_issue"] for x in rows)),
        "unique_pair_experience_counts": dict(Counter(x["experience"] for x in rows)),
        "unique_pair_outcome_categories": counts(list(labels), labels),
        "methods": method_rows, "primary_conditional_calculation": inference,
        "uncertainty_definitions": {
            "submitted_target": "same_issue=yes AND experience=ongoing; includes known secondhand ID in as-submitted analysis",
            "submitted_non_target": "same_issue=no OR same_issue=yes with improved_or_absent/historical; these are submitted determinations, not validated true negatives",
            "unresolved": "Everything else; in this layer every uncertain same-issue response, even historical/improved experience",
            "experience_compatible": "Additional possible targets: same_issue=yes/uncertain AND experience=ongoing/mixed/unclear, excluding already-target rows. This holds submitted historical/improved experience fixed; it does not turn other unresolved rows into known negatives.",
            "historical_relaxed": "Also permits uncertain/historical assessments to be possible ongoing targets, relaxing the temporal categorization; improved_or_absent assessments remain excluded. A wider scenario, not a change to submitted experience codes.",
            "all_uncertain_maximum_relaxation": "All uncertain same-issue rows can be targets, even historical/improved experience; explicitly relaxes those temporal codes. A broader worst-case scenario, not a claim every uncertain item is genuinely eligible.",
            "pair_consistency": "Use one possible binary outcome per unique pair across methods. Common pair IDs cancel before bound optimization; no independently contradictory method-specific outcomes.",
            "scope_of_bounds": "Finite-label-scenario identification bounds, not confidence intervals and not bounds allowing every supplied yes/no decision to be wrong.",
        },
        "shared_pair_uncertainty_bounds": bounds_summary,
        "matched_k": matched_summary,
        "duplicate_check_reused": {"path": RESULTS + "revision-ac-2026-11-03/analysis/duplicate-check.json",
                                   "exact_within_query_duplicate_count_previously_reported": len(duplicates["exact_full_text_duplicates_within_query"]),
                                   "prior_action": duplicates["action"],
                                   "no_recheck_or_removal": True,
                                   "limit": "A within-query duplicate check does not itself establish cross-game independence; inferential assumptions remain conditional."},
        "verification_scope": "Hash checks and arithmetic/schema/join invariants only; no repeated full intake/source/semantic QA and no new retrieval or label judgments.",
        "runtime": {"python": platform.python_version(), "implementation": platform.python_implementation(),
                    "dependencies": "Python standard library; system Python had no NumPy; no package installed", "platform": sys.platform},
        "bootstrap_implementation_note": "Matches protocol n, B, seed and paired-game resampling rule; uses the existing helper's linear type-7 quantile. Protocol freezes B/seed/game-unit but does not name an RNG. Python MT19937 is an implementation choice made now and differs from the existing reference function's NumPy PCG64 stream. Do not claim identical resample vectors to that implementation.",
    })
    verify_inputs()
    write_json("input-manifest.json", {"status": STATUS, "sha256_before_and_after_match": INPUTS,
                                       "inputs_unchanged": True, "script_sha256": digest(Path(__file__)),
                                       "outputs_sha256": {name: digest(OUT / name) for name in FILES}})
    print(json.dumps({"status": STATUS, "methods": [{k: x[k] for k in ("method", "returned", "submitted_target_yes_ongoing", "submitted_non_target", "unresolved")} for x in method_rows],
                      "primary": inference, "bounds": bounds_summary}, indent=2))


if __name__ == "__main__":
    main()
