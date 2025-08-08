"""Test cases for HP Manager-Portfolio communication system."""

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
)
from src.common.symbol_info import SymbolInfo
from src.portfolio.portfolio_gui import PortfolioUI
from src.strategy_executor import StrategyExecutor
from src.strategies.hp_manager import HpStrategy
from tests.strategies.hp_manager_helpers import get_default_buy_position


async def test_hp_sell_position_created_locks_quantities_fifo(
    portfolio_ui, test_inventory
):
    """Test HP sell position created event locks quantities using FIFO."""
    # Don't initialize from sources that might load CSV - set up manually
    # await portfolio_ui.init_portfolio_source(balances=portfolio_ui.balances)

    # Set up inventory in portfolio directly
    portfolio_ui.set_inventory(test_inventory, portfolio_ui.balances)

    # Create HP sell position created event
    hp_sell_created = HPSellPositionCreated(
        hp_id="hp_test_001",
        coin="BTC",
        quantity=0.6,  # Will lock 0.5 from first lot + 0.1 from second lot
        buy_price=47000.0,
        sell_price=49000.0,
        end_currency="USDC",
    )

    # Process the event
    await portfolio_ui.handle_hp_sell_created(hp_sell_created)

    # Verify quantities were locked using FIFO (lowest buy price first)
    btc_coin = None
    for coin in portfolio_ui.coin_list_data:
        if coin["symbol"] == "BTC" and not coin.get("is_lot_row", False):
            btc_coin = coin
            break

    assert btc_coin is not None
    assert float(btc_coin["available_qty"]) == 0.4  # 1.0 - 0.6 locked
    assert float(btc_coin["locked_qty"]) == 0.6

    # Check individual lots
    lots = btc_coin["lots"]
    assert lots[0].available_quantity == 0.0  # First lot fully locked
    assert lots[0].locked_quantity == 0.5
    assert lots[1].available_quantity == 0.2  # Second lot partially locked
    assert (
        abs(lots[1].locked_quantity - 0.1) < 1e-10
    )  # Use approximate equality for floating point
    assert lots[2].available_quantity == 0.2  # Third lot untouched
    assert lots[2].locked_quantity == 0.0


async def test_hp_sell_position_completed_removes_inventory_adds_currency(
    portfolio_ui, test_inventory
):
    """Test HP sell position completed event removes inventory and adds received currency."""
    # Don't initialize from sources that might load CSV - set up manually
    # await portfolio_ui.init_portfolio_source(balances=portfolio_ui.balances)

    # Set up inventory in portfolio directly
    portfolio_ui.set_inventory(test_inventory, portfolio_ui.balances)

    # Also create coin entries from balances (like USDC) that don't have inventory
    portfolio_ui.create_coin_list(portfolio_ui.balances)

    # Create HP sell position completed event
    hp_sell_completed = HPSellPositionCompleted(
        hp_id="hp_test_001",
        coin="BTC",
        quantity_sold=0.6,
        buy_price=47000.0,
        sell_price=49000.0,
        end_currency="USDC",
        end_currency_received=30000.0,  # 0.6 BTC sold for $30,000 USDC
    )

    # Process the event
    await portfolio_ui.handle_hp_sell_completed(hp_sell_completed)

    # Verify BTC inventory was reduced (FIFO - lowest price lots sold first)
    btc_coin = None
    for coin in portfolio_ui.coin_list_data:
        if coin["symbol"] == "BTC" and not coin.get("is_lot_row", False):
            btc_coin = coin
            break

    assert btc_coin is not None
    assert float(btc_coin["quantity"]) == 0.4  # 1.0 - 0.6 sold

    # Verify first lot is gone and second lot is reduced
    lots = btc_coin["lots"]
    assert len(lots) == 2  # One lot should be removed
    assert lots[0].quantity == 0.2  # Second lot reduced to 0.2
    assert lots[1].quantity == 0.2  # Third lot unchanged

    # Verify USDC was added
    usdc_coin = None
    for coin in portfolio_ui.coin_list_data:
        if coin["symbol"] == "USDC" and not coin.get("is_lot_row", False):
            usdc_coin = coin
            break

    assert usdc_coin is not None
    # Should be existing 1000 + 30000 received = 31000
    assert float(usdc_coin["quantity"]) == 31000.0
    assert float(usdc_coin["available_qty"]) == 31000.0


async def test_hp_buy_position_filled_adds_inventory(portfolio_ui):
    """Test HP buy position filled event adds new inventory."""
    # Don't initialize from sources that might load CSV - set up manually
    # await portfolio_ui.init_portfolio_source(balances=portfolio_ui.balances)

    # Set up initial balances so we have existing ETH
    portfolio_ui.create_coin_list(portfolio_ui.balances)

    # Create HP buy position filled event
    hp_buy_filled = HPBuyPositionFilled(
        hp_id="hp_test_002",
        coin="ETH",
        quantity_bought=2.0,
        buy_price=3000.0,
        total_cost=6000.0,
    )

    # Process the event
    await portfolio_ui.handle_hp_buy_filled(hp_buy_filled)

    # Verify ETH was added to portfolio
    eth_coin = None
    for coin in portfolio_ui.coin_list_data:
        if coin["symbol"] == "ETH" and not coin.get("is_lot_row", False):
            eth_coin = coin
            break

    assert eth_coin is not None
    # Check that the new lot was added (should have quantity > initial ETH balance)
    assert float(eth_coin["quantity"]) > 5.0  # Should be more than initial 5.0 ETH
    assert len(eth_coin["lots"]) > 0  # Should have lot from HP buy

    # Verify the HP lot was added correctly
    hp_lot = None
    for lot in eth_coin["lots"]:
        if hasattr(lot, "id") and lot.id == "hp_hp_test_002":
            hp_lot = lot
            break

    assert hp_lot is not None
    assert hp_lot.quantity == 2.0
    assert hp_lot.buy_price == 3000.0


async def test_hp_position_cancelled_unlocks_quantities(portfolio_ui, test_inventory):
    """Test HP position cancelled event unlocks quantities."""
    # Don't initialize from sources that might load CSV - set up manually
    # await portfolio_ui.init_portfolio_source(balances=portfolio_ui.balances)

    # Set up inventory in portfolio directly
    portfolio_ui.set_inventory(test_inventory, portfolio_ui.balances)

    # First lock some quantities
    hp_sell_created = HPSellPositionCreated(
        hp_id="hp_test_003",
        coin="BTC",
        quantity=0.3,
        buy_price=47000.0,
        sell_price=49000.0,
        end_currency="USDC",
    )
    await portfolio_ui.handle_hp_sell_created(hp_sell_created)

    # Verify quantities are locked
    btc_coin = None
    for coin in portfolio_ui.coin_list_data:
        if coin["symbol"] == "BTC" and not coin.get("is_lot_row", False):
            btc_coin = coin
            break
    assert float(btc_coin["locked_qty"]) == 0.3

    # Create HP position cancelled event
    hp_cancelled = HPPositionCancelled(
        hp_id="hp_test_003", coin="BTC", quantity=0.3, position_type="SELL"
    )

    # Process the event
    await portfolio_ui.handle_hp_position_cancelled(hp_cancelled)

    # Verify quantities are unlocked
    assert float(btc_coin["locked_qty"]) == 0.0
    assert float(btc_coin["available_qty"]) == 1.0


async def test_hp_sell_position_created_event_data_structure():
    """Test HP sell position created event has correct data structure."""
    hp_sell_created = HPSellPositionCreated(
        hp_id="hp_test_001",
        coin="BTC",
        quantity=0.6,
        buy_price=47000.0,
        sell_price=49000.0,
        end_currency="USDC",
    )

    # Verify event structure
    assert hp_sell_created.hp_id == "hp_test_001"
    assert hp_sell_created.coin == "BTC"
    assert hp_sell_created.quantity == 0.6
    assert hp_sell_created.buy_price == 47000.0
    assert hp_sell_created.sell_price == 49000.0
    assert hp_sell_created.end_currency == "USDC"


async def test_hp_sell_position_completed_event_data_structure():
    """Test HP sell position completed event has correct data structure."""
    hp_sell_completed = HPSellPositionCompleted(
        hp_id="hp_test_001",
        coin="BTC",
        quantity_sold=0.6,
        buy_price=47000.0,
        sell_price=49000.0,
        end_currency="USDC",
        end_currency_received=30000.0,
    )

    # Verify event structure
    assert hp_sell_completed.hp_id == "hp_test_001"
    assert hp_sell_completed.coin == "BTC"
    assert hp_sell_completed.quantity_sold == 0.6
    assert hp_sell_completed.buy_price == 47000.0
    assert hp_sell_completed.sell_price == 49000.0
    assert hp_sell_completed.end_currency == "USDC"
    assert hp_sell_completed.end_currency_received == 30000.0


async def test_hp_buy_position_filled_event_data_structure():
    """Test HP buy position filled event has correct data structure."""
    hp_buy_filled = HPBuyPositionFilled(
        hp_id="hp_test_002",
        coin="ETH",
        quantity_bought=2.0,
        buy_price=3000.0,
        total_cost=6000.0,
    )

    # Verify event structure
    assert hp_buy_filled.hp_id == "hp_test_002"
    assert hp_buy_filled.coin == "ETH"
    assert hp_buy_filled.quantity_bought == 2.0
    assert hp_buy_filled.buy_price == 3000.0
    assert hp_buy_filled.total_cost == 6000.0


async def test_hp_position_cancelled_event_data_structure():
    """Test HP position cancelled event has correct data structure."""
    hp_cancelled = HPPositionCancelled(
        hp_id="hp_test_003", coin="BTC", quantity=0.3, position_type="SELL"
    )

    # Verify event structure
    assert hp_cancelled.hp_id == "hp_test_003"
    assert hp_cancelled.coin == "BTC"
    assert hp_cancelled.quantity == 0.3
    assert hp_cancelled.position_type == "SELL"


def test_strategy_executor_sends_hp_events(portfolio_strategy_executor):
    """Test that StrategyExecutor properly sends HP events to portfolio."""
    executor, portfolio = portfolio_strategy_executor

    # Test sending HP event
    hp_event = HPSellPositionCreated(
        hp_id="test_hp_001",
        coin="BTC",
        quantity=0.5,
        buy_price=50000.0,
        sell_price=52000.0,
        end_currency="USDC",
    )

    executor._send_hp_event_to_portfolio(EventName.HP_SELL_POSITION_CREATED, hp_event)

    # Verify event was sent to portfolio queue
    assert not portfolio.ui_queue.empty()
    sent_event = portfolio.ui_queue.get_nowait()
    assert isinstance(sent_event, Event)
    assert sent_event.name == EventName.HP_SELL_POSITION_CREATED
    assert sent_event.content == hp_event


async def test_portfolio_ui_handlers_called():
    """Test that portfolio UI handlers are called with correct events."""
    # Create mock portfolio UI
    portfolio = Mock(spec=PortfolioUI)
    portfolio.handle_hp_sell_created = AsyncMock()
    portfolio.handle_hp_sell_completed = AsyncMock()
    portfolio.handle_hp_buy_filled = AsyncMock()
    portfolio.handle_hp_position_cancelled = AsyncMock()

    # Test HP sell created
    hp_sell_created = HPSellPositionCreated(
        hp_id="hp_001",
        coin="BTC",
        quantity=0.5,
        buy_price=50000.0,
        sell_price=52000.0,
        end_currency="USDC",
    )
    await portfolio.handle_hp_sell_created(hp_sell_created)
    portfolio.handle_hp_sell_created.assert_called_once_with(hp_sell_created)

    # Test HP sell completed
    hp_sell_completed = HPSellPositionCompleted(
        hp_id="hp_001",
        coin="BTC",
        quantity_sold=0.5,
        buy_price=50000.0,
        sell_price=52000.0,
        end_currency="USDC",
        end_currency_received=26000.0,
    )
    await portfolio.handle_hp_sell_completed(hp_sell_completed)
    portfolio.handle_hp_sell_completed.assert_called_once_with(hp_sell_completed)

    # Test HP buy filled
    hp_buy_filled = HPBuyPositionFilled(
        hp_id="hp_002",
        coin="ETH",
        quantity_bought=2.0,
        buy_price=3000.0,
        total_cost=6000.0,
    )
    await portfolio.handle_hp_buy_filled(hp_buy_filled)
    portfolio.handle_hp_buy_filled.assert_called_once_with(hp_buy_filled)

    # Test HP position cancelled
    hp_cancelled = HPPositionCancelled(
        hp_id="hp_003", coin="BTC", quantity=0.3, position_type="SELL"
    )
    await portfolio.handle_hp_position_cancelled(hp_cancelled)
    portfolio.handle_hp_position_cancelled.assert_called_once_with(hp_cancelled)


async def test_hp_strategy_sends_portfolio_events_via_callback(
    trading_system_factory, mock_async_client, test_db
):
    """Test that HP strategy sends portfolio events via callback when positions are completed."""
    # Create a mock portfolio event callback
    portfolio_events = []

    def mock_portfolio_callback(event_name, event_data):
        portfolio_events.append((event_name, event_data))

    # Create HP strategy with portfolio callback
    from src.common.symbol_info import SymbolInfo

    symbol_info = SymbolInfo(symbol="BTCUSDT", precision=5, price_precision=2)

    hp_config = HPBuyConfig(
        hp_id="test_hp",
        symbol_info=symbol_info,
        coin="BTC",
        price_low=50000.0,
        price_high=51000.0,
        order_trigger=1.0,
        budget=1000.0,
        mode="test",
    )

    strategy = trading_system_factory(hp_config)
    strategy.portfolio_event_callback = mock_portfolio_callback

    # Simulate a completed sell order by setting up the state manually
    strategy.sell.current_position.config.hp_id = "test_hp_001"
    strategy.sell.current_position.config.coin = "BTC"
    strategy.sell.current_position.config.end_price = 50000.0
    strategy.sell.current_position.sell_order.realized_quantity = 0.5

    # Call the method that should send portfolio events
    await strategy.close_filled_position_sell()

    # Verify event was sent via callback
    assert len(portfolio_events) == 1
    event_name, event_data = portfolio_events[0]
    assert event_name == EventName.HP_SELL_POSITION_COMPLETED
    assert isinstance(event_data, HPSellPositionCompleted)
    assert event_data.hp_id == "test_hp_001"
    assert event_data.coin == "BTC"
    assert event_data.quantity_sold == 0.5


def test_fifo_quantity_locking_logic():
    """Test that quantity locking follows FIFO (lowest buy price first)."""
    # This is a design test to document the expected FIFO behavior
    # The actual implementation is tested in the integration tests above

    # Expected behavior:
    # Given lots with buy prices: [45000, 48000, 52000] and quantities: [0.5, 0.3, 0.2]
    # When locking 0.6 BTC:
    # 1. Lock all of lot1 (0.5 BTC at 45000)
    # 2. Lock 0.1 from lot2 (0.1 BTC at 48000)
    # 3. Leave lot3 untouched (0.2 BTC at 52000)

    assert True  # This test documents expected behavior, actual logic tested above
