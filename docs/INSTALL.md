# Install and run

Crew Evolve supports Python 3.10 or later and has no required runtime
dependencies. Build or install a wheel from a checkout:

```bash
python -m pip wheel --no-deps --no-build-isolation --wheel-dir dist .
python -m pip install --no-deps dist/crew_evolve-0.2.0rc1-py3-none-any.whl
crew-evolve
```

The wheel carries the web interface and example CSV files inside the Python
package, so the command works from a directory outside the source checkout.
The default server listens on `127.0.0.1:8780`; open that address and choose
**Explore example data**. Use `--port` or `--data-dir` to change the local
workspace location.

The core package supports Python 3.10 or later. The optional `local` extra is
for Python 3.11 or later and adds the local model packages:

```bash
python3.11 -m pip install './dist/crew_evolve-0.2.0rc1-py3-none-any.whl[local]'
```

To build and smoke-test both source archives and an isolated wheel install
without downloading dependencies:

```bash
python scripts/package_smoke.py
```

The default smoke check uses only the standard library and local build tools.
For an installed UI check, install the optional browser tooling and Chromium in
the host environment, then pass `--browser`:

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python scripts/package_smoke.py --browser
```

This opens each installed wheel and source-archive server outside the checkout,
reviews one source-scoped boolean inversion, tests the normalized preview, and
reuses that reviewed contract on a later file. The browser mode is optional;
it does not add browser packages to the runtime or distributions.

The repository is private while release work continues. License selection and
publication remain owner decisions.
