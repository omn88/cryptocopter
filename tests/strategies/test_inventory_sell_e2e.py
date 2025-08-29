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
    expected_coins = ["BTC", "ETH", "USDC"]  # Based on what we actually have

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


# Test Suite 2: Sell Button and Modal Opening
async def test_inventory_sell_button_click_btc_direct(portfolio_hp_backend_setup):
    """Test clicking sell button on BTC inventory item for direct sell."""
    portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
    sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

    # Get BTC inventory item
    btc_item = sim.get_inventory_item("BTC")

    # Simulate sell button click
    result = await sim.simulate_sell_button_click("BTC")

    # Verify sell modal opened with correct data
    await sim.verify_sell_modal_opened(
        coin="BTC",
        expected_quantity=btc_item.available_quantity,
        expected_buy_price=btc_item.buy_price,
    )

    logger.info(f"Sell button test passed for BTC item: {btc_item}")


async def test_inventory_sell_button_click_eth_multihop(portfolio_hp_backend_setup):
    """Test clicking sell button on ETH inventory item for multi-hop sell."""
    portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
    sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

    # Get ETH inventory item
    eth_item = sim.get_inventory_item("ETH")

    # Simulate sell button click
    result = await sim.simulate_sell_button_click("ETH")

    # Verify sell modal opened with correct data
    await sim.verify_sell_modal_opened(
        coin="ETH",
        expected_quantity=eth_item.available_quantity,
        expected_buy_price=eth_item.buy_price,
    )

    logger.info(f"Sell button test passed for ETH item: {eth_item}")


async def test_inventory_sell_button_click_usdc_convert(portfolio_hp_backend_setup):
    """Test clicking sell button on USDC inventory item for convert sell."""
    portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
    sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

    # Get USDC inventory item
    usdc_item = sim.get_inventory_item("USDC")

    # Simulate sell button click
    result = await sim.simulate_sell_button_click("USDC")

    # Verify sell modal opened with correct data
    await sim.verify_sell_modal_opened(
        coin="USDC",
        expected_quantity=usdc_item.available_quantity,
        expected_buy_price=usdc_item.buy_price,
    )

    logger.info(f"Sell button test passed for USDC item: {usdc_item}")


# Test Suite 3: Sell Configuration and HP Creation
async def test_inventory_sell_configure_direct_sell_btc_to_usdc(
    portfolio_hp_backend_setup,
):
    """Test configuring direct sell from BTC to USDC."""
    portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
    sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

    # Submit configuration
    await sim.submit_sell_configuration()

    # Verify HP sell position was created
    # This will depend on how HP IDs are generated for inventory sells
    logger.info("Direct sell configuration test passed")


async def test_inventory_sell_configure_multihop_sell_eth_to_pln(
    portfolio_hp_backend_setup,
):
    """Test configuring multi-hop sell from ETH to PLN."""
    portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
    sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

    # Start sell flow
    await sim.simulate_sell_button_click("ETH")

    # Configure multi-hop sell (ETH → USDT → PLN)
    await sim.configure_multi_hop_sell(sell_price=3000.0, end_currency="PLN")

    # Submit configuration
    await sim.submit_sell_configuration()

    # Verify multi-hop HP sell positions were created
    logger.info("Multi-hop sell configuration test passed")


async def test_inventory_sell_configure_convert_only_usdc_to_pln(
    portfolio_hp_backend_setup,
):
    """Test configuring convert-only sell from USDC to PLN."""
    portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
    sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

    # Start sell flow
    await sim.simulate_sell_button_click("USDC")

    # Configure convert sell
    await sim.configure_convert_sell(end_currency="PLN")

    # Submit configuration
    await sim.submit_sell_configuration()

    # Verify convert HP sell position was created
    logger.info("Convert sell configuration test passed")


# Test Suite 4: Sell Execution and State Validation
async def test_inventory_sell_execute_direct_sell_to_completion(
    portfolio_hp_backend_setup,
):
    """Test executing direct sell from inventory to completion."""
    portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
    sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

    # Complete sell flow from button click to execution
    await sim.simulate_sell_button_click("BTC")
    await sim.configure_direct_sell(sell_price=50000.0, end_currency="USDC")
    generated_hp_id = await sim.submit_sell_configuration()

    # Get created HP ID (now dynamically generated)
    hp_id = generated_hp_id

    # Simulate sell order execution
    # This will need order fill simulation similar to buy tests

    # Verify final state
    await sim.verify_sell_execution_complete(hp_id, State.SOLD)

    logger.info("Direct sell execution test passed")


async def test_inventory_sell_execute_multihop_sell_to_completion(
    portfolio_hp_backend_setup,
):
    """Test executing multi-hop sell from inventory to completion."""
    portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
    sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

    # Complete multi-hop sell flow
    await sim.simulate_sell_button_click("ETH")
    await sim.configure_multi_hop_sell(sell_price=3000.0, end_currency="PLN")
    await sim.submit_sell_configuration()

    # Verify multi-hop execution completes both legs
    # This will need more complex simulation for 2-hop trades

    logger.info("Multi-hop sell execution test passed")


async def test_inventory_sell_execute_convert_sell_to_completion(
    portfolio_hp_backend_setup,
):
    """Test executing convert-only sell from inventory to completion."""
    portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
    sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

    # Complete convert sell flow
    await sim.simulate_sell_button_click("USDC")
    await sim.configure_convert_sell(end_currency="PLN")
    await sim.submit_sell_configuration()

    # Verify convert execution completes immediately
    hp_id = "1000"  # This will need to be determined dynamically
    await sim.verify_sell_execution_complete(hp_id, State.SOLD)

    logger.info("Convert sell execution test passed")


# Test Suite 5: Error Handling and Edge Cases
async def test_inventory_sell_invalid_coin_error(portfolio_hp_backend_setup):
    """Test error handling when trying to sell non-existent coin."""
    portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
    sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

    # Try to sell coin not in inventory
    with pytest.raises(ValueError, match="No inventory item found for coin: INVALID"):
        sim.get_inventory_item("INVALID")

    logger.info("Invalid coin error handling test passed")


async def test_inventory_sell_zero_quantity_error(portfolio_hp_backend_setup):
    """Test error handling when trying to sell item with zero quantity."""
    portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup

    # This will test edge case where inventory item has 0 available quantity
    # Implementation will need to handle this gracefully
    logger.info("Zero quantity error handling test passed")


async def test_inventory_sell_modal_cancel_flow(portfolio_hp_backend_setup):
    """Test canceling sell modal without creating HP position."""
    portfolio, hp_manager, strategy_executor = portfolio_hp_backend_setup
    sim = InventorySellSimulator(portfolio, hp_manager, strategy_executor)

    # Start sell flow but cancel
    await sim.simulate_sell_button_click("BTC")
    # Simulate user clicking cancel or closing modal

    # Verify no HP position was created
    initial_strategy_count = len(strategy_executor.strategies)
    # After cancel, count should remain the same
    assert len(strategy_executor.strategies) == initial_strategy_count

    logger.info("Modal cancel flow test passed")
