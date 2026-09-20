"""Locate web and example assets in a checkout or an installed package."""

from pathlib import Path


_ASSET_NAMES = frozenset(("web", "examples"))


def asset_dir(kind: str) -> Path:
    """Return the directory for a supported runtime asset collection.

    Built wheels and source distributions contain copied files below
    ``crew_evolve/_assets``.  During checkout development those files do not
    need to exist: the root-level source directories are used instead.
    """

    if not isinstance(kind, str) or kind not in _ASSET_NAMES:
        choices = ", ".join(sorted(_ASSET_NAMES))
        raise ValueError(f"Unknown asset collection {kind!r}; choose {choices}.")

    package_root = Path(__file__).resolve().parent
    packaged = package_root / "_assets" / kind
    if packaged.is_dir():
        return packaged

    checkout = package_root.parent / kind
    if checkout.is_dir():
        return checkout

    raise FileNotFoundError(f"Could not locate Crew Evolve {kind} assets.")


__all__ = ["asset_dir"]
