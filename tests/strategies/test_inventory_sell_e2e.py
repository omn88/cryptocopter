"""
End-to-end tests for inventory-based sell functionality.

These tests cover the complete flow from inventory items to sell positions:
1. Portfolio displays inventory items from previous buy positions
2. User clicks sell button on inventory item
3. Sell modal opens with pre-populated data from inventory
4. User configures sell parameters (direct, multi-hop, convert)
5. HP manager creates new sell position
6. Strategy executor handles sell order execution
7. Final state validation (SOLD/CLOSED)

This module is separate from test_hp_manager_e2e.py as it tests a different domain:
- test_hp_manager_e2e.py: Tests creating new buy positions and selling from HP list
- test_inventory_sell_e2e.py: Tests selling existing inventory items through portfolio
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.gui.hp_manager.hpfront import HpFront
from src.strategy_executor import StrategyExecutor
from src.portfolio.portfolio_gui import PortfolioUI
from src.identifiers import InventoryItem, State
from tests.strategies.hp_simulator import HPSimulator
from tests.strategies.inventory_simulator import InventorySellSimulator
from tests.strategies.hp_manager_helpers import wait_for_condition

import logging

logger = logging.getLogger(__name__)


# Test Suite 1: Basic Infrastructure and Setup
async def test_inventory_sell_setup_inventory_items(portfolio_hp_backend_setup):
    """Test that inventory items are properly available for selling."""
    portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup

    # Verify we have inventory items available (portfolio has the inventory, not strategy executor)
    assert len(portfolio.inventory) > 0, "Should have inventory items for testing"

    # Verify inventory contains expected items (from mock_inventory fixture)
    inventory_coins = [item.coin for item in portfolio.inventory]
    logger.info(f"Available inventory coins: {inventory_coins}")

    # Use actual coins from the mock inventory fixture
    expected_coins = ["BTC", "ETH", "AXL", "USDC"]  # Based on what we actually have

    for coin in expected_coins:
        assert coin in inventory_coins, f"Inventory should contain {coin}"

    # Verify inventory items have the expected structure
    btc_item = next(item for item in portfolio.inventory if item.coin == "BTC")
    assert btc_item.available_quantity > 0, "BTC item should have positive quantity"
    assert btc_item.buy_price > 0, "BTC item should have positive buy price"

    logger.info(f"Verified inventory setup with {len(portfolio.inventory)} items")


async def test_inventory_sell_portfolio_hp_connection(portfolio_hp_backend_setup):
    """Test that portfolio and HP manager are properly connected."""
    portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
    sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

    # Use the simulator to verify all connections
    sim.verify_connections()

    logger.info("Verified portfolio-HP manager-backend connections")


# Test Suite 3: Sell Configuration and HP Creation
async def test_inventory_sell_configure_direct_sell_btc_to_usdc(
    portfolio_hp_backend_setup,
):
    """Test configuring direct sell from BTC to USDC."""
    portfolio, hp_front, hp_back = portfolio_hp_backend_setup
    sim = InventorySellSimulator(portfolio, hp_front, hp_back)
    hp_sim = HPSimulator(front=hp_front, back=hp_back)

    # Submit configuration and get the generated HP ID
    hp_id = await sim.submit_sell_configuration("BTC", sell_price=100000.0)

    # Verify HP sell position was created
    assert hp_id in hp_back.strategies
    strategy = hp_back.strategies[hp_id]

    # Verify strategy configuration
    assert strategy.sell.current_position.config.coin == "BTC"
    assert strategy.sell.current_position.config.sell_price == 100000.0
    assert strategy.sell.current_position.config.end_currency == "USDC"
    assert strategy.sell.current_position.config.quantity == 1.0
    assert (
        strategy.state.name == "BOUGHT"
    )  # Should start in BOUGHT state for inventory sells

    await wait_for_condition(
        condition_func=lambda: len(hp_front.hp_list_data) > 0, timeout=5.0
    )

    # Verify HP front data structure using HPSimulator validation methods
    hp_list = hp_front.hp_list_data
    logger.info(f"HP List data: {hp_list}")

    assert len(hp_list) == 2, "There should be two HP entries in the front-end list"

    # Validate parent container using hp_simulator validate_parent method
    hp_sim.validate_parent(
        hp_id=hp_id,
        quantity="1.0",  # Inventory quantity that should be available to sell
        realized_quantity="0.0",  # Nothing sold yet
        state="BOUGHT",  # Starting state for inventory sells
        buy_price="50000.0",
        sell_price="100000.0",
    )

    # Validate SELL child container using hp_simulator validate_child_sell method
    hp_sim.validate_child_sell(
        hp_id=hp_id,
        quantity="1.0",  # Child should show same quantity as parent for initial state
        realized_quantity="0.0",  # Nothing realized yet
        state="NEW",  # Initial state for SELL child
        sell_price="100000.0",
    )

    logger.info("Direct sell configuration test passed with HP simulator validation")


async def test_inventory_sell_configure_multihop_sell_axl_to_pln(
    portfolio_hp_backend_setup,
):
    """
    Test configuring a multihop sell from AXL to PLN.
    This should trigger multihop strategy: AXL → BTC → PLN
    """
    portfolio, hp_front, hp_back = portfolio_hp_backend_setup
    simulator = InventorySellSimulator(portfolio, hp_front, hp_back)
    hp_simulator = HPSimulator(front=hp_front, back=hp_back)

    # Submit sell configuration for AXL with PLN as end currency
    hp_id = await simulator.submit_sell_configuration(
        coin="AXL", end_currency="PLN", sell_price=1.5
    )

    # Verify HP sell position was created
    assert hp_id in hp_back.strategies
    strategy = hp_back.strategies[hp_id]

    # Verify strategy configuration
    assert strategy.sell.current_position.config.coin == "AXL"
    assert (
        strategy.sell.current_position.config.sell_price == 0.00000469
    )  # First hop price
    assert (
        strategy.sell.current_position.config.end_currency == "USDC"
    )  # First hop end currency
    assert strategy.sell.current_position.config.quantity == 100.0
    assert (
        strategy.state.name == "BOUGHT"
    )  # Should start in BOUGHT state for inventory sells

    await wait_for_condition(
        condition_func=lambda: len(hp_front.hp_list_data) > 0, timeout=5.0
    )

    # Verify HP front data structure using HPSimulator validation methods
    hp_list = hp_front.hp_list_data
    logger.info(f"HP List data: {hp_list}")

    # For multihop, we should have 3 HP entries: parent + 2 children
    expected_count = 3  # 1 parent + 2 multihop children
    assert (
        len(hp_list) == expected_count
    ), f"There should be {expected_count} HP entries in the front-end list for multihop"

    # Validate parent container (1000) using hp_simulator validate_parent method
    hp_simulator.validate_parent(
        hp_id=hp_id,
        quantity="100.0",  # AXL inventory quantity that should be available to sell
        realized_quantity="0.0",  # Nothing sold yet
        state="BOUGHT",  # Starting state for inventory sells
        buy_price="0.8",  # AXL buy price from inventory
        sell_price="1.5",  # Target sell price for AXL to PLN
    )

    # Validate first multihop child (1000a): AXL → BTC using hp_simulator validate_multihop_child method
    hp_simulator.validate_multihop_child(
        child_hp_id="1000a",
        quantity="100.0",  # Child should show same quantity as parent for initial state
        realized_quantity="0.0",  # Nothing realized yet
        state="NEW",  # Initial state for first multihop child
        parent_hp_id="1000",  # Parent HP ID
        coin="AXL",  # Source coin for first hop
        sell_price="0.00000469",  # AXL to BTC sell price using full number notation
        buy_price="0.0000025",  # AXL buy price using full number notation
    )

    # Validate second multihop child (1000b): BTC → PLN using hp_simulator validate_multihop_child method
    hp_simulator.validate_multihop_child(
        child_hp_id="1000b",
        quantity="0.00047",  # BTC quantity from first hop using full number notation
        realized_quantity="0.0",  # Nothing realized yet
        state="NEW",  # Initial state for second multihop child (shows as NEW in frontend, WAITING_CHILD in backend)
        parent_hp_id="1000",  # Parent HP ID
        coin="BTC",  # Source coin for second hop
        sell_price="320000.0",  # BTC to PLN sell price using full number notation
        buy_price="320000.0",  # BTC buy price using full number notation
    )

    logger.info("Multihop sell configuration test passed with HP simulator validation")


# async def test_inventory_sell_configure_convert_only_usdc_to_pln(
#     portfolio_hp_backend_setup,
# ):
#     """Test configuring convert-only sell from USDC to PLN."""
#     portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
#     sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

#     # Configure convert sell
#     await sim.configure_convert_sell(end_currency="PLN")

#     # Submit configuration
#     await sim.submit_sell_configuration()

#     # Verify convert HP sell position was created
#     logger.info("Convert sell configuration test passed")


# # Test Suite 4: Sell Execution and State Validation
# async def test_inventory_sell_execute_direct_sell_to_completion(
#     portfolio_hp_backend_setup,
# ):
#     """Test executing direct sell from inventory to completion."""
#     portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
#     sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

#     generated_hp_id = await sim.submit_sell_configuration()

#     # Get created HP ID (now dynamically generated)
#     hp_id = generated_hp_id

#     # Simulate sell order execution
#     # This will need order fill simulation similar to buy tests

#     # Verify final state
#     await sim.verify_sell_execution_complete(hp_id, State.SOLD)

#     logger.info("Direct sell execution test passed")


# async def test_inventory_sell_execute_multihop_sell_to_completion(
#     portfolio_hp_backend_setup,
# ):
#     """Test executing multi-hop sell from inventory to completion."""
#     portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
#     sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

#     await sim.configure_multi_hop_sell(sell_price=3000.0, end_currency="PLN")
#     await sim.submit_sell_configuration()

#     # Verify multi-hop execution completes both legs
#     # This will need more complex simulation for 2-hop trades

#     logger.info("Multi-hop sell execution test passed")


# async def test_inventory_sell_execute_convert_sell_to_completion(
#     portfolio_hp_backend_setup,
# ):
#     """Test executing convert-only sell from inventory to completion."""
#     portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
#     sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

#     # Complete convert sell flow
#     await sim.configure_convert_sell(end_currency="PLN")
#     await sim.submit_sell_configuration()

#     # Verify convert execution completes immediately
#     hp_id = "1000"  # This will need to be determined dynamically
#     await sim.verify_sell_execution_complete(hp_id, State.SOLD)

#     logger.info("Convert sell execution test passed")


# # Test Suite 5: Error Handling and Edge Cases
# async def test_inventory_sell_invalid_coin_error(portfolio_hp_backend_setup):
#     """Test error handling when trying to sell non-existent coin."""
#     portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
#     sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

#     # Try to sell coin not in inventory
#     with pytest.raises(ValueError, match="No inventory item found for coin: INVALID"):
#         sim.get_inventory_item("INVALID")

#     logger.info("Invalid coin error handling test passed")


# async def test_inventory_sell_zero_quantity_error(portfolio_hp_backend_setup):
#     """Test error handling when trying to sell item with zero quantity."""
#     portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup

#     # This will test edge case where inventory item has 0 available quantity
#     # Implementation will need to handle this gracefully
#     logger.info("Zero quantity error handling test passed")


# async def test_inventory_sell_modal_cancel_flow(portfolio_hp_backend_setup):
#     """Test canceling sell modal without creating HP position."""
#     portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
#     sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

#     # Verify no HP position was created
#     initial_strategy_count = len(strategy_executor.strategies)
#     # After cancel, count should remain the same
#     assert len(strategy_executor.strategies) == initial_strategy_count

#     logger.info("Modal cancel flow test passed")
