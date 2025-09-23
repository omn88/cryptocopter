"""Test inventory locking persistence and crash recovery."""

import asyncio
import pytest
import logging

from src.identifiers import HPSellPositionCreated
from tests.strategies.hp_manager_helpers import wait_for_condition
from tests.strategies.hp_simulator import HPSimulator


logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_comprehensive_portfolio_crash_recovery(portfolio_crash_recovery_factory):
    """
    Test comprehensive crash recovery for portfolio inventory locking system.

    This test verifies:
    1. Portfolio + HP + Backend setup works correctly
    2. Inventory locking persists to database
    3. System crash simulation
    4. Recovery setup restores inventory locking state
    5. Full system continues to work after recovery
    """
    create_portfolio_hp_setup, simulate_crash = portfolio_crash_recovery_factory

    # === Phase 1: Original setup and operations ===
    logger.info("Phase 1: Creating original setup")

    portfolio_ui_orig, hp_frontend_orig, backend_orig = create_portfolio_hp_setup(
        "original"
    )

    # Create sell events that will lock inventory
    btc_sell_event = HPSellPositionCreated(
        hp_id="1001",
        coin="BTC",
        quantity=0.6,  # Should lock 0.6 BTC from multiple lots
        buy_price=45000.0,
        sell_price=90000.0,
        end_currency="USDC",
    )

    eth_sell_event = HPSellPositionCreated(
        hp_id="1002",
        coin="ETH",
        quantity=1.5,  # Should lock 1.5 ETH
        buy_price=2800.0,
        sell_price=5600.0,
        end_currency="USDC",
    )

    # Handle events to lock inventory and save to database
    await portfolio_ui_orig.handle_hp_sell_created(btc_sell_event)
    await portfolio_ui_orig.handle_hp_sell_created(eth_sell_event)

    # Verify original locking worked
    btc_locked_orig = sum(
        getattr(item, "locked_quantity", 0)
        for item in portfolio_ui_orig.inventory
        if getattr(item, "coin", "") == "BTC"
    )
    eth_locked_orig = sum(
        getattr(item, "locked_quantity", 0)
        for item in portfolio_ui_orig.inventory
        if getattr(item, "coin", "") == "ETH"
    )

    assert btc_locked_orig >= 0.6, f"BTC should be locked (got {btc_locked_orig})"
    assert eth_locked_orig >= 1.5, f"ETH should be locked (got {eth_locked_orig})"

    logger.info(
        f"Phase 1 complete: BTC locked={btc_locked_orig}, ETH locked={eth_locked_orig}"
    )

    # === Phase 2: Simulate system crash ===
    logger.info("Phase 2: Simulating complete system crash")
    await simulate_crash(portfolio_ui_orig, hp_frontend_orig, backend_orig)
    logger.info("System crash completed")

    # === Phase 3: Recovery setup ===
    logger.info("Phase 3: Creating recovery setup")
    portfolio_ui_recovered, hp_frontend_recovered, backend_recovered = (
        create_portfolio_hp_setup("recovered")
    )

    # Verify inventory locking persisted through crash
    btc_locked_recovered = sum(
        getattr(item, "locked_quantity", 0)
        for item in portfolio_ui_recovered.inventory
        if getattr(item, "coin", "") == "BTC"
    )
    eth_locked_recovered = sum(
        getattr(item, "locked_quantity", 0)
        for item in portfolio_ui_recovered.inventory
        if getattr(item, "coin", "") == "ETH"
    )

    # The database should have preserved the locked state
    assert (
        btc_locked_recovered >= 0.6
    ), f"BTC locking should survive crash (got {btc_locked_recovered})"
    assert (
        eth_locked_recovered >= 1.5
    ), f"ETH locking should survive crash (got {eth_locked_recovered})"

    logger.info(f"✓ Crash recovery successful!")
    logger.info(f"  BTC: {btc_locked_orig} → {btc_locked_recovered}")
    logger.info(f"  ETH: {eth_locked_orig} → {eth_locked_recovered}")

    # === Phase 4: Verify recovered system works ===
    logger.info("Phase 4: Testing recovered system functionality")

    # Create another sell event to test the recovered system
    dym_sell_event = HPSellPositionCreated(
        hp_id="1003",
        coin="DYM",
        quantity=50.0,  # Lock some DYM
        buy_price=1.0,
        sell_price=2.0,
        end_currency="USDC",
    )

    await portfolio_ui_recovered.handle_hp_sell_created(dym_sell_event)

    # Verify new locking works on recovered system
    dym_locked_recovered = sum(
        getattr(item, "locked_quantity", 0)
        for item in portfolio_ui_recovered.inventory
        if getattr(item, "coin", "") == "DYM"
    )

    assert (
        dym_locked_recovered >= 50.0
    ), f"Recovered system should be able to lock DYM (got {dym_locked_recovered})"

    logger.info("✓ Comprehensive crash recovery test completed successfully!")


@pytest.mark.asyncio
async def test_selective_component_crash_recovery(portfolio_crash_recovery_factory):
    """
    Example test showing selective crash recovery - crash only specific components.

    This demonstrates the flexibility of the portfolio_crash_recovery_factory:
    - Can crash individual components (portfolio only, HP only, backend only)
    - Can test partial system failures and recovery
    - Useful for testing different failure scenarios
    """
    create_portfolio_hp_setup, simulate_crash = portfolio_crash_recovery_factory

    logger.info("Creating setup for selective crash testing")
    portfolio_ui, hp_frontend, backend = create_portfolio_hp_setup("selective_test")

    # Create a sell position to establish some state
    sell_event = HPSellPositionCreated(
        hp_id="2001",
        coin="AXL",
        quantity=100.0,
        buy_price=0.6,
        sell_price=1.2,
        end_currency="USDC",
    )

    await portfolio_ui.handle_hp_sell_created(sell_event)

    # Verify initial state
    axl_locked_initial = sum(
        getattr(item, "locked_quantity", 0)
        for item in portfolio_ui.inventory
        if getattr(item, "coin", "") == "AXL"
    )

    assert (
        axl_locked_initial >= 100.0
    ), f"AXL should be locked initially (got {axl_locked_initial})"

    # Test 1: Crash only the portfolio component
    logger.info("Testing portfolio-only crash")
    await simulate_crash(portfolio_ui)  # Only crash portfolio

    # Test 2: Create new portfolio (simulating portfolio app restart)
    portfolio_ui_new, _, _ = create_portfolio_hp_setup("portfolio_recovered")

    # Verify portfolio state survived (HP and backend still running)
    axl_locked_recovered = sum(
        getattr(item, "locked_quantity", 0)
        for item in portfolio_ui_new.inventory
        if getattr(item, "coin", "") == "AXL"
    )

    assert (
        axl_locked_recovered >= 100.0
    ), f"AXL locking should survive portfolio crash (got {axl_locked_recovered})"

    logger.info("✓ Selective component crash recovery test completed successfully!")


async def test_multihop_inventory_locking_crash_recovery(
    portfolio_crash_recovery_factory,
):
    """
    End-to-end test for multihop position inventory locking with crash recovery.

    This test reproduces the double-locking issue by:
    1. Creating a real multihop sell position that locks inventory
    2. Verifying HP list and inventory state are correct
    3. Simulating system crash
    4. Recovering and validating inventory doesn't get double-locked
    """
    create_portfolio_hp_setup, simulate_crash = portfolio_crash_recovery_factory

    # === Phase 1: Create original setup with multihop position ===
    logger.info("Phase 1: Creating original setup with multihop sell position")

    portfolio_ui, hp_frontend, backend = create_portfolio_hp_setup("multihop_original")

    # Create simulator for multihop operations
    sim = HPSimulator(front=hp_frontend, back=backend)

    # Get initial AXL inventory state
    axl_inventory_initial = [
        item for item in portfolio_ui.inventory if getattr(item, "coin", "") == "AXL"
    ]
    initial_axl_available = sum(
        item.available_quantity for item in axl_inventory_initial
    )
    initial_axl_locked = sum(item.locked_quantity for item in axl_inventory_initial)

    logger.info(
        f"Initial AXL state: available={initial_axl_available}, locked={initial_axl_locked}"
    )

    # Create a multihop sell position using the simulator
    await sim.open_first_sell_position_from_two_hop_trade(quantity=500.0)

    # Wait for HP position to appear in frontend
    await wait_for_condition(
        condition_func=lambda: len(hp_frontend.hp_list_data) > 0, timeout=5.0
    )

    # Verify HP position was created
    assert len(hp_frontend.hp_list_data) > 0, "HP position should be created"
    hp_position = hp_frontend.hp_list_data[0]
    logger.info(
        f"Created HP position: {hp_position['hp_id']} - {hp_position['coin']} qty:{hp_position['quantity']}"
    )

    # Wait for inventory locking to be processed
    await portfolio_ui.process_test_events()
    await asyncio.sleep(1.0)

    # Get AXL inventory state after multihop position creation
    axl_inventory_after = [
        item for item in portfolio_ui.inventory if getattr(item, "coin", "") == "AXL"
    ]
    after_axl_available = sum(item.available_quantity for item in axl_inventory_after)
    after_axl_locked = sum(item.locked_quantity for item in axl_inventory_after)

    logger.info(
        f"After multihop creation: available={after_axl_available}, locked={after_axl_locked}"
    )

    # Verify inventory locking occurred
    assert (
        after_axl_locked > initial_axl_locked
    ), f"AXL should be locked after position creation: {initial_axl_locked} -> {after_axl_locked}"
    assert (
        after_axl_available < initial_axl_available
    ), f"AXL available should decrease: {initial_axl_available} -> {after_axl_available}"

    # Store expected locked quantity for comparison after recovery
    expected_locked_quantity = after_axl_locked
    expected_available_quantity = after_axl_available

    # === Phase 2: Simulate system crash ===
    logger.info("Phase 2: Simulating complete system crash")
    await simulate_crash(portfolio_ui, hp_frontend, backend)
    logger.info("System crash completed")

    # === Phase 3: Recovery and validation ===
    logger.info("Phase 3: Creating recovery setup and validating inventory state")

    portfolio_ui_recovered, hp_frontend_recovered, backend_recovered = (
        create_portfolio_hp_setup("multihop_recovered")
    )

    # Manually trigger crash recovery to restore HP positions
    logger.info("Triggering crash recovery...")
    await backend_recovered.recover_positions_from_crash()

    # Wait for recovery to complete
    await wait_for_condition(
        condition_func=lambda: len(backend_recovered.strategies) > 0, timeout=10.0
    )

    logger.info(
        f"Recovery completed. Strategies restored: {len(backend_recovered.strategies)}"
    )

    # Wait for UI updates to be processed after recovery
    await asyncio.sleep(2.0)

    # Get AXL inventory state after recovery
    axl_inventory_recovered = [
        item
        for item in portfolio_ui_recovered.inventory
        if getattr(item, "coin", "") == "AXL"
    ]
    recovered_axl_available = sum(
        item.available_quantity for item in axl_inventory_recovered
    )
    recovered_axl_locked = sum(item.locked_quantity for item in axl_inventory_recovered)

    logger.info(
        f"After recovery: available={recovered_axl_available}, locked={recovered_axl_locked}"
    )

    # === Critical Assertions: Check for double-locking bug ===
    logger.info("Phase 4: Validating inventory consistency after recovery")

    # The core issue: inventory should maintain the same state, not double-lock
    assert recovered_axl_available == expected_available_quantity, (
        f"AXL available quantity mismatch after recovery: "
        f"expected={expected_available_quantity}, got={recovered_axl_available}"
    )

    assert recovered_axl_locked == expected_locked_quantity, (
        f"AXL locked quantity mismatch after recovery (possible double-locking): "
        f"expected={expected_locked_quantity}, got={recovered_axl_locked}"
    )

    # Verify HP positions were restored correctly
    await wait_for_condition(
        condition_func=lambda: len(hp_frontend_recovered.hp_list_data) > 0, timeout=5.0
    )

    assert (
        len(hp_frontend_recovered.hp_list_data) > 0
    ), "HP position should be restored after recovery"
    recovered_hp = hp_frontend_recovered.hp_list_data[0]

    logger.info(
        f"Recovered HP position: {recovered_hp['hp_id']} - {recovered_hp['coin']} qty:{recovered_hp['quantity']}"
    )

    # Verify the recovered position matches the original
    assert (
        recovered_hp["coin"] == hp_position["coin"]
    ), "Recovered HP position coin should match original"
    assert (
        recovered_hp["quantity"] == hp_position["quantity"]
    ), "Recovered HP position quantity should match original"

    # Final validation: Total AXL should be conserved
    total_axl = recovered_axl_available + recovered_axl_locked
    expected_total = expected_available_quantity + expected_locked_quantity

    assert abs(total_axl - expected_total) < 0.01, (
        f"Total AXL not conserved after recovery: "
        f"expected={expected_total}, got={total_axl}"
    )

    logger.info(
        "✓ Multihop inventory locking crash recovery test completed successfully!"
    )
    logger.info(
        f"  Final state: available={recovered_axl_available}, locked={recovered_axl_locked}, total={total_axl}"
    )
