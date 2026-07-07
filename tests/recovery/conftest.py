from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from src.common.symbol import Symbol
from src.database.models import (
    Order as DatabaseOrder,
    OrderStatus,
    Position,
    PositionStatus,
    PositionType,
)
from src.recovery.position_converter import PositionConverter
from src.recovery.position_verifier import PositionVerifier


@pytest.fixture
def make_position():
    """Factory fixture: create a Position with sensible defaults."""

    def _factory(
        status: PositionStatus = PositionStatus.NEW,
        completeness: float = 0.0,
        position_type: PositionType = PositionType.BUY,
        symbol: str = "BTCUSDC",
    ) -> Position:
        return Position(
            hp_id="hp-001",
            symbol=symbol,
            coin="BTC",
            buy_price=50000.0,
            sell_price=0.0,
            quantity=0.001,
            realized_quantity=0.0,
            budget=100.0,
            status=status,
            position_type=position_type,
            completeness=completeness,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    return _factory


@pytest.fixture
def make_order():
    """Factory fixture: create a DatabaseOrder with sensible defaults."""

    def _factory(
        status: OrderStatus = OrderStatus.FILLED,
        quantity: float = 0.001,
        realized_quantity: float = 0.001,
        exchange_order_id: str | None = "12345",
    ) -> DatabaseOrder:
        return DatabaseOrder(
            position_id="pos-001",
            symbol="BTCUSDC",
            side="BUY",
            status=status,
            price=50000.0,
            quantity=quantity,
            quantity_stable=100.0,
            realized_quantity=realized_quantity,
            exchange_order_id=exchange_order_id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    return _factory


@pytest.fixture
def make_converter():
    """Factory fixture: create a PositionConverter for a given symbol."""

    def _factory(symbol: str = "BTCUSDC") -> PositionConverter:
        symbols = {symbol: Symbol(name=symbol, precision=5, price_precision=2)}
        return PositionConverter(symbols=symbols)

    return _factory


@pytest.fixture
def db_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def converter() -> PositionConverter:
    return PositionConverter(
        symbols={"BTCUSDC": Symbol(name="BTCUSDC", precision=5, price_precision=2)}
    )


@pytest.fixture
def verifier(db_mock, converter) -> PositionVerifier:
    return PositionVerifier(database=db_mock, converter=converter)
