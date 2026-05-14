"""
Unit tests for recovery modules (A12):
- src/recovery/position_verifier.py
- src/recovery/order_restorer.py
- src/recovery/position_converter.py
"""

from unittest.mock import AsyncMock

from src.database.models import OrderStatus, PositionStatus, PositionType
from src.domain.enums import PositionSide, State
from src.recovery.position_converter import PositionConverter


# ===========================================================================
# PositionConverter
# ===========================================================================


class TestPositionConverter:
    def test_convert_to_state_info_state_filled(self, make_converter):
        conv = make_converter()
        state = conv.convert_to_state_info_state(
            PositionStatus.FILLED, 1.0, PositionSide.LONG
        )
        assert state == State.BOUGHT

    def test_convert_to_state_info_state_filled_sell(self, make_converter):
        conv = make_converter()
        state = conv.convert_to_state_info_state(
            PositionStatus.FILLED, 1.0, PositionSide.SHORT
        )
        assert state == State.SOLD

    def test_convert_to_state_info_state_partially_filled_buy(self, make_converter):
        conv = make_converter()
        state = conv.convert_to_state_info_state(
            PositionStatus.PARTIALLY_FILLED, 0.5, PositionSide.LONG
        )
        assert state == State.PARTIALLY_BOUGHT

    def test_convert_to_state_info_state_open_buy(self, make_converter):
        conv = make_converter()
        state = conv.convert_to_state_info_state(
            PositionStatus.OPEN, 0.0, PositionSide.LONG
        )
        assert state == State.BUYING

    def test_convert_to_state_info_state_new(self, make_converter):
        conv = make_converter()
        state = conv.convert_to_state_info_state(
            PositionStatus.NEW, 0.0, PositionSide.LONG
        )
        assert state == State.NEW

    def test_convert_to_state_info_state_canceled(self, make_converter):
        conv = make_converter()
        state = conv.convert_to_state_info_state(
            PositionStatus.CANCELED, 0.0, PositionSide.LONG
        )
        assert state == State.CLOSED

    def test_convert_to_state_info_state_waiting_child(self, make_converter):
        conv = make_converter()
        state = conv.convert_to_state_info_state(
            PositionStatus.WAITING_CHILD, 0.0, PositionSide.LONG
        )
        assert state == State.WAITING_CHILD

    def test_convert_exchange_status_filled(self, make_converter):
        conv = make_converter()
        status = conv.convert_exchange_status("FILLED")
        assert status == OrderStatus.FILLED

    def test_convert_exchange_status_new(self, make_converter):
        conv = make_converter()
        status = conv.convert_exchange_status("NEW")
        assert status == OrderStatus.NEW

    def test_convert_exchange_status_partially_filled(self, make_converter):
        conv = make_converter()
        status = conv.convert_exchange_status("PARTIALLY_FILLED")
        assert status == OrderStatus.PARTIALLY_FILLED

    async def test_convert_to_buy_data_missing_symbol_returns_none(
        self, make_position
    ):
        conv = PositionConverter(symbols={})  # no symbols
        position = make_position()
        result = await conv.convert_to_buy_data(position)
        assert result is None

    async def test_convert_to_buy_data_filled_position(
        self, make_converter, make_position
    ):
        conv = make_converter()
        position = make_position(status=PositionStatus.FILLED, completeness=1.0)

        result = await conv.convert_to_buy_data(position)

        assert result is not None
        assert result.state_info.state == State.BOUGHT

    async def test_convert_to_sell_data_missing_symbol_returns_none(
        self, make_position
    ):
        conv = PositionConverter(symbols={})
        position = make_position(position_type=PositionType.SELL)
        result = await conv.convert_to_sell_data(position)
        assert result is None

    async def test_convert_to_sell_data_open_position(
        self, make_converter, make_position
    ):
        conv = make_converter()
        position = make_position(
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
    def test_all_filled_returns_true(self, verifier, make_order):
        orders = [make_order(OrderStatus.FILLED), make_order(OrderStatus.FILLED)]
        assert verifier._all_orders_filled(orders) is True

    def test_one_not_filled_returns_false(self, verifier, make_order):
        orders = [make_order(OrderStatus.FILLED), make_order(OrderStatus.NEW)]
        assert verifier._all_orders_filled(orders) is False

    def test_empty_list_returns_false(self, verifier):
        assert verifier._all_orders_filled([]) is False

    def test_single_canceled_returns_false(self, verifier, make_order):
        orders = [make_order(OrderStatus.CANCELED)]
        assert verifier._all_orders_filled(orders) is False


# ===========================================================================
# PositionVerifier.verify_positions_with_exchange
# ===========================================================================


class TestVerifyPositionsWithExchange:
    async def test_all_filled_skips_exchange_call(
        self, verifier, db_mock, make_position, make_order
    ):
        mock_client = AsyncMock()
        mock_client.get_order = AsyncMock()

        position = make_position(status=PositionStatus.FILLED, completeness=1.0)
        db_mock.get_position_orders = AsyncMock(
            return_value=[make_order(OrderStatus.FILLED)]
        )

        result = await verifier.verify_positions_with_exchange(mock_client, [position])

        assert len(result) == 1
        mock_client.get_order.assert_not_called()

    async def test_open_order_checks_exchange(
        self, verifier, db_mock, make_position, make_order
    ):
        mock_client = AsyncMock()
        mock_client.get_order = AsyncMock(
            return_value={"status": "FILLED", "executedQty": "0.001"}
        )

        position = make_position(status=PositionStatus.OPEN)
        open_order = make_order(status=OrderStatus.NEW)
        db_mock.get_position_orders = AsyncMock(return_value=[open_order])
        db_mock.save_order = AsyncMock()

        result = await verifier.verify_positions_with_exchange(mock_client, [position])

        assert len(result) == 1
        mock_client.get_order.assert_awaited_once()

    async def test_no_orders_keeps_position_as_is(
        self, verifier, db_mock, make_position
    ):
        mock_client = AsyncMock()

        position = make_position()
        db_mock.get_position_orders = AsyncMock(return_value=[])

        result = await verifier.verify_positions_with_exchange(mock_client, [position])

        assert result == [position]

    async def test_exception_during_verify_keeps_position_in_result(
        self, verifier, db_mock, make_position
    ):
        """If an exception is raised, the position is still returned for manual review."""
        mock_client = AsyncMock()

        position = make_position()
        db_mock.get_position_orders = AsyncMock(side_effect=RuntimeError("DB error"))

        result = await verifier.verify_positions_with_exchange(mock_client, [position])

        assert len(result) == 1
        assert result[0] is position

    async def test_order_without_exchange_id_is_kept_without_api_call(
        self, verifier, db_mock, make_position, make_order
    ):
        """Orders without exchange_order_id are included but not checked with exchange."""
        mock_client = AsyncMock()
        mock_client.get_order = AsyncMock()

        position = make_position()
        order_no_exchange_id = make_order(
            status=OrderStatus.NEW, exchange_order_id=None
        )
        db_mock.get_position_orders = AsyncMock(return_value=[order_no_exchange_id])

        await verifier.verify_positions_with_exchange(mock_client, [position])

        mock_client.get_order.assert_not_called()

    async def test_multiple_positions_all_verified(
        self, verifier, db_mock, make_position
    ):
        mock_client = AsyncMock()

        positions = [make_position() for _ in range(3)]
        db_mock.get_position_orders = AsyncMock(return_value=[])

        result = await verifier.verify_positions_with_exchange(mock_client, positions)

        assert len(result) == 3

