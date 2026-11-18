"""Supported Binance spot symbols for the multi-asset pipeline."""

from __future__ import annotations

from typing import Literal, get_args

MarketSymbol = Literal[
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
]

MARKET_SYMBOLS: tuple[str, ...] = get_args(MarketSymbol)
DEFAULT_MARKET_SYMBOLS = MARKET_SYMBOLS
