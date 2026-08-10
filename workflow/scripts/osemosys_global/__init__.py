
# -*- coding: utf-8 -*-
try:
    from importlib.metadata import version, PackageNotFoundError
except ImportError:  # pragma: no cover
    from importlib_metadata import version, PackageNotFoundError  # backport if needed

try:
    __version__ = version("osemosys_global")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = ["extract_country"]

