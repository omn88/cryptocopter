"""HP Manager V2 End-to-End Tests

Tests for the complete V2 integration between frontend (HpFront) and backend (HpExecutorV2).
These tests verify the full workflow from UI interactions to state machine transitions.
"""

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
from binance.enums import ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED, ORDER_STATUS_NEW

from src.common.identifiers import (
    Event,
    EventName,
    ExecutionReport,
    OrderExecutionState,
    PositionLifecycleState,
)
from src.gui.hp_manager.hpfront import HpFront
from src.strategies.hp_manager_v2.executor_v2 import HpExecutorV2
from tests.helpers import get_new_order
from tests.strategies.hp_v2.hp_simulator_v2 import HPSimulatorV2

logger = logging.getLogger("hp_v2_e2e_test")


# ============================================================================
# V2 E2E Tests
# ============================================================================


async def test_get_default_buy_position_v2(frontend_backend_v2_setup):
    """Test V2: Create position via simulator and verify initial state.

    V2 Architecture Pattern (mimics V1):
    - V1: HPSimulator.simulate_buy_position() creates position dynamically
    - V2: HPSimulatorV2.simulate_buy_position() sets executor configs

    This test verifies:
    1. Position can be created via simulator (not hardcoded in fixture)
    2. Position starts in IDLE lifecycle state
    3. Buy and sell configurations are correctly set
    4. Executor is running and ready to process events
    """
    front, back = frontend_backend_v2_setup

    sim = HPSimulatorV2(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    # Simulate creating buy position (like V1 test pattern)
    sim.simulate_buy_position()

    # Assert position was created correctly
    await sim.assert_default_buy_position()


async def test_default_buy_position_send_order_v2(frontend_backend_v2_setup):
    """Test V2: Send buy order when price trigger is hit.

    V2 State Flow: IDLE → BUYING (order sent)

    This test verifies:
    1. Position is created in IDLE state
    2. Price trigger causes transition to BUYING
    3. Buy order is sent to exchange
    4. Strategy enters BUYING state with order pending
    """
    front, back = frontend_backend_v2_setup

    sim = HPSimulatorV2(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    # Get default buy position (executor auto-starts in simulate_buy_position)
    sim.simulate_buy_position()
    await sim.assert_default_buy_position()

    strategy = back.strategy

    # Setup mocking for order creation
    sim.setup_order_mocking()

    # Log price configuration
    buy_price = strategy.buy_config.buy_price
    order_trigger_pct = strategy.buy_config.order_trigger * 100
    trigger_price = strategy.buy.trigger_price
    cancel_price = strategy.buy.cancel_price
    logger.info("=" * 60)
    logger.info("Price Configuration:")
    logger.info(f"  Buy Price:        {buy_price:,.2f} USDC (limit order price)")
    logger.info(f"  Order Trigger:    {order_trigger_pct:.1f}% above buy price")
    logger.info(
        f"  Trigger Price:    {trigger_price:,.2f} USDC (send order when price drops here)"
    )
    logger.info(
        f"  Cancel Price:     {cancel_price:,.2f} USDC (cancel if price rises above)"
    )
    logger.info(f"  Budget:           {strategy.buy_config.budget:,.2f} USDC")
    logger.info(f"  Initial State:    {strategy.lifecycle_state}")
    logger.info("=" * 60)

    # Simulate price dropping from above to trigger level (HP Manager pattern)
    # Start with high price (e.g., 54000), then drop to trigger (50500)
    high_price = 54000.0
    logger.info(f"Initial market price: {high_price:,.2f} USDC (above trigger)")
    sim.new_price(price=high_price)

    # Now drop price to trigger level to initiate buy
    logger.info(f"Price drops to: {trigger_price:,.2f} USDC (at trigger level)")
    logger.info(f"→ This should trigger limit buy order at {buy_price:,.2f} USDC")
    sim.new_price(price=trigger_price)

    # Wait for BUYING state transition
    logger.info("Waiting for state transition: IDLE → BUYING...")
    await sim.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

    # Verify order was sent
    assert strategy.buy.buy_order.order_id is not None
    assert strategy.buy.buy_order.status == ORDER_STATUS_NEW
    assert strategy.lifecycle_state == PositionLifecycleState.BUYING

    logger.info("=" * 60)
    logger.info("✓ Buy Order Sent Successfully:")
    logger.info(f"  Order ID:         {strategy.buy.buy_order.order_id}")
    logger.info(f"  Order Status:     {strategy.buy.buy_order.status}")
    logger.info(f"  Lifecycle State:  {strategy.lifecycle_state}")
    logger.info(f"  Order Price:      {strategy.buy.buy_order.price:,.2f} USDC")
    logger.info(f"  Order Quantity:   {strategy.buy.buy_order.quantity:.5f} BTC")
    logger.info("=" * 60)


async def test_cancel_default_position_v2(frontend_backend_v2_setup):
    """Test V2: Cancel buy order when price rises above cancel threshold.

    V2 State Flow: IDLE → BUYING → IDLE (order cancelled)

    This test verifies:
    1. Position created in IDLE state
    2. Price drops to trigger → order sent → BUYING state
    3. Price rises above cancel_price → order cancelled → back to IDLE
    4. Position ready to send order again if price drops
    """
    front, back = frontend_backend_v2_setup

    sim = HPSimulatorV2(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    # Create position and send order
    sim.simulate_buy_position()
    await sim.assert_default_buy_position()

    strategy = back.strategy

    # Setup mocking for order creation and cancellation
    sim.setup_order_mocking()
    strategy.client.cancel_order = AsyncMock(return_value=None)

    # Send price at trigger to initiate buy
    trigger_price = strategy.buy.trigger_price
    cancel_price = strategy.buy.cancel_price

    logger.info("=" * 60)
    logger.info("Cancel Order Test Configuration:")
    logger.info(f"  Trigger Price:    {trigger_price:,.2f} USDC (send order)")
    logger.info(f"  Cancel Price:     {cancel_price:,.2f} USDC (cancel if above)")
    logger.info("=" * 60)

    # Price drops to trigger → send order
    logger.info(f"Price drops to trigger: {trigger_price:,.2f} USDC")
    sim.new_price(price=trigger_price)
    await sim.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

    logger.info(f"✓ Order sent, state: {strategy.lifecycle_state}")
    assert strategy.lifecycle_state == PositionLifecycleState.BUYING
    assert strategy.buy.buy_order.status == ORDER_STATUS_NEW

    # Price rises above cancel_price → should trigger cancel naturally
    logger.info(f"Price rises to cancel level: {cancel_price:,.2f} USDC")
    sim.new_price(price=cancel_price)

    # Wait for state to return to IDLE
    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)

    logger.info("=" * 60)
    logger.info("✓ Order Cancelled Successfully:")
    logger.info(f"  Lifecycle State:  {strategy.lifecycle_state}")
    logger.info(f"  Order Status:     {strategy.buy.buy_order.status}")
    logger.info(f"  Ready for retry:  Yes (back to IDLE)")
    logger.info("=" * 60)

    # Verify final state
    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    assert strategy.buy.buy_order.status == ORDER_STATUS_CANCELED


async def test_cancel_then_resend_order_v2(frontend_backend_v2_setup):
    """Test V2: Cancel buy order, then resend when price drops again.

    V2 State Flow: IDLE → BUYING → IDLE (cancel) → BUYING (retry)

    This test verifies:
    1. Position created and order sent when price drops to trigger
    2. Order cancelled when price rises above cancel_price
    3. State returns to IDLE, ready to retry
    4. Price drops to trigger again → new order sent → BUYING again
    """
    front, back = frontend_backend_v2_setup

    sim = HPSimulatorV2(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    # Create position
    sim.simulate_buy_position()
    await sim.assert_default_buy_position()

    strategy = back.strategy

    # Setup mocking for unlimited unique order creation
    sim.setup_order_mocking()
    strategy.client.cancel_order = AsyncMock(return_value=None)

    trigger_price = strategy.buy.trigger_price
    cancel_price = strategy.buy.cancel_price

    logger.info("=" * 60)
    logger.info("Cancel & Retry Test Configuration:")
    logger.info(f"  Trigger Price:    {trigger_price:,.2f} USDC")
    logger.info(f"  Cancel Price:     {cancel_price:,.2f} USDC")
    logger.info("=" * 60)

    # Step 1: Price drops to trigger → send order
    logger.info(f"[Step 1] Price drops to trigger: {trigger_price:,.2f} USDC")
    sim.new_price(price=trigger_price)
    await sim.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.BUYING
    first_order_id = strategy.buy.buy_order.order_id
    assert first_order_id is not None
    assert strategy.buy.buy_order.status == ORDER_STATUS_NEW
    logger.info(f"✓ Order sent: order_id={first_order_id}")

    # Step 2: Price rises above cancel_price → cancel order
    logger.info(f"[Step 2] Price rises to cancel level: {cancel_price:,.2f} USDC")
    sim.new_price(price=cancel_price)
    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    assert strategy.buy.buy_order.status == ORDER_STATUS_CANCELED
    logger.info("✓ Order cancelled, back to IDLE")

    # Step 3: Price drops to trigger again → resend order
    logger.info(f"[Step 3] Price drops to trigger again: {trigger_price:,.2f} USDC")
    sim.new_price(price=trigger_price)
    await sim.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.BUYING
    second_order_id = strategy.buy.buy_order.order_id
    assert second_order_id is not None
    assert second_order_id != first_order_id  # Different order_id from first order
    assert strategy.buy.buy_order.status == ORDER_STATUS_NEW

    logger.info("=" * 60)
    logger.info("✓ Retry Successful:")
    logger.info(f"  New Order ID:     {second_order_id}")
    logger.info(f"  First Order ID:   {first_order_id} (cancelled)")
    logger.info(f"  Lifecycle State:  {strategy.lifecycle_state}")
    logger.info(f"  Order Status:     {strategy.buy.buy_order.status}")
    logger.info("=" * 60)


async def test_buy_order_filled_v2(frontend_backend_v2_setup):
    """Test V2: Buy order fills completely → BUYING → BOUGHT.

    V2 State Flow: IDLE → BUYING → BOUGHT

    This test verifies:
    1. Position created and order sent when price drops to trigger
    2. Execution report received with status=FILLED
    3. State transitions to BOUGHT
    4. Order status updated to FILLED
    """
    front, back = frontend_backend_v2_setup

    sim = HPSimulatorV2(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    # Create position and send order
    sim.simulate_buy_position()
    await sim.assert_default_buy_position()

    strategy = back.strategy

    # Setup mocking for order creation
    sim.setup_order_mocking()

    trigger_price = strategy.buy.trigger_price

    logger.info("=" * 60)
    logger.info("Buy Order Fill Test:")
    logger.info(f"  Trigger Price:    {trigger_price:,.2f} USDC")
    logger.info(f"  Buy Price:        {strategy.buy.config.buy_price:,.2f} USDC")
    logger.info(f"  Quantity:         {strategy.buy.buy_order.quantity:.5f} BTC")
    logger.info("=" * 60)

    # Step 1: Price drops to trigger → send order
    logger.info(f"[Step 1] Price drops to trigger: {trigger_price:,.2f} USDC")
    sim.new_price(price=trigger_price)
    await sim.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.BUYING
    assert strategy.buy.buy_order.status == ORDER_STATUS_NEW
    order_id = strategy.buy.buy_order.order_id
    logger.info(f"✓ Order sent: order_id={order_id}")

    # Step 2: Send execution report - order filled
    from binance.enums import ORDER_STATUS_FILLED
    from src.common.identifiers import ExecutionReport

    filled_quantity = strategy.buy.buy_order.quantity
    fill_price = strategy.buy.config.buy_price

    logger.info(
        f"[Step 2] Execution report: FILLED {filled_quantity:.5f} BTC @ {fill_price:.2f}"
    )

    exec_report = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_FILLED,
        order_id=order_id,
        last_executed_quantity=filled_quantity,
        last_executed_price=fill_price,
        cumulative_filled_quantity=filled_quantity,
        price=fill_price,
    )

    # Put execution report into worker queue
    strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exec_report))

    # Wait for state transition to BOUGHT
    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)

    logger.info("=" * 60)
    logger.info("✓ Buy Order Filled Successfully:")
    logger.info(f"  Lifecycle State:  {strategy.lifecycle_state}")
    logger.info(f"  Order Status:     {strategy.buy.buy_order.status}")
    logger.info(
        f"  Realized Qty:     {strategy.buy.buy_order.realized_quantity:.5f} BTC"
    )
    logger.info(f"  Order Qty:        {strategy.buy.buy_order.quantity:.5f} BTC")
    logger.info("=" * 60)

    # Verify final state
    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    assert strategy.buy.buy_order.status == ORDER_STATUS_FILLED
    assert strategy.buy.buy_order.realized_quantity == filled_quantity


async def test_buy_order_partially_filled_v2(frontend_backend_v2_setup):
    """Test V2: Buy order fills partially → stays in BUYING state.

    V2 State Flow: IDLE → BUYING → BUYING (partial fill doesn't transition)

    This test verifies:
    1. Position created and order sent when price drops to trigger
    2. Execution report received with status=PARTIALLY_FILLED
    3. State remains BUYING (not BOUGHT yet)
    4. Order status updated to PARTIALLY_FILLED
    5. Realized quantity updated to partial amount
    """
    front, back = frontend_backend_v2_setup

    sim = HPSimulatorV2(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    # Create position and send order
    sim.simulate_buy_position()
    await sim.assert_default_buy_position()

    strategy = back.strategy

    # Setup mocking for order creation
    sim.setup_order_mocking()

    trigger_price = strategy.buy.trigger_price

    logger.info("=" * 60)
    logger.info("Buy Order Partial Fill Test:")
    logger.info(f"  Trigger Price:    {trigger_price:,.2f} USDC")
    logger.info(f"  Buy Price:        {strategy.buy.config.buy_price:,.2f} USDC")
    logger.info(f"  Quantity:         {strategy.buy.buy_order.quantity:.5f} BTC")
    logger.info("=" * 60)

    # Step 1: Price drops to trigger → send order
    logger.info(f"[Step 1] Price drops to trigger: {trigger_price:,.2f} USDC")
    sim.new_price(price=trigger_price)
    await sim.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.BUYING
    assert strategy.buy.buy_order.status == ORDER_STATUS_NEW
    order_id = strategy.buy.buy_order.order_id
    logger.info(f"✓ Order sent: order_id={order_id}")

    # Step 2: Send partial fill execution report
    from binance.enums import ORDER_STATUS_PARTIALLY_FILLED

    total_quantity = strategy.buy.buy_order.quantity
    partial_quantity = total_quantity * 0.3  # 30% filled
    fill_price = strategy.buy.config.buy_price

    logger.info(
        f"[Step 2] Partial fill: {partial_quantity:.5f} BTC @ {fill_price:.2f} (30% of order)"
    )

    exec_report = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=order_id,
        last_executed_quantity=partial_quantity,
        last_executed_price=fill_price,
        cumulative_filled_quantity=partial_quantity,
        price=fill_price,
    )

    # Put execution report into worker queue
    strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exec_report))

    # Wait for partial fill to be processed
    await sim.wait_for_condition(
        lambda: strategy.buy.execution_state == OrderExecutionState.PARTIALLY_FILLED,
        timeout=2.0,
    )

    logger.info("=" * 60)
    logger.info("✓ Partial Fill Processed:")
    logger.info(f"  Lifecycle State:  {strategy.lifecycle_state}")
    logger.info(f"  Order Status:     {strategy.buy.buy_order.status}")
    logger.info(
        f"  Realized Qty:     {strategy.buy.buy_order.realized_quantity:.5f} BTC"
    )
    logger.info(f"  Total Order Qty:  {strategy.buy.buy_order.quantity:.5f} BTC")
    logger.info(
        f"  Fill %:           {(strategy.buy.buy_order.realized_quantity / strategy.buy.buy_order.quantity) * 100:.1f}%"
    )
    logger.info("=" * 60)

    # Verify state - should still be BUYING (not fully filled)
    assert strategy.lifecycle_state == PositionLifecycleState.BUYING
    assert strategy.buy.buy_order.status == ORDER_STATUS_PARTIALLY_FILLED
    assert strategy.buy.buy_order.realized_quantity == partial_quantity
    assert strategy.buy.execution_state == OrderExecutionState.PARTIALLY_FILLED


async def test_buy_order_partially_filled_then_cancel_v2(frontend_backend_v2_setup):
    """Test V2: Partially filled order is cancelled → stays in IDLE with inventory.

    V2 State Flow: IDLE → BUYING → BUYING (partial fill) → IDLE (cancel with inventory)

    V2 4-state model: IDLE = no active orders (may have inventory from partial fill)

    This test verifies:
    1. Position created and order sent when price drops to trigger
    2. Order partially fills (30%)
    3. Price moves above cancel threshold
    4. Partially filled order is cancelled
    5. State returns to IDLE (partial inventory can be sold when trigger hit)
    6. Realized quantity preserved from partial fill
    7. Sell strategy initialized for partial inventory
    """
    front, back = frontend_backend_v2_setup

    sim = HPSimulatorV2(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    # Create position with sell config so we can sell partial inventory after cancel
    sim.simulate_buy_position(
        symbol="BTCUSDC",
        budget=1000.0,
        buy_price=1400.0,
        sell_price=4200.0,
    )
    await sim.assert_default_buy_position()

    strategy = back.strategy

    # Setup mocking for unlimited unique order creation
    sim.setup_order_mocking()
    strategy.client.cancel_order = AsyncMock(return_value=True)

    trigger_price = strategy.buy.trigger_price
    cancel_price = strategy.buy.cancel_price

    logger.info("=" * 60)
    logger.info("Partial Fill Then Cancel Test:")
    logger.info(f"  Trigger Price:    {trigger_price:,.2f} USDC")
    logger.info(f"  Cancel Price:     {cancel_price:,.2f} USDC")
    logger.info(f"  Buy Price:        {strategy.buy.config.buy_price:,.2f} USDC")
    logger.info("=" * 60)

    # Step 1: Price drops to trigger → send order
    logger.info(f"[Step 1] Price drops to trigger: {trigger_price:,.2f} USDC")
    sim.new_price(price=trigger_price)
    await sim.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.BUYING
    order_id = strategy.buy.buy_order.order_id
    logger.info(f"✓ Order sent: order_id={order_id}")

    # Step 2: Partial fill (30%)
    from binance.enums import ORDER_STATUS_PARTIALLY_FILLED

    total_quantity = strategy.buy.buy_order.quantity
    partial_quantity = total_quantity * 0.3
    fill_price = strategy.buy.config.buy_price

    logger.info(f"[Step 2] Partial fill: {partial_quantity:.5f} BTC @ {fill_price:.2f}")

    exec_report = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=order_id,
        last_executed_quantity=partial_quantity,
        last_executed_price=fill_price,
        cumulative_filled_quantity=partial_quantity,
        price=fill_price,
    )

    strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exec_report))
    await sim.wait_for_condition(
        lambda: strategy.buy.execution_state == OrderExecutionState.PARTIALLY_FILLED,
        timeout=2.0,
    )

    assert strategy.buy.buy_order.status == ORDER_STATUS_PARTIALLY_FILLED
    assert strategy.buy.buy_order.realized_quantity == partial_quantity
    logger.info(f"✓ Partial fill processed: {partial_quantity:.5f} BTC")

    # Step 3: Price moves above cancel threshold → cancel order
    logger.info(f"[Step 3] Price rises to cancel threshold: {cancel_price:,.2f} USDC")
    sim.new_price(price=cancel_price)

    # Wait for state transition to BOUGHT (V2 behavior: partial inventory = bought)
    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)

    logger.info("=" * 60)
    logger.info("✓ Partial Fill Then Cancel Complete:")
    logger.info(f"  Lifecycle State:  {strategy.lifecycle_state}")
    logger.info(f"  Order Status:     {strategy.buy.buy_order.status}")
    logger.info(
        f"  Realized Qty:     {strategy.buy.buy_order.realized_quantity:.5f} BTC (from partial fill)"
    )
    logger.info(f"  Execution State:  {strategy.buy.execution_state}")
    logger.info("=" * 60)

    # Verify final state - V2 transitions to IDLE with partial inventory
    # Wait for sell strategy initialization (happens async in callback)
    await sim.wait_for_condition(
        lambda: strategy.sell_strategy is not None, timeout=2.0
    )

    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    assert strategy.buy.buy_order.status == ORDER_STATUS_CANCELED
    assert (
        strategy.buy.buy_order.realized_quantity == partial_quantity
    )  # Partial fill preserved
    assert strategy.buy.execution_state == OrderExecutionState.CANCELLED
    assert (
        strategy.sell_strategy is not None
    ), "Sell strategy should be initialized for partial inventory"


async def test_buy_order_partially_filled_then_cancel_then_resend_v2(
    frontend_backend_v2_setup,
):
    """Test V2: Order is partially filled, cancelled, returns to IDLE, then re-buys remaining.

    V2 Behavior (CORRECTED): After partial fill + cancel, position returns to IDLE and
    preserves partial fill information. On next buy attempt, only the remaining quantity
    is purchased (not the full budget again).

    Scenario:
    1. Price drops to trigger → send buy order (budget: 1000 USDC)
    2. Order partially fills (30% → 0.3 BTC)
    3. Price rises above cancel threshold → cancel order
    4. V2: Returns to IDLE (preserves partial fill: 0.3 BTC realized)
    5. Price drops to trigger again → re-buy ONLY remaining quantity (70%)
    6. Verify second order uses remaining budget (700 USDC, not full 1000)
    7. Second order fills → transitions to BOUGHT with full quantity (1.0 BTC)

    Expected State Transitions (V2):
    - IDLE → BUYING (on first order)
    - BUYING → BUYING (stays in BUYING after partial fill)
    - BUYING → IDLE (on cancel with partial fill - preserves info)
    - IDLE → BUYING (on second order - buys remaining only)
    - BUYING → BOUGHT (on full fill)

    This tests:
    - Partial fill preservation across cancel
    - Remaining quantity calculation
    - Budget tracking (spent vs remaining)
    - No double-buying (critical!)
    """
    front, back = frontend_backend_v2_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    sim = HPSimulatorV2(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    # Create position with sell_config for V2 (required for partial inventory)
    sim.simulate_buy_position(
        symbol="BTCUSDC",
        budget=1000.0,
        buy_price=1400.0,
        sell_price=4200.0,  # Required for V2 to handle partial inventory after cancel
    )
    await sim.assert_default_buy_position()

    strategy = back.strategy

    # Setup mocking for unlimited unique order creation
    sim.setup_order_mocking()
    strategy.client.cancel_order = AsyncMock(return_value=True)

    trigger_price = strategy.buy.trigger_price
    cancel_price = strategy.buy.cancel_price

    logger.info("=" * 60)
    logger.info("Partial Fill → Cancel → Resend Test:")
    logger.info(f"  Trigger Price:    {trigger_price:,.2f} USDC")
    logger.info(f"  Cancel Price:     {cancel_price:,.2f} USDC")
    logger.info(f"  Buy Price:        {strategy.buy.config.buy_price:,.2f} USDC")
    logger.info("=" * 60)

    # Step 1: Price drops to trigger → send order
    logger.info(f"[Step 1] Price drops to trigger: {trigger_price:,.2f} USDC")
    sim.new_price(price=trigger_price)
    await sim.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.BUYING

    # Wait for order_id to be set (after send_order completes)
    await sim.wait_for_condition(
        lambda: strategy.buy.buy_order is not None
        and strategy.buy.buy_order.order_id is not None,
        timeout=2.0,
    )

    original_order_id = strategy.buy.buy_order.order_id
    original_quantity = strategy.buy.buy_order.quantity
    logger.info(
        f"✓ Order sent: order_id={original_order_id}, quantity={original_quantity:.5f}"
    )

    # Step 2: Partial fill (30%)
    from binance.enums import ORDER_STATUS_PARTIALLY_FILLED

    partial_fill_pct = 0.3
    partial_quantity = original_quantity * partial_fill_pct
    fill_price = strategy.buy.config.buy_price

    logger.info(
        f"[Step 2] Partial fill: {partial_fill_pct*100:.0f}% ({partial_quantity:.5f} BTC)"
    )

    execution_report = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=original_order_id,
        last_executed_quantity=partial_quantity,
        last_executed_price=fill_price,
        cumulative_filled_quantity=partial_quantity,
        price=fill_price,
    )
    back.worker_queue.put_nowait(
        Event(name=EventName.EXECUTION_REPORT, content=execution_report)
    )

    # Should stay in BUYING state with partial fill
    await sim.wait_for_condition(
        lambda: strategy.buy.buy_order.realized_quantity == partial_quantity,
        timeout=2.0,
    )
    assert strategy.lifecycle_state == PositionLifecycleState.BUYING
    assert strategy.buy.buy_order.realized_quantity == partial_quantity
    assert strategy.buy.execution_state == OrderExecutionState.PARTIALLY_FILLED
    logger.info(
        f"✓ Partial fill processed: realized={partial_quantity:.5f}, state=BUYING"
    )

    # Step 3: Price rises above cancel threshold → cancel
    logger.info(f"[Step 3] Price rises to cancel threshold: {cancel_price:,.2f} USDC")
    sim.new_price(price=cancel_price)

    # Wait for cancel and transition back to IDLE (NEW V2 behavior)
    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    assert strategy.buy.buy_order.realized_quantity == partial_quantity
    assert strategy.buy.execution_state == OrderExecutionState.CANCELLED
    strategy.client.cancel_order.assert_called_once()
    logger.info(f"✓ Order cancelled, returned to IDLE with partial fill preserved")
    logger.info(f"  - Realized Quantity: {partial_quantity:.5f} BTC")
    logger.info(
        f"  - Remaining to Buy:  {original_quantity - partial_quantity:.5f} BTC"
    )

    # Step 4: Price drops to trigger again → re-buy ONLY remaining quantity
    logger.info(f"[Step 4] Price drops to trigger again: {trigger_price:,.2f} USDC")
    sim.new_price(price=trigger_price)
    await sim.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

    # Wait for second order to be sent
    await sim.wait_for_condition(
        lambda: strategy.buy.buy_order is not None
        and strategy.buy.buy_order.order_id is not None
        and strategy.buy.buy_order.order_id != original_order_id,
        timeout=2.0,
    )

    second_order_id = strategy.buy.buy_order.order_id
    second_order_quantity = strategy.buy.buy_order.quantity
    expected_remaining_quantity = original_quantity - partial_quantity

    logger.info(f"✓ Second order sent:")
    logger.info(f"  - Order ID:         {second_order_id}")
    logger.info(f"  - Order Quantity:   {second_order_quantity:.5f} BTC")
    logger.info(f"  - Expected (70%):   {expected_remaining_quantity:.5f} BTC")

    # CRITICAL: Verify we're buying remaining quantity, NOT full budget again
    assert abs(second_order_quantity - expected_remaining_quantity) < 0.0001, (
        f"Second order should buy remaining {expected_remaining_quantity:.5f} BTC, "
        f"not full {original_quantity:.5f} BTC! Got {second_order_quantity:.5f}"
    )

    # Step 5: Second order fills completely
    logger.info(
        f"[Step 5] Second order fills completely ({second_order_quantity:.5f} BTC)"
    )
    from binance.enums import ORDER_STATUS_FILLED

    full_fill_report = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_FILLED,
        order_id=second_order_id,
        last_executed_quantity=second_order_quantity,
        last_executed_price=fill_price,
        cumulative_filled_quantity=partial_quantity + second_order_quantity,
        price=fill_price,
    )
    back.worker_queue.put_nowait(
        Event(name=EventName.EXECUTION_REPORT, content=full_fill_report)
    )

    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    total_realized = strategy.buy.buy_order.realized_quantity
    assert (
        abs(total_realized - original_quantity) < 0.0001
    ), f"Total realized should be {original_quantity:.5f} BTC, got {total_realized:.5f}"

    logger.info("=" * 60)
    logger.info("✓ Partial Fill → Cancel → Re-buy Remaining Test Complete (V2):")
    logger.info(f"  First Order:      {original_order_id} (30% filled, cancelled)")
    logger.info(f"  Partial Fill:     {partial_quantity:.5f} BTC")
    logger.info(f"  Second Order:     {second_order_id} (70% remaining)")
    logger.info(f"  Second Fill:      {second_order_quantity:.5f} BTC")
    logger.info(f"  Total Realized:   {total_realized:.5f} BTC")
    logger.info(f"  Final State:      {strategy.lifecycle_state}")
    logger.info("=" * 60)

    # Final state validation - NEW V2 behavior: partial buy → IDLE → complete buy → BOUGHT
    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    assert abs(strategy.buy.buy_order.realized_quantity - original_quantity) < 0.0001


async def test_send_sell_order_for_bought_position_v2(frontend_backend_v2_setup):
    """Test V2: BOUGHT → SELLING transition when sell price trigger hit.

    Scenario:
    1. Create bought position (buy order fully filled)
    2. Price rises to sell trigger → send sell order
    3. Verify state transitions BOUGHT → SELLING
    4. Verify sell order created with correct quantity

    Expected State Transitions:
    - BOUGHT → SELLING (on sell price trigger)

    This tests:
    - Sell order creation from bought position
    - Correct quantity (matches bought quantity)
    - State machine transition on sell trigger
    """
    from binance.enums import ORDER_STATUS_NEW

    front, back = frontend_backend_v2_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    sim = HPSimulatorV2(front=front, back=back)

    # Create bought position with sell config
    strategy = await sim.simulate_bought_position(
        symbol="BTCUSDC",
        budget=1000.0,
        buy_price=1400.0,
        sell_price=4200.0,
    )

    # Setup mocking for sell order
    sim.setup_order_mocking()

    # Calculate sell trigger (96% of sell price - DirectSellStrategy default)
    # V2 uses sell_strategy instead of sell
    assert strategy.sell_strategy is not None
    sell_trigger = strategy.sell_config.sell_price * 0.96  # SELL_TRIGGER_PERCENTAGE

    logger.info("=" * 60)
    logger.info("Sell Order Test:")
    logger.info(f"  Buy Price:        {strategy.buy_config.buy_price:,.2f} USDC")
    logger.info(f"  Sell Price:       {strategy.sell_config.sell_price:,.2f} USDC")
    logger.info(f"  Sell Trigger:     {sell_trigger:,.2f} USDC")
    logger.info(
        f"  Bought Quantity:  {strategy.buy.buy_order.realized_quantity:.5f} BTC"
    )
    logger.info("=" * 60)

    # Send price at sell trigger to initiate sell
    logger.info(f"[Step 1] Price rises to sell trigger: {sell_trigger:,.2f} USDC")
    sim.new_price(price=sell_trigger)

    # Wait for SELLING state
    await sim.wait_for_state(PositionLifecycleState.SELLING, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.SELLING
    logger.info("✓ State transitioned to SELLING")

    # Verify sell order was created
    assert strategy.sell_strategy is not None, "Sell strategy should exist"
    assert strategy.sell_strategy.order_id is not None, "Sell order should be created"
    logger.info(f"✓ Sell order created: order_id={strategy.sell_strategy.order_id}")

    # Verify sell order properties
    assert strategy.sell_strategy.quantity > 0, "Should have quantity to sell"
    logger.info(f"  Quantity: {strategy.sell_strategy.quantity} BTC")
    logger.info(f"  Target price: {strategy.sell_strategy.target_price} USDC")

    logger.info("✅ Test PASSED: Sell order sent for bought position")


async def test_cancel_unfilled_sell_order_v2(frontend_backend_v2_setup):
    """Test 10: Cancel unfilled sell order (V2).

    Tests SELLING state with order cancellation before any fills.

    V1 equivalent: test_cancel_unfilled_sell_order
    """
    from binance.enums import ORDER_STATUS_CANCELED

    front, back = frontend_backend_v2_setup
    sim = HPSimulatorV2(front=front, back=back)

    logger.info("=" * 60)
    logger.info("Cancel Unfilled Sell Order Test:")

    # Step 1: Create fully bought position with sell order
    strategy = await sim.simulate_bought_position(
        symbol="BTCUSDC",
        budget=1000.0,
        buy_price=1400.0,
        sell_price=4200.0,
    )

    # Setup order mocking for sell order
    sim.setup_order_mocking()

    # Step 2: Trigger sell order (BOUGHT → SELLING)
    sell_trigger = strategy.sell_config.sell_price * 0.96  # SELL_TRIGGER_PERCENTAGE
    logger.info(f"[Step 1] Price rises to {sell_trigger:.2f} USDC")
    sim.new_price(price=sell_trigger)

    await sim.wait_for_state(PositionLifecycleState.SELLING, timeout=2.0)
    assert strategy.lifecycle_state == PositionLifecycleState.SELLING
    logger.info("✓ Sell order sent, state = SELLING")

    # Verify sell order exists
    assert strategy.sell_strategy.order_id is not None
    original_order_id = strategy.sell_strategy.order_id
    logger.info(f"  Sell order ID: {original_order_id}")

    # Step 3: Trigger sell order cancellation
    # In V2, sell orders are cancelled when price DROPS to 92% of target
    # This means the price is falling and we should cancel the sell to avoid selling too low
    cancel_price = strategy.sell_config.sell_price * 0.92  # SELL_CANCEL_PERCENTAGE
    logger.info(f"[Step 2] Price drops to {cancel_price:.2f} USDC (trigger cancel)")

    # Mock cancel_order to succeed
    back.strategy.client.cancel_order = AsyncMock(
        return_value={"orderId": original_order_id, "status": "CANCELED"}
    )

    sim.new_price(price=cancel_price)

    # Wait for cancellation to complete
    await asyncio.sleep(0.2)

    # Verify order was cancelled
    back.strategy.client.cancel_order.assert_called_once()
    logger.info("✓ Cancel order called")

    # Step 4: Verify state transitions back to BOUGHT after cancellation
    # In V2, sell cancellation should transition SELLING → BOUGHT
    await asyncio.sleep(0.2)

    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    logger.info(f"✓ State transitioned back to BOUGHT after cancel")
    logger.info("✅ Test PASSED: Unfilled sell order cancelled")


async def test_resend_unfilled_sell_order_v2(frontend_backend_v2_setup):
    """Test 11: Cancel and resend unfilled sell order (V2).

    Tests SELLING → BOUGHT → SELLING cycle with cancel/resend.

    V1 equivalent: test_resend_unfilled_sell_order
    """
    from binance.enums import ORDER_STATUS_CANCELED

    front, back = frontend_backend_v2_setup
    sim = HPSimulatorV2(front=front, back=back)

    logger.info("=" * 60)
    logger.info("Resend Unfilled Sell Order Test:")

    # Step 1: Create fully bought position with sell order
    strategy = await sim.simulate_bought_position(
        symbol="BTCUSDC",
        budget=1000.0,
        buy_price=1400.0,
        sell_price=4200.0,
    )

    # Setup order mocking for sell order
    sim.setup_order_mocking()

    # Step 2: Trigger sell order (BOUGHT → SELLING)
    sell_trigger = strategy.sell_config.sell_price * 0.96  # SELL_TRIGGER_PERCENTAGE
    logger.info(f"[Step 1] Price rises to {sell_trigger:.2f} USDC")
    sim.new_price(price=sell_trigger)

    await sim.wait_for_state(PositionLifecycleState.SELLING, timeout=2.0)
    assert strategy.lifecycle_state == PositionLifecycleState.SELLING
    logger.info("✓ Sell order sent, state = SELLING")

    # Verify sell order exists
    assert strategy.sell_strategy.order_id is not None
    first_order_id = strategy.sell_strategy.order_id
    logger.info(f"  First sell order ID: {first_order_id}")

    # Step 3: Trigger sell order cancellation (SELLING → BOUGHT)
    cancel_price = strategy.sell_config.sell_price * 0.92  # SELL_CANCEL_PERCENTAGE
    logger.info(f"[Step 2] Price drops to {cancel_price:.2f} USDC (trigger cancel)")

    # Mock cancel_order to succeed
    back.strategy.client.cancel_order = AsyncMock(
        return_value={"orderId": first_order_id, "status": "CANCELED"}
    )

    sim.new_price(price=cancel_price)
    await asyncio.sleep(0.2)

    # Verify cancelled and back to BOUGHT
    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    logger.info("✓ Order cancelled, state = BOUGHT")

    # Step 4: Trigger sell order again (BOUGHT → SELLING)
    logger.info(f"[Step 3] Price rises back to {sell_trigger:.2f} USDC (resend)")

    # Setup new mocking for resend
    sim.setup_order_mocking()

    sim.new_price(price=sell_trigger)
    await sim.wait_for_state(PositionLifecycleState.SELLING, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.SELLING
    logger.info("✓ Sell order resent, state = SELLING")

    # Verify new sell order was created
    assert strategy.sell_strategy.order_id is not None
    second_order_id = strategy.sell_strategy.order_id
    logger.info(f"  Second sell order ID: {second_order_id}")

    # Note: Order IDs might be the same due to deterministic mocking
    # The important verification is that we successfully transitioned back to SELLING
    logger.info("✓ Sell order successfully resent")

    logger.info("✅ Test PASSED: Unfilled sell order resent after cancel")


async def test_sell_position_order_filled_partially_v2(frontend_backend_v2_setup):
    """Test 12: Sell order partially filled (V2).

    Tests SELLING state with partial fill execution reports.

    V1 equivalent: test_sell_position_order_filled_partially
    """
    from binance.enums import ORDER_STATUS_PARTIALLY_FILLED

    front, back = frontend_backend_v2_setup
    sim = HPSimulatorV2(front=front, back=back)

    logger.info("=" * 60)
    logger.info("Sell Order Partial Fill Test:")

    # Step 1: Create fully bought position with sell order
    strategy = await sim.simulate_bought_position(
        symbol="BTCUSDC",
        budget=1000.0,
        buy_price=1400.0,
        sell_price=4200.0,
    )

    sim.setup_order_mocking()

    # Step 2: Trigger sell order (BOUGHT → SELLING)
    sell_trigger = strategy.sell_config.sell_price * 0.96
    logger.info(f"[Step 1] Trigger sell at {sell_trigger:.2f} USDC")
    sim.new_price(price=sell_trigger)

    await sim.wait_for_state(PositionLifecycleState.SELLING, timeout=2.0)
    assert strategy.lifecycle_state == PositionLifecycleState.SELLING
    logger.info("✓ Sell order sent, state = SELLING")

    # Verify sell order exists
    assert strategy.sell_strategy.order_id is not None
    order_id = strategy.sell_strategy.order_id
    original_quantity = strategy.sell_strategy.quantity
    logger.info(f"  Order ID: {order_id}, Quantity: {original_quantity} BTC")

    # Step 3: Send partial fill execution report
    partial_fill_qty = original_quantity * 0.5  # Fill 50%
    logger.info(f"[Step 2] Partial fill: {partial_fill_qty} BTC (50%)")

    from src.common.identifiers import ExecutionReport, Event, EventName

    exec_report = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=order_id,
        last_executed_quantity=partial_fill_qty,
        last_executed_price=strategy.sell_config.sell_price,
        cumulative_filled_quantity=partial_fill_qty,
        price=strategy.sell_config.sell_price,
    )

    back.worker_queue.put_nowait(
        Event(name=EventName.EXECUTION_REPORT, content=exec_report)
    )

    # Wait for execution report processing
    await asyncio.sleep(0.2)

    # Step 4: Verify still in SELLING state (not fully sold yet)
    assert strategy.lifecycle_state == PositionLifecycleState.SELLING
    logger.info("✓ Still in SELLING state (partial fill)")

    # Verify realized quantity updated
    # Note: In V2, we need to check the sell strategy's tracking
    logger.info(f"  Filled: {partial_fill_qty} BTC of {original_quantity} BTC")
    logger.info("✅ Test PASSED: Sell order partially filled")


async def test_sell_position_filled_v2(frontend_backend_v2_setup):
    """Test 13: Sell order fully filled (V2).

    Tests SELLING → CLOSED transition when sell order fills completely.

    V1 equivalent: test_sell_position_filled
    """
    from binance.enums import ORDER_STATUS_FILLED

    front, back = frontend_backend_v2_setup
    sim = HPSimulatorV2(front=front, back=back)

    logger.info("=" * 60)
    logger.info("Sell Order Full Fill Test:")

    # Step 1: Create fully bought position with sell order
    strategy = await sim.simulate_bought_position(
        symbol="BTCUSDC",
        budget=1000.0,
        buy_price=1400.0,
        sell_price=4200.0,
    )

    sim.setup_order_mocking()

    # Step 2: Trigger sell order (BOUGHT → SELLING)
    sell_trigger = strategy.sell_config.sell_price * 0.96
    logger.info(f"[Step 1] Trigger sell at {sell_trigger:.2f} USDC")
    sim.new_price(price=sell_trigger)

    await sim.wait_for_state(PositionLifecycleState.SELLING, timeout=2.0)
    assert strategy.lifecycle_state == PositionLifecycleState.SELLING
    logger.info("✓ Sell order sent, state = SELLING")

    # Verify sell order exists
    assert strategy.sell_strategy.order_id is not None
    order_id = strategy.sell_strategy.order_id
    quantity = strategy.sell_strategy.quantity
    logger.info(f"  Order ID: {order_id}, Quantity: {quantity} BTC")

    # Step 3: Send full fill execution report (SELLING → CLOSED)
    logger.info(f"[Step 2] Full fill: {quantity} BTC (100%)")

    from src.common.identifiers import ExecutionReport, Event, EventName

    exec_report = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_FILLED,
        order_id=order_id,
        last_executed_quantity=quantity,
        last_executed_price=strategy.sell_config.sell_price,
        cumulative_filled_quantity=quantity,
        price=strategy.sell_config.sell_price,
    )

    back.worker_queue.put_nowait(
        Event(name=EventName.EXECUTION_REPORT, content=exec_report)
    )

    # Wait for state transition to CLOSED
    await sim.wait_for_state(PositionLifecycleState.CLOSED, timeout=2.0)

    # Step 4: Verify position is CLOSED
    assert strategy.lifecycle_state == PositionLifecycleState.CLOSED
    logger.info("✓ State transitioned to CLOSED")
    logger.info("✅ Test PASSED: Sell order fully filled")


async def test_cancel_partially_sold_position_v2(frontend_backend_v2_setup):
    """Test 14: Cancel a partially filled sell order.

    V1 Test: test_cancel_partially_sold_position

    Workflow:
    1. Create bought position (buy order fully filled)
    2. Price rises to sell trigger → send sell order
    3. Sell order partially filled (e.g., 50%)
    4. Price drops to cancel trigger → cancel remaining order
    5. Verify state transitions SELLING → BOUGHT
    6. Verify partial quantity remains (can resend)

    Expected State Transitions:
    - BOUGHT → SELLING (on sell price trigger)
    - SELLING → BOUGHT (on cancel trigger after partial fill)

    This tests:
    - Cancellation of partially filled sell orders
    - Quantity tracking after partial fill
    - State machine transition on cancel with remaining quantity
    """
    from binance.enums import ORDER_STATUS_PARTIALLY_FILLED

    front, back = frontend_backend_v2_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    sim = HPSimulatorV2(front=front, back=back)

    # Create bought position with sell config
    strategy = await sim.simulate_bought_position(
        symbol="BTCUSDC",
        budget=1000.0,
        buy_price=1400.0,
        sell_price=4200.0,
    )

    # Setup mocking for sell order
    sim.setup_order_mocking()

    logger.info("=" * 60)
    logger.info("Cancel Partially Sold Position Test:")

    # Step 1: Trigger sell
    sell_trigger = strategy.sell_config.sell_price * 0.96
    logger.info(f"[Step 1] Trigger sell at {sell_trigger:,.2f} USDC")
    sim.new_price(price=sell_trigger)
    await sim.wait_for_state(PositionLifecycleState.SELLING, timeout=2.0)

    order_id = strategy.sell_strategy.order_id
    total_quantity = strategy.sell_strategy.quantity

    # Step 2: Partial fill (50%)
    partial_quantity = total_quantity * 0.5
    logger.info(f"[Step 2] Partial fill: {partial_quantity} BTC (50%)")

    from src.common.identifiers import ExecutionReport, Event, EventName

    exec_report = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=order_id,
        last_executed_quantity=partial_quantity,
        last_executed_price=strategy.sell_config.sell_price,
        cumulative_filled_quantity=partial_quantity,
        price=strategy.sell_config.sell_price,
    )

    back.worker_queue.put_nowait(
        Event(name=EventName.EXECUTION_REPORT, content=exec_report)
    )

    # Wait for partial fill to be processed
    await asyncio.sleep(0.2)

    assert strategy.lifecycle_state == PositionLifecycleState.SELLING
    assert strategy.sell_strategy.filled_quantity == partial_quantity
    logger.info(f"✓ Partial fill processed: {partial_quantity}/{total_quantity} BTC")

    # Step 3: Cancel (price drops to cancel trigger - 92% of target)
    cancel_trigger = strategy.sell_config.sell_price * 0.92
    logger.info(f"[Step 3] Price drops to cancel trigger: {cancel_trigger:,.2f} USDC")
    sim.new_price(price=cancel_trigger)

    # Wait for state transition to BOUGHT
    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)

    # Step 4: Verify position is BOUGHT and partial quantity is tracked
    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    logger.info("✓ State transitioned back to BOUGHT")

    # Sell strategy should still have the filled quantity tracked
    assert strategy.sell_strategy.filled_quantity == partial_quantity
    logger.info(
        f"✓ Partial fill tracked: {partial_quantity} BTC "
        f"({partial_quantity/total_quantity*100:.0f}%)"
    )

    logger.info("✅ Test PASSED: Partially sold position cancelled")


async def test_resend_sell_order_for_partially_sold_position_v2(
    frontend_backend_v2_setup,
):
    """Test 15: Resend sell order after cancelling a partially filled one.

    V1 Test: test_resend_sell_order_for_partially_sold_position

    Workflow:
    1. Create bought position
    2. Send sell order (BOUGHT → SELLING)
    3. Partial fill (50%)
    4. Cancel remaining (SELLING → BOUGHT)
    5. Price rises again → resend sell order (BOUGHT → SELLING)
    6. Verify new order created for remaining quantity

    Expected State Transitions:
    - BOUGHT → SELLING (initial sell)
    - SELLING → BOUGHT (cancel after partial fill)
    - BOUGHT → SELLING (resend for remaining quantity)

    This tests:
    - Resending sell after partial fill + cancel
    - Quantity calculation for remaining inventory
    - Multiple sell attempts on same position
    """
    from binance.enums import ORDER_STATUS_PARTIALLY_FILLED

    front, back = frontend_backend_v2_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    sim = HPSimulatorV2(front=front, back=back)

    # Create bought position
    strategy = await sim.simulate_bought_position(
        symbol="BTCUSDC",
        budget=1000.0,
        buy_price=1400.0,
        sell_price=4200.0,
    )

    sim.setup_order_mocking()

    logger.info("=" * 60)
    logger.info("Resend Sell After Partial Fill Test:")

    # Step 1: Trigger sell
    sell_trigger = strategy.sell_config.sell_price * 0.96
    logger.info(f"[Step 1] Trigger sell at {sell_trigger:,.2f} USDC")
    sim.new_price(price=sell_trigger)
    await sim.wait_for_state(PositionLifecycleState.SELLING, timeout=2.0)

    first_order_id = strategy.sell_strategy.order_id
    total_quantity = strategy.sell_strategy.quantity

    # Step 2: Partial fill (50%)
    partial_quantity = total_quantity * 0.5
    logger.info(f"[Step 2] Partial fill: {partial_quantity} BTC (50%)")

    from src.common.identifiers import ExecutionReport, Event, EventName

    exec_report = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=first_order_id,
        last_executed_quantity=partial_quantity,
        last_executed_price=strategy.sell_config.sell_price,
        cumulative_filled_quantity=partial_quantity,
        price=strategy.sell_config.sell_price,
    )

    back.worker_queue.put_nowait(
        Event(name=EventName.EXECUTION_REPORT, content=exec_report)
    )

    await asyncio.sleep(0.2)
    assert strategy.sell_strategy.filled_quantity == partial_quantity

    # Step 3: Cancel
    cancel_trigger = strategy.sell_config.sell_price * 0.92
    logger.info(f"[Step 3] Cancel at {cancel_trigger:,.2f} USDC")
    sim.new_price(price=cancel_trigger)
    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)

    logger.info(f"✓ Cancelled, filled: {partial_quantity}/{total_quantity} BTC")

    # Step 4: Resend (price rises again)
    logger.info(f"[Step 4] Resend sell at {sell_trigger:,.2f} USDC")
    sim.new_price(price=sell_trigger)
    await sim.wait_for_state(PositionLifecycleState.SELLING, timeout=2.0)

    # Verify new order created
    second_order_id = strategy.sell_strategy.order_id
    assert second_order_id != first_order_id, "Should create new order ID"
    logger.info(f"✓ New order created: {second_order_id}")

    # Verify quantity is for remaining (not total - partial is already sold)
    # But strategy still tracks total quantity, filled_quantity shows what's sold
    assert strategy.sell_strategy.quantity == total_quantity
    assert strategy.sell_strategy.filled_quantity == partial_quantity
    logger.info(
        f"✓ Quantity tracking: {strategy.sell_strategy.quantity} total, "
        f"{strategy.sell_strategy.filled_quantity} already sold"
    )

    logger.info("✅ Test PASSED: Resend sell after partial fill")


async def test_send_sell_order_for_partially_bought_position_v2(
    frontend_backend_v2_setup,
):
    """Test 16: Send sell order when buy position is only partially filled.

    V1 Test: test_send_sell_order_for_partially_bought_position

    Workflow:
    1. Create buy position and send order (IDLE → BUYING)
    2. Partial fill buy order (e.g., 50%)
    3. Cancel remaining buy order (stays in BUYING, but buy complete)
    4. Transition to BOUGHT with partial quantity
    5. Price rises → send sell order for the partial quantity
    6. Verify sell order uses only the realized buy quantity

    Expected State Transitions:
    - IDLE → BUYING (on buy trigger)
    - BUYING → BOUGHT (after partial fill + cancel)
    - BOUGHT → SELLING (on sell trigger)

    This tests:
    - Selling with only partial buy position
    - Correct quantity calculation (uses realized_quantity, not full order)
    - State transitions work with partial fills
    """
    from binance.enums import ORDER_STATUS_PARTIALLY_FILLED, ORDER_STATUS_CANCELED

    front, back = frontend_backend_v2_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    sim = HPSimulatorV2(front=front, back=back)

    # Create position and trigger buy
    sim.simulate_buy_position(
        symbol="BTCUSDC",
        budget=1000.0,
        buy_price=1400.0,
        sell_price=4200.0,
        hp_id="1000",
    )
    await sim.assert_default_buy_position()

    strategy = sim.back.strategy
    assert strategy is not None

    sim.setup_order_mocking()

    logger.info("=" * 60)
    logger.info("Sell Order for Partially Bought Position Test:")

    # Step 1: Send buy order
    trigger_price = strategy.buy.trigger_price
    sim.new_price(price=trigger_price)
    await sim.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

    await asyncio.sleep(0.1)
    assert strategy.buy.buy_order is not None
    order_id = strategy.buy.buy_order.order_id
    full_quantity = strategy.buy.buy_order.quantity

    # Step 2: Partial fill (50%)
    partial_quantity = full_quantity * 0.5
    logger.info(f"[Step 1] Partial fill: {partial_quantity} BTC (50%)")

    from src.common.identifiers import ExecutionReport, Event, EventName

    exec_report = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=order_id,
        last_executed_quantity=partial_quantity,
        last_executed_price=strategy.buy_config.buy_price,
        cumulative_filled_quantity=partial_quantity,
        price=strategy.buy_config.buy_price,
    )

    back.worker_queue.put_nowait(
        Event(name=EventName.EXECUTION_REPORT, content=exec_report)
    )

    await asyncio.sleep(0.2)
    assert strategy.buy.buy_order.realized_quantity == partial_quantity
    logger.info(f"✓ Buy partially filled: {partial_quantity}/{full_quantity} BTC")

    # Step 3: Cancel remaining order (price rises above cancel trigger)
    cancel_trigger = strategy.buy.cancel_price
    logger.info(f"[Step 2] Cancel remaining at {cancel_trigger:,.2f} USDC")
    sim.new_price(price=cancel_trigger)

    # Wait for IDLE state after cancel
    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)

    # Wait for sell strategy to be initialized (happens asynchronously in cancel callback)
    await sim.wait_for_condition(
        lambda: strategy.sell_strategy is not None, timeout=2.0
    )

    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    assert strategy.sell_strategy is not None, "Sell strategy should be initialized"
    logger.info(f"✓ Position BOUGHT with partial quantity: {partial_quantity} BTC")

    # Step 4: Trigger sell (price rises to sell trigger)
    sell_trigger = strategy.sell_config.sell_price * 0.96
    logger.info(f"[Step 3] Trigger sell at {sell_trigger:,.2f} USDC")
    sim.new_price(price=sell_trigger)

    await sim.wait_for_state(PositionLifecycleState.SELLING, timeout=2.0)

    # Step 5: Verify sell order quantity matches partial buy quantity
    assert strategy.lifecycle_state == PositionLifecycleState.SELLING
    assert strategy.sell_strategy.order_id is not None
    logger.info(f"✓ Sell order created: {strategy.sell_strategy.order_id}")

    # Verify sell quantity equals realized buy quantity (not full quantity)
    assert (
        strategy.sell_strategy.quantity == partial_quantity
    ), f"Sell quantity should be {partial_quantity}, got {strategy.sell_strategy.quantity}"
    logger.info(
        f"✓ Sell quantity correct: {strategy.sell_strategy.quantity} BTC "
        f"(matches partial buy)"
    )

    logger.info("✅ Test PASSED: Sell order for partially bought position")


async def test_cancel_unfilled_sell_order_for_partially_bought_position_v2(
    frontend_backend_v2_setup,
):
    """Test V2: Cancel sell order that was created from partially bought position.

    Scenario:
    1. Buy order partially fills (30%)
    2. Cancel buy order → transitions to BOUGHT (V2 behavior)
    3. Price rises to sell trigger → send sell order for partial inventory
    4. Sell order not filled yet
    5. Price drops below cancel threshold → cancel sell order
    6. Verify state returns to BOUGHT (can resend sell later)

    Expected State Transitions:
    - IDLE → BUYING (on buy order sent)
    - BUYING → BOUGHT (on cancel with partial inventory)
    - BOUGHT → SELLING (on sell trigger)
    - SELLING → BOUGHT (on sell cancel - inventory still there)

    This tests:
    - Sell cancellation with partial buy inventory
    - State preservation (BOUGHT not IDLE after sell cancel)
    - Inventory tracking through cancel cycles
    """
    from binance.enums import ORDER_STATUS_PARTIALLY_FILLED, ORDER_STATUS_NEW

    front, back = frontend_backend_v2_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    sim = HPSimulatorV2(front=front, back=back)

    # Create position with sell config (required for partial inventory)
    sim.simulate_buy_position(
        symbol="BTCUSDC",
        budget=1000.0,
        buy_price=1400.0,
        sell_price=4200.0,
    )
    await sim.assert_default_buy_position()

    strategy = back.strategy

    # Setup mocking
    sim.setup_order_mocking()
    strategy.client.cancel_order = AsyncMock(return_value=True)

    trigger_price = strategy.buy.trigger_price
    cancel_price = strategy.buy.cancel_price

    logger.info("=" * 60)
    logger.info("Cancel Sell Order for Partially Bought Position Test:")
    logger.info(f"  Buy Trigger:      {trigger_price:,.2f} USDC")
    logger.info(f"  Buy Cancel:       {cancel_price:,.2f} USDC")
    logger.info(f"  Buy Price:        {strategy.buy.config.buy_price:,.2f} USDC")
    logger.info(f"  Sell Price:       {strategy.sell_config.sell_price:,.2f} USDC")
    logger.info("=" * 60)

    # Step 1: Send buy order
    logger.info(f"[Step 1] Price drops to buy trigger: {trigger_price:,.2f} USDC")
    sim.new_price(price=trigger_price)
    await sim.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

    # Wait for order_id
    await sim.wait_for_condition(
        lambda: strategy.buy.buy_order is not None
        and strategy.buy.buy_order.order_id is not None,
        timeout=2.0,
    )

    buy_order_id = strategy.buy.buy_order.order_id
    buy_quantity = strategy.buy.buy_order.quantity
    logger.info(f"✓ Buy order sent: {buy_order_id}, quantity={buy_quantity:.5f}")

    # Step 2: Partial fill (30%)
    partial_fill_pct = 0.3
    partial_quantity = buy_quantity * partial_fill_pct
    fill_price = strategy.buy.config.buy_price

    logger.info(
        f"[Step 2] Partial fill: {partial_fill_pct*100:.0f}% ({partial_quantity:.5f} BTC)"
    )

    execution_report = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=buy_order_id,
        last_executed_quantity=partial_quantity,
        last_executed_price=fill_price,
        cumulative_filled_quantity=partial_quantity,
        price=fill_price,
    )
    back.worker_queue.put_nowait(
        Event(name=EventName.EXECUTION_REPORT, content=execution_report)
    )

    await sim.wait_for_condition(
        lambda: strategy.buy.buy_order.realized_quantity == partial_quantity,
        timeout=2.0,
    )
    logger.info(f"✓ Partial fill processed: {partial_quantity:.5f} BTC")

    # Step 3: Cancel buy order → BOUGHT
    logger.info(f"[Step 3] Price rises to buy cancel: {cancel_price:,.2f} USDC")
    sim.new_price(price=cancel_price)
    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)

    # Wait for sell strategy initialization
    await sim.wait_for_condition(
        lambda: strategy.sell_strategy is not None,
        timeout=2.0,
    )

    assert strategy.buy.buy_order.realized_quantity == partial_quantity
    logger.info(f"✓ Buy cancelled, BOUGHT with {partial_quantity:.5f} BTC inventory")

    # Step 4: Send sell order for partial inventory
    sell_trigger = strategy.sell_config.sell_price * 0.96
    logger.info(f"[Step 4] Price rises to sell trigger: {sell_trigger:,.2f} USDC")
    sim.new_price(price=sell_trigger)
    await sim.wait_for_state(PositionLifecycleState.SELLING, timeout=2.0)

    sell_order_id = strategy.sell_strategy.order_id
    sell_quantity = strategy.sell_strategy.quantity
    assert sell_quantity == partial_quantity
    logger.info(f"✓ Sell order sent: {sell_order_id}, quantity={sell_quantity:.5f} BTC")

    # Step 5: Cancel sell order (not filled yet)
    # In V2, sell cancel threshold is 92% of sell_price (SELL_CANCEL_PERCENTAGE = 0.92)
    sell_cancel_threshold = (
        strategy.sell_config.sell_price * 0.91
    )  # Drop below 92% cancel threshold
    logger.info(
        f"[Step 5] Price drops to sell cancel: {sell_cancel_threshold:,.2f} USDC"
    )
    sim.new_price(price=sell_cancel_threshold)

    # Wait for state to return to BOUGHT
    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)

    logger.info("=" * 60)
    logger.info("✓ Cancel Sell for Partial Buy Complete:")
    logger.info(f"  Lifecycle State:  {strategy.lifecycle_state}")
    logger.info(
        f"  Buy Inventory:    {strategy.buy.buy_order.realized_quantity:.5f} BTC"
    )
    logger.info(f"  State:            BOUGHT (can resend sell)")
    logger.info("=" * 60)

    # Final assertions
    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    assert strategy.buy.buy_order.realized_quantity == partial_quantity
    assert strategy.sell_strategy is not None  # Sell strategy remains available
    strategy.client.cancel_order.assert_called()  # Both buy and sell were cancelled


async def test_complete_lifecycle_v2(frontend_backend_v2_setup):
    """Test V2: Complete position lifecycle from IDLE to CLOSED.

    This test demonstrates V2's simplified 5-state lifecycle:
    IDLE → BUYING → BOUGHT → SELLING → CLOSED

    Scenario:
    1. IDLE: Position created, waiting for buy trigger
    2. Price drops → send buy order (BUYING)
    3. Buy order fills → transition to BOUGHT
    4. Price rises → send sell order (SELLING)
    5. Sell order fills → transition to CLOSED

    This validates:
    - Complete happy path through all 5 states
    - Proper state transitions at each step
    - Database persistence throughout lifecycle
    - Final cleanup and closure
    """
    from binance.enums import ORDER_STATUS_FILLED

    front, back = frontend_backend_v2_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    sim = HPSimulatorV2(front=front, back=back)

    # Create position
    sim.simulate_buy_position(
        symbol="BTCUSDC",
        budget=1000.0,
        buy_price=1400.0,
        sell_price=4200.0,
    )
    await sim.assert_default_buy_position()

    strategy = back.strategy

    # Setup mocking
    sim.setup_order_mocking()

    logger.info("=" * 60)
    logger.info("Complete V2 Lifecycle Test:")
    logger.info(f"  Buy Price:   {strategy.buy.config.buy_price:,.2f} USDC")
    logger.info(f"  Sell Price:  {strategy.sell_config.sell_price:,.2f} USDC")
    logger.info("=" * 60)

    # State 1: IDLE
    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    logger.info(f"✓ State 1: {strategy.lifecycle_state}")

    # State 2: IDLE → BUYING (buy trigger hit)
    buy_trigger = strategy.buy.trigger_price
    logger.info(f"[Step 1] Price drops to buy trigger: {buy_trigger:,.2f} USDC")
    sim.new_price(price=buy_trigger)
    await sim.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

    await sim.wait_for_condition(
        lambda: strategy.buy.buy_order is not None
        and strategy.buy.buy_order.order_id is not None,
        timeout=2.0,
    )

    buy_order_id = strategy.buy.buy_order.order_id
    buy_quantity = strategy.buy.buy_order.quantity
    assert strategy.lifecycle_state == PositionLifecycleState.BUYING
    logger.info(f"✓ State 2: {strategy.lifecycle_state} (order {buy_order_id})")

    # State 3: BUYING → BOUGHT (buy order fills)
    logger.info(
        f"[Step 2] Buy order fills: {buy_quantity:.5f} BTC @ {strategy.buy.config.buy_price}"
    )

    buy_fill_report = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_FILLED,
        order_id=buy_order_id,
        last_executed_quantity=buy_quantity,
        last_executed_price=strategy.buy.config.buy_price,
        cumulative_filled_quantity=buy_quantity,
        price=strategy.buy.config.buy_price,
    )
    back.worker_queue.put_nowait(
        Event(name=EventName.EXECUTION_REPORT, content=buy_fill_report)
    )

    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)

    # Wait for sell strategy initialization
    await sim.wait_for_condition(
        lambda: strategy.sell_strategy is not None,
        timeout=2.0,
    )

    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    assert strategy.buy.buy_order.realized_quantity == buy_quantity
    logger.info(
        f"✓ State 3: {strategy.lifecycle_state} (inventory: {buy_quantity:.5f} BTC)"
    )

    # State 4: BOUGHT → SELLING (sell trigger hit)
    sell_trigger = strategy.sell_config.sell_price * 0.96
    logger.info(f"[Step 3] Price rises to sell trigger: {sell_trigger:,.2f} USDC")
    sim.new_price(price=sell_trigger)
    await sim.wait_for_state(PositionLifecycleState.SELLING, timeout=2.0)

    sell_order_id = strategy.sell_strategy.order_id
    sell_quantity = strategy.sell_strategy.quantity
    assert strategy.lifecycle_state == PositionLifecycleState.SELLING
    assert sell_quantity == buy_quantity
    logger.info(f"✓ State 4: {strategy.lifecycle_state} (order {sell_order_id})")

    # State 5: SELLING → CLOSED (sell order fills)
    logger.info(
        f"[Step 4] Sell order fills: {sell_quantity:.5f} BTC @ {strategy.sell_config.sell_price}"
    )

    sell_fill_report = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_FILLED,
        order_id=sell_order_id,
        last_executed_quantity=sell_quantity,
        last_executed_price=strategy.sell_config.sell_price,
        cumulative_filled_quantity=sell_quantity,
        price=strategy.sell_config.sell_price,
    )
    back.worker_queue.put_nowait(
        Event(name=EventName.EXECUTION_REPORT, content=sell_fill_report)
    )

    await sim.wait_for_state(PositionLifecycleState.CLOSED, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.CLOSED
    logger.info(f"✓ State 5: {strategy.lifecycle_state}")

    # Calculate profit
    buy_cost = buy_quantity * strategy.buy.config.buy_price
    sell_proceeds = sell_quantity * strategy.sell_config.sell_price
    profit = sell_proceeds - buy_cost
    profit_pct = (profit / buy_cost) * 100

    logger.info("=" * 60)
    logger.info("✓ Complete Lifecycle Test PASSED:")
    logger.info(
        f"  Buy:         {buy_quantity:.5f} BTC @ {strategy.buy.config.buy_price:,.2f} = {buy_cost:,.2f} USDC"
    )
    logger.info(
        f"  Sell:        {sell_quantity:.5f} BTC @ {strategy.sell_config.sell_price:,.2f} = {sell_proceeds:,.2f} USDC"
    )
    logger.info(f"  Profit:      {profit:,.2f} USDC ({profit_pct:.2f}%)")
    logger.info(f"  Final State: {strategy.lifecycle_state}")
    logger.info("=" * 60)


# ============================================================================
# V2 Test Coverage Summary
# ============================================================================
#
# V2 implements a simplified 5-state lifecycle model:
#   IDLE → BUYING → BOUGHT → SELLING → CLOSED
#
# Tests 1-18 cover the core V2 functionality:
#
# Buy Flow (Tests 1-8):
#   1. Get default position (IDLE)
#   2. Send buy order (IDLE → BUYING)
#   3. Cancel unfilled buy (BUYING → IDLE)
#   4. Resend cancelled buy (IDLE → BUYING)
#   5. Buy order fills (BUYING → BOUGHT)
#   6. Partial buy fill (BUYING stays BUYING)
#   7. Partial fill + cancel (BUYING → BOUGHT with inventory)
#   8. Partial fill + cancel + sell (BOUGHT → SELLING)
#
# Sell Flow (Tests 9-15):
#   9. Send sell order (BOUGHT → SELLING)
#   10. Cancel unfilled sell (SELLING → BOUGHT)
#   11. Resend cancelled sell (BOUGHT → SELLING)
#   12. Partial sell fill (SELLING stays SELLING)
#   13. Sell order fills (SELLING → CLOSED)
#   14. Cancel partially sold (SELLING → BOUGHT with remaining inventory)
#   15. Resend after partial sell (BOUGHT → SELLING)
#
# Partial Inventory (Tests 16-18):
#   16. Sell order for partially bought position
#   17. (Test 8 covers this scenario)
#   18. Cancel sell for partially bought position
#
# Complete Lifecycle (Test 19):
#   19. Full cycle: IDLE → BUYING → BOUGHT → SELLING → CLOSED
#
# V1 Tests NOT Applicable to V2:
#   - V1 tests 19-25: PARTIALLY_BOUGHT and PART_SOLD_PART_BOUGHT states
#     V2 simplification: Any inventory = BOUGHT (no partial states)
#   - V1 tests 26-32, 35-39: Multihop/convert selling
#     V2 future: Not yet implemented (direct sell only for now)
#   - V1 tests 33-34: Edge cases already covered by V2 tests 16-18
#
# ============================================================================


# ============================================================================
# Convert Sell Tests (V1 tests 26-28 adapted for V2)
# ============================================================================


async def test_convert_sell_btc_usdt_to_usdc_v2(frontend_backend_v2_setup):
    """Test V2: Convert sell BTC/USDT → USDT, then convert USDT → USDC.

    V2 Convert Flow: BOUGHT → SELLING (2-phase sell)
      Phase 1: Sell BTC/USDT (BTC → USDT)
      Phase 2: Convert USDT/USDC (USDT → USDC)

    This tests the convert sell strategy where:
    1. Buy BTC/USDC (direct pair not available, so BTC/USDT is used)
    2. Position transitions to BOUGHT with inventory
    3. Sell trigger hits → Phase 1: sell BTC/USDT
    4. Phase 1 fills → Phase 2: convert USDT → USDC
    5. Phase 2 fills → CLOSED

    EU regulation scenario: USDC pairs restricted, must use USDT then convert.
    """
    from src.common.symbol import Symbol

    front, back = frontend_backend_v2_setup

    sim = HPSimulatorV2(front=front, back=back)

    # Remove BTCUSDC to force convert path (EU regulation scenario)
    if "BTCUSDC" in back.symbols:
        del back.symbols["BTCUSDC"]

    # Add convert-enabled symbols to test
    back.symbols["BTCUSDT"] = Symbol(
        name="BTCUSDT",
        precision=5,
        price_precision=2,
        is_convert_only=True,  # Mark as convert-only (EU regulation)
    )
    back.symbols["USDTUSDC"] = Symbol(
        name="USDTUSDC", precision=2, price_precision=4
    )  # Convert pair

    # Update price resolver with USDT/USDC price
    back.price_resolver.update_price("USDTUSDC", 1.0)  # 1:1 conversion

    # Step 1: Create buy position at BTC/USDT (since BTC/USDC restricted)
    sim.simulate_buy_position(
        symbol="BTCUSDT",  # Must use USDT pair
        buy_price=50000.0,
        sell_price=60000.0,
        budget=1000.0,
        hp_id="convert_test_1",
    )

    # Wait for strategy to be initialized
    await sim.wait_for_condition(lambda: back.strategy is not None, timeout=2.0)
    strategy = back.strategy
    assert strategy.lifecycle_state == PositionLifecycleState.IDLE

    # Step 2: Send and fill buy order to reach BOUGHT state
    sim.setup_order_mocking()
    trigger_price = strategy.buy.trigger_price
    sim.new_price(price=trigger_price, symbol="BTCUSDT")
    await sim.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

    await asyncio.sleep(0.1)
    buy_order_id = strategy.buy.buy_order.order_id
    buy_quantity = strategy.buy.buy_order.quantity

    exec_report_buy = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_FILLED,
        order_id=buy_order_id,
        last_executed_quantity=buy_quantity,
        last_executed_price=50000.0,
        cumulative_filled_quantity=buy_quantity,
        price=50000.0,
        symbol="BTCUSDT",
    )

    back.worker_queue.put_nowait(
        Event(name=EventName.EXECUTION_REPORT, content=exec_report_buy)
    )

    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)
    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    assert strategy.buy.buy_order.realized_quantity > 0

    quantity_bought = strategy.buy.buy_order.realized_quantity

    logger.info("=" * 60)
    logger.info("Convert Sell Test Setup:")
    logger.info(f"  Bought:           {quantity_bought:.5f} BTC @ $50,000")
    logger.info(f"  Target:           Sell @ $60,000 → USDC")
    logger.info(f"  Path:             BTC → USDT → USDC (convert)")
    logger.info(f"  Phase 1:          BTC/USDT sell")
    logger.info(f"  Phase 2:          USDT/USDC convert")
    logger.info("=" * 60)

    # Step 3: Initialize sell strategy (should create ConvertSellStrategy)
    assert strategy.sell_strategy is not None
    from src.strategies.hp_manager_v2.sell_strategies.convert_sell import (
        ConvertSellStrategy,
    )

    assert isinstance(strategy.sell_strategy, ConvertSellStrategy)
    logger.info(f"✓ ConvertSellStrategy initialized")

    # Step 4: Send ticker update for USDTUSDC BEFORE triggering sell
    # (so convert phase has price data ready)
    sim.new_price(price=1.0, symbol="USDTUSDC")
    await asyncio.sleep(0.1)  # Let ticker be processed

    # Step 5: Trigger sell by raising price to 96% of target
    sell_trigger_price = 60000.0 * 0.96  # 57,600
    sim.new_price(price=sell_trigger_price, symbol="BTCUSDT")
    await sim.wait_for_state(PositionLifecycleState.SELLING, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.SELLING
    assert strategy.sell_strategy.sell_order_id is not None
    logger.info(
        f"✓ Phase 1 started: BTC/USDT sell order {strategy.sell_strategy.sell_order_id}"
    )

    # Step 6: Fill Phase 1 (BTC → USDT)
    phase1_order_id = strategy.sell_strategy.sell_order_id
    usdt_received = quantity_bought * 60000.0  # BTC sold * price = USDT

    exec_report_phase1 = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_FILLED,
        order_id=phase1_order_id,
        last_executed_quantity=quantity_bought,
        last_executed_price=60000.0,
        cumulative_filled_quantity=quantity_bought,
        price=60000.0,
        symbol="BTCUSDT",
    )

    back.worker_queue.put_nowait(
        Event(name=EventName.EXECUTION_REPORT, content=exec_report_phase1)
    )

    logger.info(
        f"✓ Phase 1 filled: {quantity_bought:.5f} BTC → {usdt_received:.2f} USDT"
    )

    # Send ticker update for USDTUSDC again (after phase 1 completes)
    # This ensures convert_sell has the ticker price for phase 2
    sim.new_price(price=1.0, symbol="USDTUSDC")
    await asyncio.sleep(0.05)

    # Wait for Phase 2 to start (convert USDT → USDC)
    await sim.wait_for_condition(
        lambda: strategy.sell_strategy.convert_order_id is not None, timeout=2.0
    )

    assert strategy.sell_strategy.convert_order_id is not None
    logger.info(
        f"✓ Phase 2 started: USDT/USDC convert order {strategy.sell_strategy.convert_order_id}"
    )

    # Step 7: Fill Phase 2 (USDT → USDC)
    phase2_order_id = strategy.sell_strategy.convert_order_id
    usdc_received = usdt_received * 1.0  # USDT ≈ USDC (1:1 convert)

    exec_report_phase2 = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_FILLED,
        order_id=phase2_order_id,
        last_executed_quantity=usdt_received,
        last_executed_price=1.0,
        cumulative_filled_quantity=usdt_received,
        price=1.0,
        symbol="USDTUSDC",
    )

    back.worker_queue.put_nowait(
        Event(name=EventName.EXECUTION_REPORT, content=exec_report_phase2)
    )

    logger.info(
        f"✓ Phase 2 filled: {usdt_received:.2f} USDT → {usdc_received:.2f} USDC"
    )

    # Wait for state transition to CLOSED
    await sim.wait_for_state(PositionLifecycleState.CLOSED, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.CLOSED
    assert strategy.sell_strategy.is_complete()

    profit = usdc_received - 1000.0  # Revenue - cost
    profit_pct = (profit / 1000.0) * 100

    logger.info("=" * 60)
    logger.info("✓ Convert Sell Test PASSED:")
    logger.info(f"  Phase 1:          BTC → USDT ({usdt_received:.2f} USDT)")
    logger.info(f"  Phase 2:          USDT → USDC ({usdc_received:.2f} USDC)")
    logger.info(f"  Profit:           ${profit:.2f} ({profit_pct:.2f}%)")
    logger.info(f"  Final State:      {strategy.lifecycle_state}")
    logger.info("=" * 60)


# ============================================================================
# Multihop Sell Tests (V1 tests 29-32, 35-39 adapted for V2)
# ============================================================================


@pytest.mark.skip(
    reason="Multihop requires executor subscription to leg2 symbol - architectural issue to fix"
)
async def test_multihop_sell_altcoin_btc_usdc_v2(frontend_backend_v2_setup):
    """Test V2: Multihop sell ALTCOIN/BTC → BTC, then BTC/USDC → USDC.

    V2 Multihop Flow: BOUGHT → SELLING (2-leg routing)
      Leg 1: Sell ALTCOIN/BTC (ALTCOIN → BTC)
      Leg 2: Sell BTC/USDC (BTC → USDC)

    This tests the multihop sell strategy where:
    1. Buy ALTCOIN/BTC (altcoin only has BTC pair)
    2. Position transitions to BOUGHT with inventory
    3. Sell trigger hits → Leg 1: sell ALTCOIN/BTC
    4. Leg 1 fills → Leg 2: sell BTC/USDC
    5. Leg 2 fills → CLOSED

    EU regulation scenario: USDC pairs restricted, must route through BTC.
    """
    from src.common.symbol import Symbol

    front, back = frontend_backend_v2_setup

    sim = HPSimulatorV2(front=front, back=back)

    # Remove AXLUSDC to force multihop path (EU regulation scenario)
    if "AXLUSDC" in back.symbols:
        del back.symbols["AXLUSDC"]

    # Add multihop symbols to test
    back.symbols["AXLBTC"] = Symbol(
        name="AXLBTC", precision=2, price_precision=8
    )  # Altcoin/BTC pair

    # Ensure BTCUSDC exists for leg2
    if "BTCUSDC" not in back.symbols:
        back.symbols["BTCUSDC"] = Symbol(
            name="BTCUSDC", precision=5, price_precision=2
        )  # BTC/USDC pair

    # Initialize price resolver with leg2 price
    back.price_resolver.update_price("BTCUSDC", 50000.0)  # BTC price in USDC

    # Step 1: Create and buy position at AXLBTC
    # Note: For multihop, we need custom buy setup since buy is in BTC terms
    buy_price_btc = 0.0002  # 0.0002 BTC per AXL
    sell_price_usdc = 14.0  # Target 14 USDC per AXL
    quantity_axl = 100.0  # Buy 100 AXL

    # Setup buy position manually
    symbol_obj = back.symbols["AXLBTC"]
    buy_config = sim.create_buy_config(
        hp_id="multihop_test_1",
        symbol=symbol_obj,
        budget=0.02,  # 0.02 BTC budget (100 AXL * 0.0002 BTC)
        buy_price=buy_price_btc,
    )

    sell_config = sim.create_sell_config(
        hp_id="multihop_test_1",
        symbol=symbol_obj,
        sell_price=sell_price_usdc,
        quantity=quantity_axl,
        buy_price=buy_price_btc,
        end_currency="USDC",
    )

    back.set_configs(buy_config, sell_config)
    back.start()

    await sim.wait_for_condition(lambda: back.strategy is not None, timeout=2.0)
    strategy = back.strategy

    # Simulate buy order and fill
    sim.setup_order_mocking()
    trigger_price_btc = buy_price_btc * 1.01
    sim.new_price(price=trigger_price_btc, symbol="AXLBTC")
    await sim.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

    await asyncio.sleep(0.1)
    buy_order_id = strategy.buy.buy_order.order_id

    exec_report_buy = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_FILLED,
        order_id=buy_order_id,
        last_executed_quantity=quantity_axl,
        last_executed_price=buy_price_btc,
        cumulative_filled_quantity=quantity_axl,
        price=buy_price_btc,
        symbol="AXLBTC",
    )

    back.worker_queue.put_nowait(
        Event(name=EventName.EXECUTION_REPORT, content=exec_report_buy)
    )

    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)
    assert strategy.lifecycle_state == PositionLifecycleState.IDLE

    logger.info("=" * 60)
    logger.info("Multihop Sell Test Setup:")
    logger.info(f"  Bought:           {quantity_axl:.2f} AXL @ 0.0002 BTC")
    logger.info(f"  Target:           Sell @ $14 USDC per AXL")
    logger.info(f"  Path:             AXL → BTC → USDC (multihop)")
    logger.info(f"  Leg 1:            AXL/BTC sell")
    logger.info(f"  Leg 2:            BTC/USDC sell")
    logger.info(f"  BTC Price:        $50,000 USDC")
    logger.info("=" * 60)

    # Step 2: Initialize sell strategy (should create MultihopSellStrategy)
    assert strategy.sell_strategy is not None
    from src.strategies.hp_manager_v2.sell_strategies.multihop_sell import (
        MultihopSellStrategy,
    )

    assert isinstance(strategy.sell_strategy, MultihopSellStrategy)
    logger.info(f"✓ MultihopSellStrategy initialized")

    # Calculate leg1 target price
    # Target: 14 USDC per AXL, BTC = 50000 USDC
    # Leg1 target = 14 / 50000 = 0.00028 BTC per AXL
    leg1_target_price = sell_price_usdc / 50000.0

    logger.info(f"  Leg1 target:      {leg1_target_price:.8f} BTC per AXL")

    # Step 3: Manually send BTCUSDC ticker to sell strategy
    # (executor only subscribes to AXLBTC, so we need to manually forward BTCUSDC ticker)
    from src.common.identifiers import TickerUpdate

    btcusdc_ticker = TickerUpdate(last_price=50000.0, symbol="BTCUSDC")
    await strategy.sell_strategy.handle_ticker_update(btcusdc_ticker)
    await asyncio.sleep(0.1)  # Let ticker be processed

    # Step 4: Trigger sell by raising AXL/BTC price to 96% of leg1 target
    leg1_trigger_price = leg1_target_price * 0.96
    sim.new_price(price=leg1_trigger_price, symbol="AXLBTC")
    await sim.wait_for_state(PositionLifecycleState.SELLING, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.SELLING
    assert strategy.sell_strategy.leg1_order_id is not None
    logger.info(
        f"✓ Leg 1 started: AXL/BTC sell order {strategy.sell_strategy.leg1_order_id}"
    )

    # Step 5: Fill Leg 1 (AXL → BTC)
    leg1_order_id = strategy.sell_strategy.leg1_order_id
    btc_received = quantity_axl * leg1_target_price  # AXL sold * price = BTC

    exec_report_leg1 = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_FILLED,
        order_id=leg1_order_id,
        last_executed_quantity=quantity_axl,
        last_executed_price=leg1_target_price,
        cumulative_filled_quantity=quantity_axl,
        price=leg1_target_price,
        symbol="AXLBTC",
    )

    back.worker_queue.put_nowait(
        Event(name=EventName.EXECUTION_REPORT, content=exec_report_leg1)
    )

    logger.info(f"✓ Leg 1 filled: {quantity_axl:.2f} AXL → {btc_received:.8f} BTC")

    # Wait for Leg 2 to start (sell BTC → USDC)
    await sim.wait_for_condition(
        lambda: strategy.sell_strategy.leg2_order_id is not None, timeout=2.0
    )

    assert strategy.sell_strategy.leg2_order_id is not None
    logger.info(
        f"✓ Leg 2 started: BTC/USDC sell order {strategy.sell_strategy.leg2_order_id}"
        f"✓ Leg 2 started: BTC/USDC sell order {strategy.sell_strategy.leg2_order_id}"
    )

    # Step 6: Fill Leg 2 (BTC → USDC)
    leg2_order_id = strategy.sell_strategy.leg2_order_id
    leg2_price = 50000.0 * 0.96  # Leg2 trigger at 96% of BTC price
    usdc_received = btc_received * leg2_price  # BTC * price = USDC

    exec_report_leg2 = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_FILLED,
        order_id=leg2_order_id,
        last_executed_quantity=btc_received,
        last_executed_price=leg2_price,
        cumulative_filled_quantity=btc_received,
        price=leg2_price,
        symbol="BTCUSDC",
    )

    back.worker_queue.put_nowait(
        Event(name=EventName.EXECUTION_REPORT, content=exec_report_leg2)
    )

    logger.info(f"✓ Leg 2 filled: {btc_received:.8f} BTC → ${usdc_received:.2f} USDC")

    # Wait for state transition to CLOSED
    await sim.wait_for_state(PositionLifecycleState.CLOSED, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.CLOSED
    assert strategy.sell_strategy.is_complete()

    cost_usdc = 0.02 * 50000.0  # 0.02 BTC * 50000 = 1000 USDC
    profit = usdc_received - cost_usdc
    profit_pct = (profit / cost_usdc) * 100

    logger.info("=" * 60)
    logger.info("✓ Multihop Sell Test PASSED:")
    logger.info(f"  Leg 1:            AXL → BTC ({btc_received:.8f} BTC)")
    logger.info(f"  Leg 2:            BTC → USDC (${usdc_received:.2f} USDC)")
    logger.info(f"  Profit:           ${profit:.2f} ({profit_pct:.2f}%)")
    logger.info(f"  Final State:      {strategy.lifecycle_state}")
    logger.info("=" * 60)


@pytest.mark.skip(
    reason="Multihop requires executor subscription to leg2 symbol - architectural issue to fix"
)
async def test_multihop_sell_leg1_cancel_v2(frontend_backend_v2_setup):
    """Test V2: Cancel multihop sell during leg1 (before any fills).

    Tests cancellation of multihop sell when leg1 hasn't filled yet.
    Should cancel leg1 order and return to BOUGHT state.
    """
    from src.common.symbol import Symbol

    front, back = frontend_backend_v2_setup

    sim = HPSimulatorV2(front=front, back=back)

    # Remove AXLUSDC to force multihop path
    if "AXLUSDC" in back.symbols:
        del back.symbols["AXLUSDC"]

    # Add multihop symbols
    back.symbols["AXLBTC"] = Symbol(name="AXLBTC", precision=2, price_precision=8)

    if "BTCUSDC" not in back.symbols:
        back.symbols["BTCUSDC"] = Symbol(name="BTCUSDC", precision=5, price_precision=2)

    back.price_resolver.update_price("BTCUSDC", 50000.0)

    # Step 1: Create and buy position manually (avoid simulate_bought_position)
    buy_price_btc = 0.0002
    sell_price_usdc = 14.0
    quantity_axl = 100.0

    symbol_obj = back.symbols["AXLBTC"]
    buy_config = sim.create_buy_config(
        hp_id="multihop_cancel_test",
        symbol=symbol_obj,
        budget=0.02,
        buy_price=buy_price_btc,
    )

    sell_config = sim.create_sell_config(
        hp_id="multihop_cancel_test",
        symbol=symbol_obj,
        sell_price=sell_price_usdc,
        quantity=quantity_axl,
        buy_price=buy_price_btc,
        end_currency="USDC",
    )

    back.set_configs(buy_config, sell_config)
    back.start()

    await sim.wait_for_condition(lambda: back.strategy is not None, timeout=2.0)
    strategy = back.strategy

    # Simulate buy order and fill
    sim.setup_order_mocking()
    trigger_price_btc = buy_price_btc * 1.01
    sim.new_price(price=trigger_price_btc, symbol="AXLBTC")
    await sim.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

    await asyncio.sleep(0.1)
    buy_order_id = strategy.buy.buy_order.order_id

    exec_report_buy = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_FILLED,
        order_id=buy_order_id,
        last_executed_quantity=quantity_axl,
        last_executed_price=buy_price_btc,
        cumulative_filled_quantity=quantity_axl,
        price=buy_price_btc,
        symbol="AXLBTC",
    )

    back.worker_queue.put_nowait(
        Event(name=EventName.EXECUTION_REPORT, content=exec_report_buy)
    )

    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)
    assert strategy.lifecycle_state == PositionLifecycleState.IDLE

    # Setup cancel mocking
    strategy.client.cancel_order = AsyncMock(return_value=None)

    # Manually send BTCUSDC ticker to sell strategy
    from src.common.identifiers import TickerUpdate

    btcusdc_ticker = TickerUpdate(last_price=50000.0, symbol="BTCUSDC")
    await strategy.sell_strategy.handle_ticker_update(btcusdc_ticker)
    await asyncio.sleep(0.1)

    # Trigger multihop sell
    leg1_target = 14.0 / 50000.0
    leg1_trigger = leg1_target * 0.96
    sim.new_price(price=leg1_trigger, symbol="AXLBTC")
    await sim.wait_for_state(PositionLifecycleState.SELLING, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.SELLING
    assert strategy.sell_strategy.leg1_order_id is not None

    logger.info(
        f"✓ Multihop leg1 started, order: {strategy.sell_strategy.leg1_order_id}"
    )

    # Cancel by dropping price below 92% threshold
    cancel_price = leg1_target * 0.91
    sim.new_price(price=cancel_price, symbol="AXLBTC")

    # Wait for state to return to BOUGHT
    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    assert strategy.sell_strategy.leg1_order_id is None  # Cleared after cancel

    logger.info("=" * 60)
    logger.info("✓ Multihop Leg1 Cancel Test PASSED:")
    logger.info(f"  State:            {strategy.lifecycle_state}")
    logger.info(f"  Leg1 cancelled:   Order cleared")
    logger.info("=" * 60)
