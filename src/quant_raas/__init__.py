"""Quant Research-as-a-Service domain package.

The package is intentionally a modular monolith: domain and quantitative code
remain independent of delivery mechanisms and vendor SDKs, while storage and
connector modules implement the small ports defined by the domain.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("quant-raas")
except PackageNotFoundError:  # Running directly from a source checkout.
    __version__ = "0.1.0"

__all__ = ["__version__"]
