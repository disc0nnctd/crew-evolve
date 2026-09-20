# Verification record

The first version was exercised locally on Linux with Python 3.12 and Python 3.10, using synthetic data only. No real crew files, model credentials, or paid model calls were used.

## Commands

```bash
python3 -m unittest discover -v
python3.10 -m unittest discover -q
python3 -m compileall -q crew_evolve
node --check web/app.js
python3 -m tests.browser_check
python3 -m crew_evolve.optimize --sizes 100,1000,5000 --repeats 7 \
  --output docs/benchmark-results.json
```

Unit checks cover validation, retained source values, missing and conflicting data, deterministic expected coverage, both directions of rest, overlap, rolling-window clipping, random algorithm equivalence, dense histories, deliberately corrupted optimized output, learning persistence and rollback, conflicting corrections, stale policy proposals, cache invalidation, concurrent assignments, HTTP protections, and the model transport against a local synthetic endpoint.

The Chromium scenario uses the real local HTTP server and application. It loads an example, inspects exclusions, assigns/releases crew, teaches a workflow and applies it to another duty, compares/activates a policy, imports unfamiliar columns, checks the next import's learned mapping, runs the background optimization agent, and checks all screens for page overflow at mobile width. Browser errors fail the scenario.

## Cold engine benchmark

Full output equality passed on every measured and held-out workload. These are local synthetic results, not a production service guarantee.

| Crew | Assignment records | Reference p95 | Indexed p95 | Indexed peak allocations |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 200 | 6.473 ms | 4.754 ms | 0.197 MB |
| 1,000 | 2,000 | 179.421 ms | 41.767 ms | 1.867 MB |
| 5,000 | 10,000 | 3,874.229 ms | 344.300 ms | 9.160 MB |

The largest workload improves by about 11.3× at p95, with higher allocation cost. It still misses the 200 ms interactive target on a cold computation. The reported aggregate speedup is 4.04× across the three sizes, using their geometric mean. The [raw report](benchmark-results.json) is the authoritative measurement; [metric definitions](METRICS.md) explain denominators and limits.

Not verified: a live external model provider, real airline data, regulatory completeness, concurrent production load, distributed deployment, or correctness of future generated algorithms. Those are separate tests, not inferred from the local results.
