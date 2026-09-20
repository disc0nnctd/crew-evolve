# Build verification and measured limits

Date: 2026-09-20. Private developer release candidate, not a public release.
Implementation was completed by Luna agents and reviewed by Terra agents.
The [release status](RELEASE_STATUS.md) distinguishes implemented capabilities
from the broader research and publication requirements.
[Captured check output](reports/functional-verification.json) records commands
and the tested implementation revision.

## Functional verification

| Check | Result |
| --- | --- |
| `python3 -m unittest discover -q` | 137 tests run, 136 passed, 1 optional real-model test skipped. |
| `python3 -m tests.browser_check` | Passed real Chromium import, learned mapping, workflow transfer, coverage, assignment/release, policy review, algorithm comparison, desktop/mobile layouts. |
| `python3 -m tests.browser_release` | Passed explicit inversion, reuse, changed-scope review, rejection retention, preview invalidation, rollback, and mobile layout. |
| `python3 scripts/package_smoke.py --browser` | Wheel and source archive installed outside checkout; actual browser correction/test/accept/reuse passed for each. Wheel environment has no system packages; source build reuses installed build tools. |
| `CREW_LOCAL_MODEL=minilm python3 scripts/local_model_check.py --strict` | Four actual offline inference cases, no execution errors. Three route plans plus a mapping suggestion that omits availability. This is not a measured accuracy rate. |
| `python3 scripts/record_demo.py` | Recorded actual browser flow; six screenshots and a 25.12-second video under ignored `artifacts/`. |
| Repository check | GitHub reports `PRIVATE`; no visibility changes or package publication. Checked tracked/proposed files for workspace files and common credential patterns; none found. This is a bounded check, not a guarantee about all secret formats. |

The first installed-browser run exposed a smoke-runner ordering bug: it tried
to load example data after an import. The application correctly refused to
replace existing data. The runner now loads the demo first; the complete
installed-browser check subsequently passed.

## Internal synthetic adaptation result

Protocol and inputs were frozen at commit `4448641` before the final run.
[Freeze hashes](reports/adaptation-freeze.json) and
[completion hashes](reports/adaptation-completion.json) identify the exact
sources and raw reports. Both methods used budgets 0/1/5/10/20 and five scenario
seeds over three final source families. Each correction packet describes one
source field and its declared interpretation. The alias method cannot use the
explicit-transform part. Both methods receive the same input cases and budget
cap, but feedback is chosen from each method's current failures. Packets,
timing, counts, and information can differ. This compares the complete alias
and contract approaches, not equal-information feedback or the isolated effect
of transforms. A strictly matched-feedback experiment remains pending.

**This is an internal, author-generated synthetic evaluation.** The generator
and final labels were accessible in the workspace. It is not a blind,
independent research test. The accidentally evaluated v1 final split was
retired and is excluded from these results; see [evaluation log](EVALUATION_LOG.md).
No code or protocol was tuned against the v2 final outcome.

Coverage below is the mean, across source families, of valid imports accepted
with all normalized values and relationships correct. Overall accuracy also
counts correct rejection of malformed cases, while abstention receives no
credit. Neither measure is the probability that a live operational answer is
correct.

| Field-correction budget per stream | Alias coverage | Contract coverage | Contract overall accuracy |
| ---: | ---: | ---: | ---: |
| 0 | 0.00% | 0.00% | 1.11% |
| 1 | 1.23% | 1.23% | 4.44% |
| 5 | 1.23% | 30.86% | 33.33% |
| 10 | 1.23% | 30.86% | 36.67% |
| 20 | 1.23% | 62.20% | 66.67% |

At budget 20, there were 450 evaluated cases: 400 expected-valid imports and
50 malformed cases. The contract path accepted 250, all correct. That is
250/400 useful valid imports by pooled count; the table reports source-family
macro coverage instead. Conditional correctness among accepted imports is a
different denominator from coverage. Source/scenario repetitions are correlated,
so these counts are not 250 independent examples of real-world reliability.
The alias path correctly accepted 5/15 accepted cases. Contract coverage
improved on these constructed formats but remained below the proposed 70%
target. There is no established reduction in correction burden at matched
accuracy/coverage, and no model-call savings claim: model baselines were not run.

One raw-trace limitation remains: `actual_accept` mixes parsing acceptance and
semantic agreement for single-table cases. Acceptance counts above use
`outcome == "accepted"`, including wrong accepted meanings. Five alias cases
are parse-accepted semantic mismatches despite `actual_accept == false`.
The grouped outcome/coverage scores are unchanged; a future protocol should
separate those fields. The frozen traces have not been rewritten.

Raw score-before-feedback traces:
[final aliases](reports/adaptation-final-aliases.json),
[final contracts](reports/adaptation-final-contracts.json),
[development aliases](reports/adaptation-development-aliases.json), and
[development contracts](reports/adaptation-development-contracts.json).
Further tuning requires a new reserved evaluation rather than repeated tuning
against this result.

## Scaling measurements

[Recorded report](reports/load-10000.json): 10,000 crew, 50,000 assignments,
50,064 duties, and 1,000 requests for each of four scenarios. Rotating queries
cycle 32 duties, exceeding the 16-result cache. The engine snapshot is retained;
the result cache is reset before each scenario. Hardware: Intel(R) Core(TM) Ultra 7 155H,
22 reported logical CPUs, Linux x86_64, CPython 3.12.3. This is one development
machine run, not a hardware-independent guarantee.

| Clients | Query pattern | Median ms | p95 ms | p99 ms | Requests/sec | Cache hits | Errors |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | rotating | 353.18 | 618.80 | 656.99 | 2.49 | 0.0% | 0 |
| 1 | repeated | 8.18 | 11.77 | 13.98 | 109.77 | 99.9% | 0 |
| 4 | rotating | 1934.68 | 2340.06 | 2580.95 | 2.04 | 0.0% | 0 |
| 4 | repeated | 37.06 | 61.64 | 103.90 | 80.69 | 99.6% | 0 |

Cold initialization took 2847.11 ms.
The first query after an assignment took 2980.34 ms,
returned the new revision, and missed the old cache as expected. The stale
assignment attempt was rejected. Both the small reference oracle and sampled
HTTP response checks passed. All 4,000 warm requests completed without errors.

The process memory high-water mark was 442.27 MiB;
143.41 MiB was already reached during seeding.
This includes the server, load client, synthetic data, engine copies, and
correctness checks in one process; it is not isolated server memory. The
collector keeps only three complete response samples per scenario. An earlier
run retained every response, was stopped, and is excluded from these metrics.

**Changing-duty queries missed the proposed 200 ms p95 target.** Cached replies
meet that number in this run, but do not demonstrate the general scaling goal.
The harness measures structured local HTTP requests, excluding language/model
interpretation, imports, GUI rendering, and distributed networking. The large
workload is seeded directly and exceeds the single-file duty import limit;
this is an engine/API workload, not proof of an interactive import at that size.
Large response samples use direct indexed shaping, while the independent
reference oracle is bounded to 96 crew. Model calls are zero by construction,
not evidence of model-call savings over a competing assistant.

Reproduce from the checkout:

```bash
python3 scripts/load_benchmark.py --crew 10000 --history 5 --requests 1000 \
  --clients 1,4 --output artifacts/load-10000.json
```

## Review record

| Terra review | Disposition |
| --- | --- |
| Contracts, workflows, local model, App integration, indexed engine | Passed after fixing case-distinct duty binding, bounded context and evidence, local encoder load synchronization, actual model provenance, rollback invalidation, and long-duty rolling-window parity. |
| Browser, workspace backup, load harness, contract integration | Passed after fixing preview invalidation, source-change transform reuse, restore cleanup, post-assignment restore, per-client response checks, cache isolation, and stale-response/CLI failure gates. |
| Adaptation protocol | Passed for the restricted synthetic scope after correcting accepted-invalid scoring, chronological field feedback, later-case variation, per-budget reporting, malformed control checks, and v1 retirement disclosure. |

The independent reference implementation, known-answer fixtures, review, and
browser checks provide evidence for the implemented scope. They do not certify
crew policy compliance or establish research novelty. Public licensing,
independent-user trials, and broader model/workflow comparisons remain pending.
