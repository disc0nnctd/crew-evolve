# Scaling through measured algorithm choices

The initial implementation has a reference path and an optimized path, both runnable against the same inputs. Improving the engine must preserve the full result. A large speedup with different exclusions is a failure.

## Implemented

- Assignment lookup by crew and duty position replaces a full assignment scan per candidate.
- A sweep of duty start/end events builds integrated duty hours. Binary searches replace repeated interval summation for rolling windows.
- Candidate ordering is stable, so equivalent inputs produce equivalent ranked output.
- A bounded result cache keys on the entire operation and workspace revision. Mutations make old answers ineligible for reuse.
- Algorithm benchmarks include index-building cost, hold out independent workloads, and activate a measured winner only after exact equality.
- Import, response, policy-comparison, and cache limits are explicit. The prototype rejects work outside certain interactive bounds rather than silently sampling a policy comparison.

For C crew, A assignments, and H duties per crew, the reference performs assignment scans approaching O(C × A) and repeated rolling sums approaching O(H²) per crew. Index construction costs O(A), assignment retrieval costs O(H), and the sweep costs O(H log H) per crew. Sorting returned candidates still costs O(C log C). This explains the expected shape; the benchmark measures whether it holds on this machine.

## Next scaling experiments

1. Persist versioned indexes and immutable operational snapshots so cold queries do not reconstruct all state. Measure build time, invalidation time, resident memory, and cold/warm latency separately.
2. Add a batch-query portfolio and select strategies by workload shape, not only geometric mean across synthetic sizes. Include many duties per crew, different time-window widths, and skewed station distributions.
3. Move large imports and policy comparisons into bounded jobs with progress, cancellation, and resumable chunks. Avoid synchronous whole-dataset JSON loading.
4. Measure end-to-end latency under concurrent operators, including lock contention, queue depth, cache hit rate, and stale-answer rejection. Add identity and tenant separation before serving multiple users.
5. Add incremental invalidation: a change to one crew member should recompute only affected duties and cached answers, with the full reference path retained as an oracle.
6. Evaluate newly proposed algorithms in an isolated process with time/memory limits, known-answer cases, randomized differential tests, held-out workloads, and reviewable code changes. The current agent chooses within a reviewed catalog; it does not invent and execute arbitrary code.

Each experiment should record a correctness gate, an explicit workload, latency percentiles, memory, throughput, cost of updates, and a rollback path. Improvements to planning rules still require operator review even when the implementation becomes faster.
