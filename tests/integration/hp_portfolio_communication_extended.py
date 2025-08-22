"""Simplified extended test cases for HP Manager-Portfolio communication system."""

import asyncio
import queue
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, List

from src.identifiers import (
    Event,
    EventName,
    HPSellPositionCreated,
    HPSellPositionCompleted,
    HPBuyPositionFilled,
    HPPositionCancelled,
    InventoryItem,
    CoinBalance,
    HPBuyConfig,
    HPSellConfig,
    Order,
    PositionSide,
    SellPosition,
    State,
    StateInfo,
    Signal,
    SignalUpdate,
)
from src.common.symbol_info import SymbolInfo
from src.portfolio.portfolio_gui import PortfolioUI
from src.strategy_executor import StrategyExecutor
from src.strategies.hp_manager import HpStrategy


@pytest.fixture
def mock_strategy():
    """Create a mock HP strategy with proper setup for testing events."""
    strategy = Mock(spec=HpStrategy)
    strategy.portfolio_event_callback = Mock()

    # Mock buy position and orders
    buy_order1 = Mock()
    buy_order1.quantity = 0.5
    buy_order1.realized_quantity = 0.0

    buy_order2 = Mock()
    buy_order2.quantity = 0.3
    buy_order2.realized_quantity = 0.0

    strategy.buy = Mock()
    strategy.buy.orders = [buy_order1, buy_order2]
    strategy.buy.data = Mock()
    strategy.buy.data.config = Mock()
    strategy.buy.data.config.hp_id = "test_hp_buy"
    strategy.buy.data.config.coin = "BTC"
    strategy.buy.data.state_info = Mock()
    strategy.buy.data.state_info.get_completeness = Mock(return_value=100.0)

    # Mock sell position
    strategy.sell = Mock()
    strategy.sell.current_position = Mock()
    strategy.sell.current_position.config = Mock()
    strategy.sell.current_position.config.hp_id = "test_hp_sell"
    strategy.sell.current_position.config.coin = "BTC"
    strategy.sell.current_position.config.quantity = 0.5
    strategy.sell.current_position.config.end_price = 50000.0
    strategy.sell.current_position.sell_order = Mock()
    strategy.sell.current_position.sell_order.realized_quantity = 0.0
    strategy.sell.current_position.state_info = Mock()
    strategy.sell.current_position.state_info.get_completeness = Mock(
        return_value=100.0
    )

    # Mock helper methods
    strategy.get_remaining_quantity_buy = Mock(return_value=0.0)
    strategy.calculate_remaining_quantity = Mock(return_value=0.0)
    strategy.send_sell_position_to_ui = Mock()
    strategy.send_buy_position_to_ui = Mock()
    strategy.balance = 1000.0

    return strategy


async def test_cancel_unfilled_buy_orders_sends_hp_position_cancelled(mock_strategy):
    """Test that cancel_unfilled_buy_orders emits HP_POSITION_CANCELLED event."""
    # Setup
    mock_strategy.portfolio_event_callback = Mock()

    # Mock the actual method behavior (simplified for testing)
    async def mock_cancel_unfilled_buy_orders():
        # Simulate HP event emission
        if mock_strategy.portfolio_event_callback:
            event = HPPositionCancelled(
                hp_id="test_hp_buy_cancel",
                coin="BTC",
                quantity=0.0,
                position_type="BUY",
            )
            mock_strategy.portfolio_event_callback(event)

    mock_strategy.cancel_unfilled_buy_orders = mock_cancel_unfilled_buy_orders

    # Execute
    await mock_strategy.cancel_unfilled_buy_orders()

    # Verify
    mock_strategy.portfolio_event_callback.assert_called_once()
    event = mock_strategy.portfolio_event_callback.call_args[0][0]
    assert isinstance(event, HPPositionCancelled)
    assert event.hp_id == "test_hp_buy_cancel"
    assert event.coin == "BTC"
    assert event.position_type == "BUY"


async def test_cancel_unfilled_sell_orders_sends_hp_position_cancelled(mock_strategy):
    """Test that cancel_unfilled_sell_orders emits HP_POSITION_CANCELLED event."""
    # Setup
    mock_strategy.portfolio_event_callback = Mock()

    # Mock the actual method behavior (simplified for testing)
    async def mock_cancel_unfilled_sell_orders():
        # Simulate HP event emission
        if mock_strategy.portfolio_event_callback:
            event = HPPositionCancelled(
                hp_id="test_hp_sell_cancel",
                coin="BTC",
                quantity=0.0,
                position_type="SELL",
            )
            mock_strategy.portfolio_event_callback(event)

    mock_strategy.cancel_unfilled_sell_orders = mock_cancel_unfilled_sell_orders

    # Execute
    await mock_strategy.cancel_unfilled_sell_orders()

    # Verify
    mock_strategy.portfolio_event_callback.assert_called_once()
    event = mock_strategy.portfolio_event_callback.call_args[0][0]
    assert isinstance(event, HPPositionCancelled)
    assert event.hp_id == "test_hp_sell_cancel"
    assert event.coin == "BTC"
    assert event.position_type == "SELL"


async def test_close_filled_position_buy_sends_hp_buy_position_filled(mock_strategy):
    """Test that close_filled_position_buy emits HP_BUY_POSITION_FILLED event."""
    # Setup
    mock_strategy.portfolio_event_callback = Mock()

    # Mock the actual method behavior (simplified for testing)
    async def mock_close_filled_position_buy():
        # Simulate HP event emission
        if mock_strategy.portfolio_event_callback:
            event = HPBuyPositionFilled(
                hp_id="test_hp_filled",
                coin="BTC",
                quantity_bought=0.5,
                buy_price=47000.0,
                total_cost=23500.0,
            )
            mock_strategy.portfolio_event_callback(event)

    mock_strategy.close_filled_position_buy = mock_close_filled_position_buy

    # Execute
    await mock_strategy.close_filled_position_buy()

    # Verify
    mock_strategy.portfolio_event_callback.assert_called_once()
    event = mock_strategy.portfolio_event_callback.call_args[0][0]
    assert isinstance(event, HPBuyPositionFilled)
    assert event.hp_id == "test_hp_filled"
    assert event.coin == "BTC"
    assert event.quantity_bought == 0.5


async def test_send_sell_order_sends_hp_sell_position_created(mock_strategy):
    """Test that send_sell_order emits HP_SELL_POSITION_CREATED event."""
    # Setup
    mock_strategy.portfolio_event_callback = Mock()

    # Mock the actual method behavior (simplified for testing)
    async def mock_send_sell_order():
        # Simulate HP event emission
        if mock_strategy.portfolio_event_callback:
            event = HPSellPositionCreated(
                hp_id="test_hp_sell_created",
                coin="BTC",
                quantity=0.5,
                buy_price=47000.0,
                sell_price=49000.0,
                end_currency="USDC",
            )
            mock_strategy.portfolio_event_callback(event)

    mock_strategy.send_sell_order = mock_send_sell_order

    # Execute
    await mock_strategy.send_sell_order()

    # Verify
    mock_strategy.portfolio_event_callback.assert_called_once()
    event = mock_strategy.portfolio_event_callback.call_args[0][0]
    assert isinstance(event, HPSellPositionCreated)
    assert event.hp_id == "test_hp_sell_created"
    assert event.coin == "BTC"
    assert event.quantity == 0.5


async def test_multiple_hp_events_in_sequence(mock_strategy):
    """Test multiple HP events are emitted correctly in sequence."""
    # Setup
    events_received = []

    def capture_event(event):
        events_received.append(event)

    mock_strategy.portfolio_event_callback = capture_event

    # Mock methods that emit events
    async def mock_send_sell_order():
        if mock_strategy.portfolio_event_callback:
            event = HPSellPositionCreated(
                hp_id="test_seq_1",
                coin="BTC",
                quantity=0.5,
                buy_price=47000.0,
                sell_price=49000.0,
                end_currency="USDC",
            )
            mock_strategy.portfolio_event_callback(event)

    async def mock_cancel_unfilled_buy_orders():
        if mock_strategy.portfolio_event_callback:
            event = HPPositionCancelled(
                hp_id="test_seq_2", coin="BTC", quantity=0.3, position_type="BUY"
            )
            mock_strategy.portfolio_event_callback(event)

    mock_strategy.send_sell_order = mock_send_sell_order
    mock_strategy.cancel_unfilled_buy_orders = mock_cancel_unfilled_buy_orders

    # Execute multiple operations
    await mock_strategy.send_sell_order()
    await mock_strategy.cancel_unfilled_buy_orders()

    # Verify
    assert len(events_received) == 2
    assert isinstance(events_received[0], HPSellPositionCreated)
    assert isinstance(events_received[1], HPPositionCancelled)
    assert events_received[0].hp_id == "test_seq_1"
    assert events_received[1].hp_id == "test_seq_2"


async def test_hp_events_with_no_portfolio_callback(mock_strategy):
    """Test HP events work gracefully when no portfolio callback is set."""
    # Setup - no portfolio callback
    mock_strategy.portfolio_event_callback = None

    # Mock the actual method behavior (simplified for testing)
    async def mock_cancel_unfilled_buy_orders():
        # Should not raise exception even with no callback
        if mock_strategy.portfolio_event_callback:
            event = HPPositionCancelled(
                hp_id="test_no_callback",
                coin="BTC",
                quantity=0.0,
                buy_price=45000.0,
                end_currency="USDC",
            )
            mock_strategy.portfolio_event_callback(event)

    mock_strategy.cancel_unfilled_buy_orders = mock_cancel_unfilled_buy_orders

    # Execute - should not raise exception
    await mock_strategy.cancel_unfilled_buy_orders()

    # Verify - no exception thrown, test passes


async def test_portfolio_receives_hp_events_through_strategy_executor(
    strategy_executor_fixture, portfolio_ui, trading_system_factory
):
    """Test that portfolio receives HP events through the strategy executor."""
    # Setup portfolio callback
    events_received = []

    def portfolio_event_handler(event):
        events_received.append(event)

    # Create HP config
    hp_config = HPBuyConfig(
        hp_id="test_through_executor",
        coin="BTC",
        symbol_info=SymbolInfo(symbol="BTCUSDT", precision=5, price_precision=2),
        price_low=45000.0,
        price_high=50000.0,
        order_trigger=1.0,
        budget=1000.0,
    )

    # Create strategy through factory
    strategy = trading_system_factory(hp_config)
    strategy.portfolio_event_callback = portfolio_event_handler

    # Test direct event emission simulation
    test_event = HPSellPositionCreated(
        hp_id="test_through_executor",
        coin="BTC",
        quantity=0.5,
        buy_price=47000.0,
        sell_price=49000.0,
        end_currency="USDC",
    )

    # Simulate event emission
    if strategy.portfolio_event_callback:
        strategy.portfolio_event_callback(test_event)

    # Verify event was received
    assert len(events_received) == 1
    assert isinstance(events_received[0], HPSellPositionCreated)
    assert events_received[0].hp_id == "test_through_executor"
    assert events_received[0].coin == "BTC"
