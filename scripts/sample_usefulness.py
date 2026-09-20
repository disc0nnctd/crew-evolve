"""Bounded, offline usefulness checks against the original crew sample.

The source sample contains regulatory concepts the demo engine does not model.
This runner imports only the supported crew and supplied duty-block projection,
and records the unsupported parts as explicit gaps.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import platform
import sys
import tempfile
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

# Permit direct invocation from any working directory without installation.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from crew_evolve.app import App
from crew_evolve.store import DEMO_POLICY, Store


CASE_SPEC_VERSION = "sample-usefulness-1"
CASE_SPEC = {
    "version": CASE_SPEC_VERSION,
    "groups": [
        "full crew import and reviewed contract reuse",
        "two supplied P-2291 day-block coverage checks",
        "workflow correction and reuse on a new target",
        "assignment, stale revision, and release",
        "review a new sick status and recompute scoped coverage",
        "unsupported source concepts and nested roster abstention",
    ],
    "scope": "Captain coverage over a pilot two-slot projection; no full-pairing, certification, reserve, costs, calendar-day, flight-time, or multi-cabin-seat claims.",
}
CREW_HEADERS = ["crew_id", "name", "base", "rank", "ratings", "status"]
CREW_MAPPING = {
    "crew_id": "crew_id",
    "name": "name",
    "base": "base",
    "rank": "role",
    "ratings": "aircraft",
    "status": "available",
}
CREW_TRANSFORMS = {
    "rank": {
        "op": "enum",
        "values": {
            "Cabin Crew": "cabin_crew",
            "Captain": "captain",
            "First Officer": "first_officer",
            "Senior Cabin Crew": "senior_cabin_crew",
        },
    },
    "status": {
        "op": "enum",
        "values": {"active": "true", "leave": "false", "training": "false"},
    },
}
RANK_TO_ROLE = {
    "Cabin Crew": "cabin_crew",
    "Captain": "captain",
    "First Officer": "first_officer",
    "Senior Cabin Crew": "senior_cabin_crew",
}


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


CASE_SPEC_HASH = canonical_hash(CASE_SPEC)


def load_json(sample_dir: Path, name: str) -> Any:
    return json.loads((sample_dir / name).read_text(encoding="utf-8"))


def source_hashes(sample_dir: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(sample_dir.glob("*.json"))
    }


def project_crew_rows(crew: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Project only fields covered by the reviewed source contract."""
    return [
        {
            "crew_id": str(row["crew_id"]),
            "name": str(row["name"]),
            "base": str(row["base"]),
            "rank": str(row["rank"]),
            "ratings": "|".join(row["ratings"]),
            "status": str(row["status"]),
        }
        for row in crew
    ]


def expected_canonical_crew(crew: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the independent expected canonical records before App calls."""
    return [
        {
            "crew_id": str(row["crew_id"]).strip(),
            "name": str(row["name"]).strip(),
            "base": str(row["base"]).strip().upper(),
            "role": RANK_TO_ROLE[row["rank"]],
            "aircraft": sorted(str(value).strip().upper() for value in row["ratings"]),
            "available": row["status"] == "active",
        }
        for row in crew
    ]


def csv_text(headers: list[str], rows: list[dict[str, Any]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def derive_pairing_duties(
    rosters: dict[str, Any], flights: list[dict[str, Any]], pairing_id: str = "P-2291"
) -> list[dict[str, Any]]:
    """Use operator supplied day blocks and first/last flight stations."""
    flight_by_id = {flight["flight_id"]: flight for flight in flights}
    pairing = next(item for item in rosters["pairings"] if item["pairing_id"] == pairing_id)
    duties = []
    for day in pairing["days"]:
        first = flight_by_id[day["flights"][0]]
        last = flight_by_id[day["flights"][-1]]
        duties.append(
            {
                "duty_id": f"{pairing_id}-{day['date']}",
                "report_at": day["report_utc"],
                "release_at": day["release_utc"],
                "start_base": first["dep_station"],
                "end_base": last["arr_station"],
                "aircraft": first["aircraft_type"],
                "required_roles": "captain|first_officer",
                "source_pairing_id": pairing_id,
                "source_flights": list(day["flights"]),
            }
        )
    return duties


def expected_captains(
    crew: list[dict[str, Any]], duty: dict[str, Any], max_duty_hours: float
) -> list[str]:
    """Independent fact filter run before importing or querying the engine."""
    report = datetime.fromisoformat(duty["report_at"].replace("Z", "+00:00"))
    release = datetime.fromisoformat(duty["release_at"].replace("Z", "+00:00"))
    duration = (release - report).total_seconds() / 3600
    return sorted(
        row["crew_id"]
        for row in crew
        if row["status"] == "active"
        and row["rank"] == "Captain"
        and duty["aircraft"] in row["ratings"]
        and row["base"] == duty["start_base"]
        and duration <= max_duty_hours
    )


class OfflineModel:
    """Explicitly prevent paid or network model routing during this runner."""

    configured = False
    name = None


def stored_record_count(app: App, kind: str) -> int:
    with app.store.connect() as db:
        return len(app.store.datasets(db)[kind]["records"])


def code_hashes() -> dict[str, str]:
    files = [
        REPO_ROOT / "scripts" / "sample_usefulness.py",
        REPO_ROOT / "crew_evolve" / "app.py",
        REPO_ROOT / "crew_evolve" / "engine.py",
        REPO_ROOT / "crew_evolve" / "workflows.py",
    ]
    return {str(path.relative_to(REPO_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


def import_table(
    app: App,
    kind: str,
    filename: str,
    content: str,
    mapping: dict[str, str] | None,
    *,
    transforms: dict[str, Any] | None = None,
    source_contract: str | None = None,
) -> dict[str, Any]:
    preview = app.preview(kind, filename, content, source_contract=source_contract)
    effective_mapping = mapping if mapping is not None else preview["mapping"]
    effective_transforms = transforms if transforms is not None else preview.get("transforms", {})
    checked = app.test_import(preview["id"], effective_mapping, effective_transforms, source_contract)
    if not checked["valid"]:
        raise AssertionError(f"test rejected {kind}: {checked.get('issue')}")
    with app.store.connect() as db:
        revision = app.store.get(db, "revision")
    accepted = app.accept_import(
        preview["id"], effective_mapping, revision, effective_transforms, source_contract
    )
    if not accepted.get("accepted"):
        raise AssertionError(f"accept rejected {kind}: {accepted}")
    return {
        "preview": preview,
        "test": checked,
        "accept": accepted,
        "mapping_used": effective_mapping,
        "transforms_used": effective_transforms,
    }


def clean_candidates(result: dict[str, Any]) -> list[str]:
    return sorted(row["crew_id"] for row in result["result"]["candidates"] if row["passes"])


def stored_clean_records(app: App, kind: str) -> list[dict[str, Any]]:
    with app.store.connect() as db:
        records = app.store.datasets(db)[kind]["records"]
    return [{key: value for key, value in record.items() if not key.startswith("_")} for record in records]


def record_diff(expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> dict[str, Any]:
    mismatches = [
        {"index": index, "expected": want, "actual": got}
        for index, (want, got) in enumerate(zip(expected, actual))
        if want != got
    ]
    mismatches.extend(
        {"index": index, "expected": want, "actual": None}
        for index, want in enumerate(expected[len(actual):], start=len(actual))
    )
    mismatches.extend(
        {"index": index, "expected": None, "actual": got}
        for index, got in enumerate(actual[len(expected):], start=len(expected))
    )
    return {
        "expected_hash": canonical_hash(expected),
        "actual_hash": canonical_hash(actual),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:5],
    }


def run(sample_dir: Path, output: Path) -> dict[str, Any]:
    sample_dir = sample_dir.resolve()
    crew = load_json(sample_dir, "crew.json")
    rosters = load_json(sample_dir, "rosters.json")
    flights = load_json(sample_dir, "flights.json")
    duties = derive_pairing_duties(rosters, flights)
    source_rows = project_crew_rows(crew)
    expected_canonical = expected_canonical_crew(crew)
    expected_by_duty = {
        duty["duty_id"]: expected_captains(crew, duty, DEMO_POLICY["max_duty_hours"])
        for duty in duties
    }
    spec = {"version": CASE_SPEC_VERSION, "hash": CASE_SPEC_HASH, "case_spec": CASE_SPEC}
    report: dict[str, Any] = {
        "runner": {"version": "1", "created_utc": datetime.now(timezone.utc).isoformat()},
        "case_spec": spec,
        "source": {
            "directory": str(sample_dir),
            "hashes": source_hashes(sample_dir),
            "machine": platform.platform(),
            "python": sys.version,
            "crew_evolve_version": _package_version(),
        },
        "scope": {
            "crew_projection": "rank -> supported role; active -> available; leave/training -> unavailable",
            "duty_projection": "two supplied P-2291 day blocks, captain/first_officer roles only, no history or assignments",
            "limitations": [
                "three identical cabin-seat positions are omitted because the supported duty schema requires unique role slots",
                "the two P-2291 days are separate supplied duty blocks; no atomic full-pairing plan is claimed",
                "the coverage check is captain-only; first_officer is retained as the second projected pilot slot but not queried",
                "calendar-day duty and flight-time rules are unsupported by the demo engine",
                "certifications, reserve windows, costs, positioning, and multiple cabin seats are unsupported",
                "passing here is a scoped rehearsal, not full sample scenario legality",
            ],
        },
        "cases": [],
        "failures": [],
        "source_hashes_start": source_hashes(sample_dir),
        "code_hashes_start": code_hashes(),
    }
    cert_rows = load_json(sample_dir, "certifications.json")
    future_licences = sum(
        row.get("cert_type") == "licence" and row.get("valid_from", "") > "2026-09-20"
        for row in cert_rows
    )
    report["source"]["data_gaps"] = {
        "licence_valid_from_after_snapshot": future_licences,
        "all_licences_future_relative_to_snapshot": future_licences == 150,
        "note": "Certification validity is not evaluated; all 150 source licence start dates need operator review against the snapshot date.",
    }

    def case(name: str, expected: Any, observed: Any, result: str, **extra: Any) -> None:
        row = {"name": name, "expected": expected, "observed": observed, "result": result}
        row.update(extra)
        report["cases"].append(row)
        if result == "fail":
            report["failures"].append(row)

    with tempfile.TemporaryDirectory(prefix="sample-usefulness-") as temp:
        app = App(Store(Path(temp) / "workspace.sqlite"), model=OfflineModel())
        contract_name = "original-crew-v1"
        full_content = csv_text(CREW_HEADERS, source_rows)
        first = import_table(
            app,
            "crew",
            "original-crew.csv",
            full_content,
            CREW_MAPPING,
            transforms=CREW_TRANSFORMS,
            source_contract=contract_name,
        )
        full_actual = stored_clean_records(app, "crew")
        full_diff = record_diff(expected_canonical, full_actual)
        case(
            "full150 crew import",
            {"records": len(expected_canonical), "canonical_fields": "exact"},
            {"records": len(full_actual), **full_diff},
            "pass" if not full_diff["mismatch_count"] else "fail",
            mapping=CREW_MAPPING,
            transforms=CREW_TRANSFORMS,
            preview_issue=first["preview"].get("issue"),
            contract_version=first["accept"]["learning"]["report"].get("version"),
            projected_role_counts={role: sum(row["rank"] == role for row in crew) for role in sorted({row["rank"] for row in crew})},
            projected_status_counts={status: sum(row["status"] == status for row in crew) for status in sorted({row["status"] for row in crew})},
            source_ids=[row["crew_id"] for row in crew],
        )

        subset_rows = source_rows[::11]
        subset = import_table(
            app,
            "crew",
            "original-crew.csv",
            csv_text(CREW_HEADERS, subset_rows),
            None,
            transforms=None,
            source_contract=contract_name,
        )
        subset_diff = record_diff(expected_canonical_crew(crew[::11]), stored_clean_records(app, "crew"))
        restored = import_table(
            app,
            "crew",
            "original-crew.csv",
            full_content,
            None,
            transforms=None,
            source_contract=contract_name,
        )
        restored_actual = stored_clean_records(app, "crew")
        restored_diff = record_diff(expected_canonical, restored_actual)
        reuse_observed = {
            "subset_records": len(subset_rows),
            "subset_canonical": subset_diff,
            "subset_contract_reused": subset["preview"]["contract_reused"],
            "restore_contract_reused": restored["preview"]["contract_reused"],
            "restore_records": len(restored_actual),
            "subset_status": subset["accept"]["learning"]["status"],
            "restore_status": restored["accept"]["learning"]["status"],
            "subset_mapping_reused": subset["preview"]["mapping"] == first["mapping_used"],
            "restore_mapping_reused": restored["preview"]["mapping"] == first["mapping_used"],
            "subset_transforms_reused": subset["preview"]["transforms"] == first["transforms_used"],
            "restore_transforms_reused": restored["preview"]["transforms"] == first["transforms_used"],
            "restored_mismatch_count": restored_diff["mismatch_count"],
            "restored_canonical": restored_diff,
        }
        case(
            "same source schema reuses reviewed contract",
            {"subset_contract_reused": True, "restore_contract_reused": True, "restore_records": 150, "restored_mismatch_count": 0},
            reuse_observed,
            "pass"
            if reuse_observed["subset_contract_reused"]
            and reuse_observed["restore_contract_reused"]
            and reuse_observed["restore_records"] == 150
            and reuse_observed["subset_mapping_reused"]
            and reuse_observed["restore_mapping_reused"]
            and reuse_observed["subset_transforms_reused"]
            and reuse_observed["restore_transforms_reused"]
            and not restored_diff["mismatch_count"]
            and not subset_diff["mismatch_count"]
            else "fail",
        )

        duty_headers = [
            "duty_id",
            "report_at",
            "release_at",
            "start_base",
            "end_base",
            "aircraft",
            "required_roles",
        ]
        duty_content = csv_text(duty_headers, duties)
        duty_mapping = {header: header for header in duty_headers}
        import_table(app, "duties", "P-2291-supplied-blocks.csv", duty_content, duty_mapping)

        coverage_results = {}
        for duty in duties:
            expected = expected_by_duty[duty["duty_id"]]
            query = app.execute({"action": "coverage", "duty_id": duty["duty_id"], "role": "captain"})
            # App.execute bounds the response to 100 candidates. Read the same
            # immutable App snapshot for complete evidence on the four fixed
            # source facts and the expected-ID comparison.
            with app.store.connect() as db:
                direct = app.snapshot_engine(db).coverage(duty["duty_id"], "captain")
            observed = sorted(row["crew_id"] for row in direct["candidates"] if row["passes"])
            coverage_results[duty["duty_id"]] = {
                "expected_ids": expected,
                "observed_ids": observed,
                "candidate_checks": {
                    row["crew_id"]: {"passes": row["passes"], "reasons": row["reasons"]}
                    for row in direct["candidates"]
                },
                "passing": direct["passing"],
                "duty_source": {k: duty[k] for k in ("source_pairing_id", "source_flights")},
                "engine_limits": direct["limits"],
                "app_response_candidate_count": query["result"]["candidate_count"],
            }
            case(
                f"scoped coverage {duty['duty_id']}",
                expected,
                observed,
                "pass" if expected == observed else "fail",
                provenance="source-derived facts filtered before engine invocation",
                scoped_rehearsal=True,
            )
        day1_checks = coverage_results[duties[0]["duty_id"]]["candidate_checks"]
        known = {cid for ids in coverage_results.values() for cid in ids["observed_ids"]}
        projection_checks = {
            "C-3310_passes_day1": day1_checks["C-3310"]["passes"],
            "C-2091_aircraft_rejected_day1": any("No recorded qualification" in reason for reason in day1_checks["C-2091"]["reasons"]),
            "C-2210_location_rejected_day1": any("Last recorded location" in reason for reason in day1_checks["C-2210"]["reasons"]),
            "C-2087_is_scoped_only": "C-2087" in known,
        }
        case(
            "fixed source fact filters",
            {key: True for key in projection_checks},
            projection_checks,
            "pass" if all(projection_checks.values()) else "fail",
            note="C-2087 passing means only this no-history rehearsal; source scenario rules reject it on cumulative history.",
            actual_reasons={key: day1_checks[key]["reasons"] for key in ("C-2091", "C-2210")},
        )
        case(
            "P-2291 two-day continuity",
            "capability gap: blocks are not linked by history or atomic pairing state",
            {
                "day1_actual_passing": coverage_results[duties[0]["duty_id"]]["observed_ids"],
                "day2_actual_passing": coverage_results[duties[1]["duty_id"]]["observed_ids"],
                "C-3310_day2_passes": "C-3310" in coverage_results[duties[1]["duty_id"]]["observed_ids"],
                "atomic_pairing_supported": False,
                "sick_event_applied": False,
                "C-1042_day1_passes": "C-1042" in coverage_results[duties[0]["duty_id"]]["observed_ids"],
            },
            "capability_gap",
            gap="full pairing continuity, overnight location, and cumulative history are unsupported",
            baseline_projection=True,
        )

        before = app.ask(f"Find someone for {duties[0]['duty_id']} as captain")
        taught = app.teach(f"Find someone for {duties[0]['duty_id']} as captain", "coverage")
        after = app.ask(f"Find someone for {duties[1]['duty_id']} as captain")
        workflow_observed = {
            "before_action": before["action"],
            "after_action": after["action"],
            "after_target": after.get("plan", {}).get("duty_id"),
            "manual_corrections": 1,
            "learning_status": taught["status"],
        }
        case(
            "teach exact day1 then reuse on day2",
            {"before_action": "clarify", "after_action": "coverage", "manual_corrections": 1},
            workflow_observed,
            "pass"
            if workflow_observed["before_action"] == "clarify"
            and workflow_observed["after_action"] == "coverage"
            and workflow_observed["after_target"] == duties[1]["duty_id"]
            and workflow_observed["manual_corrections"] == 1
            else "fail",
            no_timesavings_claim=True,
        )

        day1_expected = coverage_results[duties[0]["duty_id"]]["expected_ids"]
        assign_id = "C-3310" if "C-3310" in day1_expected else day1_expected[0]
        with app.store.connect() as db:
            current_revision = app.store.get(db, "revision")
        assigned = app.assign(assign_id, duties[0]["duty_id"], "captain", current_revision)
        stale_error = None
        try:
            app.assign(assign_id, duties[1]["duty_id"], "captain", current_revision)
        except ValueError as exc:
            stale_error = str(exc)
        with app.store.connect() as db:
            release_revision = app.store.get(db, "revision")
        released = app.unassign(duties[0]["duty_id"], "captain", release_revision)
        lifecycle_observed = {
            "assigned_crew": assign_id,
            "stale_rejected": stale_error is not None,
            "stale_error": stale_error,
            "released": released.get("revision") == release_revision + 1,
            "assignment_revision": assigned["revision"],
        }
        case(
            "assignment stale revision and release",
            {"stale_rejected": True, "released": True},
            lifecycle_observed,
            "pass" if lifecycle_observed["stale_rejected"] and lifecycle_observed["released"] else "fail",
        )

        # Explicit event overlay, separate from baseline projection: the source
        # remains untouched, and an operator reviews the new status meaning.
        sick_rows = [dict(row, status="sick") if row["crew_id"] == "C-1042" else dict(row)
                     for row in source_rows]
        sick_expected = [cid for cid in expected_by_duty[duties[0]["duty_id"]] if cid != "C-1042"]
        sick_preview = app.preview("crew", "original-crew.csv", csv_text(CREW_HEADERS, sick_rows), contract_name)
        with app.store.connect() as db:
            sick_revision = app.store.get(db, "revision")
        unknown_status = app.test_import(sick_preview["id"], sick_preview["mapping"], sick_preview["transforms"])
        before_sick_records = stored_clean_records(app, "crew")
        reviewed_transforms = copy.deepcopy(sick_preview["transforms"])
        reviewed_transforms["status"]["values"]["sick"] = "false"
        reviewed = app.test_import(sick_preview["id"], sick_preview["mapping"], reviewed_transforms)
        accepted = app.accept_import(sick_preview["id"], sick_preview["mapping"], sick_revision, reviewed_transforms)
        sick_records = stored_clean_records(app, "crew")
        sick_canonical_expected = [dict(row, available=False) if row["crew_id"] == "C-1042" else row
                                   for row in expected_canonical]
        sick_diff = record_diff(sick_canonical_expected, sick_records)
        sick_answer = app.execute({"action": "coverage", "duty_id": duties[0]["duty_id"], "role": "captain"})
        sick_observed = clean_candidates(sick_answer)
        case(
            "review sick status then recompute coverage",
            {"unknown_status_rejected": True, "crew_id": "C-1042", "available": False,
             "passing_ids": sick_expected, "other_records_unchanged": True},
            {"unknown_status_rejected": not unknown_status["valid"], "unknown_status_issue": unknown_status["issue"],
             "preview_kept_baseline": before_sick_records == expected_canonical,
             "review_passed": reviewed["valid"], "accepted": accepted["accepted"],
             "canonical_comparison": sick_diff, "passing_ids": sick_observed,
             "cache_hit": sick_answer["metrics"]["cache_hit"]},
            "pass" if not unknown_status["valid"] and reviewed["valid"] and accepted["accepted"]
            and before_sick_records == expected_canonical and not sick_diff["mismatch_count"]
            and sick_observed == sick_expected and "C-3310" in sick_observed
            and not sick_answer["metrics"]["cache_hit"] else "fail",
            note="Explicit availability-only overlay after baseline checks; not the full S2 scenario or its legality/cost answer.",
            reviewed_mapping_changes=1,
        )

        unsupported_questions = {
            "cost": f"What is the reserve callout cost for covering {duties[0]['duty_id']} as captain?",
            "certification": f"Is C-3310 certification valid for {duties[0]['duty_id']} as captain?",
            "reserve": f"Who is on reserve for {duties[0]['duty_id']} as captain and what window applies?",
        }
        for label, question in unsupported_questions.items():
            answer = app.ask(question)
            observed = {
                "action": answer.get("action"),
                "reply": answer.get("reply"),
                "has_result": "result" in answer,
            }
            result = (
                "expected_abstention"
                if answer.get("action") == "clarify" and "result" not in answer
                else "fail"
            )
            case(
                f"unsupported {label} question",
                "clarify/abstain without coverage answer",
                observed,
                result,
                gap="unsupported source concept",
            )

        raw_rosters = (sample_dir / "rosters.json").read_text(encoding="utf-8")
        try:
            raw_preview = app.preview("duties", "rosters.json", raw_rosters)
            raw_observed = {"issue": raw_preview.get("issue"), "accepted": False}
        except ValueError as exc:
            raw_observed = {"issue": str(exc), "accepted": False}
        case(
            "nested original rosters import",
            "abstention/rejection",
            raw_observed,
            "expected_abstention" if raw_observed["issue"] else "fail",
            gap="nested pairings require an explicit reviewed projection",
        )

    report["source_hashes_end"] = source_hashes(sample_dir)
    report["code_hashes_end"] = code_hashes()
    report["source_unchanged"] = report["source_hashes_start"] == report["source_hashes_end"]
    report["code_unchanged_during_run"] = report["code_hashes_start"] == report["code_hashes_end"]
    if not report["source_unchanged"] or not report["code_unchanged_during_run"]:
        report["failures"].append({
            "name": "input/code hashes stable during run",
            "expected": True,
            "observed": {
                "source_unchanged": report["source_unchanged"],
                "code_unchanged_during_run": report["code_unchanged_during_run"],
            },
            "result": "fail",
        })
    report["summary"] = {
        "completed": sum(case["result"] == "pass" for case in report["cases"]),
        "expected_abstentions": sum(case["result"] == "expected_abstention" for case in report["cases"]),
        "capability_gaps": sum(case["result"] == "capability_gap" for case in report["cases"]),
        "failures": len(report["failures"]),
        "unsupported_gaps": sum("gap" in case for case in report["cases"]),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _package_version() -> str:
    try:
        return version("crew-evolve")
    except PackageNotFoundError:
        return "workspace-source"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = run(args.sample_dir, args.output)
    except (AssertionError, KeyError, TypeError, ValueError, OSError) as exc:
        print(f"sample usefulness runner failed: {exc}", file=sys.stderr)
        return 1
    if report["failures"]:
        print(f"sample usefulness assertions failed: {len(report['failures'])}", file=sys.stderr)
        return 1
    print(f"sample usefulness report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
