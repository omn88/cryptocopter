"""Unit tests for PortfolioEventHelper.

Covers:
- Correct event dataclass is constructed and passed to the callback
- _send_portfolio_event swallows nothing – errors propagate as RuntimeError
- No callback (None) is a no-op
- handle_* convenience wrappers delegate to the correct send_* method
- handle_buy_cancellation skips the event when state is NEW
"""

import pytest
from unittest.mock import MagicMock, patch

from src.domain.enums import EventName, State
from src.domain.events import (
    HPBuyOrdersPlaced,
    HPBuyPositionCreated,
    HPBuyPositionFilled,
    HPBuyPositionPartiallyFilled,
    HPPositionCancelled,
    HPSellPositionCompleted,
    HPSellPositionCreated,
    HPSellPositionPartiallyFilled,
)
from src.domain.positions import HPSellConfig, StateInfo
from src.domain.enums import PositionSide
from src.gui.identifiers import HPClose
from src.portfolio.portfolio_event_helper import PortfolioEventHelper

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_helper():
    cb = MagicMock()
    helper = PortfolioEventHelper(portfolio_event_callback=cb)
    return helper, cb


def _last_call(cb):
    """Return (event_name, event_data) from the last callback invocation."""
    args = cb.call_args[0]
    return args[0], args[1]


def _make_close(
    hp_id="1000",
    coin="BTC",
    quantity=1.0,
    buy_price=50000.0,
    sell_price=55000.0,
    end_currency="USDC",
):
    config = HPSellConfig(
        hp_id=hp_id,
        symbol=f"{coin}{end_currency}",
        coin=coin,
        sell_price=sell_price,
        quantity=quantity,
        buy_price=buy_price,
        end_currency=end_currency,
    )
    state_info = StateInfo(side=PositionSide.SHORT)
    return HPClose(config=config, state_info=state_info)


# ---------------------------------------------------------------------------
# No callback → no-op
# ---------------------------------------------------------------------------


class TestNoCallback:
    def test_send_event_with_none_callback_does_not_raise(self):
        helper = PortfolioEventHelper(portfolio_event_callback=None)
        # Should simply do nothing
        helper.send_buy_creation_event("1000", "BTC", 1000.0, 50000.0)


# ---------------------------------------------------------------------------
# send_buy_creation_event
# ---------------------------------------------------------------------------


class TestSendBuyCreationEvent:
    def test_fires_correct_event_name(self):
        helper, cb = _make_helper()
        helper.send_buy_creation_event("1000", "BTC", 1000.0, 50000.0)
        name, _ = _last_call(cb)
        assert name == EventName.HP_BUY_POSITION_CREATED

    def test_event_data_fields(self):
        helper, cb = _make_helper()
        helper.send_buy_creation_event("1000", "BTC", 1000.0, 50000.0)
        _, data = _last_call(cb)
        assert isinstance(data, HPBuyPositionCreated)
        assert data.hp_id == "1000"
        assert data.coin == "BTC"
        assert data.budget == 1000.0
        assert data.buy_price == 50000.0


# ---------------------------------------------------------------------------
# send_buy_orders_placed_event
# ---------------------------------------------------------------------------


class TestSendBuyOrdersPlacedEvent:
    def test_fires_correct_event_name(self):
        helper, cb = _make_helper()
        helper.send_buy_orders_placed_event("1000", "BTC", 1000.0, "USDC")
        name, _ = _last_call(cb)
        assert name == EventName.HP_BUY_ORDERS_PLACED

    def test_event_data_fields(self):
        helper, cb = _make_helper()
        helper.send_buy_orders_placed_event("1000", "BTC", 1000.0, "USDC")
        _, data = _last_call(cb)
        assert isinstance(data, HPBuyOrdersPlaced)
        assert data.hp_id == "1000"
        assert data.coin == "BTC"
        assert data.budget_amount == 1000.0
        assert data.end_currency == "USDC"


# ---------------------------------------------------------------------------
# send_buy_position_filled_event
# ---------------------------------------------------------------------------


class TestSendBuyPositionFilledEvent:
    def test_fires_correct_event_name(self):
        helper, cb = _make_helper()
        helper.send_buy_position_filled_event(
            "1000", "BTC", "BTCUSDC", 0.02, 50000.0, 1000.0
        )
        name, _ = _last_call(cb)
        assert name == EventName.HP_BUY_POSITION_FILLED

    def test_event_data_fields(self):
        helper, cb = _make_helper()
        helper.send_buy_position_filled_event(
            "1000", "BTC", "BTCUSDC", 0.02, 50000.0, 1000.0
        )
        _, data = _last_call(cb)
        assert isinstance(data, HPBuyPositionFilled)
        assert data.quantity_bought == 0.02
        assert data.symbol == "BTCUSDC"
        assert data.total_cost == 1000.0


# ---------------------------------------------------------------------------
# send_buy_position_partially_filled_event
# ---------------------------------------------------------------------------


class TestSendBuyPositionPartiallyFilledEvent:
    def test_fires_correct_event_name(self):
        helper, cb = _make_helper()
        helper.send_buy_position_partially_filled_event(
            "1000", "BTC", 0.01, 0.01, 50000.0, 500.0
        )
        name, _ = _last_call(cb)
        assert name == EventName.HP_BUY_POSITION_PARTIALLY_FILLED

    def test_event_data_fields(self):
        helper, cb = _make_helper()
        helper.send_buy_position_partially_filled_event(
            "1000", "BTC", 0.01, 0.01, 50000.0, 500.0
        )
        _, data = _last_call(cb)
        assert isinstance(data, HPBuyPositionPartiallyFilled)
        assert data.filled_quantity == 0.01
        assert data.total_filled == 0.01
        assert data.partial_cost == 500.0


# ---------------------------------------------------------------------------
# send_sell_creation_event
# ---------------------------------------------------------------------------


class TestSendSellCreationEvent:
    def test_fires_correct_event_name(self):
        helper, cb = _make_helper()
        helper.send_sell_creation_event("1000", "BTC", 0.5, 50000.0, 55000.0, "USDC")
        name, _ = _last_call(cb)
        assert name == EventName.HP_SELL_POSITION_CREATED

    def test_event_data_fields(self):
        helper, cb = _make_helper()
        helper.send_sell_creation_event("1000", "BTC", 0.5, 50000.0, 55000.0, "USDC")
        _, data = _last_call(cb)
        assert isinstance(data, HPSellPositionCreated)
        assert data.quantity == 0.5
        assert data.sell_price == 55000.0
        assert data.end_currency == "USDC"


# ---------------------------------------------------------------------------
# send_sell_completion_event
# ---------------------------------------------------------------------------


class TestSendSellCompletionEvent:
    def test_fires_correct_event_name(self):
        helper, cb = _make_helper()
        helper.send_sell_completion_event("1000", "BTC", 0.5, 50000.0, 55000.0, "USDC")
        name, _ = _last_call(cb)
        assert name == EventName.HP_SELL_POSITION_COMPLETED

    def test_event_data_computes_end_currency_received(self):
        helper, cb = _make_helper()
        helper.send_sell_completion_event("1000", "BTC", 0.5, 50000.0, 55000.0, "USDC")
        _, data = _last_call(cb)
        assert isinstance(data, HPSellPositionCompleted)
        assert data.end_currency_received == pytest.approx(0.5 * 55000.0)


# ---------------------------------------------------------------------------
# send_sell_position_partially_filled_event
# ---------------------------------------------------------------------------


class TestSendSellPartiallyFilledEvent:
    def test_fires_correct_event_name(self):
        helper, cb = _make_helper()
        helper.send_sell_position_partially_filled_event("1000", "BTC", 0.1, 0.1)
        name, _ = _last_call(cb)
        assert name == EventName.HP_SELL_POSITION_PARTIALLY_FILLED

    def test_event_data_fields(self):
        helper, cb = _make_helper()
        helper.send_sell_position_partially_filled_event("1000", "BTC", 0.1, 0.3)
        _, data = _last_call(cb)
        assert isinstance(data, HPSellPositionPartiallyFilled)
        assert data.filled_quantity == 0.1
        assert data.total_filled == 0.3


# ---------------------------------------------------------------------------
# send_cancellation_event
# ---------------------------------------------------------------------------


class TestSendCancellationEvent:
    def test_fires_correct_event_name(self):
        helper, cb = _make_helper()
        helper.send_cancellation_event("1000", "BTC", 0.5, "SELL")
        name, _ = _last_call(cb)
        assert name == EventName.HP_POSITION_CANCELLED

    def test_event_data_fields(self):
        helper, cb = _make_helper()
        helper.send_cancellation_event("1000", "USDC", 1000.0, "BUY")
        _, data = _last_call(cb)
        assert isinstance(data, HPPositionCancelled)
        assert data.coin == "USDC"
        assert data.quantity == 1000.0
        assert data.position_type == "BUY"


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    def test_type_error_in_callback_raises_runtime_error(self):
        cb = MagicMock(side_effect=TypeError("bad type"))
        helper = PortfolioEventHelper(portfolio_event_callback=cb)
        with pytest.raises(RuntimeError, match="delivery failed"):
            helper.send_buy_creation_event("1000", "BTC", 1000.0, 50000.0)

    def test_value_error_in_callback_raises_runtime_error(self):
        cb = MagicMock(side_effect=ValueError("bad value"))
        helper = PortfolioEventHelper(portfolio_event_callback=cb)
        with pytest.raises(RuntimeError):
            helper.send_buy_creation_event("1000", "BTC", 1000.0, 50000.0)

    def test_unexpected_error_re_raises(self):
        cb = MagicMock(side_effect=RuntimeError("unexpected"))
        helper = PortfolioEventHelper(portfolio_event_callback=cb)
        with pytest.raises(RuntimeError):
            helper.send_buy_creation_event("1000", "BTC", 1000.0, 50000.0)


# ---------------------------------------------------------------------------
# handle_* convenience wrappers
# ---------------------------------------------------------------------------


class TestHandleSellCompletion:
    def test_delegates_to_sell_completion(self):
        helper, cb = _make_helper()
        close_data = _make_close()
        helper.handle_sell_completion(close_data)
        name, data = _last_call(cb)
        assert name == EventName.HP_SELL_POSITION_COMPLETED
        assert data.hp_id == "1000"
        assert data.coin == "BTC"
        assert data.quantity_sold == 1.0


class TestHandleSellCancellation:
    def test_delegates_to_cancellation_event(self):
        helper, cb = _make_helper()
        close_data = _make_close()
        helper.handle_sell_cancellation(close_data, sell_quantity=0.5)
        name, data = _last_call(cb)
        assert name == EventName.HP_POSITION_CANCELLED
        assert data.position_type == "SELL"
        assert data.quantity == 0.5


class TestHandleBuyCancellation:
    def test_sends_event_when_state_is_not_new(self):
        helper, cb = _make_helper()
        close_data = _make_close(coin="USDC")
        helper.handle_buy_cancellation(close_data, State.BUYING, remaining_budget=800.0)
        name, data = _last_call(cb)
        assert name == EventName.HP_POSITION_CANCELLED
        assert data.coin == "USDC"
        assert data.quantity == 800.0
        assert data.position_type == "BUY"

    def test_skips_event_when_state_is_new(self):
        helper, cb = _make_helper()
        close_data = _make_close()
        helper.handle_buy_cancellation(close_data, State.NEW, remaining_budget=1000.0)
        cb.assert_not_called()
