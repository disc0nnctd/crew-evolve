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
