#!/usr/bin/env python3
"""Run a small real local-model check and save raw evidence.

The check does not use a fake encoder.  It records unavailable dependencies,
missing cache files, and model errors as data so a run cannot be mistaken for
successful model evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _cases() -> list[dict]:
    return [
        {
            "name": "coverage_unseen_wording",
            "kind": "route",
            "question": "Who could cover D-100 as captain?",
            "context": {
                "duties": ["D-100", "D-101"],
                "roles": ["captain", "first_officer"],
                "approved_examples": [
                    {"template": "Find eligible crew for {duty} as {role}", "action": "coverage"},
                    {"template": "Show the duty-by-duty roster", "action": "roster"},
                    {"template": "Give an aggregate summary of crew and duties", "action": "summary"},
                ],
            },
        },
        {
            "name": "roster_unseen_wording",
            "kind": "route",
            "question": "List every planned duty position.",
            "context": {
                "duties": ["D-100", "D-101"],
                "roles": ["captain", "first_officer"],
                "approved_examples": [
                    {"template": "Find eligible crew for {duty} as {role}", "action": "coverage"},
                    {"template": "Show the duty-by-duty roster", "action": "roster"},
                    {"template": "Give an aggregate summary of crew and duties", "action": "summary"},
                ],
            },
        },
        {
            "name": "summary_unseen_wording",
            "kind": "route",
            "question": "How many crew and duties are in the workspace?",
            "context": {
                "duties": ["D-100", "D-101"],
                "roles": ["captain", "first_officer"],
                "approved_examples": [
                    {"template": "Find eligible crew for {duty} as {role}", "action": "coverage"},
                    {"template": "Show the duty-by-duty roster", "action": "roster"},
                    {"template": "Give an aggregate summary of crew and duties", "action": "summary"},
                ],
            },
        },
        {
            "name": "mapping_unseen_headers",
            "kind": "mapping",
            "pending": {
                "kind": "crew",
                "headers": ["Badge", "Person", "Home station", "Can work"],
                "rows": [{"Badge": "C-01", "Person": "Asha", "Home station": "BOM", "Can work": "yes"}],
            },
            "fields": ["crew_id", "name", "base", "available"],
        },
    ]


def _run_case(model, case: dict) -> dict:
    started = time.perf_counter()
    try:
        if case["kind"] == "route":
            result = model.route(case["question"], case["context"])
        else:
            result = model.mapping(case["pending"], case["fields"])
        evidence = result.get("evidence") if isinstance(result, dict) else None
        return {
            "name": case["name"],
            "kind": case["kind"],
            "ok": isinstance(result, dict),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "prediction": result,
            "real_inference": bool(isinstance(evidence, dict) and evidence.get("inference") is True),
        }
    except Exception as exc:  # the raw report must record unavailable local state
        return {
            "name": case["name"],
            "kind": case["kind"],
            "ok": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "real_inference": False,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run real offline MiniLM candidate checks.")
    parser.add_argument("--output", default="artifacts/local-model-check.json",
                        help="Raw JSON report path (default: artifacts/local-model-check.json).")
    parser.add_argument("--strict", action="store_true",
                        help="Return a failure status when any case cannot run.")
    args = parser.parse_args(argv)

    from crew_evolve.local_model import LocalModel

    model = LocalModel()
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": model.model_id,
        "revision": model.revision or None,
        "configured": model.configured,
        "name": model.name if model.configured else None,
        "local_files_only": True,
        "selection": os.environ.get("CREW_LOCAL_MODEL", ""),
        "calibration": "heuristic retrieval gates, not probabilities of correctness",
        "cases": [],
    }
    for case in _cases():
        report["cases"].append(_run_case(model, case))
    report["successful_cases"] = sum(1 for case in report["cases"] if case["ok"])
    report["errors"] = sum(1 for case in report["cases"] if not case["ok"])
    report["real_inference_cases"] = sum(1 for case in report["cases"] if case["real_inference"])

    output = Path(args.output)
    if str(output) != "-":
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.strict and report["errors"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
