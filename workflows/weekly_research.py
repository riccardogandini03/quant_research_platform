"""Weekly reusable-screen workflow wrapper."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from quant_raas.screens.engine import ScreenResult, run_screen
from quant_raas.screens.models import ScreenDefinition


def run_weekly_screen(
    features: pd.DataFrame,
    definition: ScreenDefinition,
    *,
    as_of: datetime,
) -> ScreenResult:
    return run_screen(features, definition, as_of=as_of)
