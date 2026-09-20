#!/usr/bin/env python3
"""Rehearse bounded requests, separating answered tasks from clarifications."""

import argparse
import hashlib
import json
import platform
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crew_evolve.app import App
from crew_evolve.store import Store


# Frozen before the first run; this is a regression rehearsal, not an unseen
# language benchmark. Keep original failures in request-usefulness-initial.json.
CASES = [
    ("basic", "Who can cover D-100 as captain?", "coverage"),
    ("new_duty", "Who can cover D-101 as captain?", "coverage"),
    ("missing_role", "Who can cover D-100?", "clarify"),
    ("unknown_duty", "Who can cover D-999 as captain?", "clarify"),
    ("cost", "Who is the cheapest captain who can cover D-100?", "clarify"),
    ("certificate", "Who can cover D-100 as captain with a valid medical certificate?", "clarify"),
    ("reserve", "Who can cover D-100 as captain within their reserve on-call window?", "clarify"),
    ("sick_followup", "Who can cover D-100 as captain if Asha Rao is sick?", "clarify"),
    ("person_exclusion", "Who can cover D-100 as captain excluding Asha Rao?", "clarify"),
    ("calendar_rule", "Who can cover D-100 as captain under calendar-day limits?", "clarify"),
    ("hypothetical_delay", "Who can cover D-100 as captain after a three hour delay?", "clarify"),
    ("write", "Assign Asha Rao to D-100 as captain", "clarify"),
]


class NoModel:
    configured = False

    def route(self, *args):
        raise AssertionError("The rehearsal must not call a model")


def run():
    paths = ["crew_evolve/app.py", "crew_evolve/workflows.py", "crew_evolve/engine.py",
             "scripts/request_usefulness.py", "examples/crew.csv", "examples/duties.csv",
             "examples/assignments.csv"]
    source_hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    results = []
    with tempfile.TemporaryDirectory() as directory:
        app = App(Store(Path(directory) / "workspace.sqlite"), model=NoModel())
        app.demo()
        app.teach("Who can cover D-100 as captain?", "coverage")
        for name, question, expected in CASES:
            before = app.state()["revision"]
            answer = app.ask(question)
            actual = answer.get("action", answer.get("plan", {}).get("action"))
            passing = [c["crew_id"] for c in answer.get("result", {}).get("candidates", []) if c["passes"]]
            expected_ids = {"basic": ["C-01"], "new_duty": ["C-01", "C-02"]}.get(name)
            revision_unchanged = app.state()["revision"] == before
            result_matches = sorted(passing) == expected_ids if expected_ids is not None else "result" not in answer
            results.append({
                "id": name, "question": question,
                "category": "supported_task" if expected == "coverage" else "expected_clarification",
                "expected_action": expected, "actual_action": actual,
                "expected_passing_ids": expected_ids, "observed_passing_ids": passing,
                "passed": actual == expected and result_matches and revision_unchanged,
                "revision_unchanged": revision_unchanged, "reply": answer.get("reply"),
                "reason": answer.get("reason"), "limits": answer.get("result", {}).get("limits"),
            })
    assert source_hashes == {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}, "Source changed during rehearsal"
    return {
        "scope": "Fixed requests on the supplied small example, after one approved workflow correction; no general language or human usability claim",
        "python": platform.python_version(), "model_calls": 0,
        "case_specification": CASES,
        "case_specification_sha256": hashlib.sha256(json.dumps(CASES).encode()).hexdigest(),
        "source_sha256": source_hashes, "results": results,
        "totals": {category: {"passed": sum(r["passed"] for r in results if r["category"] == category),
                              "count": sum(r["category"] == category for r in results)}
                   for category in ("supported_task", "expected_clarification")},
        "all_checks_passed": all(r["passed"] for r in results),
        "limits": ["Clarifications are not completed operational tasks.",
                   "Known-case repair does not prove understanding of arbitrary qualifiers.",
                   "No model training, measured operator time savings, or human usability trial."],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/request-usefulness.json"))
    args = parser.parse_args()
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"totals": report["totals"], "all_checks_passed": report["all_checks_passed"],
                      "report": str(args.output)}))
    return 0 if report["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
