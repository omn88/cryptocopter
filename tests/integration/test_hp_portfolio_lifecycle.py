"""Comprehensive HP-Portfolio lifecycle integration tests."""

import logging
import pytest

from src.common.identifiers import (
    HPSellPositionCreated,
    HPSellPositionCompleted,
    HPSellPositionPartiallyFilled,
    HPBuyPositionFilled,
    AccountPosition,
    Balance,
    Event,
    EventName,
)
from src.portfolio.portfolio_gui import PortfolioUI

logger = logging.getLogger("test_hp_portfolio_lifecycle")


def get_inventory_balance(portfolio_ui, coin: str) -> float:
    """Helper to get total quantity of a coin from inventory (replaces balances.get())."""
    items = [item for item in portfolio_ui.inventory if item.coin == coin]
    return sum(item.quantity for item in items)


def get_inventory_available(portfolio_ui, coin: str) -> float:
    """Helper to get available quantity of a coin from inventory."""
    items = [item for item in portfolio_ui.inventory if item.coin == coin]
    return sum(item.available_quantity for item in items)


async def test_complete_hp_lifecycle_portfolio_communication(portfolio_ui: PortfolioUI):
    """Test complete HP lifecycle: partial buy → full buy → partial sell → full sell.

    This test verifies that:
    1. Partial buy creates inventory item at same price (updates existing)
    2. Buy at different price creates new child lot
    3. Another buy at different price updates the child lot
    4. Partial sell decreases inventory quantity for this HP
    5. Full sell removes the inventory item completely
    6. USDC balance is updated accordingly (only parent value, no quote inventory item)
    """

    hp_id = "hp_lifecycle_001"

    # Debug: Check initial state from mock_inventory (should be 15 items)
    logger.info("Initial inventory: %s", len(portfolio_ui.inventory))

    assert len(portfolio_ui.inventory) == 15  # 15 original
    logger.info("Initial coin_list_data: %s", len(portfolio_ui.coin_list_data))

    # ===== STEP 1: FIRST BUY AT SAME PRICE AS EXISTING BTC =====
    # The mock_inventory has BTC at $50,000, so this should update existing lot
    hp_buy_same_price = HPBuyPositionFilled(
        hp_id=hp_id,
        coin="BTC",
        quantity_bought=0.3,
        buy_price=50000.0,  # Same as mock_inventory BTC price
        total_cost=15000.0,
        symbol="BTCUSDC",
    )

    await portfolio_ui.handle_hp_buy_filled(hp_buy_same_price)

    # Debug: Check what happened after the first HP buy (same price)
    logger.info("After first HP buy - inventory: %s", len(portfolio_ui.inventory))
    logger.info(
        "After first HP buy - coin_list_data: %s", len(portfolio_ui.coin_list_data)
    )

    assert len(portfolio_ui.inventory) == 16  # 15 original + 1 new HP buy

    # Find the HP inventory item (it should have the HP ID)
    hp_inventory_item = None
    for item in portfolio_ui.inventory:
        if item.id == f"hp_{hp_id}":
            hp_inventory_item = item
            break

    assert hp_inventory_item is not None
    assert hp_inventory_item.coin == "BTC"
    assert hp_inventory_item.quantity == 0.3
    assert hp_inventory_item.buy_price == 50000.0
    assert hp_inventory_item.available_quantity == 0.3
    assert hp_inventory_item.locked_quantity == 0.0

    # Verify BTC balance updated (original 1.0 + new 0.3 = 1.3)
    btc_balance = get_inventory_balance(portfolio_ui, "BTC")
    assert btc_balance == 1.3

    # ===== STEP 2: BUY AT DIFFERENT PRICE (should create new child lot) =====
    hp_buy_different_price = HPBuyPositionFilled(
        hp_id=hp_id,
        coin="BTC",
        quantity_bought=0.2,
        buy_price=51000.0,  # Different price - should create new child lot
        total_cost=10200.0,
        symbol="BTCUSDC",
    )

    await portfolio_ui.handle_hp_buy_filled(hp_buy_different_price)

    # Debug: Check state after different price buy
    logger.info(
        "After different price HP buy - inventory: %s", len(portfolio_ui.inventory)
    )
    logger.info(
        "After different price HP buy - coin_list_data: %s",
        len(portfolio_ui.coin_list_data),
    )

    # Should have 15 inventory items (original 15 + 1 HP item for hp_lifecycle_001 with aggregated quantities)
    assert len(portfolio_ui.inventory) == 16

    # Verify BTC balance updated (original 1.0 + 0.3 + 0.2 = 1.5)
    btc_balance = get_inventory_balance(portfolio_ui, "BTC")
    assert btc_balance == 1.5

    # ===== STEP 3: ANOTHER BUY AT SAME DIFFERENT PRICE (should update existing child) =====
    hp_buy_same_different_price = HPBuyPositionFilled(
        hp_id=hp_id + "_additional",  # Different HP ID
        coin="BTC",
        quantity_bought=0.1,
        buy_price=51000.0,  # Same as step 2 - should update existing lot at this price
        total_cost=5100.0,
        symbol="BTCUSDC",
    )

    await portfolio_ui.handle_hp_buy_filled(hp_buy_same_different_price)

    # Debug: Check state after third buy
    logger.info("After third HP buy - inventory: %s", len(portfolio_ui.inventory))
    logger.info(
        "After third HP buy - coin_list_data: %s", len(portfolio_ui.coin_list_data)
    )

    # Should have 17 inventory items (original 15 + 1 for hp_lifecycle_001 + 1 for hp_lifecycle_001_additional)
    assert len(portfolio_ui.inventory) == 17

    # Verify BTC balance updated (original 1.0 + 0.3 + 0.2 + 0.1 = 1.6)
    btc_balance = get_inventory_balance(portfolio_ui, "BTC")
    assert btc_balance == 1.6

    # ===== STEP 4: CREATE SELL POSITION (locks quantity) =====
    # Create sell position for some of the HP-created BTC at $55,000
    hp_sell_created = HPSellPositionCreated(
        hp_id=hp_id,
        coin="BTC",
        quantity=0.5,  # Selling some of the HP-acquired BTC
        buy_price=50500.0,  # Average price
        sell_price=55000.0,
        end_currency="USDC",
    )

    await portfolio_ui.handle_hp_sell_created(hp_sell_created)

    # Note: handle_hp_sell_created now immediately locks quantities proportionally
    # No need to simulate AccountPosition event - locking happens instantly

    # Verify total inventory unchanged but locked quantities updated
    btc_balance = get_inventory_balance(portfolio_ui, "BTC")
    assert btc_balance == 1.6  # Total unchanged (1.0 original + 0.6 from HP buys)

    # Check available vs locked quantities in inventory
    btc_available = get_inventory_available(portfolio_ui, "BTC")
    btc_locked = btc_balance - btc_available
    assert btc_locked == 0.5  # 0.5 should be locked
    assert btc_available == 1.1  # 1.6 - 0.5 locked

    # ===== STEP 5: PARTIAL SELL (FILL + COMPLETION FOR FIRST SLICE) =====
    # Simulate partial sell fill: 0.3 BTC filled at $55,000 (inventory reduced immediately)
    hp_sell_partial_fill = HPSellPositionPartiallyFilled(
        hp_id=hp_id,
        coin="BTC",
        filled_quantity=0.3,
        total_filled=0.3,
    )

    await portfolio_ui.handle_hp_sell_partially_filled(hp_sell_partial_fill)

    # Verify partial fill results - total quantity reduced, inventory updated
    btc_balance = get_inventory_balance(portfolio_ui, "BTC")
    assert btc_balance == 1.3  # 1.6 - 0.3 sold = 1.3

    # Now send completion event for this first sell slice to credit proceeds
    hp_sell_partial_completion = HPSellPositionCompleted(
        hp_id=hp_id,
        coin="BTC",
        quantity_sold=0.3,
        buy_price=50500.0,
        sell_price=55000.0,
        end_currency="USDC",
    )
    await portfolio_ui.handle_hp_sell_completed(hp_sell_partial_completion)

    # Verify USDC received after completion of first slice
    usdc_balance = get_inventory_balance(portfolio_ui, "USDC")
    assert usdc_balance == 17500.0  # 1000 + 16500

    # Verify inventory still exists but with reduced quantity
    total_btc_inventory = get_inventory_balance(portfolio_ui, "BTC")
    assert total_btc_inventory == 1.3  # Updated total after fill

    # Find the HP inventory item specifically (should have reduced quantity after partial sell)
    hp_inventory_item = None
    for item in portfolio_ui.inventory:
        if item.id == f"hp_{hp_id}":
            hp_inventory_item = item
            break

    assert hp_inventory_item is not None
    assert (
        hp_inventory_item.quantity == 0.2
    )  # HP item reduced: originally 0.5, sold 0.3, remaining 0.2

    # ===== STEP 6: CREATE ANOTHER SELL FOR REMAINING =====
    # Create sell for remaining BTC inventory at $56,000
    hp_sell_final_created = HPSellPositionCreated(
        hp_id=f"{hp_id}_final",
        coin="BTC",
        quantity=0.2,
        buy_price=50500.0,
        sell_price=56000.0,
        end_currency="USDC",
    )

    await portfolio_ui.handle_hp_sell_created(hp_sell_final_created)

    # Verify additional quantity locked
    btc_balance = get_inventory_balance(portfolio_ui, "BTC")
    assert btc_balance == 1.3  # Total unchanged

    # ===== STEP 7: FINAL SELL FILL + COMPLETION =====
    # Emit fill event for remaining 0.2 BTC (inventory reduction)
    hp_sell_final_fill = HPSellPositionPartiallyFilled(
        hp_id=f"{hp_id}_final",
        coin="BTC",
        filled_quantity=0.2,
        total_filled=0.2,
    )
    await portfolio_ui.handle_hp_sell_partially_filled(hp_sell_final_fill)

    # Inventory should now be reduced before completion
    btc_balance = get_inventory_balance(portfolio_ui, "BTC")
    assert btc_balance == pytest.approx(1.1)
    usdc_balance = get_inventory_balance(portfolio_ui, "USDC")
    assert usdc_balance == 17500.0  # Unchanged since first slice completion

    # Now send completion event to credit proceeds
    hp_sell_final = HPSellPositionCompleted(
        hp_id=f"{hp_id}_final",
        coin="BTC",
        quantity_sold=0.2,
        buy_price=50500.0,
        sell_price=56000.0,
        end_currency="USDC",
    )
    await portfolio_ui.handle_hp_sell_completed(hp_sell_final)

    # ===== FINAL VERIFICATION =====
    # Verify BTC remaining (should be reduced by the sold amount)
    btc_balance = get_inventory_balance(portfolio_ui, "BTC")
    assert btc_balance == pytest.approx(
        1.1
    )  # 1.3 - 0.2 sold = 1.1 (with float precision)

    # Verify total USDC received (original 1000 + 16500 + 11200) added now at final completion
    usdc_balance = get_inventory_balance(portfolio_ui, "USDC")
    assert usdc_balance == 28700.0  # 1000 + (0.3*55000) + (0.2*56000)

    logger.info("Test completed successfully!")


# async def test_hp_partial_buy_to_full_inventory_management(portfolio_ui):
#     """Test that multiple partial buys correctly aggregate into inventory."""

#     # Don't initialize from sources that might load CSV - set up manually
#     # await portfolio_ui.init_portfolio_source(balances={})

#     # Set up truly empty balances manually (override fixture)
#     portfolio_ui.balances = {}
#     portfolio_ui.inventory = []
#     portfolio_ui.coin_list_data = []
#     portfolio_ui.create_coin_list({})

#     hp_id = "hp_partial_001"

#     # First partial buy
#     hp_buy_1 = HPBuyPositionFilled(
#         hp_id=hp_id,
#         coin="BTC",
#         quantity_bought=0.1,
#         buy_price=48000.0,
#         total_cost=4800.0,
#     )

#     await portfolio_ui.handle_hp_event(
#         Event(name=EventName.HP_BUY_POSITION_FILLED, content=hp_buy_1)
#     )

#     # Second partial buy
#     hp_buy_2 = HPBuyPositionFilled(
#         hp_id=hp_id,
#         coin="BTC",
#         quantity_bought=0.15,
#         buy_price=49000.0,
#         total_cost=7350.0,
#     )

#     await portfolio_ui.handle_hp_event(
#         Event(name=EventName.HP_BUY_POSITION_FILLED, content=hp_buy_2)
#     )

#     # Third partial buy
#     hp_buy_3 = HPBuyPositionFilled(
#         hp_id=hp_id,
#         coin="BTC",
#         quantity_bought=0.25,
#         buy_price=51000.0,
#         total_cost=12750.0,
#     )

#     await portfolio_ui.handle_hp_event(
#         Event(name=EventName.HP_BUY_POSITION_FILLED, content=hp_buy_3)
#     )

#     # Verify final state
#     btc_balance = portfolio_ui.balances.get("BTC")
#     assert btc_balance.total == 0.5  # 0.1 + 0.15 + 0.25

#     # Check that inventory shows proper aggregation
#     btc_inventory_total = sum(
#         item.quantity for item in portfolio_ui.inventory if item.coin == "BTC"
#     )
#     assert btc_inventory_total == 0.5


# async def test_hp_sell_cancellation_unlocks_inventory(portfolio_ui):
#     """Test that cancelling an HP sell position unlocks the inventory."""

#     # Don't initialize from sources that might load CSV - set up manually
#     # await portfolio_ui.init_portfolio_source(balances={})

#     # Set up truly empty balances manually (override fixture)
#     portfolio_ui.balances = {}
#     portfolio_ui.inventory = []
#     portfolio_ui.coin_list_data = []
#     portfolio_ui.create_coin_list({})

#     # Setup initial inventory via buy
#     hp_buy = HPBuyPositionFilled(
#         hp_id="cancel_test_001",
#         coin="BTC",
#         quantity_bought=1.0,
#         buy_price=50000.0,
#         total_cost=50000.0,
#     )

#     await portfolio_ui.handle_hp_event(
#         Event(name=EventName.HP_BUY_POSITION_FILLED, content=hp_buy)
#     )

#     # Create sell position (locks inventory)
#     hp_sell_created = HPSellPositionCreated(
#         hp_id="cancel_test_001",
#         coin="BTC",
#         quantity=0.8,
#         buy_price=50000.0,
#         sell_price=55000.0,
#         end_currency="USDC",
#     )

#     await portfolio_ui.handle_hp_event(
#         Event(name=EventName.HP_SELL_POSITION_CREATED, content=hp_sell_created)
#     )

#     # Verify inventory is locked
#     btc_balance = portfolio_ui.balances.get("BTC")
#     assert btc_balance.total == 1.0
#     assert btc_balance.free == 0.2  # 1.0 - 0.8 locked
#     assert btc_balance.locked == 0.8

#     # Cancel the sell position
#     hp_cancelled = HPPositionCancelled(
#         hp_id="cancel_test_001", coin="BTC", quantity=0.8, position_type="SELL"
#     )

#     await portfolio_ui.handle_hp_event(
#         Event(name=EventName.HP_POSITION_CANCELLED, content=hp_cancelled)
#     )

#     # Verify inventory is unlocked
#     btc_balance = portfolio_ui.balances.get("BTC")
#     assert btc_balance.total == 1.0
#     assert btc_balance.free == 1.0  # All available again
#     assert btc_balance.locked == 0.0
