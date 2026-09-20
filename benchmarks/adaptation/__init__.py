"""The source-format adaptation benchmark.

The package deliberately keeps source records and answer labels in separate
files.  Importing :mod:`benchmarks.adaptation` does not evaluate the final
holdout.
"""

from .protocol import (BUDGETS, MANIFEST, SEEDS, SPLITS, load_family,
                       load_manifest, run_protocol)

__all__ = ["BUDGETS", "MANIFEST", "SEEDS", "SPLITS", "load_family",
           "load_manifest", "run_protocol"]
