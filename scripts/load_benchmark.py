#!/usr/bin/env python3
"""Measure complete structured-query requests through a loopback HTTP server.

The benchmark deliberately exercises the same path as an operator request:
JSON encoding, socket I/O, the HTTP handler, application caches, the immutable
engine, result shaping, JSON encoding, and the client response.  It does not
send natural-language questions to a model.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import platform
import random
import resource
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

# Running ``python scripts/load_benchmark.py`` does not put the repository root
# on sys.path.  Keep the script directly runnable without installing a wheel.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crew_evolve.app import App  # noqa: E402
from crew_evolve.engine import Engine  # noqa: E402
from crew_evolve.server import Server  # noqa: E402
from crew_evolve.store import DEMO_POLICY, Store  # noqa: E402


DEFAULT_TARGETS = 64
HTTP_TIMEOUT_SECONDS = 60


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Return nearest-rank percentile values in milliseconds."""
    if not values:
        return None
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


# A short alias is convenient for callers that use the statistical term.
quantile = percentile


def _iso(start: datetime, hours: int) -> tuple[str, str]:
    end = start + timedelta(hours=hours)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


def synthetic_workload(crew_count: int, history_per_crew: int, *, seed: int = 7301,
                       target_count: int = DEFAULT_TARGETS) -> dict[str, dict[str, Any]]:
    """Create a valid, deterministic roster with many independent target plans.

    Each crew member gets ``history_per_crew`` private duties.  This avoids
    duplicate assignment slots while producing 50,000 assignments at the
    recommended 10,000 crew and five history duties.  The first crew member is
    intentionally a valid captain candidate for every target so the update
    invalidation check always has a candidate to assign.
    """
    if type(crew_count) is not int or crew_count < 1:
        raise ValueError("crew must be a positive integer")
    if type(history_per_crew) is not int or history_per_crew < 1:
        raise ValueError("history must be a positive integer")
    if type(target_count) is not int or target_count < 32:
        raise ValueError("target_count must be at least 32")

    rng = random.Random(seed)
    target_start = datetime(2026, 10, 12, 8, tzinfo=timezone.utc)
    crew: list[dict[str, Any]] = []
    duties: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []

    # Unassigned targets exercise plan-key cache behaviour.  Thirty-two are
    # required because the application result cache intentionally holds sixteen.
    for target_index in range(target_count):
        target_id = f"TARGET-{target_index:04d}"
        start, end = _iso(target_start + timedelta(hours=target_index * 12), 8)
        duties.append({
            "duty_id": target_id,
            "report_at": start,
            "release_at": end,
            "start_base": "DEL",
            "end_base": "DEL",
            "aircraft": ["A320"],
            "required_roles": ["captain"],
            "_record": len(duties) + 1,
        })

    # History is intentionally comfortably before the target window.  Duties
    # are still real intervals and checks still walk them on every coverage.
    for crew_index in range(crew_count):
        role = "captain" if crew_index % 5 != 0 else "first_officer"
        # Make the first member the guaranteed update candidate.
        if crew_index == 0:
            role = "captain"
        aircraft = ["A320"] if crew_index % 11 != 0 or crew_index == 0 else ["B737"]
        base = "DEL" if crew_index % 7 != 0 or crew_index == 0 else "BOM"
        member = {
            "crew_id": f"C-{crew_index:06d}",
            "name": f"Crew {crew_index:06d}",
            "base": base,
            "role": role,
            "aircraft": aircraft,
            "available": crew_index % 13 != 0 or crew_index == 0,
            "_record": crew_index + 1,
        }
        crew.append(member)
        for history_index in range(history_per_crew):
            # Private duty IDs make assignments valid and preserve a moderate
            # amount of history for every candidate.  Tiny jitter prevents all
            # records from having the exact same timestamp while keeping rest
            # and overlap behaviour deterministic.
            days_before = 16 + (history_per_crew - history_index) * 3
            jitter_hours = rng.randrange(0, 3)
            start_at = target_start - timedelta(days=days_before, hours=jitter_hours)
            start, end = _iso(start_at, 8)
            duty_id = f"H-{crew_index:06d}-{history_index:03d}"
            duties.append({
                "duty_id": duty_id,
                "report_at": start,
                "release_at": end,
                "start_base": base,
                "end_base": base,
                "aircraft": list(aircraft),
                "required_roles": [role],
                "_record": len(duties) + 1,
            })
            assignments.append({
                "crew_id": member["crew_id"],
                "duty_id": duty_id,
                "role": role,
                "_record": len(assignments) + 1,
            })

    def table(records: list[dict[str, Any]], source: str) -> dict[str, Any]:
        return {"records": records, "source": source, "mapping": {}}

    return {
        "crew": table(crew, "Synthetic load benchmark crew"),
        "duties": table(duties, "Synthetic load benchmark duties"),
        "assignments": table(assignments, "Synthetic load benchmark assignments"),
    }


def seed_store(store: Store, datasets: dict[str, dict[str, Any]], strategy: str = "indexed") -> None:
    """Seed a fresh store without measuring import parsing or SQLite writes."""
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for kind in ("crew", "duties", "assignments"):
            payload = copy.deepcopy(datasets[kind])
            db.execute("INSERT OR REPLACE INTO datasets VALUES (?, ?)", (kind, json.dumps(payload)))
        Store.put(db, "strategy", strategy)
        Store.put(db, "revision", 0)


def http_json(base: str, token: str, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any], float]:
    started = time.perf_counter()
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json", "X-Workspace-Token": token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read()
            result = json.loads(raw)
            return response.status, result, (time.perf_counter() - started) * 1000
    except urllib.error.HTTPError as exc:
        try:
            raw_error = exc.read()
            result = json.loads(raw_error) if raw_error else {"error": str(exc)}
        except (ValueError, json.JSONDecodeError):
            result = {"error": str(exc)}
        return exc.code, result, (time.perf_counter() - started) * 1000
    except Exception as exc:  # A failed request is part of the measured error count.
        return 0, {"error": f"{type(exc).__name__}: {exc}"}, (time.perf_counter() - started) * 1000


def http_get(base: str, path: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(base + path, method="GET")
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return response.status, json.loads(response.read())


def _client_call(base: str, token: str, plan: dict[str, Any]) -> dict[str, Any]:
    status, body, latency = http_json(base, token, "/api/query", {"plan": plan})
    return {"status": status, "body": body, "latency_ms": latency}


def reset_result_cache(app: App) -> None:
    """Start a scenario with no inherited structured-result entries.

    The immutable engine remains warm after the cold request, so the scenario
    measures query/result caching without rebuilding the data index each time.
    """
    with app.cache_lock:
        app.cache.clear()


def run_requests(base: str, token: str, plans: Sequence[dict[str, Any]], clients: int) -> dict[str, Any]:
    """Run plans with at most ``clients`` in flight and report request wall time."""
    if clients < 1:
        raise ValueError("clients must be positive")
    started = time.perf_counter()
    latencies: list[float] = []
    sample_observations: list[dict[str, Any]] = []
    successes = 0
    cache_hits = 0
    statuses: dict[str, int] = {}

    def consume(observation: dict[str, Any]) -> None:
        nonlocal successes, cache_hits
        latencies.append(float(observation["latency_ms"]))
        status = observation["status"]
        statuses[str(status)] = statuses.get(str(status), 0) + 1
        body = observation["body"]
        if status == 200 and "error" not in body:
            successes += 1
            cache_hits += int(bool(body.get("metrics", {}).get("cache_hit")))
        if len(sample_observations) < 3:
            sample_observations.append(observation)

    if clients == 1:
        for plan in plans:
            consume(_client_call(base, token, plan))
    else:
        # Keep only ``clients`` futures in flight.  A full response is released
        # as soon as its scalar metrics are consumed, except for three samples
        # needed by the correctness oracle.
        with ThreadPoolExecutor(max_workers=clients, thread_name_prefix="load-client") as pool:
            plan_iterator = iter(plans)
            pending = {pool.submit(_client_call, base, token, next(plan_iterator))
                       for _ in range(min(clients, len(plans)))}
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    consume(future.result())
                    try:
                        pending.add(pool.submit(_client_call, base, token, next(plan_iterator)))
                    except StopIteration:
                        pass
    wall_seconds = max(time.perf_counter() - started, 1e-9)
    queue_wall = {
        "p50": _round_or_none(percentile(latencies, 0.50)),
        "p95": _round_or_none(percentile(latencies, 0.95)),
        "p99": _round_or_none(percentile(latencies, 0.99)),
    }
    return {
        "requests": len(plans),
        "responses_counted": len(latencies),
        "response_samples": len(sample_observations),
        "clients": clients,
        "wall_seconds": round(wall_seconds, 6),
        "latency_definition": "client request wall time from JSON request start through response parse; closed-loop at most clients in flight",
        "queue_wall_ms": queue_wall,
        "p50_ms": queue_wall["p50"],
        "p95_ms": queue_wall["p95"],
        "p99_ms": queue_wall["p99"],
        "throughput_rps": round(successes / wall_seconds, 3),
        "error_count": len(plans) - successes,
        "statuses": statuses,
        "cache_hits": cache_hits,
        "cache_hit_rate": round(cache_hits / successes, 6) if successes else 0.0,
        "model_calls": 0,
        "latency_scope": "structured plans over real loopback HTTP; no natural-language model calls",
        "observations": sample_observations,
    }


def _round_or_none(value: float | None) -> float | None:
    return round(value, 3) if value is not None else None


def _stable_response(body: dict[str, Any]) -> dict[str, Any]:
    """Remove timing and cache metadata before correctness comparisons."""
    return {
        key: copy.deepcopy(body[key])
        for key in ("action", "reply", "result", "revision", "plan")
        if key in body
    }


def _compact_response(body: dict[str, Any]) -> dict[str, Any]:
    """Keep report evidence bounded while retaining a reproducible result hash."""
    compact = _stable_response(body)
    result = compact.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("candidates"), list):
        return compact
    candidates = result.pop("candidates")
    encoded = json.dumps(candidates, sort_keys=True, separators=(",", ":")).encode()
    result["candidate_sha256"] = hashlib.sha256(encoded).hexdigest()
    result["candidate_sample"] = candidates[:2]
    result["candidate_sample_count"] = len(result["candidate_sample"])
    return compact


def expected_response(engine: Engine, plan: dict[str, Any], revision: int) -> dict[str, Any]:
    """Shape an independent Engine result exactly as App.execute does."""
    action = plan.get("action")
    if action == "coverage":
        result = engine.coverage(plan.get("duty_id"), plan.get("role"))
        count = result["passing"]
        subject = "crew member passes" if count == 1 else "crew members pass"
        reply = f"{count} {subject} the configured checks for {plan['duty_id']} / {plan['role']}."
        result["candidate_count"] = len(result["candidates"])
        result["candidates"] = result["candidates"][:100]
        result["truncated"] = result["candidate_count"] > 100
    else:
        raise ValueError("expected_response currently supports coverage plans only")
    return {"action": action, "reply": reply, "result": result, "revision": revision,
            "plan": {k: plan[k] for k in ("action", "duty_id", "role") if k in plan}}


def _rss_high_water_mb() -> float:
    # Linux reports KiB; macOS reports bytes.  ru_maxrss is a process high-water
    # mark, so it includes memory retained after synthetic seeding.
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return round(value / (1024 * 1024), 3)
    return round(value / 1024, 3)


def _code_hash() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True, timeout=2,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _git_dirty() -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT,
            check=True, capture_output=True, text=True, timeout=3,
        )
        return bool(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return None


def _source_fingerprint() -> str:
    """Hash benchmark and request-path sources in a stable path order."""
    paths = (
        Path(__file__), ROOT / "crew_evolve" / "app.py", ROOT / "crew_evolve" / "server.py",
        ROOT / "crew_evolve" / "engine.py", ROOT / "crew_evolve" / "store.py",
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
        "code_hash": _code_hash(),
        "git_dirty": _git_dirty(),
        "source_fingerprint": _source_fingerprint(),
    }


def _parse_clients(value: str | int | Iterable[int]) -> list[int]:
    if isinstance(value, int):
        values = [value]
    elif isinstance(value, str):
        try:
            values = [int(part.strip()) for part in value.split(",") if part.strip()]
        except ValueError:
            raise ValueError("clients must be an integer or comma-separated integers") from None
    else:
        values = list(value)
    if not values or any(type(item) is not int or item < 1 for item in values):
        raise ValueError("clients must contain positive integers")
    return list(dict.fromkeys(values))


def _oracle_report(datasets: dict[str, dict[str, Any]], target_ids: Sequence[str],
                   plans: Sequence[dict[str, Any]], revision: int) -> dict[str, Any]:
    """Run a bounded reference correctness gate outside the large load loop."""
    # Full reference coverage is quadratic in crew/history.  Keep it bounded,
    # while still comparing complete HTTP-shaped responses on a real workload.
    oracle_crew = min(len(datasets["crew"]["records"]), 96)
    if oracle_crew < len(datasets["crew"]["records"]):
        oracle = synthetic_workload(oracle_crew, min(3, len(datasets["assignments"]["records"]) // max(1, len(datasets["crew"]["records"]))))
    else:
        oracle = datasets
    reference = Engine(oracle, DEMO_POLICY, "reference")
    indexed = Engine(oracle, DEMO_POLICY, "indexed")
    checked: list[dict[str, Any]] = []
    oracle_targets = [
        duty["duty_id"] for duty in oracle["duties"]["records"]
        if str(duty.get("duty_id", "")).startswith("TARGET-")
    ] or list(target_ids)
    for target_id in list(oracle_targets)[:3]:
        plan = {"action": "coverage", "duty_id": target_id, "role": "captain"}
        expected = expected_response(reference, plan, revision)
        actual = expected_response(indexed, plan, revision)
        checked.append({"target": target_id, "equal": _stable_response(expected) == _stable_response(actual)})
    return {
        "strategy": "reference",
        "crew_checked": oracle_crew,
        "large_reference_skipped": oracle_crew < len(datasets["crew"]["records"]),
        "samples": checked,
        "passed": all(item["equal"] for item in checked),
        "note": "Reference checks are bounded separately; the 10k/50k load does not run reference coverage for every request.",
    }


def _http_oracle_report(datasets: dict[str, dict[str, Any]], observations: Sequence[dict[str, Any]],
                        revision: int, *, engine: Engine | None = None) -> dict[str, Any]:
    """Compare a few complete HTTP responses with independently shaped output."""
    crew_count = len(datasets["crew"]["records"])
    # Reference coverage is deliberately bounded.  For a large run, an
    # indexed direct engine still verifies every response field without making
    # the benchmark accidentally spend minutes in the quadratic reference.
    strategy = "reference" if crew_count <= 96 else "indexed"
    engine = engine or Engine(datasets, DEMO_POLICY, strategy)
    checks: list[dict[str, Any]] = []
    for observation in list(observations)[:3]:
        body = observation.get("body", {})
        plan = body.get("plan")
        if observation.get("status") != 200 or not isinstance(plan, dict):
            checks.append({"equal": False, "reason": "request did not return a structured response"})
            continue
        expected = expected_response(engine, plan, revision)
        checks.append({
            "target": plan.get("duty_id"),
            "equal": _stable_response(body) == _stable_response(expected),
            "revision_equal": body.get("revision") == revision,
            "strategy": strategy,
        })
    return {
        "samples": checks,
        "passed": bool(checks) and all(item["equal"] and item["revision_equal"] for item in checks),
        "reference_for_full_workload": strategy == "reference",
        "note": "Full response fields are compared; large workloads use indexed direct shaping to avoid a quadratic reference scan.",
    }


def benchmark(crew: int = 100, history: int = 5, requests: int = 100,
              clients: int | str | Iterable[int] = 1, *, seed: int = 7301,
              progress: Any = None) -> dict[str, Any]:
    """Run cold, rotating-cache, repeated-cache, and invalidation measurements."""
    for name, value in (("crew", crew), ("history", history), ("requests", requests)):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    client_counts = _parse_clients(clients)
    def emit(message: str) -> None:
        if progress is not None:
            progress(message)

    datasets = synthetic_workload(crew, history, seed=seed)
    target_ids = [
        duty["duty_id"] for duty in datasets["duties"]["records"]
        if str(duty.get("duty_id", "")).startswith("TARGET-")
    ]
    plans = [{"action": "coverage", "duty_id": target_id, "role": "captain"} for target_id in target_ids]

    with tempfile.TemporaryDirectory(prefix="crew-load-") as directory:
        store = Store(Path(directory) / "workspace.sqlite")
        seed_store(store, datasets)
        rss_after_seed = _rss_high_water_mb()
        app = App(store)
        server = Server(("127.0.0.1", 0), app)
        thread = threading.Thread(target=server.serve_forever, name="crew-load-server", daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            # The first structured request builds the immutable engine.  Keep it
            # separate from warm-cache measurements and report its whole HTTP
            # latency as the cold initialization path.
            cold_plan = plans[0]
            cold_status, cold_body, cold_latency = http_json(base, server.token, "/api/query", {"plan": cold_plan})
            old_revision = int(cold_body.get("revision", 0)) if cold_status == 200 else 0
            emit(f"cold initialization complete (status={cold_status})")

            # Rotate 32 targets.  The app cache holds 16 plans, so a full cycle
            # cannot remain resident and repeated misses are intentional.
            rotating_plans = [plans[1 + (index % (len(plans) - 1)) % min(32, len(plans) - 1)] for index in range(requests)]
            repeated_plan = plans[1]
            repeated_plans = [repeated_plan for _ in range(requests)]
            run_reports: list[dict[str, Any]] = []
            for client_count in client_counts:
                reset_result_cache(app)
                rotating = run_requests(base, server.token, rotating_plans, client_count)
                emit(f"clients={client_count} rotating complete ({rotating['requests']} requests)")
                reset_result_cache(app)
                repeated = run_requests(base, server.token, repeated_plans, client_count)
                emit(f"clients={client_count} repeated complete ({repeated['requests']} requests)")
                run_reports.append({
                    "clients": client_count,
                    "rotating": rotating,
                    "repeated": repeated,
                    "cache_isolation": {
                        "result_cache_reset_before_each_scenario": True,
                        "engine_cache_retained_after_cold_initialization": True,
                    },
                })

            # Verify the current application response against a direct reference
            # engine on a bounded workload before mutating the workspace.
            oracle = _oracle_report(datasets, target_ids, rotating_plans[:3], old_revision)
            oracle_strategy = "reference" if crew <= 96 else "indexed"
            http_oracle_engine = Engine(datasets, DEMO_POLICY, oracle_strategy)
            http_oracle_runs = []
            for run in run_reports:
                http_oracle_runs.append({
                    "clients": run["clients"],
                    "rotating": _http_oracle_report(
                        datasets, run["rotating"]["observations"], old_revision,
                        engine=http_oracle_engine,
                    ),
                    "repeated": _http_oracle_report(
                        datasets, run["repeated"]["observations"], old_revision,
                        engine=http_oracle_engine,
                    ),
                })
            http_oracle = {
                "runs": http_oracle_runs,
                "passed": all(item[scenario]["passed"] for item in http_oracle_runs for scenario in ("rotating", "repeated")),
                "reference_for_full_workload": oracle_strategy == "reference",
                "samples": http_oracle_runs[0]["rotating"]["samples"] if http_oracle_runs else [],
                "note": "Each client/scenario run compares complete sampled HTTP responses; large workloads use indexed direct shaping to avoid a quadratic reference scan.",
            }

            # Assign the guaranteed valid candidate.  The old revision must be
            # rejected, and the next query must show the new revision and a
            # cache miss even if this plan was previously hot.
            candidate_id = datasets["crew"]["records"][0]["crew_id"]
            assignment_status, assignment_body, _ = http_json(
                base, server.token, "/api/assign",
                {"crew_id": candidate_id, "duty_id": cold_plan["duty_id"], "role": "captain", "revision": old_revision},
            )
            stale_status, stale_body, _ = http_json(
                base, server.token, "/api/assign",
                {"crew_id": candidate_id, "duty_id": cold_plan["duty_id"], "role": "captain", "revision": old_revision},
            )
            current_revision = int(assignment_body.get("revision", old_revision)) if assignment_status == 200 else old_revision
            invalidated_status, invalidated_body, invalidated_latency = http_json(
                base, server.token, "/api/query", {"plan": cold_plan}
            )
            invalidation = {
                "assignment_status": assignment_status,
                "assignment_revision": current_revision,
                "stale_revision_status": stale_status,
                "stale_revision_rejected": stale_status == 400 and
                                           "workspace changed" in str(stale_body.get("error", "")).casefold(),
                "stale_revision_error": stale_body.get("error"),
                "query_status": invalidated_status,
                "query_revision": invalidated_body.get("revision"),
                "current_version_expected": current_revision,
                "query_cache_hit": invalidated_body.get("metrics", {}).get("cache_hit"),
                "query_latency_ms": round(invalidated_latency, 3),
                "passed": assignment_status == 200 and stale_status == 400 and
                          "workspace changed" in str(stale_body.get("error", "")).casefold() and
                          invalidated_status == 200 and invalidated_body.get("revision") == current_revision and
                          invalidated_body.get("metrics", {}).get("cache_hit") is False,
            }
            emit(f"revision invalidation complete (passed={invalidation['passed']})")
            # Full response bodies are useful for a few correctness samples,
            # but retaining every 10k-candidate response would make the JSON
            # report larger than the benchmark itself.
            for run in run_reports:
                for scenario in ("rotating", "repeated"):
                    observations = run[scenario].pop("observations")
                    run[scenario]["response_samples"] = [
                        {"status": item["status"], "latency_ms": round(item["latency_ms"], 3),
                         "response": _compact_response(item["body"])}
                        for item in observations[:3]
                    ]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=10)

    return {
        "benchmark": "full-request-load",
        "model_calls": 0,
        "request_kind": "structured plans (no natural-language latency)",
        "workload": {"crew": crew, "history_per_crew": history,
                      "assignments": len(datasets["assignments"]["records"]),
                      "duties": len(datasets["duties"]["records"]),
                      "rotating_targets": min(32, len(target_ids) - 1)},
        "cold_initialization": {
            "status": cold_status,
            "latency_ms": round(cold_latency, 3),
            "cache_hit": cold_body.get("metrics", {}).get("cache_hit"),
            "scope": "first complete structured-plan HTTP request, including immutable engine construction",
        },
        "runs": run_reports,
        "cache_isolation": {
            "result_cache_reset_before_each_scenario": True,
            "engine_cache_retained_after_cold_initialization": True,
            "note": "Warm scenarios compare result-cache behavior with the immutable engine retained from cold initialization.",
        },
        "correctness_oracle": oracle,
        "http_response_oracle": http_oracle,
        "invalidation": invalidation,
        "memory": {
            "process_rss_high_water_mb": _rss_high_water_mb(),
            "rss_after_seed_mb": rss_after_seed,
            "source": "resource.getrusage(RUSAGE_SELF).ru_maxrss; Linux KiB high-water mark includes seeded data retained by this process",
        },
        "machine": machine_info(),
        "requests_note": "The default is a quick 100-request run. Use --requests 1000 for the required load run; rotating and repeated scenarios each use that count.",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crew", type=int, default=100, help="Synthetic crew members (default: 100).")
    parser.add_argument("--history", type=int, default=5, help="Assigned history duties per crew member (default: 5).")
    parser.add_argument("--requests", type=int, default=100, help="Requests per warm scenario (default: 100; use 1000 for load).")
    parser.add_argument("--clients", default="1", help="Concurrent clients, or comma-separated values such as 1,4 (default: 1).")
    parser.add_argument("--output", type=Path, default=Path("artifacts/load_benchmark.json"),
                        help="Write JSON report here as well as stdout (default: artifacts/load_benchmark.json).")
    args = parser.parse_args(argv)
    report = benchmark(
        args.crew, args.history, args.requests, args.clients,
        progress=lambda message: print(message, file=sys.stderr, flush=True),
    )
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    def measured_summary(scenario: dict[str, Any]) -> dict[str, Any]:
        return {key: scenario[key] for key in (
            "requests", "clients", "latency_definition", "queue_wall_ms", "p50_ms", "p95_ms", "p99_ms",
            "throughput_rps", "error_count", "cache_hits", "cache_hit_rate", "model_calls",
        ) if key in scenario}

    # Keep terminal output useful for a 1,000-request run. The output artifact
    # retains compact response evidence and hashes for sampled candidate lists.
    stdout_report = {
        "benchmark": report["benchmark"],
        "workload": report["workload"],
        "cold_initialization": report["cold_initialization"],
        "runs": [{"clients": run["clients"],
                  "rotating": measured_summary(run["rotating"]),
                  "repeated": measured_summary(run["repeated"])} for run in report["runs"]],
        "correctness_oracle": report["correctness_oracle"],
        "http_response_oracle": report["http_response_oracle"],
        "invalidation": report["invalidation"],
        "memory": report["memory"],
        "machine": report["machine"],
    }
    print(json.dumps(stdout_report, indent=2, sort_keys=True))
    failures = report_failures(report)
    if failures:
        print("Benchmark failed: " + "; ".join(failures), file=sys.stderr)
        return 1
    return 0


# Keep a descriptive API name for callers embedding the harness in a test or
# a local measurement notebook.
run_benchmark = benchmark


def report_failures(report: dict[str, Any]) -> list[str]:
    """Return gate failures that should make a command-line run fail."""
    failures: list[str] = []
    cold = report.get("cold_initialization", {})
    if cold.get("status") != 200:
        failures.append(f"cold initialization HTTP status {cold.get('status')}")
    for run in report.get("runs", []):
        for scenario in ("rotating", "repeated"):
            details = run.get(scenario, {})
            if details.get("error_count", 0):
                failures.append(f"{run.get('clients')} clients {scenario} errors={details['error_count']}")
    if not report.get("correctness_oracle", {}).get("passed", False):
        failures.append("reference/indexed correctness oracle failed")
    if not report.get("http_response_oracle", {}).get("passed", False):
        failures.append("sampled HTTP response oracle failed")
    if not report.get("invalidation", {}).get("passed", False):
        failures.append("revision invalidation check failed")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
