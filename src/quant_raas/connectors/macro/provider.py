"""Protocol for canonical timestamped economic-release vintages."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

import pandas as pd


class MacroReleaseProvider(Protocol):
    @property
    def name(self) -> str: ...

    def fetch_releases(self, *, start: datetime, end: datetime) -> pd.DataFrame: ...
