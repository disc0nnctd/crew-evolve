# Optional local model

The local model is an opt-in candidate generator. It uses the cached
`sentence-transformers/all-MiniLM-L6-v2` encoder at revision
`c9745ed1d9f207416be6d2e6f8de32d1f16199bf`. It ranks at most twenty
operator-approved workflow examples and returns a reviewable suggestion. It
does not assign crew, execute an operation, activate a policy, or replace the
engine's arithmetic checks.

Install the optional dependency and select the model explicitly:

```bash
python3 -m pip install sentence-transformers
export CREW_LOCAL_MODEL=minilm
python3 -m crew_evolve.server
```

The model loader uses `local_files_only=True`. A cached model or an explicit
local directory is required; it will not download weights or call a provider.
`CREW_LOCAL_MODEL_PATH` can point to a local Sentence Transformers directory.
`CREW_LOCAL_MODEL_NAME` and `CREW_LOCAL_MODEL_REVISION` are available for a
reviewed local cache, with the pinned model and revision used by default.

The model implements the same `configured`, `name`, `route`, `mapping`, and
`policy` interface as the provider model. Route requests first pass the
existing request guard. A coverage candidate must contain one exact duty ID
and one exact role from the supplied workspace context. Unknown, ambiguous,
unsupported, or weakly matched requests return `action: clarify` with
evidence. Mapping suggestions rank canonical field descriptions with the
sample values from each source column. A negative availability column is
always left for explicit operator inversion; it is never silently mapped as
positive availability. Policy requests return a question for the exact manual
rule, jurisdiction, and values instead of inventing safety limits.

Every suggestion includes retrieval similarities, thresholds, selected
examples, model revision, local-only status, and latency. Similarity thresholds
are initial heuristics and are not probabilities of correctness. The returned
candidate remains subject to manual review and the existing application
validation.

Run the real local check after setting `CREW_LOCAL_MODEL=minilm`:

```bash
python3 scripts/local_model_check.py
```

The command runs unseen wording against three approved templates plus a small
field mapping case. It writes raw JSON to
`artifacts/local-model-check.json` by default and prints the same report. A
missing dependency or cache is recorded as an error with no synthetic success.
Use `--strict` when a nonzero status is useful in a local verification job.

The check is evidence for this cache and machine only. It is not a routing or
mapping benchmark, and the local model is never autoactivated by learned
weights.

Laya supplies an upstream recipe for actual model-weight training. The separate
[model-tuning design](MODEL_TUNING.md) records inspected code, private output
requirements, and the proposed evaluation loop. That training loop is not yet
implemented here; saved corrections currently change configuration only.
