"""
Unit tests for recovery modules (A12):
- src/recovery/position_verifier.py
- src/recovery/order_restorer.py
- src/recovery/position_converter.py
"""

import time
from datetime import datetime
from decimal import Decimal
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.common.symbol import Symbol
from src.database.models import (
    Order as DatabaseOrder,
    OrderStatus,
    Position,
    PositionStatus,
    PositionType,
)
from src.domain.enums import PositionSide, State
from src.recovery.position_converter import PositionConverter
from src.recovery.position_verifier import PositionVerifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_position(
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


def _make_order(
    status: OrderStatus = OrderStatus.FILLED,
    quantity: float = 0.001,
    realized_quantity: float = 0.001,
    exchange_order_id: int | None = 12345,
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


def _make_converter(symbol: str = "BTCUSDC") -> PositionConverter:
    symbols = {symbol: Symbol(name=symbol, precision=5, price_precision=2)}
    return PositionConverter(symbols=symbols)


def _make_verifier() -> tuple[PositionVerifier, AsyncMock]:
    db = AsyncMock()
    converter = _make_converter()
    verifier = PositionVerifier(database=db, converter=converter)
    return verifier, db


# ===========================================================================
# PositionConverter
# ===========================================================================


class TestPositionConverter:
    def test_convert_to_state_info_state_filled(self):
        conv = _make_converter()
        state = conv.convert_to_state_info_state(
            PositionStatus.FILLED, 1.0, PositionSide.LONG
        )
        assert state == State.BOUGHT

    def test_convert_to_state_info_state_filled_sell(self):
        conv = _make_converter()
        state = conv.convert_to_state_info_state(
            PositionStatus.FILLED, 1.0, PositionSide.SHORT
        )
        assert state == State.SOLD

    def test_convert_to_state_info_state_partially_filled_buy(self):
        conv = _make_converter()
        state = conv.convert_to_state_info_state(
            PositionStatus.PARTIALLY_FILLED, 0.5, PositionSide.LONG
        )
        assert state == State.PARTIALLY_BOUGHT

    def test_convert_to_state_info_state_open_buy(self):
        conv = _make_converter()
        state = conv.convert_to_state_info_state(
            PositionStatus.OPEN, 0.0, PositionSide.LONG
        )
        assert state == State.BUYING

    def test_convert_to_state_info_state_new(self):
        conv = _make_converter()
        state = conv.convert_to_state_info_state(
            PositionStatus.NEW, 0.0, PositionSide.LONG
        )
        assert state == State.NEW

    def test_convert_to_state_info_state_canceled(self):
        conv = _make_converter()
        state = conv.convert_to_state_info_state(
            PositionStatus.CANCELED, 0.0, PositionSide.LONG
        )
        assert state == State.CLOSED

    def test_convert_to_state_info_state_waiting_child(self):
        conv = _make_converter()
        state = conv.convert_to_state_info_state(
            PositionStatus.WAITING_CHILD, 0.0, PositionSide.LONG
        )
        assert state == State.WAITING_CHILD

    def test_convert_exchange_status_filled(self):
        conv = _make_converter()
        status = conv.convert_exchange_status("FILLED")
        assert status == OrderStatus.FILLED

    def test_convert_exchange_status_new(self):
        conv = _make_converter()
        status = conv.convert_exchange_status("NEW")
        assert status == OrderStatus.NEW

    def test_convert_exchange_status_partially_filled(self):
        conv = _make_converter()
        status = conv.convert_exchange_status("PARTIALLY_FILLED")
        assert status == OrderStatus.PARTIALLY_FILLED

    @pytest.mark.asyncio
    async def test_convert_to_buy_data_missing_symbol_returns_none(self):
        conv = PositionConverter(symbols={})  # no symbols
        position = _make_position()
        result = await conv.convert_to_buy_data(position)
        assert result is None

    @pytest.mark.asyncio
    async def test_convert_to_buy_data_filled_position(self):
        conv = _make_converter()
        position = _make_position(status=PositionStatus.FILLED, completeness=1.0)

        result = await conv.convert_to_buy_data(position)

        assert result is not None
        assert result.state_info.state == State.BOUGHT

    @pytest.mark.asyncio
    async def test_convert_to_sell_data_missing_symbol_returns_none(self):
        conv = PositionConverter(symbols={})
        position = _make_position(position_type=PositionType.SELL)
        result = await conv.convert_to_sell_data(position)
        assert result is None

    @pytest.mark.asyncio
    async def test_convert_to_sell_data_open_position(self):
        conv = _make_converter()
        position = _make_position(
            status=PositionStatus.OPEN,
            completeness=0.0,
            position_type=PositionType.SELL,
        )
        position.sell_price = 55000.0
        position.end_currency = "USDC"

        result = await conv.convert_to_sell_data(position)

        assert result is not None
        assert result.state_info.state == State.SELLING


# ===========================================================================
# PositionVerifier._all_orders_filled
# ===========================================================================


class TestAllOrdersFilled:
    def setup_method(self):
        self.verifier, _ = _make_verifier()

    def test_all_filled_returns_true(self):
        orders = [_make_order(OrderStatus.FILLED), _make_order(OrderStatus.FILLED)]
        assert self.verifier._all_orders_filled(orders) is True

    def test_one_not_filled_returns_false(self):
        orders = [_make_order(OrderStatus.FILLED), _make_order(OrderStatus.NEW)]
        assert self.verifier._all_orders_filled(orders) is False

    def test_empty_list_returns_false(self):
        assert self.verifier._all_orders_filled([]) is False

    def test_single_canceled_returns_false(self):
        orders = [_make_order(OrderStatus.CANCELED)]
        assert self.verifier._all_orders_filled(orders) is False


# ===========================================================================
# PositionVerifier.verify_positions_with_exchange
# ===========================================================================


class TestVerifyPositionsWithExchange:
    @pytest.mark.asyncio
    async def test_all_filled_skips_exchange_call(self):
        verifier, db = _make_verifier()
        mock_client = AsyncMock()
        mock_client.get_order = AsyncMock()

        position = _make_position(status=PositionStatus.FILLED, completeness=1.0)
        db.get_position_orders = AsyncMock(
            return_value=[_make_order(OrderStatus.FILLED)]
        )

        result = await verifier.verify_positions_with_exchange(mock_client, [position])

        assert len(result) == 1
        mock_client.get_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_open_order_checks_exchange(self):
        verifier, db = _make_verifier()
        mock_client = AsyncMock()
        mock_client.get_order = AsyncMock(
            return_value={"status": "FILLED", "executedQty": "0.001"}
        )

        position = _make_position(status=PositionStatus.OPEN)
        open_order = _make_order(status=OrderStatus.NEW)
        db.get_position_orders = AsyncMock(return_value=[open_order])
        db.save_order = AsyncMock()

        result = await verifier.verify_positions_with_exchange(mock_client, [position])

        assert len(result) == 1
        mock_client.get_order.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_orders_keeps_position_as_is(self):
        verifier, db = _make_verifier()
        mock_client = AsyncMock()

        position = _make_position()
        db.get_position_orders = AsyncMock(return_value=[])

        result = await verifier.verify_positions_with_exchange(mock_client, [position])

        assert result == [position]

    @pytest.mark.asyncio
    async def test_exception_during_verify_keeps_position_in_result(self):
        """If an exception is raised, the position is still returned for manual review."""
        verifier, db = _make_verifier()
        mock_client = AsyncMock()

        position = _make_position()
        db.get_position_orders = AsyncMock(side_effect=RuntimeError("DB error"))

        result = await verifier.verify_positions_with_exchange(mock_client, [position])

        assert len(result) == 1
        assert result[0] is position

    @pytest.mark.asyncio
    async def test_order_without_exchange_id_is_kept_without_api_call(self):
        """Orders without exchange_order_id are included but not checked with exchange."""
        verifier, db = _make_verifier()
        mock_client = AsyncMock()
        mock_client.get_order = AsyncMock()

        position = _make_position()
        order_no_exchange_id = _make_order(
            status=OrderStatus.NEW, exchange_order_id=None
        )
        db.get_position_orders = AsyncMock(return_value=[order_no_exchange_id])

        await verifier.verify_positions_with_exchange(mock_client, [position])

        mock_client.get_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_positions_all_verified(self):
        verifier, db = _make_verifier()
        mock_client = AsyncMock()

        positions = [_make_position() for _ in range(3)]
        db.get_position_orders = AsyncMock(return_value=[])

        result = await verifier.verify_positions_with_exchange(mock_client, positions)

        assert len(result) == 3
