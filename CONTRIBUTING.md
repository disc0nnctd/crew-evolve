# Contributing

Crew Evolve is developed as a private local application. Keep changes small,
inspectable, and covered by tests that exercise the behavior being changed.

## Development setup

Python 3.10 or later is enough for the core application. Runtime dependencies
are empty. The optional `local` extra is intended for Python 3.11 or later:

```bash
python3 -m pip install -e '.[local]'
```

The browser checks use the packages in `requirements-dev.txt`. They are
optional; the standard library test suite does not require a model provider,
browser, network access, or model weights.

## Checks before review

Run the unit suite and packaging checks from the repository root:

```bash
python3 -m unittest discover -v
python3 scripts/package_smoke.py
```

The package smoke check builds a wheel and source archive, installs each in a
temporary environment outside the checkout, and exercises the web page and
example-data endpoint. Do not commit build directories, archives, SQLite
workspaces, screenshots, downloaded models, provider keys, or private operator
data.

## Change boundaries

Keep operational decisions inspectable and preserve the core runtime's empty
dependency list. Model-assisted behavior remains optional and must not bypass
the engine's validation. Do not publish the repository or package from a
development change. License selection and release ownership remain pending
owner decisions.
