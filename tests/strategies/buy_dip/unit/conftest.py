import queue
from decimal import Decimal
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.broker import BrokerSpot
from src.common.client import KrakenClient
from src.common.symbol import Symbol
from src.database import Database
from src.strategies.buy_dip.config import BuyDipConfig
from src.strategies.buy_dip.executor import BuyDipExecutor


@pytest.fixture
def buy_dip_config() -> BuyDipConfig:
    return BuyDipConfig(
        min_consecutive_rising=3,
        min_total_gain_pct=1.0,
        dca_distances_pct=[2.0, 4.0],
    )


@pytest.fixture
def symbols_dict() -> Dict[str, Any]:
    return {
        "BTCUSDC": Symbol(
            name="BTCUSDC",
            precision=5,
            price_precision=2,
            min_notional=10.0,
            price_filter=0.01,
        )
    }


@pytest.fixture
def make_executor(buy_dip_config: BuyDipConfig, symbols_dict: Dict[str, Any]):
    """Factory fixture: build a BuyDipExecutor for given symbols."""

    def _factory(symbols: list[str] | None = None):
        return BuyDipExecutor(
            db=MagicMock(spec=Database),
            broker=MagicMock(spec=BrokerSpot),
            client=AsyncMock(spec=KrakenClient),
            ui_queue=queue.Queue(),
            config=buy_dip_config,
            total_budget=Decimal("1000"),
            order_budget_pct=Decimal("10"),
            symbols=symbols or ["BTCUSDC"],
            symbols_dict=symbols_dict,
        )

    return _factory


@pytest.fixture
def executor(make_executor):
    return make_executor()
