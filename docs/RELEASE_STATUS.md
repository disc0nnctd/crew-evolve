# Private release foundation

This branch builds the first developer release candidate, `0.2.0rc1`. The
repository remains **private**. No package, model, workspace, or public site
has been published. The release roadmap is in [RELEASE_PLAN.md](RELEASE_PLAN.md);
that roadmap's research and performance targets are not implied by shipping
these features.

[Verification and measured limits](BUILD_VERIFICATION.md) records passing
functional/install checks and the completed synthetic/load evaluations. The
internal import-coverage goal and changing-duty latency goal were missed;
these remain development targets rather than release claims.

The [changing-duty follow-up](PERFORMANCE_FOLLOWUP.md) records a tested indexed
engine improvement, stronger reference checks, and a shorter concurrent web
load run. Its changing-duty latency still misses the target.

## Implemented

| Capability | What is inspectable |
| --- | --- |
| Learn export meanings | Named source contracts, exact schemas, explicit boolean inversion, enum translation, and declared date/time conversion. Preview, version, historical replay, rejection, and rollback are integrated into the browser. |
| Learn workflow corrections | Exact corrected templates and a bounded phrase matcher for coverage, roster, and summary. Duty identifiers stay case-sensitive; unknown or ambiguous targets and write requests clarify. |
| Optional actual model | Offline cached sentence encoder ranks reviewed examples and mapping candidates. The application returns bounded model evidence and checks the selected operation and targets. |
| Reuse work as data grows | Immutable engine snapshots per workspace revision, indexed crew histories and interval summaries, bounded result caching, and reference-equivalence checks. |
| Preserve work | SQLite schema migration and consistent local export/restore into a new destination. Raw imports, learning versions, and evidence remain local. |
| Reproduce the tool | Installable wheel and source archive with assets/examples, automated checks, a recorded browser walkthrough, and adaptation/load runners. |

Self-evolution here means **reviewed configuration reuse**. It does not train a
new language model, invent algorithms, or silently change planning constraints.
The existing algorithm selector compares reviewed implementations and activates
only a measured candidate that passes its correctness gate. Policy changes
remain explicit proposals requiring operator activation.

## Evaluation boundaries

The adaptation benchmark measures imports, including canonical values and
relationships, on synthetic source variants. It is not an independent human
trial or a general test of understanding arbitrary data. The alias baseline and
explicit-transform path receive a declared correction stream; model baselines
remain separately marked when not run. The original final split was accidentally
evaluated during review and retired. See the
[evaluation log](../benchmarks/adaptation/EVALUATION_LOG.md) for the replacement
and subsequent freeze/run record.

The [real model check](reports/local-model-check.json) records actual cached
inference, including omitted mapping fields and measured cold-start cost. It is
a candidate-generation smoke check, not an accuracy benchmark. Unit tests with
injected encoders only test integration and decision boundaries.

The load runner uses real local HTTP requests with structured plans. It excludes
natural-language interpretation, import parsing, and distributed networking.
Synthetic data is seeded directly into a temporary workspace. Cold startup,
repeated result reuse, rotating targets, update cost, memory, and client
concurrency are reported separately. The small reference oracle is independent
of the indexed engine; the large response samples compare against direct
indexed results and are not an independent full-scale correctness proof.

## Before a public release

- Complete the broader model/workflow comparisons and correction-efficiency
  evidence in the roadmap. Keep failed targets visible; do not substitute
  synthetic import reuse for those claims.
- Have independent people install and complete the correction/reuse flow.
  Automated browser checks are not a usability trial.
- Select an owner-approved license and review dependencies/data/model notices.
  No license choice or public distribution is assumed.
- Review the concrete release artifacts before changing GitHub visibility or
  publishing a package. Keep real operational workspaces and credentials out.

This remains a local, single-operator developer tool with explicit resource
bounds. It is not an operationally certified crew scheduler, a multi-tenant
service, or an airport ground-service model.
