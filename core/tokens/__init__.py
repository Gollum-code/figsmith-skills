"""Semantic style tokens.

The loader is exposed lazily so `python -m core.tokens.loader --check` does not import
the module twice (once as part of the package, once as `__main__`), which made runpy
print a RuntimeWarning right next to the pass/fail line of the documented check.
"""

from __future__ import annotations

__all__ = ["Tokens", "load", "available", "hex_to_gray", "gray_delta", "measure_text"]


def __getattr__(name: str):
    if name in __all__:
        from . import loader

        return getattr(loader, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
