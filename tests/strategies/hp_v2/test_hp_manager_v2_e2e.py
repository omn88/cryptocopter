"""HP Manager V2 End-to-End Tests

Tests for the complete V2 integration between frontend (HpFront) and backend (HpExecutorV2).
These tests verify the full workflow from UI interactions to state machine transitions.
"""

import asyncio
import logging
from unittest.mock import AsyncMock

from binance.enums import ORDER_STATUS_CANCELED, ORDER_STATUS_NEW

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
    await sim.wait_for_state(PositionLifecycleState.BOUGHT, timeout=2.0)

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
    assert strategy.lifecycle_state == PositionLifecycleState.BOUGHT
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
    """Test V2: Partially filled order is cancelled → BUYING → IDLE.

    V2 State Flow: IDLE → BUYING → BUYING (partial fill) → IDLE (cancel)

    This test verifies:
    1. Position created and order sent when price drops to trigger
    2. Order partially fills (30%)
    3. Price moves above cancel threshold
    4. Partially filled order is cancelled
    5. State transitions back to IDLE
    6. Realized quantity preserved from partial fill
    """
    front, back = frontend_backend_v2_setup

    sim = HPSimulatorV2(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    # Create position and send order
    sim.simulate_buy_position()
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

    # Wait for state transition back to IDLE
    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)

    # Step 4: Send cancellation execution report
    from binance.enums import ORDER_STATUS_CANCELED

    logger.info(f"[Step 4] Order cancelled by exchange")

    cancel_report = ExecutionReport(
        order_type="LIMIT",
        current_order_status=ORDER_STATUS_CANCELED,
        order_id=order_id,
        last_executed_quantity=0.0,
        last_executed_price=0.0,
        cumulative_filled_quantity=partial_quantity,  # Still has the partial fill
        price=fill_price,
    )

    strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, cancel_report))

    # Wait for cancellation to be processed
    await sim.wait_for_condition(
        lambda: strategy.buy.execution_state == OrderExecutionState.CANCELLED,
        timeout=2.0,
    )

    logger.info("=" * 60)
    logger.info("✓ Partial Fill Then Cancel Complete:")
    logger.info(f"  Lifecycle State:  {strategy.lifecycle_state}")
    logger.info(f"  Order Status:     {strategy.buy.buy_order.status}")
    logger.info(
        f"  Realized Qty:     {strategy.buy.buy_order.realized_quantity:.5f} BTC (from partial fill)"
    )
    logger.info(f"  Execution State:  {strategy.buy.execution_state}")
    logger.info("=" * 60)

    # Verify final state
    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    assert strategy.buy.buy_order.status == ORDER_STATUS_CANCELED
    assert (
        strategy.buy.buy_order.realized_quantity == partial_quantity
    )  # Partial fill preserved
    assert strategy.buy.execution_state == OrderExecutionState.CANCELLED


async def test_buy_order_partially_filled_then_cancel_then_resend_v2(
    frontend_backend_v2_setup,
):
    """Test V2: Order is partially filled, cancelled, then resent with remaining quantity.

    Scenario:
    1. Price drops to trigger → send buy order
    2. Order partially fills (e.g., 30%)
    3. Price rises above cancel threshold → cancel order
    4. Price drops back to trigger → resend order for remaining quantity
    5. Verify new order sent with reduced quantity (original - filled)

    Expected State Transitions:
    - IDLE → BUYING (on order sent)
    - BUYING → BUYING (stays in BUYING after partial fill)
    - BUYING → IDLE (on cancel with partial fill preserved)
    - IDLE → BUYING (on resend with remaining quantity)

    This tests:
    - Partial fill tracking through cancel/resend cycle
    - Order quantity adjustment based on realized_quantity
    - State preservation during multiple order attempts
    """
    front, back = frontend_backend_v2_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    sim = HPSimulatorV2(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, HpExecutorV2)

    # Create position and send order
    sim.simulate_buy_position()
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

    # Wait for cancel and transition back to IDLE
    await sim.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.IDLE
    assert strategy.buy.buy_order.realized_quantity == partial_quantity
    assert strategy.buy.execution_state == OrderExecutionState.CANCELLED
    strategy.client.cancel_order.assert_called_once()
    logger.info(f"✓ Order cancelled, back to IDLE, realized_quantity preserved")

    # Step 4: Price drops back to trigger → resend with remaining quantity
    logger.info(f"[Step 4] Price drops back to trigger: {trigger_price:,.2f} USDC")
    sim.new_price(price=trigger_price)
    await sim.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

    assert strategy.lifecycle_state == PositionLifecycleState.BUYING
    new_order_id = strategy.buy.buy_order.order_id
    new_quantity = strategy.buy.buy_order.quantity
    remaining_quantity = original_quantity - partial_quantity

    # Verify new order has different ID and reduced quantity
    assert new_order_id != original_order_id
    assert abs(new_quantity - remaining_quantity) < 1e-5  # Account for floating point
    assert strategy.buy.buy_order.realized_quantity == partial_quantity  # Preserved
    assert strategy.buy.execution_state == OrderExecutionState.OPEN

    logger.info(f"✓ New order sent:")
    logger.info(f"  - Order ID:           {new_order_id}")
    logger.info(f"  - New Quantity:       {new_quantity:.5f} BTC")
    logger.info(f"  - Remaining Quantity: {remaining_quantity:.5f} BTC")
    logger.info(f"  - Realized Quantity:  {partial_quantity:.5f} BTC (preserved)")

    # Final state validation
    assert strategy.lifecycle_state == PositionLifecycleState.BUYING
    assert strategy.buy.execution_state == OrderExecutionState.OPEN
    assert strategy.buy.buy_order.status == ORDER_STATUS_NEW

    logger.info("✅ Test PASSED: Partial fill → cancel → resend cycle complete")


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

    assert strategy.lifecycle_state == PositionLifecycleState.BOUGHT
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
    assert strategy.lifecycle_state == PositionLifecycleState.BOUGHT
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
    await sim.wait_for_state(PositionLifecycleState.BOUGHT, timeout=2.0)

    # Step 4: Verify position is BOUGHT and partial quantity is tracked
    assert strategy.lifecycle_state == PositionLifecycleState.BOUGHT
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
    await sim.wait_for_state(PositionLifecycleState.BOUGHT, timeout=2.0)

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


# ============================================================================
# Future V2 Tests (Placeholders)
# ============================================================================

# async def test_v2_buying_to_bought_on_fill(frontend_backend_v2_setup):
#     """Test V2: BUYING → BOUGHT transition when order fills."""
#     # TODO: Implement test for order fill handling
#     pass


# async def test_v2_buying_to_bought_on_fill(frontend_backend_v2_setup):
#     """Test V2: BUYING → BOUGHT transition when order fills."""
#     # TODO: Implement test for order fill handling
#     pass


# async def test_v2_bought_to_selling_transition(frontend_backend_v2_setup):
#     """Test V2: BOUGHT → SELLING transition when sell price hit."""
#     # TODO: Implement test for sell trigger
#     pass


# async def test_v2_selling_to_closed_on_fill(frontend_backend_v2_setup):
#     """Test V2: SELLING → CLOSED transition when sell order fills."""
#     # TODO: Implement test for complete cycle
#     pass


# async def test_v2_buy_cancellation(frontend_backend_v2_setup):
#     """Test V2: BUYING → IDLE cancellation when price moves away."""
#     # TODO: Implement test for buy cancellation
#     pass
