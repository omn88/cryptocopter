"""HP Manager V2 End-to-End Tests

Tests for the complete V2 integration between frontend (HpFront) and backend (HpExecutorV2).
These tests verify the full workflow from UI interactions to state machine transitions.
"""

import logging

from binance.enums import ORDER_STATUS_NEW

from src.common.identifiers import PositionLifecycleState
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

    # Mock order creation to return NEW order
    strategy = back.strategy
    strategy.client.create_order.side_effect = [
        get_new_order(order=strategy.buy.buy_order)
    ]

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
