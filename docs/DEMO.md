# Offline release demonstration

Run the recorder from the repository root:

```bash
python3 scripts/record_demo.py
```

The script starts the real local HTTP server with a temporary SQLite workspace,
opens a real Chromium browser, and records the visible import and learning
flow. It writes `artifacts/demo.webm` plus six screenshots named
`demo-01-start.png` through `demo-06-rollback.png`. These files are generated
artifacts and are not release source files.

The recorded path is:

1. Inspect a synthetic crew export containing `cannot_work`.
2. Map that column to availability and explicitly enable boolean inversion.
3. Test normalized records, then accept the reviewed contract.
4. Import a later file under `staff-export-v1` and show the reused transform.
5. Remove inversion and show the saved replay rejects the regression while
   leaving Accept disabled.
6. Roll back the active contract and show that imported records stay unchanged.

All meaning in this demo comes from the reviewed rule the operator selects.
The recorder does not call a model, require a provider key, or claim that a
model inferred the polarity. The unknown-source clarification path and the
full API regression assertions are covered by `tests/browser_release.py`.

To inspect the video metadata when `ffprobe` is installed:

```bash
ffprobe -v error -show_entries format=duration,size -of default=noprint_wrappers=1 artifacts/demo.webm
```

The recorder uses only a temporary workspace and shuts down the server and
browser before returning.
