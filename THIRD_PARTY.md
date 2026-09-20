# Third-party software

The core Crew Evolve runtime declares no required third-party dependencies. It
uses Python's standard library for the local HTTP server, SQLite workspace,
CSV/JSON parsing, and model-provider transport.

Optional and development dependencies are kept separate from the core install:

| Group | Packages | Purpose |
| --- | --- | --- |
| `local` extra, Python 3.11+ | `sentence-transformers>=5.4,<6`, `scikit-learn>=1.8,<2` | Optional local model experiments |
| Development requirements | `playwright==1.58.0` | Optional browser checks |
| Build requirements | `setuptools>=61`, `wheel` | Build wheel and source distributions |

Use each dependency's own distribution metadata and license text when
installing it. This inventory does not select a project license or grant
permission to redistribute any dependency. License selection for Crew Evolve
remains pending owner review.

The optional local candidate path uses
[`sentence-transformers/all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
at revision `c9745ed1d9f207416be6d2e6f8de32d1f16199bf`. Model weights are not
included in this repository or its distributions. The operator supplies a local
cache and should review the upstream model card and license before use or
redistribution. Overrides must be reviewed separately; inference evidence
records the configured identity and revision.

Bundled example and adaptation/load benchmark records are synthetic. They are
not an airline dataset or evidence of operational validity. Historical
experiments in `research/` are separate from the runtime and are excluded from
the source and wheel distributions.
