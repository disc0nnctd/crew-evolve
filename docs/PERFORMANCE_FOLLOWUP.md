# Changing-duty query follow-up

This follow-up profiles the missed changing-duty latency target and makes a
small change to the indexed engine. The repository remains private. These are
local synthetic measurements, not a real-time service guarantee.

## Change and correctness

The indexed snapshot now retains assignment-integrity issues and dataset source
defaults instead of recomputing them on every query. It also records the earliest
start and latest end in each crew history. If all history is separated from the
target by at least seven days, the rolling-hours calculation can return the
target's clipped duration directly. Other histories use the existing sweep.
Overlap, rest, location, qualifications, availability, explanations, and ranking
still run for every crew member. No candidate is sampled or omitted by the engine.

The reference engine retains its independent assignment scan and rolling-window
calculation. The snapshot-cache test helper previously compared against the
currently selected strategy; it now always uses the reference strategy. A test
that deliberately corrupts indexed output verifies that this comparison catches
the discrepancy.

Additional checks cover exact rest/overlap/seven-day boundaries, long targets,
already-assigned targets, tied rankings, reason/source order, nested result
mutation, and mutation of returned integrity issues. Every complete result from
the before and after profile has the same SHA-256 hash, including all candidates
and source evidence. These hashes establish before/after equality on the measured
workload; they do not replace the separate reference comparisons.

## Direct engine profile

Both runs use the same profiler, seed, 10,000 crew, five historical assignments
per crew, and eight rotating target duties. They construct one indexed engine,
exclude one warm-up call, and time complete coverage results with garbage
collection enabled. Hashing and serialization are outside the timing and profile.
Profiling runs are separate from the unprofiled wall-time samples.

| Measurement | Before | After |
| --- | ---: | ---: |
| Warm mean | 295.790 ms | 228.742 ms |
| Warm median | 244.531 ms | 164.883 ms |
| Warm nearest-rank p95 | 487.376 ms | 414.556 ms |
| Engine construction, one sample | 1828.098 ms | 1826.440 ms |
| Complete outputs compared | 8 | 8 |
| Candidates per output | 10,000 | 10,000 |

The measured warm mean fell by about 23%. With only eight samples, p95 is the
largest sample, not a stable tail-latency estimate. The single construction
samples do not establish a cold-start improvement. The synthetic history is far
before the target, favoring the safe history shortcut; histories close to the
target still use the sweep. General production speedups are unproven.

The profiler identified repeated source construction, history calculations, and
integrity scans. Full candidate construction remains a major cost. Raw
[before](reports/query-profile-before.json) and
[after](reports/query-profile-after.json) reports contain individual timings,
hotspots, result hashes, garbage-collection settings, platform details, and source
fingerprints. Both report the parent commit because they ran with local changes;
the source fingerprint distinguishes the engine versions. The before engine is
from commit `1d1ddf7d4766a56594a59832baf32e413c0ca2fb`.

Reproduce the direct profile with:

```bash
python3 scripts/profile_queries.py --output artifacts/query-profile.json
```

## Complete local web requests

A shorter follow-up load run used 100 requests per scenario with 10,000 crew,
50,000 assignments, and 32 rotating target duties. It sends structured plans
through the real loopback HTTP server and measures through response parsing.
It does not measure language-model interpretation, import parsing, or external
network latency. The full engine computes all candidates before the application
returns its existing first-100 view.

| Clients | Pattern | p50 | p95 | p99 | Requests/second | Result cache hits |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | Changing duty | 269.308 ms | 580.461 ms | 887.220 ms | 2.934 | 0% |
| 1 | Repeated duty | 9.449 ms | 11.684 ms | 12.445 ms | 82.357 | 99% |
| 4 | Changing duty | 1440.952 ms | 1816.955 ms | 2023.596 ms | 2.737 | 0% |
| 4 | Repeated duty | 36.295 ms | 145.236 ms | 1432.890 ms | 39.848 | 96% |

All 400 warm requests succeeded. The bounded independent reference comparisons,
sampled web responses, assignment update, stale-write rejection, and snapshot
invalidation checks passed. Large response samples use the direct indexed
engine; the independent reference check is bounded to 96 crew. Neither is an
independent reference evaluation of every large request.

The cold web request took 2745.149 ms; the first request after an assignment
change took 3160.616 ms. Process memory high-water was 446.086 MiB, including
the benchmark client, seeded data, server, and validation work in one process.
The seed-stage high-water was 310.734 MiB. These are process high-water readings,
not isolated server allocation measurements.

**The changing-duty p95 target of 200 ms remains unmet.** This short run does not
replace the earlier [1,000-request-per-scenario run](reports/load-10000.json).
Different sample counts and cache-miss proportions make their tail percentiles
unsuitable for a paired speedup claim. The measured paired comparison above is
the direct engine profile. No stable production concurrency improvement is claimed.

The [raw follow-up report](reports/load-10000-followup.json) retains scenario
measurements, sampled responses, and machine/source metadata. Reproduce it with:

```bash
python3 scripts/load_benchmark.py --crew 10000 --history 5 --requests 100 --clients 1,4 --output artifacts/load-10000-followup.json
```

## Verification

`python3 -m unittest discover -q` ran 141 tests: 140 passed, one optional cached
model test skipped, none failed. The final shared-index assertions also passed
the 15-test engine-scaling/snapshot suite. Luna implemented the engine change;
Terra reviewed it without a remaining blocker. The frozen adaptation sources
still match their recorded hashes, and that final evaluation was not rerun.
Earlier browser/install/model checks were not rerun for this engine-only change.
The [verification record](reports/performance-followup-verification.json)
includes report hashes and command details.

The next performance work should measure ways to reduce per-candidate result
construction and concurrent duplicate computation while retaining exact
eligibility, counts, ranking, explanations, and revision checks. Warm-query
improvements do not remove the cost of rebuilding a snapshot after a change.
