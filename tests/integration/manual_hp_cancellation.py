"""Test cases for manual HP position cancellation via GUI buttons."""

import asyncio
import queue
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from src.identifiers import (
    Event,
    EventName,
    HPSellPositionCreated,
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
    RemoveRecord,
)
from src.common.symbol_info import SymbolInfo
from src.portfolio.portfolio_gui import PortfolioUI
from src.strategy_executor import StrategyExecutor
from src.strategies.hp_manager import HpStrategy
from binance.enums import ORDER_STATUS_NEW, ORDER_STATUS_FILLED


async def test_manual_hp_sell_cancellation_unlocks_quantities(
    strategy_executor_fixture, portfolio_ui, trading_system_factory
):
    """Test that manual HP sell position cancellation unlocks locked quantities."""
    # Setup inventory
    test_inventory = [
        InventoryItem(
            id="lot1",
            coin="BTC",
            buy_price=47000.0,
            quantity=0.5,
            available_quantity=0.5,
            locked_quantity=0.0,
        ),
        InventoryItem(
            id="lot2",
            coin="BTC",
            buy_price=48000.0,
            quantity=0.5,
            available_quantity=0.5,
            locked_quantity=0.0,
        ),
    ]

    test_balances = {
        "BTC": CoinBalance(
            coin="BTC", free=1.0, locked=0.0, total=1.0, total_value=50000.0
        ),
        "USDC": CoinBalance(
            coin="USDC", free=1000.0, locked=0.0, total=1000.0, total_value=1000.0
        ),
    }

    portfolio_ui.set_inventory(test_inventory, test_balances)

    # Setup strategy executor with portfolio UI queue
    strategy_executor_fixture.portfolio_ui_queue = asyncio.Queue()

    # Create and register strategy
    hp_config = HPBuyConfig(
        hp_id="test_manual_cancel",
        coin="BTC",
        symbol_info=SymbolInfo(symbol="BTCUSDT", precision=5, price_precision=2),
        price_low=45000.0,
        price_high=50000.0,
        order_trigger=1.0,
        budget=1000.0,
    )

    strategy = trading_system_factory(hp_config)
    strategy_executor_fixture.strategies[hp_config.hp_id] = strategy

    # Simulate that a sell position is already active (locked quantities)
    strategy.sell.current_position.config.hp_id = "test_manual_cancel"
    strategy.sell.current_position.config.coin = "BTC"
    strategy.sell.current_position.sell_order.quantity = 0.3
    strategy.state = State.SELLING

    # First lock quantities by simulating HP sell position created
    hp_sell_created = HPSellPositionCreated(
        hp_id="test_manual_cancel",
        coin="BTC",
        quantity=0.3,
        buy_price=47000.0,
        sell_price=49000.0,
        end_currency="USDC",
    )
    await portfolio_ui.handle_hp_sell_created(hp_sell_created)

    # Verify quantities are locked in inventory (the locking happens at inventory level, not balance level)
    locked_total = sum(
        item.locked_quantity for item in test_inventory if item.coin == "BTC"
    )
    available_total = sum(
        item.available_quantity for item in test_inventory if item.coin == "BTC"
    )
    assert locked_total == 0.3, f"Expected 0.3 locked, got {locked_total}"
    assert available_total == 0.7, f"Expected 0.7 available, got {available_total}"

    # Now test manual cancellation via RemoveRecord
    remove_record = RemoveRecord(
        hp_id="test_manual_cancel", symbol="BTCUSDT", side=PositionSide.SHORT
    )

    # Call the remove_record method directly (simulates GUI button click)
    await strategy_executor_fixture.remove_record(
        hp_id=remove_record.hp_id, side=remove_record.side
    )

    # Get the HP event from the portfolio UI queue
    event = await strategy_executor_fixture.portfolio_ui_queue.get()
    assert event.name == EventName.HP_POSITION_CANCELLED
    assert isinstance(event.content, HPPositionCancelled)
    assert event.content.hp_id == "test_manual_cancel"
    assert event.content.coin == "BTC"
    assert event.content.quantity == 0.3
    assert event.content.position_type == "SELL"

    # Process the cancellation event in portfolio
    await portfolio_ui.handle_hp_position_cancelled(event.content)

    # Verify quantities are unlocked after cancellation
    locked_total_after = sum(
        item.locked_quantity for item in test_inventory if item.coin == "BTC"
    )
    available_total_after = sum(
        item.available_quantity for item in test_inventory if item.coin == "BTC"
    )
    assert (
        locked_total_after == 0.0
    ), f"Expected 0.0 locked after cancellation, got {locked_total_after}"
    assert (
        available_total_after == 1.0
    ), f"Expected 1.0 available after cancellation, got {available_total_after}"


async def test_manual_hp_buy_cancellation_sends_event(
    strategy_executor_fixture, portfolio_ui, trading_system_factory
):
    """Test that manual HP buy position cancellation sends HP cancellation event."""
    # Setup strategy executor with portfolio UI queue
    strategy_executor_fixture.portfolio_ui_queue = asyncio.Queue()

    # Create and register strategy
    hp_config = HPBuyConfig(
        hp_id="test_manual_buy_cancel",
        coin="BTC",
        symbol_info=SymbolInfo(symbol="BTCUSDT", precision=5, price_precision=2),
        price_low=45000.0,
        price_high=50000.0,
        order_trigger=1.0,
        budget=1000.0,
    )

    strategy = trading_system_factory(hp_config)
    strategy_executor_fixture.strategies[hp_config.hp_id] = strategy

    # Set up buy orders
    buy_order1 = Order(
        price=45000.0, quantity=0.01, status=ORDER_STATUS_NEW, realized_quantity=0.0
    )
    buy_order2 = Order(
        price=47000.0, quantity=0.01, status=ORDER_STATUS_NEW, realized_quantity=0.0
    )
    strategy.buy.orders = [buy_order1, buy_order2]
    strategy.state = State.BUYING
    strategy.buy.data.state_info.state = State.NEW
    strategy.sell.current_position.state_info.state = State.NEW

    # Test manual cancellation via RemoveRecord
    remove_record = RemoveRecord(
        hp_id="test_manual_buy_cancel", symbol="BTCUSDT", side=PositionSide.LONG
    )

    # Call the remove_record method directly (simulates GUI button click)
    await strategy_executor_fixture.remove_record(
        hp_id=remove_record.hp_id, side=remove_record.side
    )

    # Get the HP event from the portfolio UI queue
    event = await strategy_executor_fixture.portfolio_ui_queue.get()
    assert event.name == EventName.HP_POSITION_CANCELLED
    assert isinstance(event.content, HPPositionCancelled)
    assert event.content.hp_id == "test_manual_buy_cancel"
    assert event.content.coin == "BTC"
    assert event.content.quantity == 0.02  # Sum of both orders
    assert event.content.position_type == "BUY"
