"""Small logging setup suitable for API, worker, and local research runs."""

from __future__ import annotations

import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure standard-library logging without imposing a logging vendor."""

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
