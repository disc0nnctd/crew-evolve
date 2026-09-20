"""Loader, scorer, and development runner for the adaptation fixtures.

The runner is intentionally small and deterministic.  A predictor sees only
the raw source tables and the request case.  The known-answer labels are read
by the evaluator after the prediction is scored.  This makes the correction
budget meaningful and prevents labels from leaking through the model input.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable

from crew_evolve.data import FIELDS, infer_mapping, normalize_records


ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "manifest.json"
BUDGETS = (0, 1, 5, 10, 20)
SEEDS = (11, 23, 37, 41, 53)
SPLITS = ("train", "development", "final")
FINAL_UNLOCK_CONFIRM = "CREW-EVOLVE-ADAPTATION-FINAL-V2"


def load_manifest(path: str | Path = MANIFEST) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "adaptation-v2":
        raise ValueError("Unsupported adaptation fixture schema.")
    families = manifest.get("families")
    if not isinstance(families, list) or len(families) != 12:
        raise ValueError("The adaptation manifest must contain exactly 12 families.")
    counts = {split: sum(1 for f in families if f.get("split") == split) for split in SPLITS}
    if counts != {"train": 6, "development": 3, "final": 3}:
        raise ValueError(f"Unexpected split counts: {counts}")
    if manifest.get("budgets") != list(BUDGETS) or manifest.get("seeds") != list(SEEDS):
        raise ValueError("Fixture budgets or scenario seeds changed without a protocol update.")
    return manifest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        text = handle.read()
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError(f"Fixture has no headers: {path}")
    rows = list(reader)
    return list(reader.fieldnames), rows


def load_family(name: str, *, include_labels: bool = False,
                manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load one family, verifying its input fingerprints.

    ``include_labels`` is opt-in for the evaluator.  A model-facing caller can
    use the default and cannot accidentally receive expected answers.
    """

    manifest = manifest or load_manifest()
    entry = next((family for family in manifest["families"] if family["name"] == name), None)
    if entry is None:
        raise KeyError(f"Unknown adaptation family: {name}")
    family_dir = ROOT / "families" / name
    tables = {}
    for filename, fingerprint in entry["files"].items():
        path = family_dir / filename
        if _sha256(path) != fingerprint:
            raise ValueError(f"Fixture fingerprint mismatch: {path}")
        kind = path.stem
        headers, rows = _read_csv(path)
        tables[kind] = {"filename": filename, "headers": headers, "rows": rows}
    result = {"name": name, "split": entry["split"], "seed": entry["seed"],
              "style": entry["style"], "tables": tables}
    if include_labels:
        labels_path = ROOT / entry["labels"]
        if _sha256(labels_path) != entry.get("labels_sha256"):
            raise ValueError(f"Label fingerprint mismatch: {labels_path}")
        result["labels"] = json.loads(labels_path.read_text(encoding="utf-8"))
        if result["labels"].get("family") != name:
            raise ValueError(f"Label family mismatch: {labels_path}")
    return result


def iter_families(split: str, *, include_labels: bool = False,
                  manifest: dict[str, Any] | None = None):
    if split not in SPLITS:
        raise ValueError(f"split must be one of {', '.join(SPLITS)}")
    manifest = manifest or load_manifest()
    for entry in manifest["families"]:
        if entry["split"] == split:
            yield load_family(entry["name"], include_labels=include_labels, manifest=manifest)


def _mutated_tables(family: dict[str, Any], case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tables = copy.deepcopy(family["tables"])
    mutation = case.get("mutation")
    if not mutation:
        return tables
    kind = case["kind"]
    if "changes" in mutation:
        for change in mutation["changes"]:
            tables[change["kind"]]["rows"][change["row"]][change["field"]] = change["value"]
        return tables
    table = tables[kind]
    if "duplicate_row" in mutation:
        table["rows"].append(copy.deepcopy(table["rows"][mutation["duplicate_row"]]))
    else:
        row = table["rows"][mutation["row"]]
        row[mutation["field"]] = mutation["value"]
    return tables


def _apply_explicit(kind: str, table: dict[str, Any], packet: dict[str, Any], known_mapping: dict[str, str]) -> list[dict[str, Any]]:
    from crew_evolve.contracts import apply_contract, validate_contract
    mapping = dict(known_mapping)
    mapping.update(packet.get("mapping", {}))
    contract = validate_contract(kind, table["headers"], mapping,
                                 packet.get("transforms", {}), packet["source_contract"])
    return apply_contract(kind, table["headers"], table["rows"], contract)


def _apply_mapping(kind: str, table: dict[str, Any], mapping: dict[str, str] | None = None):
    return normalize_records(kind, table["headers"], table["rows"],
                             mapping if mapping is not None else infer_mapping(kind, table["headers"], {}))


def _clean(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not key.startswith("_")}


def _relations(records: dict[str, list[dict[str, Any]]]) -> None:
    crew_ids = {row["crew_id"] for row in records["crew"]}
    duty_ids = {row["duty_id"] for row in records["duties"]}
    slots = set()
    for row in records["assignments"]:
        if row["crew_id"] not in crew_ids or row["duty_id"] not in duty_ids:
            raise ValueError("assignment references an unknown record")
        slot = (row["duty_id"], row["role"])
        if slot in slots:
            raise ValueError("contradictory duplicate assignment")
        slots.add(slot)


def _reason_category(exc: Exception) -> str:
    text = str(exc).casefold()
    if "map required" in text or "unknown source" in text or "mapping" in text:
        return "unsupported_schema"
    if "more than one" in text or "contradictory" in text:
        return "contradiction"
    if "duplicate" in text:
        return "duplicate"
    if "missing" in text:
        return "missing"
    if "enum" in text:
        return "unknown_enum"
    if "boolean" in text:
        return "invalid_boolean"
    if "time" in text or "datetime" in text or "timestamp" in text:
        return "bad_datetime"
    return "invalid_data"


def _predict(family: dict[str, Any], method: str, state: dict[str, Any],
             tables: dict[str, dict[str, Any]]):
    records = {}
    failures = []
    reasons = {}
    for kind, table in tables.items():
        try:
            known_mapping = infer_mapping(kind, table["headers"], {})
            if method == "contracts" and kind in state["contracts"]:
                known_mapping.update(state["contracts"][kind]["mapping"])
                records[kind] = _apply_explicit(kind, table, state["contracts"][kind], known_mapping)
            elif method == "aliases" and kind in state["aliases"]:
                known_mapping.update(state["aliases"][kind])
                records[kind] = _apply_mapping(kind, table, known_mapping)
            else:
                records[kind] = _apply_mapping(kind, table, known_mapping)
        except (ValueError, KeyError, TypeError) as exc:
            failures.append(kind)
            reasons[kind] = _reason_category(exc)
    if not failures:
        try:
            _relations(records)
        except (ValueError, KeyError, TypeError) as exc:
            failures.append("assignments")
            reasons["assignments"] = _reason_category(exc)
    return records, failures, reasons


def _apply_selected(kind: str, table: dict[str, Any], method: str,
                    state: dict[str, Any]) -> list[dict[str, Any]]:
    known_mapping = infer_mapping(kind, table["headers"], {})
    if method == "contracts" and kind in state["contracts"]:
        known_mapping.update(state["contracts"][kind]["mapping"])
        return _apply_explicit(kind, table, state["contracts"][kind], known_mapping)
    if method == "aliases" and kind in state["aliases"]:
        known_mapping.update(state["aliases"][kind])
    return _apply_mapping(kind, table, known_mapping)


def _score_case(family: dict[str, Any], labels: dict[str, Any], case: dict[str, Any],
                method: str, state: dict[str, Any]) -> tuple[bool, bool, list[str], bool, str, str]:
    expected_accept = bool(case["expected"]["accepted"])
    tables = _mutated_tables(family, case)
    failures = []
    if case["kind"] == "all":
        records, failures, reasons = _predict(family, method, state, tables)
        expected = case["expected"].get("records", labels["expected"]["valid"]["records"])
        parsed_accept = not failures
        matches = parsed_accept and all(
            [_clean(row) for row in records.get(kind, [])] == expected[kind] for kind in FIELDS
        )
        if matches:
            return expected_accept, expected_accept, failures, True, "accepted", ""
        if parsed_accept:
            failures = [kind for kind in FIELDS
                        if [_clean(row) for row in records.get(kind, [])] != expected[kind]]
            reasons = {kind: "semantic_mismatch" for kind in failures}
            return False, expected_accept, failures, True, "accepted", "semantic_mismatch"
        reason = reasons.get(failures[0], "invalid_data")
        outcome = "abstain" if reason == "unsupported_schema" else "rejected"
        return False, expected_accept, failures, False, outcome, reason
    kind = case["kind"]
    expected_records = case["expected"].get("records", {}).get(kind)
    # A rejection is informative only when the same method/state can first
    # normalize the unmutated control table.  Otherwise it is an unsupported
    # schema abstention, not semantic validation of this fault.
    try:
        _apply_selected(kind, family["tables"][kind], method, state)
    except (ValueError, KeyError, TypeError):
        return False, expected_accept, [kind], False, "abstain", "unassessable_control"
    try:
        actual_records = _apply_selected(kind, tables[kind], method, state)
        actual_accept = expected_records is None or [_clean(row) for row in actual_records] == expected_records
    except (ValueError, KeyError, TypeError) as exc:
        actual_accept = False
        failures = [kind]
        reason = _reason_category(exc)
    else:
        reason = ""
    if actual_accept:
        reason = "accepted"
        outcome = "accepted"
    elif reason == "":
        reason = "semantic_mismatch"
        outcome = "accepted"
    else:
        outcome = "abstain" if reason == "unsupported_schema" else "rejected"
    expected_reason = case["expected"].get("reason")
    correct = actual_accept == expected_accept
    if not expected_accept:
        allowed = case["expected"].get("allowed_reasons", [expected_reason])
        correct = not actual_accept and reason in allowed
    return correct, expected_accept, failures, actual_accept, outcome, reason


def _stream(family: dict[str, Any], seed: int) -> list[dict[str, Any]]:
    cases = copy.deepcopy(family["labels"]["cases"])
    # Keep valid observations chronological.  Scenario seeds alter their
    # future values, rather than merely shuffling identical rows.
    first = next(case for case in cases if case["id"] == "valid")
    replay = [case for case in cases if case["id"] == "valid_replay"]
    future = [case for case in cases if case.get("scenario")]
    faults = [case for case in cases if not case.get("scenario") and case["id"] not in {"valid", "valid_replay"}]
    for case in future:
        index = case["id"].rsplit("_", 1)[-1]
        _replace_value(case, f"Scenario {int(index)}", f"Scenario {seed}-{int(index)}")
    return [first, *replay, *future, *faults]


def _replace_value(value: Any, old: str, new: str) -> Any:
    if isinstance(value, dict):
        for key in list(value):
            value[key] = _replace_value(value[key], old, new)
        return value
    if isinstance(value, list):
        return [_replace_value(item, old, new) for item in value]
    return new if value == old else value


def evaluate_family(family: dict[str, Any], method: str, budget: int, seed: int) -> dict[str, Any]:
    labels = family["labels"]
    correction_used = 0
    state = {"contracts": {}, "aliases": {}}
    rows = []
    for case in _stream(family, seed):
        correct, expected_accept, failures, actual_accept, outcome, reason = _score_case(
            family, labels, case, method, state)
        # Feedback is revealed only after this score.  A packet covers one
        # table, so both baselines spend the same correction budget.  Aliases
        # receive the mapping only; they cannot silently gain polarity,
        # enum, or datetime semantics from a correction.
        feedback = None
        if (expected_accept and not correct and correction_used < budget and failures):
            kind = next((kind for kind in FIELDS if kind in failures), failures[0])
            known = set(infer_mapping(kind, family["tables"][kind]["headers"], {}))
            known |= set(state["aliases"].get(kind, {})) | set(state["contracts"].get(kind, {}).get("mapping", {}))
            source = next((source for source in labels["mapping"][kind] if source not in known), None)
            if source is None and method == "contracts":
                source = next((source for source in labels["transforms"].get(kind, {})
                               if source not in state["contracts"].get(kind, {}).get("transforms", {})), None)
            if source is not None:
                packet_mapping = {source: labels["mapping"][kind][source]}
                state["aliases"].setdefault(kind, {}).update(packet_mapping)
                if method == "contracts":
                    state["contracts"].setdefault(kind, {"mapping": {}, "transforms": {},
                                                           "source_contract": labels["source_contract"]})
                    state["contracts"][kind]["mapping"].update(packet_mapping)
                    if source in labels["transforms"].get(kind, {}):
                        state["contracts"][kind]["transforms"][source] = labels["transforms"][kind][source]
                correction_used += 1
                feedback = f"{kind}:{source}"
        rows.append({"case": case["id"], "scored_before_feedback": True,
                     "correct": correct, "expected_accept": expected_accept,
                     "actual_accept": actual_accept, "outcome": outcome,
                     "reason": reason, "observed_reason": reason,
                     "expected_reason": case["expected"].get("reason"),
                     "allowed_reasons": case["expected"].get("allowed_reasons"),
                     "failure_kinds": failures,
                     "feedback_after_score": feedback})
    valid_cases = sum(1 for row in rows if row["expected_accept"])
    correct = sum(1 for row in rows if row["correct"])
    valid_correct = sum(1 for row in rows if row["correct"] and row["expected_accept"])
    outcome_counts = {name: sum(1 for row in rows if row["outcome"] == name)
                      for name in ("accepted", "rejected", "abstain")}
    reason_counts = {}
    for row in rows:
        if row["reason"]:
            reason_counts[row["reason"]] = reason_counts.get(row["reason"], 0) + 1
    return {
        "family": family["name"], "split": family["split"], "method": method,
        "budget": budget, "seed": seed, "cases": len(rows), "correct": correct,
        "accuracy": correct / len(rows) if rows else 0.0,
        "valid_cases": valid_cases,
        "coverage": valid_correct / valid_cases if valid_cases else 0.0,
        "corrections": correction_used,
        "correction_burden": correction_used / len(rows) if rows else 0.0,
        "outcome_counts": outcome_counts, "reason_counts": reason_counts,
        "scenario_seed": seed,
        "trace": rows,
    }


def _aggregate(rows: list[dict[str, Any]], *, include_budget: bool = True) -> dict[str, Any]:
    grouped = {}
    for row in rows:
        grouped.setdefault(row["family"], []).append(row)
    family_rows = []
    for family, group in sorted(grouped.items()):
        reason_counts = {}
        for row in group:
            for reason, count in row["reason_counts"].items():
                reason_counts[reason] = reason_counts.get(reason, 0) + count
        family_rows.append({
            "family": family, "source_family_count": 1,
            "scenario_count": len({r["scenario_seed"] for r in group}),
            "run_count": len(group), "case_count": sum(r["cases"] for r in group),
            "correct": sum(r["correct"] for r in group),
            "accepted": sum(r["outcome_counts"]["accepted"] for r in group),
            "rejected": sum(r["outcome_counts"]["rejected"] for r in group),
            "abstain": sum(r["outcome_counts"]["abstain"] for r in group),
            "accuracy": sum(r["accuracy"] for r in group) / len(group),
            "coverage": sum(r["coverage"] for r in group) / len(group),
            "corrections": sum(r["corrections"] for r in group),
            "correction_burden": sum(r["correction_burden"] for r in group) / len(group),
            "reason_counts": reason_counts,
        })
    macro = {
        "source_family_count": len(family_rows),
        "scenario_count": len({(row["family"], row["scenario_seed"]) for row in rows}),
        "run_count": len(rows),
        "case_count": sum(r["cases"] for r in rows),
        "accepted": sum(r["accepted"] for r in family_rows),
        "rejected": sum(r["rejected"] for r in family_rows),
        "abstain": sum(r["abstain"] for r in family_rows),
        # Mean over source families keeps repeated rows in one family from
        # pretending to be independent observations.
        "accuracy": sum(r["accuracy"] for r in family_rows) / len(family_rows) if family_rows else 0.0,
        "coverage": sum(r["coverage"] for r in family_rows) / len(family_rows) if family_rows else 0.0,
        "correction_burden": sum(r["correction_burden"] for r in family_rows) / len(family_rows) if family_rows else 0.0,
    }
    by_budget = []
    if include_budget:
        for budget in sorted({row["budget"] for row in rows}):
            budget_rows = [row for row in rows if row["budget"] == budget]
            budget_summary = _aggregate(budget_rows, include_budget=False)
            by_budget.append({"budget": budget, "by_source_family": budget_summary["by_source_family"],
                              "macro_by_source_family": budget_summary["macro_by_source_family"]})
    return {"by_source_family": family_rows, "macro_by_source_family": macro,
            "by_budget": by_budget,
            "uncertainty_note": "Rows sharing a source family or scenario are correlated; no row-level significance is reported."}


def run_protocol(split: str = "development", *, method: str = "aliases",
                 budgets: Iterable[int] = BUDGETS, seeds: Iterable[int] = SEEDS,
                 include_trace: bool = False, unlock_final: bool = False,
                 confirm_final: str = "", final_version: str = "",
                 manifest_sha256: str = "") -> dict[str, Any]:
    """Run the declared development protocol.

    The final v2 holdout requires an explicit maintainer unlock. Its
    checked-in manifest and labels are reserved, with no final results yet.
    """
    manifest = load_manifest()
    manifest_hash = _sha256(MANIFEST)
    if split not in SPLITS:
        raise ValueError(f"split must be one of {', '.join(SPLITS)}")
    if split == "final":
        expected_hash = manifest_hash
        if (not unlock_final or confirm_final != FINAL_UNLOCK_CONFIRM
                or final_version != manifest["protocol_version"]
                or manifest_sha256 != expected_hash):
            raise ValueError("Final v2 requires explicit unlock, confirmation, version, and manifest hash.")
    if method not in {"aliases", "contracts"}:
        raise ValueError("method must be aliases or contracts")
    budgets = tuple(int(b) for b in budgets)
    seeds = tuple(int(s) for s in seeds)
    if any(b not in BUDGETS for b in budgets) or any(s not in SEEDS for s in seeds):
        raise ValueError("Use the frozen correction budgets and scenario seeds.")
    rows = []
    for family in iter_families(split, include_labels=True):
        for budget in budgets:
            for seed in seeds:
                result = evaluate_family(family, method, budget, seed)
                if not include_trace:
                    result.pop("trace", None)
                rows.append(result)
    return {"protocol_version": manifest["protocol_version"],
            "manifest_sha256": manifest_hash,
            "manifest_fingerprint": manifest_hash,
            "fixture_schema_version": manifest["schema_version"],
            "split": split, "method": method,
            "budgets": list(budgets), "seeds": list(seeds),
            "final_status": "final run" if split == "final" else "development run",
            "results": rows, "summary": _aggregate(rows),
            "baselines": {"aliases": "available", "contracts": "available",
                          "fixed_model": "not-run", "word_classifier": "not-run",
                          "sentence_model": "not-run"}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the crew source-format adaptation benchmark.")
    parser.add_argument("--split", choices=SPLITS, default="development",
                        help="development is the default; final requires explicit maintainer unlock")
    parser.add_argument("--method", choices=("aliases", "contracts"), default="aliases")
    parser.add_argument("--json", action="store_true", help="print the complete machine-readable report")
    parser.add_argument("--trace", action="store_true", help="include score-before-feedback traces")
    parser.add_argument("--unlock-final", action="store_true",
                        help="explicit final intent for the frozen release holdout")
    parser.add_argument("--confirm-final", default="",
                        help="must equal the frozen final confirmation string")
    parser.add_argument("--final-version", default="",
                        help="must equal the frozen protocol version")
    parser.add_argument("--manifest-sha256", default="",
                        help="must equal the current frozen manifest SHA-256")
    args = parser.parse_args(argv)
    if args.split == "final":
        manifest_hash = _sha256(MANIFEST)
        manifest = load_manifest()
        if (not args.unlock_final or args.confirm_final != FINAL_UNLOCK_CONFIRM
                or args.final_version != manifest["protocol_version"]
                or args.manifest_sha256 != manifest_hash):
            parser.error("final requires unlock, confirmation, protocol version, and frozen manifest hash")
    report = run_protocol(args.split, method=args.method, include_trace=args.trace,
                          unlock_final=args.unlock_final, confirm_final=args.confirm_final,
                          final_version=args.final_version,
                          manifest_sha256=args.manifest_sha256)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{args.split} / {args.method}: per-budget source-family macro results")
        for budget_group in report["summary"]["by_budget"]:
            macro = budget_group["macro_by_source_family"]
            print(f"  budget={budget_group['budget']}: accuracy={macro['accuracy']:.3f}, "
                  f"coverage={macro['coverage']:.3f}, correction_burden={macro['correction_burden']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
