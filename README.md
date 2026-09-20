# Crew Evolve

Crew Evolve is a private, local crew-data workspace. It imports crew,
duty, and assignment tables; keeps each interpretation reviewable; and runs
deterministic coverage checks with reasons and source records. It is a
prototype, not certified scheduling or compliance software. Bundled examples
and benchmark data are synthetic.

## Start the workspace

Python 3.10 or later is enough for the core application. It has no required
runtime packages or model key:

```bash
python3 -m crew_evolve.server
```

Open `http://127.0.0.1:8780` and choose **Explore example data**. The default
SQLite workspace is `.crew-evolve/`; use `--port` or `--data-dir` to choose
another local path. Installed-package setup and the wheel/source archive smoke
check are in [INSTALL.md](docs/INSTALL.md).

The short browser walkthrough is [DEMO.md](docs/DEMO.md). It reviews an
explicit availability inversion, tests normalized records before acceptance,
reuses the named source contract on a later file, rejects a regression, and
rolls back the contract while leaving imported records unchanged.

## What the current foundation does

- Parses CSV, TSV, JSON arrays, and JSONL with strict validation. Imports are
  staged for preview; accepting one replaces only that table and retains the
  original text and raw rows.
- Supports named, source-scoped contracts with explicit `boolean`, `enum`, and
  `datetime` transforms. The **Test preview** step runs the candidate before
  table replacement. Contract evidence is bounded to 128 reviewed imports per
  source scope and up to 32 diverse rows per import.
- Reuses only approved workflow phrases with bounded matching for coverage,
  roster, and summary. This is a rule layer, not semantic training. A request
  still passes through the operations engine before an answer is shown.
- Keeps policy changes as proposals until an operator activates them. The
  engine checks availability, role, fleet qualification, duty length, rest,
  overlap, location continuity, and rolling seven-day hours.
- Uses versioned, revision-aware engine snapshots and bounded query caching.
  Workspace changes invalidate old answers and stale writes are rejected.
- Offers an optional local model candidate path. It is opt-in, uses cached
  files only, and remains subject to review and engine validation. See
  [LOCAL_MODEL.md](docs/LOCAL_MODEL.md).
- A remote chat-completions-compatible model is also opt-in through
  `CREW_MODEL_URL`, `CREW_MODEL`, and optional `CREW_MODEL_KEY`; no model call
  occurs during ordinary local operations.
- Supports private SQLite backup and restore. Backups include source data and
  learning evidence, so keep them protected; see [WORKSPACE.md](docs/WORKSPACE.md).

## Run checks and development protocols

```bash
python3 -m unittest discover -v
python3 scripts/package_smoke.py
```

The package smoke command builds a wheel and source archive, installs each
outside the checkout, and checks the web assets and example-data flow. The
adaptation protocol is documented in [ADAPTATION.md](docs/ADAPTATION.md); the
full request load procedure is [LOAD_BENCHMARK.md](docs/LOAD_BENCHMARK.md).
Those measurements and the typed-decision research remain under review. They
are not achieved production targets or claims about independent human use.

The repository remains private. Publication, license selection, and an
independent human trial are pending owner review. Do not add real crew data,
provider keys, downloaded model weights, workspaces, or generated artifacts to
the repository or distributions.

See [ARCHITECTURE.md](docs/ARCHITECTURE.md), [DATA.md](docs/DATA.md), and
[SCALING.md](docs/SCALING.md) for the implementation boundaries.
