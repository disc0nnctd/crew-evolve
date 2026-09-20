# Full request load benchmark

`scripts/load_benchmark.py` measures complete structured query requests through a real loopback HTTP server. It seeds a temporary SQLite workspace, starts `crew_evolve.server.Server`, sends JSON to `/api/query`, and measures client request wall time from JSON request start through response parsing. The closed-loop client keeps at most the requested number of requests in flight. Import parsing, SQLite seeding, and report writing are outside the warm request timings.

The generated roster has private history duties for every crew member and at least 64 unassigned target duties. Five history duties produce 50,000 assignments at 10,000 crew members. The first request is reported separately as cold initialization because it builds the immutable engine. The rotating scenario cycles 32 targets, which exceeds the 16-entry result cache. The repeated scenario sends one target repeatedly and exposes cache hits.

Run a quick smoke benchmark. Every CLI run writes `artifacts/load_benchmark.json` unless `--output` changes the destination:

```sh
python3 scripts/load_benchmark.py --crew 50 --history 2 --requests 20 --clients 1
```

Run the required one-client and four-client load measurements and save an artifact:

```sh
python3 scripts/load_benchmark.py --crew 10000 --history 5 --requests 1000 --clients 1,4 --output artifacts/load.json
```

The defaults are deliberately smaller for local iteration:

```text
--crew       100
--history    5
--requests   100 per warm scenario
--clients    1 (accepts 1,4 for both client counts)
```

The JSON report includes nearest-rank request wall p50, p95, and p99, throughput, errors, HTTP statuses, cache hits, model calls, process RSS high-water mark, machine details, the available Git revision, a dirty-worktree marker, and a deterministic source fingerprint. The legacy `queue_wall_ms` field retains these request wall quantiles and includes its definition. Terminal output is a compact measured summary; the artifact keeps bounded response samples with candidate hashes. Each warm scenario clears the structured-result cache while retaining the immutable engine built by cold initialization, and the report records that isolation. Latency is labelled as structured-plan HTTP latency; `/api/query` does not call the natural-language model, so `model_calls` is zero.

The report also runs a bounded `reference` versus `indexed` correctness oracle outside the large request loop. For each client run it compares a few complete HTTP response bodies, including the current revision, with independently shaped engine output. A large workload uses direct indexed shaping for these few samples so a quadratic reference scan cannot dominate the load test. The invalidation check assigns the guaranteed valid first candidate, verifies that the old revision is rejected, and confirms that the next response carries the new revision with a cache miss.

The process RSS value comes from `resource.getrusage(RUSAGE_SELF).ru_maxrss`. On Linux this is a KiB process high-water mark and includes memory retained after synthetic seeding. It is a process measurement, so compare artifacts from the same machine and Python build.

The command exits with status `1` when cold initialization, any scenario request, either correctness oracle, or revision invalidation fails. A stale revision is accepted only when the assignment returns HTTP `400` with the expected workspace-changed message.
