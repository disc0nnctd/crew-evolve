# Model training from reviewed crew corrections

Status: design grounded in inspected upstream training code. **No model weights
have been trained or changed by crew-evolve.** Current self-evolution versions
source contracts and workflow corrections. The optional local sentence model
remains frozen. Training a new candidate model is a separate, feasible extension.

## What Laya actually supplies

Inspected upstream commit: `d113dca2512fb3eaca313534bc54c7162d87c1d4`.
The [README](https://github.com/NandhaKishorM/laya/blob/d113dca2512fb3eaca313534bc54c7162d87c1d4/README.md)
links a working
[fine-tuning notebook](https://github.com/NandhaKishorM/laya/blob/d113dca2512fb3eaca313534bc54c7162d87c1d4/notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb).
It loads `convaiinnovations/laya` and updates the encoder and typed-decision
parameters, rather than merely storing additional examples in a prompt.
Training items contain `state`, `questions`, and `gold` target distributions.
Question types represent choices, boolean judgments, and ordinal scores.

The notebook combines noisy sampled logits, scoring-rule rewards, normalized
within-group advantages, and soft cross-entropy guidance. Its default setup uses
two T4 GPUs and four epochs. The implementation is Laya's own recipe; inspecting
it does not establish a reproduction of Jev's private training method. TypeSafe
uses RLCD to mean
[Reinforcement Learning for Calibrated Decisions](https://typesafe.ai/blog/introducing-system-one-models-and-jev).

Two defaults require changes for our experiment:

- The notebook fits temperatures on `all_items[::15][:400]`, a subset of the
  training decisions. Our confidence calibration must use a separate split that
  has not updated weights. A separately held-out final test must remain untouched
  by both training and calibration.
- The optional upload cell creates a public Hub repository with `private=False`.
  Our adapted runner must save locally by default and must not execute that cell.
  This project and any resulting checkpoints remain private.

No notebook cell, training job, model installation, or upload was executed during
this review. Published upstream benchmark figures are not crew-task results.

## Where trained weights could help

Useful first targets are choosing a supported workflow, proposing a field
meaning, and identifying requests that need clarification. Those decisions can
be labeled from reviewed corrections and tested independently of operational
arithmetic. The current request rehearsal exposes examples where a bare coverage
route loses an extra condition; a training target must preserve those conditions
or abstain, rather than learn to ignore them.

Weights cannot supply missing backend capabilities. Certification validity,
reserve windows, costs, multi-person positions, and whole-pairing replacement
need explicit data and implementation. Current deterministic checks must stay
authoritative for the supported operation, with explicit scope checks before
execution. Training must not turn a scoped engine result into a claim that all
source rules were checked.

The measured changing-duty bottleneck is also in deterministic engine work; the
load test made no model calls. Faster or better model choices alone cannot fix
that measured bottleneck.

## Proposed experiment

1. Export reviewed corrections with the original request, source/schema identity,
   available operations, approved outcome, and label provenance. Preserve explicit
   unsupported and ambiguous cases. Do not label the model's own guesses as truth.
2. Split by source/schema and workflow family before making paraphrases or derived
   rows. Separate training, development, confidence calibration, and final test
   sets. Individual crew records from one export are not independent mapping
   examples. Use new evaluation data; do not train against the frozen adaptation
   final or present the repaired request cases as unseen evaluation.
3. Compare unchanged workflow reuse, a frozen model, ordinary supervised tuning,
   and the Laya-style training recipe on the same reviewed training records and
   the same untouched test tasks. Measure actual compute and latency as well as
   task outcomes. Reinforcement learning is a candidate method, not a required
   ingredient or an established improvement.
4. Measure completed supported tasks, exact field decisions, wrong accepted
   requests, justified clarification, confidence quality (Brier score/log loss
   and reliability buckets), and complete request latency. Keep those measures
   separate rather than concealing errors in an average score. Guard refusals
   are not successful completion of an unsupported task.
5. Save a candidate checkpoint, data hashes, training settings, evaluation report,
   and calibration parameters. Evaluate it without changing live assignments,
   operating rules, or the active model. Promotion requires better measured
   assistance without weakening constraint checks or exceeding the stated error
   budget. Retain the prior checkpoint and a rollback path.

The current source audit found licence validity dates after the sample's operating
week. Such inconsistent source facts and the source's full scenario answer keys
cannot automatically serve as correct training rewards. Corrected, verified
labels are a prerequisite for a credible improvement claim.

This is a plan for real weight adaptation. The implementation and its efficacy
remain untested; current sample rehearsals test the existing application.
