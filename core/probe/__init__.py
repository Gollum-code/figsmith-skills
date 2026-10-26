"""Reference-figure geometry probes (loaded lazily, see core/tokens for the reason)."""

from __future__ import annotations

__all__ = ["measure", "suggest_ir"]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from . import probe_geometry

    return getattr(probe_geometry, name)
