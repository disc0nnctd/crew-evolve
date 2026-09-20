# Sample-based assistance rehearsal

This is an automated rehearsal of useful tasks and failure cases, using the
original synthetic crew sample plus the small browser example. It is not an
independent operator trial and does not measure human time saved.

## Results

| Check | Observed result |
| --- | --- |
| Original-sample workflow checks | 8 passed |
| Unsupported sample requests/input shape | 4 correctly clarified/rejected, counted separately |
| Two-day pairing continuity | 1 explicit capability gap, not counted as a passed request |
| Fixed request rehearsal | 2 supported requests answered; 10 requests clarified |
| Initial misleading responses in that rehearsal | 7, now corrected; original replies retained |
| Complete automated suite | 148 passed, 1 optional local-model test skipped |
| Actual browser scenarios | Both passed, including visible unsupported-condition messages |

The eight workflow checks include exact import values, saved-contract reuse,
both scoped day-block results, candidate explanations, learned workflow transfer,
assignment/release with stale-write rejection, and the reviewed sickness update.
They are checks within a selected rehearsal, not eight independent operator
trials. The full original question suite and original operating rules were not
validated.

The [sample report](reports/sample-usefulness-final.json),
[request replay](reports/request-usefulness-final.json), and
[verification record](reports/usefulness-verification.json) include exact
outcomes, limitations, source/code hashes, and validation commands.

## What data and rules were actually tested

The original sample has 150 crew, 147 flight legs, and 39 pairings. The runner
reads it from a supplied directory; no original files are modified or copied
wholesale into this repository. Reports retain source hashes.

The supported projection imports crew identities, names, base, rank, aircraft
ratings, and status through an explicit reviewed mapping. For this rehearsal,
`active` maps to available and `leave`/`training` to unavailable. That is a declared
test assumption, not proof that an active crew member is callable for a duty.
The later sickness overlay is separately declared and explicitly reviewed.

For that overlay, `C-1042` receives a new `sick` status in a derived upload. The
old mapping rejects it. An explicit reviewed extension maps `sick` to unavailable;
the next coverage result excludes `C-1042`, retains `C-3310`, and does not reuse a
stale answer. All other imported crew values remain unchanged. This demonstrates
a useful correction flow without claiming the full original sick-call solution.

The two supplied P-2291 day blocks retain their source report/release times,
aircraft type, and first/last flight stations. Only the captain and first-officer
slots are represented; candidate queries test the captain role. The initial
workspace has no assignment history, no cabin positions, and no sick-call event.
Expected candidate identities are computed from the source facts and the stated
test policy before asking the engine. They are not copied from engine output.

This scope has concrete consequences:

- The initial day-one result includes C-1042 because the source still marks that
  person active. It is a baseline projection, not the original sick-call scenario.
- C-2087 passes this no-history projection, although the original scenario key
  rejects that person for cumulative duty hours. Imported calendar-day totals
  cannot be silently treated as timestamped rolling-window history.
- The unlinked day-two block initially returns C-2210. C-3310 would reach its start
  station by operating day one; a query on the initial day-two workspace has no
  such assignment. The assistant does not produce an atomic two-day replacement.

These differences are capability gaps, not successes against the original
scenario keys. Certification, reserve windows, sector-dependent limits,
positioning costs, flight-hour limits, and multiple cabin seats remain unsupported.

## What the request tests found and changed

After learning a basic coverage workflow, the initial assistant ignored extra
conditions in questions about cost, certificate validity, reserve windows,
sickness, excluding a person, calendar-day limits, and delay scenarios. It
returned ordinary configured-rule coverage instead of addressing the condition.
The original replies are preserved in
[request-usefulness-initial.json](reports/request-usefulness-initial.json).

The request guard now explicitly clarifies those unsupported conditions before
the request can reach a learned workflow or model. The fix does not add those
missing planning capabilities. The guard remains a bounded vocabulary; passing
these repaired cases does not establish general natural-language understanding.

The request rehearsal separates completed supported tasks from justified
clarifications. An unsupported task is not counted as delivered merely because
the assistant refuses it. Browser checks also verify that cost, certificate, and
hypothetical sickness questions show the limitation and no assignment button.

## Source quality and model training

The source audit found 150 licence records whose `valid_from` dates fall after
the sample operating week. This is a source inconsistency, separate from the
assistant's missing certificate checks. See the
[source audit](reports/source-compatibility-audit.json). Original answer keys
are therefore not automatically reliable labels for model training.

The [model-tuning design](MODEL_TUNING.md) records the inspected Laya training
notebook and how reviewed corrections could train model weights in a future
experiment. No weights were trained in this rehearsal. The frozen adaptation
final was not rerun or modified.

## Reproduction

```bash
python3 scripts/sample_usefulness.py --sample-dir /path/to/original/sample/data --output artifacts/sample-usefulness.json
python3 scripts/request_usefulness.py --output artifacts/request-usefulness.json
python3 -m tests.browser_check
python3 -m tests.browser_release
python3 -m unittest discover -q
```

The original sample is an external input, so the source hashes in the report
identify the exact data tested. Browser checks use the repository's small
examples. The sample runner uses the application's import/query/learning/write
interfaces with a temporary workspace and an explicitly disabled model; it does
not manipulate stored mappings to bypass import review.
