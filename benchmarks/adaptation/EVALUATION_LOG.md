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
holdout is reserved and has not been evaluated. The v2 process is an internal
reserved protocol, not a sealed independent research test. The command requires an
explicit owner unlock, protocol version, confirmation string, and manifest
hash after protocol freeze; no authorized run has occurred.

Development and training checks may exercise their labels. No final v2 labels
are passed through the evaluator in the checked-in test suite.
