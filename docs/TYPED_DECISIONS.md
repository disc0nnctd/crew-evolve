# Typed decisions on our sample data

Research date: 2026-09-20. Branch: `research/typed-decisions`.

**Useful pattern, not an established drop-in upgrade.** A small model can choose
among known fields or operations, then ordinary code validates and executes the
request. We ran open Laya weights and two local baselines on extrapolations of
our existing samples. We did not call Jev, reproduce its proprietary training,
train Laya, or enable these experimental models in the application.

## Source map

The [requested Reddit discussion](https://www.reddit.com/r/LocalLLaMA/comments/1wijo3e/i_literally_built_the_jev_architecture_one_year/)
mixes an earlier sales predictor, a newer general decision model, inference
experiments, and independent reproductions. Similar output formats do not
establish identical architectures or comparable performance.

| Source | What is available; relevance here |
| --- | --- |
| [Jev introduction](https://docs.typesafe.ai/introduction), [launch](https://typesafe.ai/blog/introducing-system-one-models-and-jev) | Hosted typed choices, scores, and boolean probabilities. No public weights or complete reproducible training recipe found in the reviewed material. Could be an additional provider, but not locally reproduced here. |
| [Laya code](https://github.com/NandhaKishorM/laya), [weights](https://huggingface.co/convaiinnovations/laya), [demo](https://huggingface.co/spaces/convaiinnovations/laya-demo) | Apache-2.0 code and weights; actually executed locally. Distinguish English, multilingual, and task-tuned checkpoints. Only English root tested here. |
| [SalesRLAgent paper](https://arxiv.org/abs/2503.23303), [original model](https://huggingface.co/DeepMostInnovations/sales-conversion-model-reinf-learning), [dataset](https://huggingface.co/datasets/DeepMostInnovations/saas-sales-conversations) | Original post's sales-conversion predictor. Its outcome labels and features are not crew data. Reusing the learning idea is different from transferring the trained predictor. |
| [Confidence-aware routing paper](https://arxiv.org/abs/2510.01237) | Related work on routing uncertain predictions. A candidate source of abstention ideas; requires domain-specific validation. |
| [Brain arena reproduction](https://github.com/swedishembedded/brain/tree/1f1f1b5dbbc55fcad0dfe0f39dd47cfbfa787350/samples/decision/arena) | Dynamic legal actions, frozen text encoder, learned decision head, and a simulator whose next state depends on the action. Useful design reference for future multi-duty planning. Source reviewed, not executed here. |
| [Brain sales reproduction](https://github.com/swedishembedded/brain/tree/1f1f1b5dbbc55fcad0dfe0f39dd47cfbfa787350/samples/decision/salesagent) | Documents weaker reproduction results and concerns about outcome-proxy leakage. Motivates baseline comparisons and excluding future outcomes from model inputs; not a finding of misconduct by us. |
| [Qwen-labelled experiment](https://huggingface.co/harshatheg/Qwen-2.5-1B-RLCD/tree/2af86848be75847ccb3553b0941cc51d6ef7e4e9), [parallel constrained decoding demo](https://huggingface.co/spaces/drinkmoonshine/parallel-constrained-decoding) | Additional links requested in the comments. The reviewed Qwen repository contains application/engine code, not a separately published trained weight file. A title containing RLCD does not establish reproduced reinforcement learning. Not executed. |
| [AbdelStark benchmarks](https://github.com/AbdelStark/jev-benchmarks), [nibzard benchmarks](https://github.com/nibzard/decision-model-benchmark) | Independent evaluation code and reports. Useful checks include probability quality, option-order sensitivity, and actual request latency. Their figures are not our measurements. |
| [Jev feature-discovery cookbook](https://docs.typesafe.ai/cookbooks/autoresearch_feature_discovery) | A language model revises semantic questions, a decision model turns them into features, and a downstream predictor is evaluated on separate data. Closest documented pattern to our proposed research loop; not a complete crew planner. |

### Claims to separate

[Jev's documented failure modes](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
include numeric precision, dates, irrelevant context, and inconsistencies across
separate questions. This supports keeping rest, overlap, availability, and record
counts in our engine. A schema restricts possible outputs; it does not prove a
choice is correct.

[Jev confidence](https://docs.typesafe.ai/confidence) is a distribution-derived
statistic, not a measured probability of correctness on our data. Likewise,
[Laya's implementation](https://github.com/NandhaKishorM/laya/blob/d113dca2512fb3eaca313534bc54c7162d87c1d4/laya/common.py)
computes choice confidence from normalized entropy. Our acceptance threshold uses
the largest class probability, not this entropy score. Neither earns trust without
evaluation.

Laya's [published model card](https://huggingface.co/convaiinnovations/laya)
distinguishes domain-tuned results from weaker base-checkpoint results and says
its Jev comparison uses third-party figures with different prompts and sizes.
Its [inference source](https://github.com/NandhaKishorM/laya/blob/d113dca2512fb3eaca313534bc54c7162d87c1d4/laya/agent.py)
builds a separate encoded sequence per question. Batching is not constant-cost
reasoning over an arbitrarily large crew table. Questions also do not consume
each other's answers; cross-field consistency must be enforced separately.

## Measured results

Local Intel Core Ultra 7 155H, CPU only, four computation threads. These are
results for the fixed questions and English checkpoint specified below; they do
not establish a general ranking of the model families.

| Model | Request accuracy (36 cases) | Mapping accuracy (63 cases) | Request latency, 95th percentile | Mapping latency, 95th percentile |
| --- | ---: | ---: | ---: | ---: |
| Trained word baseline | 75.0% | 100.0% | 1.24 ms | 0.84 ms |
| Frozen MiniLM + trained classifier | 83.3% | 93.7% | 39.38 ms | 25.70 ms |
| Laya English, no domain training | 33.3% | 63.5% | 1053.15 ms | 977.73 ms |

Setup plus training took approximately 1.14, 5.28, and 5.98 seconds respectively,
separate from request latency. Filesystem/model caches were already warm; these
are not download or fresh-machine startup measurements. Jev was not measured.

Confidence did not eliminate errors on unseen wording:

| Model and task | Accepted test cases | Errors among accepted | Error rate among accepted |
| --- | ---: | ---: | ---: |
| Word, requests | 30 / 36 | 6 | 20.0% |
| MiniLM, requests | 25 / 36 | 3 | 12.0% |
| Laya, requests | 0 / 36 | 0 | Undefined: no development threshold qualified |
| Word, mappings | 63 / 63 | 0 | 0.0% on this small fixture |
| MiniLM, mappings | 42 / 63 | 0 | 0.0% on this small fixture |
| Laya, mappings | 40 / 63 | 12 | 30.0% |

Concrete failures in the retained report:

- The small encoder selected `summary` for a request asking for the duty schedule
  **not** aggregate counts, with maximum class probability about 0.75.
- Laya mapped `worker_identity` containing full names to `crew_id`, with maximum
  probability about 0.94. It mapped negative availability headers directly to
  `available`, which could reverse the meaning if blindly applied.
- Reversing Laya's option order changed 7 of 33 family probes. The largest test
  input used 146 tokens, below its 512-token context limit; this run does not test
  long-table reasoning or the effects of truncation.

**Decision:** retain the current reviewed learning path. Do not promote any
experimental request router from these results. The cheap mapping baseline is
worth testing on genuinely new source tables, missing values, unfamiliar value
formats, and contradictory headers. The perfect score here is evidence that this
fixture is easy for that model, not proof of universal data understanding. More
Laya prompt/checkpoint work must use development data and a new sealed final test
set, because the current test errors are now known.

## Experiment design

Fixtures come from `examples/crew.csv` and `examples/duties.csv`, retaining their
field meanings and varying identifiers, headers, and requests. This is not new
airport ground-operation data. Assignment history is deliberately absent because
neither tested task calculates crew eligibility.

| Split | Routing cases / wording families | Mapping cases / header families |
| --- | ---: | ---: |
| Training | 48 / 16 | 84 / 28 |
| Development | 24 / 8 | 42 / 14 |
| Test | 36 / 12 | 63 / 21 |

Each family has three correlated sample-derived variants. Wording families and
scenario identifiers are disjoint across splits. Bases, qualifications, names,
and other value patterns still recur: this is intentionally a within-schema
feasibility test, not evidence of arbitrary-data generalization. The mapping
fixture is especially easy for methods recognizing recurring value patterns.

- **Routing:** choose `coverage`, `roster`, `summary`, or `clarify`. Test families
  include missing information, mutations, and negation. Correct action selection
  does not prove correct duty/role extraction or a successful complete workflow.
- **Mapping:** choose one of six crew fields or `clarify`. Negative availability
  headers need clarification because direct mapping cannot invert a boolean.
  This does not test joint column collisions, file validation, or arbitrary tables.
- **Word baseline:** word/bigram features with a trained linear classifier.
- **Small encoder baseline:** frozen MiniLM sentence encoder with a trained linear
  classifier. Both baselines learn only synthetic training labels, not genuine
  user corrections. Hyperparameters are fixed before evaluation.
- **Laya:** pinned English checkpoint, no crew-specific training, concise state,
  fixed questions and option descriptions. It gets descriptions that the trained
  baselines instead learn from labelled examples. This compares practical starting
  points, not equally trained architectures.

Development selects the lowest confidence threshold accepting at least ten cases
with zero observed errors. Test data is evaluated afterward and never used to
select that threshold. This intentionally simple rule is a diagnostic, not a
deployment guarantee. A missing threshold means abstain on everything.

Metrics: accuracy; summed multiclass Brier score per case; natural-log loss;
ten-bin expected calibration error; clarification recall; accepted coverage and
error rate; warm per-request median and 95th-percentile latency. All predictions,
probabilities, cases, setup time, versions, and a fixture fingerprint are retained
in [the raw report](typed-decisions-results.json). Laya also receives one reversed
option-order probe per test family. No single blended score hides correctness
behind speed.

## Reproduce

The app remains standard-library-only. Research dependencies are optional and
were tested on Python 3.12. Public downloads happen only during setup; inference
runs offline on CPU with four computation threads. No provider key is needed.

```bash
python3 -m venv .venv-research
. .venv-research/bin/activate
python -m pip install -r requirements-research.txt

# Cheapest baseline only; does not need either checkpoint:
python -m experiments.typed_decisions --models word

# Public source and checkpoints for the full comparison:
git clone https://github.com/NandhaKishorM/laya.git /tmp/crew-laya
git -C /tmp/crew-laya checkout d113dca2512fb3eaca313534bc54c7162d87c1d4
python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download('sentence-transformers/all-MiniLM-L6-v2',
    revision='c9745ed1d9f207416be6d2e6f8de32d1f16199bf', token=False,
    allow_patterns=['*.json', '*.txt', 'model.safetensors', '1_Pooling/*'])
snapshot_download('convaiinnovations/laya',
    revision='1c5edc17a7acd8701df6fc341c0d179f1c62c982', token=False,
    allow_patterns=['model.safetensors', 'rl_agent_config.json',
                    'encoder/config.json', 'tokenizer/*'],
    local_dir='/tmp/crew-laya-weights')
PY
python -m experiments.typed_decisions --models word embedding laya \
  --laya-source /tmp/crew-laya --laya-weights /tmp/crew-laya-weights \
  --output artifacts/typed-decisions.json
python -m unittest discover -v
```

The runner checks the Laya source commit, clean tracked files, and weight checksum.
The upstream loader can normalize its local tokenizer configuration. Checkpoints
and third-party source are not vendored. Latency includes state encoding,
inference, and probability validation; it excludes setup/training, network,
database, and crew-engine time. Each case is timed once, so these small warm
samples are not service-level or concurrency benchmarks.

## How this fits self-evolution and scale

1. Keep reviewed mappings and exact learned workflows as the cheapest path.
2. Collect corrected predictions with source/schema and time boundaries. Treat
   model suggestions as unverified until corrected or independently checked.
3. Train candidate field/request models in the background; keep whole source
   families and later time periods out of training. Preserve a final test set
   that the proposing agent cannot inspect during iterative tuning.
4. Compare accuracy, clarification behavior, confidence calibration, and complete
   request latency against simple baselines. Test negation and boolean inversion
   explicitly. Promote a version only after those checks; keep rollback evidence.
5. For huge datasets, profile columns once, cache by schema/version, filter/index
   records, and send a compact candidate set to models. Benchmark retrieval recall
   and end-to-end latency as well as inference. A fast prediction cannot repair
   missing candidates or a slow database scan.
6. For genuinely sequential planning, extrapolate multi-day scenarios from the
   crew/duty/assignment samples. Deterministic checks build feasible actions;
   choosing one changes the next scenario state. Compare a learned policy against
   greedy and optimization baselines on unobserved seeds. Report coverage,
   assignment churn, fairness, elapsed time, and hard-constraint violations
   separately. The simulator and this reinforcement-learning stage are future
   work, not results of the present classification experiment.

Algorithm selection and model selection are separate. The existing engine
benchmark still measures exact-result preservation and workload growth; this
experiment measures interpretation. Neither proves the entire assistant answers
arbitrary datasets in real time.
