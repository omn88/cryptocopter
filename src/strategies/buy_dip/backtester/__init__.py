"""Backtesting tools for Buy Dip strategy.

This package contains all backtesting-related modules:
- Historical data download from Binance
- Mock broker for simulating order execution
- Backtester for replaying strategy against historical data
- Performance metrics and analysis
"""

from src.strategies.buy_dip.backtester.backtester import (
    BacktestResult,
    HistoricalDataDownloader,
    BuyDipBacktester,
)
from src.strategies.buy_dip.backtester.mock_broker import MockBrokerAdapter

__all__ = [
    "BacktestResult",
    "HistoricalDataDownloader",
    "BuyDipBacktester",
    "MockBrokerAdapter",
]
