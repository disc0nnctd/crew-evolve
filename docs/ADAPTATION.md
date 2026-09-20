# Adaptation benchmark

The fixtures in `benchmarks/adaptation/` measure import accuracy and valid
request coverage after a correction survives a changed crew export. They are a
synthetic development protocol, not a blind independent research test or an
operational safety claim. Source families are authored variations from one
generator and remain correlated. The repository remains private while the
protocol is reviewed.

The frozen v2 manifest has twelve source export families. Six are training
families, three are development families, and three are reserved final v2
families. The prior v1 final families were retired after a read-only command
selected the old final split; their manifest is retained in
`benchmarks/adaptation/history/`. Every family has
related crew, duty, and assignment tables generated from one seed. The source
files vary headers, boolean polarity, role values, list separators, date
formats, irrelevant fields, and casing. The labels contain generated but
separate expected outputs and deliberate faults for missing values, duplicate identifiers,
contradictory assignments, and unknown enum values.

Raw tables are under `families/`; labels are under `labels/`. A model-facing
loader uses `load_family(name)` and does not return labels. The evaluator opts
into labels with `load_family(name, include_labels=True)`. `manifest.json`
records each file's SHA-256 fingerprint, split, seed, protocol version, and
label location. Re-running `python3 -m benchmarks.adaptation.generate` must
produce the same manifest and content.

The frozen feedback budgets are `0`, `1`, `5`, `10`, and `20`, with five
scenario seeds. Each stream contains more than twenty chronological valid
future cases with changed names, identifiers, dates, and availability values.
It scores a request first, then reveals at most one source field packet. The input sequence and maximum correction budget are paired. Feedback is
selected from each method's current failures; its packet sequence, timing,
count, and information can differ. Contracts can consume declared transforms,
while aliases use mappings. This is an end-to-end comparison, not an
isolated effect under equal-information feedback. The
contract vocabulary is `boolean` with `invert`, `enum` with explicit `values`,
and `datetime` with an explicit format and timezone.

Run the development protocol with:

```text
python3 -m benchmarks.adaptation --method aliases
python3 -m benchmarks.adaptation --method contracts --json
# equivalent module entry point:
python3 -m benchmarks.adaptation.runner --method contracts
```

The command reports one row per source family and a separate row for each
budget, then a macro mean over source families. It reports accepted,
rejected, and abstained outcomes with normalized reasons. Accuracy means
known-answer agreement. Coverage means accepted valid imports whose normalized
crew, duty, and assignment records and relationships match the known answer.
Fault labels declare allowed observed rejection categories. A rejection from
an unsupported control schema is reported as unassessable and receives no
credit. Traces retain expected and observed reasons separately.
Rows inside a family or scenario are correlated, so the report does not treat
them as independent observations or print inflated significance. The fixed
model, word classifier, and sentence model baselines are marked `not-run`.

`--split final` is refused without explicit maintainer intent: `--unlock-final`,
`--final-version 2.0`, `--confirm-final CREW-EVOLVE-ADAPTATION-FINAL-V2`, and
`--manifest-sha256` with the exact frozen hash. These are intentional-run guards,
not credentials or a sealed holdout. An internal v2 run was completed after
freezing commit `4448641`; raw reports and freeze/completion hashes are in
`docs/reports/`. See [evaluation log](EVALUATION_LOG.md) and
[measured results](BUILD_VERIFICATION.md). The final was available in the working
tree and is not independent or blind. Future tuning requires a new reserved test.

The benchmark checks transfer before correction and adaptation after feedback.
It does not establish a production model, regulatory compliance, or semantic
understanding outside the declared crew, duty, and assignment fields.
