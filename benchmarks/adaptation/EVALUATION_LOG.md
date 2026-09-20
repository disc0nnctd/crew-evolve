# Evaluation log

This file records holdout handling for the private repository.

On 2026-09-20 a read-only command selected the original v1 `--split final`
families while the protocol was still being reviewed. No result was written
to the repository. Those scores are invalid holdout evidence and are excluded
from reported comparison metrics and claims; the review informed protocol
repairs. The v1 final manifest is retained at
`history/manifest-v1-retired.json` for auditability.

The v1 final families are retired. The generator now freezes three new v2
families with new names, seeds, headers, and value encodings. The v2 final
holdout was reserved during implementation. The v2 process is an internal
reserved protocol, not a sealed independent research test. The command requires an
explicit maintainer unlock, protocol version, confirmation string, and manifest
hash after protocol freeze.

Development and training checks may exercise their labels. No final v2 labels
are passed through the evaluator in the checked-in test suite.

## Frozen internal v2 run, 2026-09-20

After Terra approved the synthetic protocol, implementation commit
`4448641160580a9a97f01a8f1c7905c44596912d` was frozen. The manifest SHA-256 was
`f1f8e53bbfaedfe1741a9b5f095766a8a5c4f7607f409afe2e64859fe3981395`.
Both methods then ran once on development and once on final with every declared
budget and seed. Raw traces, frozen source hashes, and completion hashes are
preserved under `docs/reports/adaptation-*.json`.

The final contract result did not reach the proposed useful-coverage target.
All outcomes are retained; no implementation or protocol changes were made
in response to this final result. Future tuning needs a new reserved test.
Because generator rules and labels were in the same working tree, this remains
an internal synthetic evaluation, not a sealed, blind, or independent holdout.
