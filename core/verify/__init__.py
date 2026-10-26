"""Verification helpers.

The submodules are exported lazily so `python -m core.verify.check_contrast` does not
import the module twice (once as part of the package, once as `__main__`), which made
runpy print a RuntimeWarning next to the pass/fail line of the documented check.
"""

from __future__ import annotations

__all__ = ["check_tiling", "check_contrast", "check_overflow"]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from . import check_contrast, check_overflow, check_tiling

    return {"check_tiling": check_tiling.check,
            "check_contrast": check_contrast.check,
            "check_overflow": check_overflow.check}[name]
