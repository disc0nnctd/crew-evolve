#!/usr/bin/env python3
"""Profile bounded direct Engine coverage requests on the synthetic load.

This utility deliberately calls ``Engine.coverage`` instead of the application
HTTP path.  The engine returns every candidate, so the result fingerprints
cover the complete 10,000-candidate result rather than the application's
100-candidate response view.
"""

from __future__ import annotations

import argparse
import cProfile
import gc
import hashlib
import json
import math
import os
import platform
import pstats
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crew_evolve.engine import Engine  # noqa: E402
from crew_evolve.store import DEMO_POLICY  # noqa: E402
from scripts.load_benchmark import synthetic_workload  # noqa: E402


DEFAULT_CREW = 10_000
DEFAULT_HISTORY = 5
DEFAULT_TARGETS = 8
MAX_TARGETS = 32
HOTSPOT_LIMIT = 20


def _git_value(arguments: Sequence[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *arguments], cwd=ROOT, check=True,
            capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value or None


def source_fingerprint() -> str:
    """Hash the profiler and the direct request path in stable path order."""
    paths = (
        Path(__file__),
        ROOT / "scripts" / "load_benchmark.py",
        ROOT / "crew_evolve" / "engine.py",
        ROOT / "crew_evolve" / "data.py",
        ROOT / "crew_evolve" / "store.py",
    )
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(ROOT).as_posix()):
        relative = path.relative_to(ROOT).as_posix().encode()
        digest.update(relative + b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def machine_info() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "git_commit": _git_value(("rev-parse", "HEAD")),
        "git_dirty": _git_value(("status", "--porcelain", "--untracked-files=all")) not in (None, ""),
        "source_fingerprint": source_fingerprint(),
    }


def _elapsed_ms(function, *arguments) -> tuple[Any, float]:
    started = time.perf_counter()
    value = function(*arguments)
    return value, (time.perf_counter() - started) * 1000


def _result_fingerprint(result: dict[str, Any]) -> str:
    """Hash a complete Engine result, including every candidate and source."""
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return round(ordered[index], 3)


def _hotspots(profile: cProfile.Profile, limit: int = HOTSPOT_LIMIT) -> list[dict[str, Any]]:
    """Return compact cumulative and self-time rows from cProfile stats."""
    stats = pstats.Stats(profile).stats
    rows = []
    for (filename, line, function), (primitive_calls, total_calls, self_seconds,
                                    cumulative_seconds, _callers) in stats.items():
        rows.append({
            "file": str(Path(filename).resolve().relative_to(ROOT))
            if Path(filename).is_absolute() and str(Path(filename).resolve()).startswith(str(ROOT) + os.sep)
            else filename,
            "line": line,
            "function": function,
            "primitive_calls": primitive_calls,
            "calls": total_calls,
            "self_ms": round(self_seconds * 1000, 3),
            "cumulative_ms": round(cumulative_seconds * 1000, 3),
        })
    rows.sort(key=lambda row: (-row["cumulative_ms"], -row["self_ms"], row["file"], row["line"]))
    return rows[:limit]


def profile_queries(*, crew: int = DEFAULT_CREW, history: int = DEFAULT_HISTORY,
                    targets: int = DEFAULT_TARGETS) -> dict[str, Any]:
    """Measure a cold indexed engine and bounded warm direct coverage calls."""
    if type(crew) is not int or crew != DEFAULT_CREW:
        raise ValueError(f"crew is fixed at {DEFAULT_CREW} for this bounded profile")
    if type(history) is not int or history != DEFAULT_HISTORY:
        raise ValueError(f"history is fixed at {DEFAULT_HISTORY} for this bounded profile")
    if type(targets) is not int or not 1 <= targets <= MAX_TARGETS:
        raise ValueError(f"targets must be between 1 and {MAX_TARGETS}")

    datasets = synthetic_workload(DEFAULT_CREW, DEFAULT_HISTORY)
    target_ids = [
        duty["duty_id"] for duty in datasets["duties"]["records"]
        if str(duty.get("duty_id", "")).startswith("TARGET-")
    ][:targets]
    plans = [(target_id, "captain") for target_id in target_ids]

    engine, cold_ms = _elapsed_ms(Engine, datasets, DEMO_POLICY, "indexed")
    warmup_result = engine.coverage(*plans[0])
    warmup_candidates = len(warmup_result["candidates"])
    del warmup_result

    unprofiled_durations: list[float] = []
    unprofiled_hashes: dict[str, str] = {}
    unprofiled_counts: dict[str, int] = {}
    for duty_id, role in plans:
        result, elapsed_ms = _elapsed_ms(engine.coverage, duty_id, role)
        unprofiled_durations.append(elapsed_ms)
        unprofiled_hashes[duty_id] = _result_fingerprint(result)
        unprofiled_counts[duty_id] = len(result["candidates"])
        del result

    profiler = cProfile.Profile()
    profiled_hashes: dict[str, str] = {}
    profiled_counts: dict[str, int] = {}
    profiled_ms = 0.0
    for duty_id, role in plans:
        # Keep serialization and hashing outside the profile.  The profile is
        # for Engine.coverage work; the separate wall time includes only the
        # profiled query call and profiler overhead.
        query_started = time.perf_counter()
        profiler.enable()
        result = engine.coverage(duty_id, role)
        profiler.disable()
        profiled_ms += (time.perf_counter() - query_started) * 1000
        profiled_hashes[duty_id] = _result_fingerprint(result)
        profiled_counts[duty_id] = len(result["candidates"])
        del result

    fingerprints_equal = unprofiled_hashes == profiled_hashes
    full_result_counts = all(count == crew for count in unprofiled_counts.values())
    return {
        "profile": "direct-engine-query-profile",
        "scope": "bounded direct Engine.coverage calls; no HTTP, model, or result-cache timing",
        "workload": {
            "crew": crew,
            "history_per_crew": history,
            "assignments": len(datasets["assignments"]["records"]),
            "duties": len(datasets["duties"]["records"]),
            "rotating_requests": len(plans),
            "target_ids": target_ids,
            "role": "captain",
        },
        "timing_ms": {
            "cold_indexed_engine_construction": round(cold_ms, 3),
            "warmup_request_excluded": True,
            "unprofiled_warm_requests": {
                "count": len(unprofiled_durations),
                "total": round(sum(unprofiled_durations), 3),
                "mean": round(sum(unprofiled_durations) / len(unprofiled_durations), 3),
                "p50": _percentile(unprofiled_durations, 0.50),
                "p95": _percentile(unprofiled_durations, 0.95),
                "durations": [round(value, 3) for value in unprofiled_durations],
            },
            "cprofile_warm_requests": {
                "count": len(plans),
                "total": round(profiled_ms, 3),
                "overhead_included": True,
            },
        },
        "cprofile": {
            "hotspots_by_cumulative_time": _hotspots(profiler),
            "requests_profiled": len(plans),
        },
        "garbage_collection": {
            "enabled": gc.isenabled(),
            "thresholds": list(gc.get_threshold()),
        },
        "full_result_integrity": {
            "engine_returns_all_candidates": full_result_counts and warmup_candidates == crew,
            "expected_candidate_count": crew,
            "warmup_candidate_count": warmup_candidates,
            "unprofiled_candidate_counts": unprofiled_counts,
            "profiled_candidate_counts": profiled_counts,
            "unprofiled_hashes": unprofiled_hashes,
            "profiled_hashes": profiled_hashes,
            "profiled_matches_unprofiled": fingerprints_equal,
        },
        "machine": machine_info(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=int, default=DEFAULT_TARGETS,
                        help=f"Rotating target requests (default: {DEFAULT_TARGETS}, max: {MAX_TARGETS}).")
    parser.add_argument("--output", type=Path, default=Path("artifacts/query-profile-before.json"),
                        help="Write the JSON artifact here (default: artifacts/query-profile-before.json).")
    args = parser.parse_args(argv)
    report = profile_queries(targets=args.targets)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    timing = report["timing_ms"]
    unprofiled = timing["unprofiled_warm_requests"]
    integrity = report["full_result_integrity"]
    print(
        "query profile: "
        f"cold={timing['cold_indexed_engine_construction']:.1f}ms "
        f"warm_total={unprofiled['total']:.1f}ms "
        f"warm_p95={unprofiled['p95']:.1f}ms "
        f"cprofile={timing['cprofile_warm_requests']['total']:.1f}ms "
        f"requests={report['workload']['rotating_requests']} "
        f"candidates={integrity['expected_candidate_count']} "
        f"full_results_equal={integrity['profiled_matches_unprofiled']}"
    )
    print(f"artifact: {args.output}")
    if not integrity["engine_returns_all_candidates"] or not integrity["profiled_matches_unprofiled"]:
        print("query profile failed full-result integrity checks", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
