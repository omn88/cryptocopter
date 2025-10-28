"""Backtesting tools for Buy Dip strategy.

This package contains all backtesting-related modules:
- Historical data download from Binance
- Backtester for replaying strategy against historical data with mocked broker
- Performance metrics and analysis
"""

from src.strategies.buy_dip.backtester.backtester import (
    BacktestResult,
    HistoricalDataDownloader,
    BuyDipBacktester,
)

__all__ = [
    "BacktestResult",
    "HistoricalDataDownloader",
    "BuyDipBacktester",
]
