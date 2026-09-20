# Metrics and scores

The measurements answer separate questions. There is deliberately no blended score that lets speed compensate for a wrong decision.

| Metric | Definition | Use |
| --- | --- | --- |
| Algorithm correctness score | Exact full-result matches / measured calls × 100 | Must be 100% for every workload |
| Held-out correctness | Exact equality on independent fixed seeds and sizes not used for timing | All must pass before strategy selection |
| p50 latency | Median elapsed time for engine construction plus complete coverage generation | Typical cold computation |
| p95 latency | Nearest-rank 95th percentile of the measured calls | Tail indicator; with seven samples this is the maximum, not a stable production tail estimate |
| Throughput | 1000 / mean latency in milliseconds | Sequential single-process queries per second, not concurrent capacity |
| Peak allocation | Peak bytes reported by tracemalloc during a separate run | Algorithm/result allocations; excludes pre-existing input data, not process RSS |
| Latency growth | Largest-workload p95 / smallest-workload p95 | Compare to the corresponding crew-count growth |
| Speedup | Reference geometric-mean p95 / selected geometric-mean p95 | Comparable across the measured workload sizes |
| Interactive target score | Number of workload sizes whose p95 is at most 200 ms | A stated target, not a guaranteed latency |
| Learning replay score | Saved corrections passing before and after candidate changes | Promotion requires all saved examples and the new correction to pass |
| Policy impact | Outcomes changed, newly failing assigned positions, total comparisons | Evidence for human review, not an autonomous policy score |
| Live response metrics | Engine time, server time, cache hit, selected strategy | Separates computation from cached responses; browser/network/model time differs |

## Reproduce

```bash
python3 -m crew_evolve.optimize --sizes 100,1000,5000 --repeats 7 \
  --output docs/benchmark-results.json
python3 -m unittest discover -v
```

The committed report contains the local measurement and machine details. Workloads have two assignments per crew member with variation in role, fleet, availability, base, and duty times. The optimized path uses crew/position indexes and an event sweep with prefix integrals for rolling duty hours. The reference scans assignments and independently sums clipped intervals.

The correctness comparison includes all candidates, exclusions, reasons, ordering, source references, and numeric results, not just the count of passing crew. Tests also use known expected answers and deliberately corrupt the optimized result to prove the selection gate fails. Dense-history tests separately compare the sweep against direct sums, including partially overlapping seven-day windows.

Warm workspace queries use a separate revision-aware cache. The benchmark excludes that cache. Data and policy changes invalidate cached decisions; tests verify that a prior coverage answer cannot be used to assign against a changed roster.

## Limits of the evidence

- Synthetic workloads are not production airline traffic. Randomized equality can miss shared conceptual errors; known-answer tests help but do not establish compliance.
- The held-out seeds are independent from selection, but committed and repeatable. They are not a secret external benchmark.
- Cold timings include constructing indexes and generating results, but exclude reading SQLite, HTTP, browser rendering, and model latency. The live API reports server timing separately.
- Model latency is neither hidden in engine timing nor claimed to be real-time. Reviewed workflows avoid the model call entirely.
- Timing order and host load can affect results. The CLI on an idle machine is the reproducible measurement path; the in-app background benchmark may share CPU and allocation tracing with other requests.
- A universal 200 ms response at arbitrary size is not established. The largest tested workload can miss the target even while the optimized path scales much better.
- The optimizer is currently latency-led after a correctness gate. Memory and growth are reported but are not hard admission budgets. No concurrent-load, multi-tenant, or distributed benchmark has been run.
- Learning replay measures retained corrections, not semantic understanding of arbitrary questions. There is no live-provider accuracy or hallucination-rate score yet.
