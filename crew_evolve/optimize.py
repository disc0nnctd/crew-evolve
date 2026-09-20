"""An algorithm-selection agent with a correctness gate and measured scores.

Candidates are reviewed algorithms, not model-generated executable code. The
agent explores this catalog, benchmarks independent workloads, and selects a
strategy only after every result agrees with the slow reference. No roster or
policy is changed. Timings include index construction and result generation.
"""

import gc
import math
import platform
import random
import statistics
import time
import tracemalloc
from datetime import datetime, timedelta, timezone

from .engine import Engine
from .store import DEMO_POLICY

CATALOG = {
    "reference": {"name": "Full scans", "description": "Scan assignment history for each crew member; independently sum each rolling window."},
    "indexed": {"name": "Assignment indexes + time sweep", "description": "Index assignments by crew and position; integrate time events for rolling-hour queries."},
}


def workload(size, seed=1):
    rng = random.Random(seed)
    target_start = datetime(2026, 10, 12, 8, tzinfo=timezone.utc)
    duties = [{"duty_id": "TARGET", "report_at": target_start.isoformat(),
               "release_at": (target_start + timedelta(hours=8)).isoformat(),
               "start_base": "DEL", "end_base": "DEL", "aircraft": ["A320"], "required_roles": ["captain"], "_record": 1}]
    for i in range(28):
        start = target_start + timedelta(hours=rng.randint(-220, 100))
        duties.append({"duty_id": f"H-{i}", "report_at": start.isoformat(),
                       "release_at": (start + timedelta(hours=rng.randint(2, 12))).isoformat(),
                       "start_base": "DEL", "end_base": "DEL", "aircraft": ["A320"],
                       "required_roles": ["captain"], "_record": i + 2})
    crew, assignments = [], []
    # Each crew has individual duty IDs so one-position-per-duty stays valid.
    expanded = [duties[0]]
    for i in range(size):
        cid = f"C-{i:06d}"
        crew.append({"crew_id": cid, "name": f"Crew {i:06d}", "base": "DEL" if i % 7 else "BOM",
                     "role": "captain" if i % 5 else "first_officer", "aircraft": ["A320"] if i % 11 else ["B737"],
                     "available": i % 13 != 0, "_record": i + 1})
        for j in range(2):
            duty = dict(duties[rng.randrange(1, len(duties))])
            duty["duty_id"] = f"H-{i}-{j}"
            duty["required_roles"] = [crew[-1]["role"]]
            expanded.append(duty)
            assignments.append({"crew_id": cid, "duty_id": duty["duty_id"], "role": crew[-1]["role"], "_record": len(assignments) + 1})
    return {k: {"records": v, "source": "Synthetic benchmark", "mapping": {}}
            for k, v in (("crew", crew), ("duties", expanded), ("assignments", assignments))}


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def benchmark(sizes=(100, 500, 1500), repeats=5, progress=None):
    if not sizes or any(type(n) is not int or not 1 <= n <= 5000 for n in sizes) or not 3 <= repeats <= 20:
        raise ValueError("Use 3–20 repetitions and crew sizes between 1 and 5000.")
    results, all_equal = [], True
    for size in sizes:
        datasets = workload(size, seed=7301 + size)
        expected = Engine(datasets, DEMO_POLICY, "reference").coverage("TARGET", "captain")
        for strategy in CATALOG:
            if progress:
                progress(f"Measuring {strategy} with {size} crew")
            latencies, matches = [], []
            for _ in range(repeats):
                started = time.perf_counter()
                actual = Engine(datasets, DEMO_POLICY, strategy).coverage("TARGET", "captain")
                latencies.append((time.perf_counter() - started) * 1000)
                matches.append(actual == expected)
            # Memory is measured separately; allocation tracing changes latency.
            gc.collect()
            tracemalloc.start()
            Engine(datasets, DEMO_POLICY, strategy).coverage("TARGET", "captain")
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            all_equal = all_equal and all(matches)
            results.append({"size": size, "assignments": size * 2, "strategy": strategy,
                            "p50_ms": round(statistics.median(latencies), 3),
                            "p95_ms": round(percentile(latencies, .95), 3),
                            "queries_per_second": round(1000 / statistics.mean(latencies), 2),
                            "peak_mb": round(peak / (1024 * 1024), 3),
                            "correctness_score": round(100 * sum(matches) / len(matches), 2),
                            "samples": repeats})
    # Different seeds and sizes are withheld from the timing/selection workloads.
    holdout = []
    for seed, size in ((99017, 37), (41123, 213), (82507, 401)):
        datasets = workload(size, seed)
        expected = Engine(datasets, DEMO_POLICY, "reference").coverage("TARGET", "captain")
        actual = Engine(datasets, DEMO_POLICY, "indexed").coverage("TARGET", "captain")
        holdout.append({"seed": seed, "crew": size, "equal": actual == expected})
    all_equal = all_equal and all(r["equal"] for r in holdout)
    scores = []
    for strategy in CATALOG:
        rows = sorted([r for r in results if r["strategy"] == strategy], key=lambda x: x["size"])
        first, last = rows[0], rows[-1]
        scores.append({"strategy": strategy, "geomean_p95_ms": round(math.exp(statistics.mean(math.log(max(.001, r["p95_ms"])) for r in rows)), 3),
                       "latency_growth": round(last["p95_ms"] / max(first["p95_ms"], .001), 3),
                       "data_growth": last["size"] / first["size"],
                       "under_200ms": sum(r["p95_ms"] <= 200 for r in rows), "workloads": len(rows)})
    selected = min(scores, key=lambda x: x["geomean_p95_ms"])["strategy"] if all_equal else "reference"
    ref = next(s for s in scores if s["strategy"] == "reference")
    chosen = next(s for s in scores if s["strategy"] == selected)
    return {"selected": selected, "correctness_gate": all_equal, "results": results, "scores": scores, "holdout": holdout,
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "speedup": round(ref["geomean_p95_ms"] / max(chosen["geomean_p95_ms"], .001), 2),
            "machine": {"python": platform.python_version(), "platform": platform.system(), "processor": platform.machine()},
            "method": "Cold engine construction + complete coverage results; sequential single-process calls; p95 is nearest-rank; memory excludes input data; no cache hits. Timings are local measurements, not a production SLA.",
            "selection_rule": "Exact result equality on all measured and held-out workloads, then lowest geometric-mean p95 latency."}


def main():
    import argparse
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default="100,500,1500")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = benchmark(tuple(int(n) for n in args.sizes.split(",")), args.repeats)
    rendered = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
