# Scaling through measured choices

The current engine keeps a correctness-first reference strategy and a reviewed
indexed strategy. Both produce the same complete candidate records, exclusions,
reasons, ordering, and source references before a strategy can be selected.
The benchmark protocol remains in review; this document describes design
boundaries rather than achieved performance targets.

## Current design

- `Engine` deep-copies datasets and policy into an immutable query snapshot.
- The indexed strategy groups assignments by crew and duty position, parses
  duty times once, and builds a rolling-duty-hours sweep for each crew.
- The reference strategy retains direct scans and interval sums as an oracle.
- The application caches at most two engine snapshots by workspace revision and
  selected strategy. Its separate query-result cache is bounded and keyed by
  revision plus the complete operation. Mutations advance the revision, so
  stale snapshots and answers are not reused.
- Candidate output is capped for the interactive response after the engine has
  evaluated the complete crew set. This keeps the browser response bounded
  without sampling the policy decision.

For `C` crew members, `A` assignments, and `H` duties in one crew history, the
reference path can revisit assignment and interval data for each candidate.
The indexed path pays a construction cost proportional to the retained
assignments and duty endpoints, then uses indexed lookups and the precomputed
sweep for repeated checks. Sorting still depends on the returned candidate
set. These are algorithmic expectations, not measurements from a production
workload.

## Evidence and boundaries

Import parsing and policy comparison have explicit request and interactive
limits. Source-contract replay keeps at most 128 reviewed import cases per
scope and at most 32 diverse rows per case. Workflow reuse scans a bounded
prefix of approved phrases and returns a bounded candidate list. The local
model path is opt-in and retrieves cached approved examples; it does not train
semantic behavior or replace the engine.

The engine does not build duties from flight legs, stream arbitrarily large
imports, infer missing regulatory rules, or run model-generated algorithms.
Large imports, policy comparisons, concurrent operators, tenant separation,
and distributed execution remain outside this local prototype's supported
scope.

## Review path for changes

An engine change should include an independent known-answer check, full-result
comparison with the reference strategy, randomized or dense-history cases where
appropriate, and explicit invalidation checks after data or policy changes.
The benchmark must report workload, correctness gate, latency distribution,
memory, update cost, and rollback path. A timing improvement cannot compensate
for a changed decision.

Run the repository checks with:

```bash
python3 -m unittest discover -v
python3 scripts/package_smoke.py
```

The package smoke command builds and installs both distributions outside the
checkout, then checks packaged assets and the example-data flow. The broader
[adaptation protocol](ADAPTATION.md) and [full request load procedure](LOAD_BENCHMARK.md)
remain development evidence under review. They contain no accepted production
target and no independent human trial result.

Workspace export and restore are local SQLite operations and preserve source
data and learning evidence. See [WORKSPACE.md](WORKSPACE.md) before copying a
workspace or interpreting a measurement artifact.
