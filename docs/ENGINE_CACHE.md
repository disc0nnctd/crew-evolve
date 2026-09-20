# Reusable Engine snapshots

`Engine` now builds an indexed snapshot once and can serve repeated coverage, roster, and direct check queries from that snapshot. The reference strategy still scans assignments and computes each rolling window independently; it remains the correctness oracle.

An indexed snapshot makes defensive copies of datasets and policy at construction. It parses duty timestamps once, stores assignments by crew and position as tuples, records each crew's duty history in assignment order, and builds one prefix-integral sweep per crew. Queries use `.get()` on those indexes, so a missing crew or slot does not mutate a shared Engine. The sweep includes future duty endpoints, including a target already assigned to that crew without double-counting it. No per-pair or all-roster result matrix is materialized.

Coverage and policy responses copy the duty and policy records before returning them. A caller can therefore change a returned nested list or policy value without changing a cached Engine's next response. The snapshot also stays stable if the input dataset or policy dictionaries are changed after construction. Workspace mutations must create a new revision so the application can discard the old snapshot.

The following is a same-workload local measurement on 2026-09-20. Each row uses `optimize.workload(size, seed=7301 + size)` and the indexed strategy. “Cold” constructs an Engine and runs one coverage query; “warm” constructs once and runs repeated coverage queries. Values are median milliseconds over 11 cold and 31 warm samples. “Before” executes the repository version before this change; “after” executes the reusable snapshot implementation. Every result was compared with the reference output.

| crew | before cold | after cold | before warm | after warm |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 4.159 | 5.131 | 3.294 | 1.663 |
| 500 | 18.608 | 28.659 | 18.300 | 9.387 |
| 1500 | 64.419 | 105.491 | 61.539 | 34.854 |

The extra cold construction work buys reusable state. On the repeated workload, warm coverage latency fell from 3.294 to 1.663 ms at 100 crew, from 18.300 to 9.387 ms at 500 crew, and from 61.539 to 34.854 ms at 1500 crew. Memory grows with assignments, duty endpoints, and crew histories, rather than with every crew-duty pair or every possible roster output.
