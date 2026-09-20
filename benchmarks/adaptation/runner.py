"""Command-line and programmatic entry point for the adaptation protocol."""

from .protocol import (evaluate_family, main, run_protocol)

__all__ = ["evaluate_family", "main", "run_protocol"]


if __name__ == "__main__":
    raise SystemExit(main())
