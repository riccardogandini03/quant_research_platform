"""LSEG integration boundary (licensed Phase 5 capability)."""

from quant_raas.connectors.lseg.gateway import (
    LsegDesktopGateway,
    LsegGatewayResult,
    LsegPriceGateway,
)
from quant_raas.connectors.lseg.provider import LsegPriceProvider

__all__ = [
    "LsegDesktopGateway",
    "LsegGatewayResult",
    "LsegPriceGateway",
    "LsegPriceProvider",
]
