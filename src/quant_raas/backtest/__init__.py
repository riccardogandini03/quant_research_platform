"""Point-in-time backtesting primitives.

The MVP exposes a deliberately small cross-sectional engine.  Live screens and
historical tests can share the same feature values without silently switching
to a different calculation path.
"""

from quant_raas.backtest.engine import BacktestResult, CrossSectionalBacktestEngine
from quant_raas.backtest.models import CrossSectionalBacktestSpec

__all__ = [
    "BacktestResult",
    "CrossSectionalBacktestEngine",
    "CrossSectionalBacktestSpec",
]
