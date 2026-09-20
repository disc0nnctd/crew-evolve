# Crew Evolve: plan for a public developer release

Status: proposed roadmap, 2026-09-20. The repository stays private during this
work. This plan does not authorize changing its visibility or publishing a
package. Target audience: developers building assistants over changing crew
tables, with an operator-friendly demonstration. This is a software release and
reproducible technical report; research-paper novelty needs a deeper literature
review and stronger independent validation.

## The contribution to pursue

**An assistant that turns crew-data and workflow corrections into reusable,
versioned behavior, and measures whether that behavior saves work without
changing the crew checks.**

The testable question is: given the same correction budget, can it answer more
future requests correctly, require fewer repeated corrections, and avoid more
large-model calls than explicit aliases or a fixed model?

The distinctive release should be the combination of a working application,
an evaluation of learning across changing source formats, and inspectable change
reports. Each report shows the correction, its scope, proposed behavior, examples
that pass or fail, measured cost, activation decision, and rollback version.
This is a proposed contribution, not a claim of world-first invention.

### What already exists elsewhere

| Related work | Existing capability | Implication for our claims |
| --- | --- | --- |
| [Google scheduling examples](https://developers.google.com/optimization/scheduling/employee_scheduling) and [Timefold quickstarts](https://github.com/TimefoldAI/timefold-quickstarts) | Constraint-based staffing/scheduling examples | A crew scheduler alone is not the new contribution. Do not rebuild a general solver for the first release. |
| [GEPA](https://github.com/gepa-ai/gepa) | Uses execution feedback to improve prompts, code, and other text-defined behavior | Generic propose/evaluate/improve loops already exist. A crew-specific protocol and measured result must justify our work. |
| [Agentic Context Engineering paper](https://arxiv.org/abs/2510.04618) | Maintains and improves contextual playbooks from experience | Remembering corrections alone is not novel. Compare with a correction-memory baseline. |
| [Jev](https://docs.typesafe.ai/introduction) and [Laya](https://github.com/NandhaKishorM/laya) | Bounded structured decisions | Typed choices are a building block, not a new model architecture we invented. |

This is a targeted comparison, not an exhaustive novelty search. Before making
a research novelty claim, also examine semantic data integration, schema
matching, programming by example, and continual-learning benchmarks.

## Starting point

| Present and tested | Missing for the release claim |
| --- | --- |
| Import crew, duties, and assignments; inspect candidates and reasons | Reliable adaptation to changed field meanings and value formats |
| Reviewed column aliases and exact workflow patterns with duty/role substitution | Generalization beyond stored names and phrase templates |
| Replay, rejection, history, latest-change rollback | Versioned, source-scoped transforms and evaluation on unseen cases |
| Reference and indexed engines; measured strategy selection | Persistent indexes, full-request measurements, mixed updates and concurrency |
| Local web app, unit checks and browser checks | Verified installed package, release documentation, fresh-user trials |
| Sample-derived model experiment and raw predictions | Meaningful correction-efficiency benchmark with independent source families |

The [first model experiment](TYPED_DECISIONS.md) is evidence of gaps, not release
quality: none of its request routers is ready for automatic activation. The
perfect word-model mapping score reflects a small fixture with recurring value
patterns. Preserve that negative result in the public report.

## Signature demonstration

1. Import a changed export derived from our crew/duty/assignment samples. It has
   unfamiliar field names and an explicit `cannot_work` column.
2. The assistant asks about that column. The operator confirms that true means
   unavailable. A candidate becomes an explicit boolean inversion, scoped to
   that source contract; it is not saved as a misleading alias to `available`.
3. Show the proposed transform, changed records, checks, and counterexamples.
   Reject an ambiguous date format rather than guessing its timezone.
4. Import a later file under the same contract with new people and duties. The
   learned transform works without repeating the correction. For an unrecognized
   or contradictory contract, ask again. Separately show measured transfer to
   other source formats; do not pretend exact reuse proves semantic transfer.
5. Correct a coverage request and later handle a paraphrase with a different duty
   and role. Show the selected operation and extracted arguments. “Don't assign
   anyone” and “assign this person” must lead to different permitted behavior.
6. Show a candidate improvement rejected because it breaks an older case. Roll
   back an accepted version and explain precisely which future decisions change.
7. Grow the workload. Show complete-request latency, memory, and identical crew
   decisions before and after selecting a faster reviewed implementation.

Aim for a short recorded walkthrough plus a repeatable local script. The default
demo must work without a provider key. Label replayed suggestions as replay;
provide a separate optional live-model path with the provider and cost recorded.

## Scope boundaries

Keep the current crew/duty/assignment domain, duty-block model, and coverage,
roster, summary, and clarification operations. Extrapolate from our own samples;
do not introduce airport ground-service entities or claim to understand every
kind of data.

For the first release, add a small declarative transform vocabulary: rename,
boolean parsing/inversion, explicit enum translation, and date parsing with a
declared format/timezone. Unknown values fail validation. No generated Python,
arbitrary joins, or silent inference of missing business rules.

Policy changes remain proposals with before/after effects and operator review.
Keep this existing path, but defer learning scheduling policies, multi-day
reinforcement learning, flight-leg pairing, arbitrary algorithm invention,
distributed hosting, and multi-tenant accounts. No claim of operational or
regulatory certification. The published scope is a local research/developer tool.

## Milestones and acceptance checks

Estimate assumes one focused builder with AI assistance, no model training from
scratch, and no external integrations. Roughly 24–33 engineering days plus
feedback/buffer: plan for 6–8 calendar weeks full-time. This is an estimate, not
a delivery guarantee; part-time work takes longer. Each phase depends on the
earlier acceptance checks, not merely on the passage of time.

| Phase | Effort | Concrete work and files | Exit evidence |
| --- | --- | --- | --- |
| 1. Define the claim and benchmark | 4–5 days | Add `benchmarks/adaptation/` fixtures, generators, labels, split manifest, replay driver, and protocol. Extend sample relationships rather than copying rows. | Freeze development protocol; run current aliases/workflows as a baseline; demonstrate at least one failure per supported drift type. |
| 2. Learn explicit data transforms | 4–6 days | Extend `data.py`, `learning.py`, `store.py`, and import review in `web/`; add contract/version representation and storage migrations. | Polarity, enum and date examples work; unknown values and collisions reject; source-scope conflicts, old evidence and rollback pass. |
| 3. Learn bounded workflows | 5–7 days | Extend `model.py`, `app.py`, `learning.py`; give candidate generation a fixed call/time budget. Compare corrected examples in model context, reviewed rules, and a small trained classifier. | Evaluate operation plus arguments together. Unsupported writes, negation, missing IDs, multiple targets and ambiguity clarify. At least one real local/provider model produces candidates; mocks do not count as this evidence. |
| 4. Test learning and show changes | 4–5 days | Add independent evaluator/reporting and browser views for each version's correction, scope, failures, decision and rollback. | Compare baselines on identical streams and budgets; show a rejected regression and successful rollback; complete a locked final run after tuning ends. |
| 5. Make growth measurable | 4–6 days | Extend `engine.py`, `store.py`, `optimize.py`, `app.py`; add reusable versioned indexes and compact model context, then optimize only measured bottlenecks. | Full response equality plus mutation/stale-result tests; complete-request latency and process memory under a declared workload, with cold and cached paths separate. |
| 6. Package and prepare release | 3–4 days | Verify `pyproject.toml`, packaged web assets and examples; add release notes, contribution/security guidance, data/model notices, owner-selected license, technical report and demo. | Fresh install and browser workflow pass outside the checkout; independent users reproduce the demo; release checklist is complete. |

The first vertical slice is phase 1 plus boolean inversion from phase 2. It must
demonstrate better behavior on a later import before building a larger learning
framework. Add no framework dependency solely because it markets self-evolution.

## Evaluation that can support publication

### Dataset and protocol

Start with 12 independently designed export families: six for training, three
for development, and three final families reserved during tuning. Change headers,
values, types and relations, not just IDs. Include positive/negative availability,
role synonyms, missing values, duplicate IDs, ambiguous dates, renamed columns,
irrelevant fields, contradictory corrections and stale duty snapshots.

Generate crew, duties and assignments together so relationships remain valid
until a case deliberately breaks one. Combine independent hand-authored expected
answers with generated checks. Differential equality alone can preserve a shared
bug. Record seed, source family, scenario, policy, schema version, and deliberate
faults for every case; none of those labels enters the model input.

Measure two different abilities:

- **Transfer before correction:** evaluate final families without showing their
  labels or examples to training.
- **Adaptation after correction:** use a predeclared correction stream on each
  final family. Score each request before revealing permitted feedback, then
  evaluate later requests. Every method receives the same feedback budget and
  timing. Keep later evaluation labels inaccessible to the proposing agent.

Show curves at correction budgets 0, 1, 5, 10 and 20 per stream. Use at least five
scenario seeds. Cases sharing a template/source are correlated: aggregate and
estimate uncertainty by source/scenario groups, not by pretending every row is
an independent observation. Final-test outcomes cannot guide further tuning of
that release's result; a subsequent revision needs a new final holdout.

### Baselines and isolated comparisons

1. Current reviewed aliases and phrase templates.
2. Fixed model with no correction memory, same available context.
3. Same model with approved corrections in context, but no compiled reuse.
4. Word classifier and small sentence model trained with the same allowed labels.
5. Proposed system with reviewed transforms/workflows, regression checks and
   measured path selection.

Where relevant, compare removing the regression check, source scoping, and fast
reuse separately in offline evaluation. Never remove assignment constraints from
the live application for an ablation. Report proposal failures and abstentions;
counting only accepted candidates would conceal wasted work and failure modes.

### Proposed targets, not achieved results

Freeze these goals after phase 1's baseline and before final evaluation. If they
prove unrealistic, document the change before the final run; do not lower them
after observing final results.

| Measure | Initial release target / reporting rule |
| --- | --- |
| Correct accepted mappings and complete operation+arguments | At least 99% on the declared final benchmark, with counts, grouped uncertainty, and per-family breakdowns |
| Useful automation | At least 70% of supported final requests answered without clarification after the declared correction budget; unsupported requests reported separately |
| Correction burden | At least 30% fewer repeated corrections than the existing alias/template baseline at matched accuracy and useful coverage |
| Large-model usage | At least 50% fewer foreground model calls on repeated supported workloads than the fixed-model baseline; include background calls, training/setup time, tokens and amortized cost separately |
| Retention | No regression on the mandatory historical and adversarial suite; report all other regressions, not only an average |
| Operational constraints | Zero observed prohibited assignment commits, polarity reversals, or stale-write acceptance in the mandatory suite; tests are evidence, not a universal guarantee |
| Algorithm correctness | Exact full-result agreement with the independent reference plus known-answer checks before selecting a strategy |
| Warm complete-request latency | 95th percentile at or below 200 ms for learned coverage requests on a declared 10,000-crew / 50,000-assignment workload; ingestion and cold startup reported separately |
| Load and memory | Report single-client and four-client runs, at least 1,000 requests each, median/95th/99th percentiles, error rate, process memory, cache rate, and update/invalidation time |
| Reproduction | Fresh user reaches the bundled demo within five minutes after prerequisites; full experiments have documented dependencies and budgets |

Keep costs, correctness, automation coverage and speed as separate measures.
If the system cannot beat simple baselines, publish the useful tool and honest
benchmark findings, but narrow the claims. Do not call stored aliases semantic
learning, catalog selection algorithm invention, or synthetic success operational
validation.

## Release package and final decision

- Installable local application with bundled assets, example reset and workspace
  export/restore; no personal workspace files in the distribution.
- Evaluator, documented data generation, versioned fixtures and raw reports.
  Publish the held-out evaluation material after the final measurement so others
  can reproduce it; future tuning requires a fresh split.
- Architecture and related-work notes; measured strengths, failures and resource
  limits; one concise walkthrough and screenshots backed by the running app.
- Owner-selected license and dependency/model/data attribution; contribution
  instructions and a way to report bugs; verify repository history and release
  contents do not expose credentials or private operational data.
- A small independent usability trial: aim for three people who did not build it
  to install and complete the import/correct/reuse flow. Operator feedback is a
  separate source of domain validation, not implied by developer testing. Do not
  contact testers or send them data without the user's authorization.

Prepare all release artifacts while the repository remains private. The final
visibility/package-publication decision belongs to the owner, after there is a
concrete release to inspect. A public release can be valuable even if the result
is a careful systems contribution rather than a new learning algorithm.

## First executable work item

Create the benchmark protocol and a known-answer scenario where `cannot_work`
changes the expected eligible crew. Record today's failure, add a reviewed,
source-scoped inversion, and prove it works on later records while an unknown
source still asks for clarification. This directly tests the proposed contribution
and starts phases 1–2 without committing to an unproven model architecture.
