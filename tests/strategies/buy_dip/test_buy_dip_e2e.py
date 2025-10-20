"""End-to-End Tests for Buy Dip Strategy.

Tests complete lifecycle scenarios:
- Single position: rising → top → DCA → sell
- Top invalidation before confirmation
- Multiple concurrent positions
- Budget management across positions
- Order sequencing and cleanup
"""

import pytest
from tests.strategies.buy_dip.buy_dip_simulator import BuyDipSimulator


# ============================================================================
# SINGLE POSITION LIFECYCLE
# ============================================================================


async def test_perfect_position_lifecycle(buy_dip_strategy, mock_broker_buy_dip):
    """
    Test complete position lifecycle with perfect fills.

    CRITICAL: Only ONE pending order at a time!

    Scenario:
    1. BTC rises 67000 → 67890 (3 candles)
    2. Order 1 placed at $66,792.78 (φ = 1.618% below top) [ONLY 1 PENDING]
    3. Order 1 fills → position ACTIVE (top confirmed!)
    4. Order 2 placed at $66,046.50 (e = 2.718% below top) [ONLY 1 PENDING]
    5. Order 2 fills → avg entry updated
    6. Order 3 placed at $65,758.30 (π = 3.142% below top) [ONLY 1 PENDING]
    7. Order 3 fills → avg entry updated
    8. Price recovers to $67,890 (top)
    9. Sell fills at top → position CLOSED
    10. No pending orders remain
    """
    sim = BuyDipSimulator(buy_dip_strategy, mock_broker_buy_dip)

    # Rising pattern to top
    top_price = await sim.simulate_rising_to_top(
        start_price=67000, end_price=67890, num_candles=3
    )

    # Wait for potential top detection
    await sim.wait_for_potential_top(timeout=2.0)

    from src.strategies.buy_dip.position import PositionState
    from decimal import Decimal

    positions = sim.get_active_positions()
    assert len(positions) == 1
    position = positions[0]
    assert position.state == PositionState.POTENTIAL_TOP
    assert position.top_price == Decimal(str(top_price))

    # Order 1 should be placed BELOW top at φ distance
    # CRITICAL: Only ONE pending order!
    assert position.pending_order is not None, "Should have exactly ONE pending order"

    expected_order_1_price = top_price * (1 - 0.01618)  # φ = 1.618%
    assert abs(float(position.pending_order.price) - expected_order_1_price) < 1.0

    # Fill Order 1 (confirmation - price dipped to φ level!)
    await sim.fill_order(position.pending_order.order_id, expected_order_1_price)
    await sim.wait_for_active_position(timeout=2.0)

    # Position now ACTIVE (top confirmed)
    assert position.state == PositionState.ACTIVE
    assert position.total_invested > 0

    # Sell order should be at TOP price
    sell_order = position.sell_order
    assert sell_order is not None
    assert float(sell_order.price) == top_price

    # Order 2 should NOW be placed (sequential, triggered by Order 1 fill)
    # CRITICAL: Still only ONE pending order!
    await sim.wait_for_order_placed(position.position_id, timeout=2.0)
    assert (
        position.pending_order is not None
    ), "Should have exactly ONE pending order (Order 2)"

    order_2 = position.pending_order
    expected_price_2 = top_price * (1 - 0.02718)  # e = 2.718%
    assert abs(float(order_2.price) - expected_price_2) < 1.0

    # Fill Order 2
    await sim.fill_order(order_2.order_id, float(order_2.price))

    # Order 3 should NOW be placed (triggered by Order 2 fill)
    # CRITICAL: Still only ONE pending order!
    await sim.wait_for_order_placed(position.position_id, timeout=2.0)
    assert (
        position.pending_order is not None
    ), "Should have exactly ONE pending order (Order 3)"

    order_3 = position.pending_order
    expected_price_3 = top_price * (1 - 0.03142)  # π = 3.142%
    assert abs(float(order_3.price) - expected_price_3) < 1.0

    # Fill Order 3
    await sim.fill_order(order_3.order_id, float(order_3.price))

    # After Order 3 fills, no more orders (max DCA reached)
    # CRITICAL: Zero pending orders now
    assert position.pending_order is None, "Should have NO pending orders after max DCA"

    # Simulate recovery to TOP
    await sim.simulate_recovery(float(order_3.price), top_price, num_candles=2)

    # Wait for position to close
    await sim.wait_for_position_closed(position.position_id, timeout=2.0)

    # Verify position closed
    assert position.state == PositionState.COMPLETED
    # Note: Position doesn't track realized_pnl, only total_invested and average_entry
    assert position.pending_order is None


async def test_top_invalidation_before_confirmation(buy_dip_strategy, mock_broker_buy_dip):
    """
    Test top invalidation when new high detected before first order fills.

    Scenario:
    1. BTC rises to 67890 → Order 1 placed at $66,792.78 (φ below) - POTENTIAL_TOP
    2. BTC rises to 68100 (new high!)
    3. Order 1 cancelled
    4. New Order 1 placed at $66,998.22 (φ below new top)
    5. Position continues with new top
    """
    from src.strategies.buy_dip.position import PositionState
    from decimal import Decimal

    sim = BuyDipSimulator(buy_dip_strategy, mock_broker_buy_dip)

    # First top
    first_top = await sim.simulate_rising_to_top(67000, 67890)
    await sim.wait_for_potential_top()

    position = sim.get_active_positions()[0]
    first_order = position.pending_order
    first_order_id = first_order.order_id

    expected_first_price = first_top * (1 - 0.01618)

    assert position.state == PositionState.POTENTIAL_TOP
    assert abs(float(first_order.price) - expected_first_price) < 1.0

    # New higher top (invalidation!)
    second_top = await sim.simulate_rising_to_top(67890, 68100, num_candles=2)

    # Wait for order cancellation
    await sim.wait_for_no_pending_orders(position.position_id, timeout=2.0)

    # Wait for new order placement
    await sim.wait_for_order_placed(position.position_id, timeout=2.0)

    # Verify
    new_order = position.pending_order
    expected_new_price = second_top * (1 - 0.01618)  # φ below new top

    assert new_order.order_id != first_order_id  # Different order
    assert abs(float(new_order.price) - expected_new_price) < 1.0  # At φ below new top
    assert position.state == PositionState.POTENTIAL_TOP  # Still watching
    assert position.top_price == Decimal(str(second_top))  # Updated top


@pytest.mark.skip(reason="TDD: Implement BuyDipStrategy first")
async def test_sell_cancels_all_remaining_orders(buy_dip_strategy, mock_broker_buy_dip):
    """
    Test that selling cancels remaining buy order (if any).

    Scenario:
    1. Position ACTIVE with 2 orders filled
    2. Order 3 pending (only this one!)
    3. Sell fills at top
    4. Order 3 CANCELLED immediately
    5. Position CLOSED
    """
    sim = BuyDipSimulator(buy_dip_strategy, mock_broker_buy_dip)

    # Create active position
    top_price = await sim.simulate_rising_to_top(67000, 67890)
    await sim.wait_for_potential_top()

    position = sim.get_active_positions()[0]

    # Fill Order 1
    order_1 = position.pending_orders[0]
    assert len(position.pending_orders) == 1, "Should have exactly ONE pending order"
    await sim.fill_order(order_1.order_id, float(order_1.price))
    await sim.wait_for_active_position()

    # Order 2 should be placed
    await sim.wait_for_order_placed(position.position_id)
    order_2 = position.pending_orders[0]
    assert len(position.pending_orders) == 1, "Should have exactly ONE pending order"
    await sim.fill_order(order_2.order_id, float(order_2.price))

    # Order 3 should be placed
    await sim.wait_for_order_placed(position.position_id, timeout=2.0)
    assert (
        len(position.pending_orders) == 1
    ), "Should have exactly ONE pending order (Order 3)"
    order_3 = position.pending_orders[0]

    # Simulate recovery and sell
    await sim.simulate_recovery(float(order_2.price), top_price)

    # Wait for position closure
    await sim.wait_for_position_closed(position.position_id, timeout=2.0)

    # Verify Order 3 was cancelled
    assert len(position.pending_orders) == 0
    assert position.state == "COMPLETED"

    # Verify budget released
    initial_budget = sim.get_total_budget()
    assert sim.get_available_budget() > initial_budget * 0.95  # Most funds back


@pytest.mark.skip(reason="TDD: Implement BuyDipStrategy first")
async def test_only_one_pending_order_at_a_time(buy_dip_strategy, mock_broker_buy_dip):
    """
    Test CRITICAL constraint: Never have multiple pending buy orders.

    Scenario:
    1. Order 1 placed (1 pending)
    2. Order 1 fills → Order 2 placed (1 pending)
    3. Order 2 fills → Order 3 placed (1 pending)
    4. At NO point should we have 2+ pending buy orders
    """
    sim = BuyDipSimulator(buy_dip_strategy, mock_broker_buy_dip)

    top_price = await sim.simulate_rising_to_top(67000, 67890)
    await sim.wait_for_potential_top()

    position = sim.get_active_positions()[0]

    # Check Order 1 is only pending order
    assert len(position.pending_orders) == 1, "Step 1: Should have exactly 1 pending"

    # Fill Order 1
    order_1 = position.pending_orders[0]
    await sim.fill_order(order_1.order_id, float(order_1.price))
    await sim.wait_for_active_position()

    # Wait for Order 2, verify only 1 pending
    await sim.wait_for_order_placed(position.position_id)
    assert len(position.pending_orders) == 1, "Step 2: Should have exactly 1 pending"

    # Fill Order 2
    order_2 = position.pending_orders[0]
    await sim.fill_order(order_2.order_id, float(order_2.price))

    # Wait for Order 3, verify only 1 pending
    await sim.wait_for_order_placed(position.position_id)
    assert len(position.pending_orders) == 1, "Step 3: Should have exactly 1 pending"

    # Fill Order 3
    order_3 = position.pending_orders[0]
    await sim.fill_order(order_3.order_id, float(order_3.price))

    # After max DCA, should have 0 pending
    assert (
        len(position.pending_orders) == 0
    ), "Step 4: Should have 0 pending (max reached)"


# ============================================================================
# BUDGET MANAGEMENT
# ============================================================================


@pytest.mark.skip(reason="TDD: Implement BudgetManager first")
async def test_percentage_based_order_sizing(buy_dip_strategy, mock_broker_buy_dip):
    """
    Test that orders are sized as percentage of available budget.

    Config: 2% per order, $10,000 initial

    Expected:
    - Order 1: $10,000 × 2% = $200
    - Order 2: $9,800 × 2% = $196
    - Order 3: $9,604 × 2% = $192
    """
    sim = BuyDipSimulator(buy_dip_strategy, mock_broker_buy_dip)

    initial_budget = sim.get_available_budget()
    assert initial_budget == 10000

    # Create position
    await sim.simulate_rising_to_top(67000, 67890)
    await sim.wait_for_potential_top()

    position = sim.get_active_positions()[0]

    # Check Order 1 size
    order_1 = position.pending_orders[0]
    expected_size_1 = initial_budget * 0.02
    assert abs(float(order_1.quantity) * float(order_1.price) - expected_size_1) < 1

    # Fill and check budget
    await sim.fill_order(order_1.order_id, float(order_1.price))
    available_after_1 = sim.get_available_budget()
    assert abs(available_after_1 - (initial_budget - expected_size_1)) < 1

    # Check Order 2 size
    await sim.wait_for_order_placed(position.position_id)
    order_2 = position.pending_orders[0]
    expected_size_2 = available_after_1 * 0.02
    assert abs(float(order_2.quantity) * float(order_2.price) - expected_size_2) < 1

    # Fill and check budget
    await sim.fill_order(order_2.order_id, float(order_2.price))
    available_after_2 = sim.get_available_budget()
    assert abs(available_after_2 - (available_after_1 - expected_size_2)) < 1


@pytest.mark.skip(reason="TDD: Implement BudgetManager first")
async def test_budget_released_on_position_close(buy_dip_strategy, mock_broker_buy_dip):
    """
    Test that closing position releases all locked funds plus profit.

    Expected flow:
    1. Lock $588 across 3 orders
    2. Position closes with +$100 profit
    3. Available budget = initial - 588 + 688 = initial + 100
    """
    sim = BuyDipSimulator(buy_dip_strategy, mock_broker_buy_dip)

    initial_budget = sim.get_available_budget()

    # Run complete position
    result = await sim.simulate_perfect_position(
        start_price=67000, top_price=67890, dca_levels=2
    )

    # Check budget after closure
    final_budget = sim.get_available_budget()

    # Should have initial + profit
    assert final_budget > initial_budget
    assert abs(final_budget - (initial_budget + result["realized_pnl"])) < 1


@pytest.mark.skip(reason="TDD: Implement BudgetManager first")
async def test_cancelled_orders_release_funds_immediately(
    buy_dip_strategy, mock_broker
):
    """
    Test that cancelled orders release locked funds immediately.

    Scenario:
    1. Order 1 placed at 67890, locks $200
    2. New top at 68100, Order 1 cancelled
    3. $200 immediately available
    4. New order placed with recalculated size
    """
    sim = BuyDipSimulator(buy_dip_strategy, mock_broker_buy_dip)

    initial_budget = sim.get_available_budget()

    # First top
    await sim.simulate_rising_to_top(67000, 67890)
    await sim.wait_for_potential_top()

    position = sim.get_active_positions()[0]
    order_1 = position.pending_orders[0]
    order_1_size = float(order_1.quantity) * float(order_1.price)

    # Budget should be locked
    budget_after_order = sim.get_available_budget()
    assert abs(budget_after_order - (initial_budget - order_1_size)) < 1

    # Invalidate top
    await sim.simulate_rising_to_top(67890, 68100, num_candles=2)
    await sim.wait_for_no_pending_orders(position.position_id)

    # Budget should be released
    budget_after_cancel = sim.get_available_budget()
    assert abs(budget_after_cancel - initial_budget) < 1  # Back to initial


# ============================================================================
# MULTIPLE CONCURRENT POSITIONS
# ============================================================================


@pytest.mark.skip(reason="TDD: Implement BuyDipStrategy first")
async def test_multiple_concurrent_positions(buy_dip_strategy, mock_broker_buy_dip):
    """
    Test multiple positions running simultaneously with shared budget.

    Scenario:
    1. Position A: BTC 67000 → 67890
    2. Position B: ETH 3200 → 3280 (different symbol)
    3. Both active simultaneously
    4. Budget shared across both
    5. Both close successfully
    """
    sim = BuyDipSimulator(buy_dip_strategy, mock_broker_buy_dip)

    initial_budget = sim.get_available_budget()

    # Start Position A (BTC)
    await sim.simulate_rising_to_top(67000, 67890, num_candles=3)
    await sim.wait_for_potential_top()

    positions = sim.get_active_positions()
    assert len(positions) == 1
    position_a = positions[0]

    # Fill Order 1 for Position A
    order_a1 = position_a.pending_orders[0]
    await sim.fill_order(order_a1.order_id, float(order_a1.price))

    # Start Position B (ETH) - would require multi-symbol support
    # This test verifies the architecture supports it
    # For now, test with second BTC position after first completes

    # Complete Position A
    await sim.wait_for_order_placed(position_a.position_id)
    order_a2 = position_a.pending_orders[0]
    await sim.fill_order(order_a2.order_id, float(order_a2.price))

    await sim.simulate_recovery(float(order_a2.price), 67890)
    await sim.wait_for_position_closed(position_a.position_id)

    # Start Position B (new BTC cycle)
    await sim.simulate_rising_to_top(67890, 68200, num_candles=3)
    await sim.wait_for_potential_top()

    positions = sim.get_active_positions()
    assert len(positions) == 1  # Position A closed, B active
    position_b = positions[0]
    assert position_b.position_id != position_a.position_id

    # Verify budget accounting
    total_locked = sim.get_locked_budget()
    total_available = sim.get_available_budget()
    assert total_locked + total_available > initial_budget * 0.95  # Accounting sound


@pytest.mark.skip(reason="TDD: Implement BuyDipStrategy first")
async def test_insufficient_funds_graceful_wait(buy_dip_strategy, mock_broker_buy_dip):
    """
    Test graceful handling when budget exhausted.

    Scenario:
    1. Drain budget to $5 available
    2. Min order size = $10
    3. New top detected
    4. Strategy logs warning, doesn't place order
    5. Position closes, funds available
    6. Next top detected, order placed successfully
    """
    sim = BuyDipSimulator(buy_dip_strategy, mock_broker_buy_dip)

    # Drain budget (would need budget manipulation method)
    # For now, test the concept

    # Simulate many positions to exhaust budget
    for i in range(50):  # 50 positions × 2% = 100% budget
        await sim.simulate_rising_to_top(67000 + i * 100, 67890 + i * 100)
        await sim.wait_for_potential_top()
        position = sim.get_active_positions()[-1]
        order = position.pending_orders[0]
        await sim.fill_order(order.order_id, float(order.price))

    # At this point, budget should be nearly exhausted
    available = sim.get_available_budget()
    assert available < 100  # Very little left

    # Try to create new position
    await sim.simulate_rising_to_top(72000, 72890)

    # Should not crash, just log warning
    # Position might not be created if budget too low
    # This tests graceful degradation


# ============================================================================
# EDGE CASES
# ============================================================================


@pytest.mark.skip(reason="TDD: Implement BuyDipStrategy first")
async def test_rapid_invalidations(buy_dip_strategy, mock_broker_buy_dip):
    """
    Test multiple rapid top invalidations.

    Scenario:
    1. Top at 67890
    2. Top at 68000 (invalidate)
    3. Top at 68100 (invalidate)
    4. Top at 68200 (invalidate)
    5. Finally confirms at 68200
    """
    sim = BuyDipSimulator(buy_dip_strategy, mock_broker_buy_dip)

    tops = [67890, 68000, 68100, 68200]

    for i, top in enumerate(tops):
        if i == 0:
            await sim.simulate_rising_to_top(67000, top)
        else:
            await sim.simulate_rising_to_top(tops[i - 1], top, num_candles=1)

        await sim.wait_for_potential_top()

        position = sim.get_active_positions()[0]
        assert position.top_price == top
        assert len(position.pending_orders) == 1
        assert float(position.pending_orders[0].price) == top

    # Confirm final top
    final_order = position.pending_orders[0]
    await sim.fill_order(final_order.order_id, tops[-1])
    await sim.wait_for_active_position()

    assert position.state == "ACTIVE"
    assert position.top_price == tops[-1]


@pytest.mark.skip(reason="TDD: Implement BuyDipStrategy first")
async def test_sell_crosses_top_not_invalidation(buy_dip_strategy, mock_broker_buy_dip):
    """
    Test that sell crossing top doesn't trigger new top detection.

    Scenario:
    1. Position ACTIVE, top at 67890
    2. Orders filled at lower prices
    3. Sell executes at 67890 (price crosses top)
    4. Should NOT treat as new top
    5. Should close position and cancel orders
    """
    sim = BuyDipSimulator(buy_dip_strategy, mock_broker_buy_dip)

    # Create active position
    top_price = await sim.simulate_rising_to_top(67000, 67890)
    await sim.wait_for_potential_top()

    position = sim.get_active_positions()[0]

    # Fill first order
    order_1 = position.pending_orders[0]
    await sim.fill_order(order_1.order_id, top_price)
    await sim.wait_for_active_position()

    # Fill second order
    await sim.wait_for_order_placed(position.position_id)
    order_2 = position.pending_orders[0]
    await sim.fill_order(order_2.order_id, float(order_2.price))

    # Third order pending
    await sim.wait_for_order_placed(position.position_id)
    order_3 = position.pending_orders[0]

    # Price recovers to top (sell executes)
    await sim.simulate_recovery(float(order_2.price), top_price)
    await sim.wait_for_position_closed(position.position_id)

    # Verify position closed, not new top detected
    assert position.state == "COMPLETED"
    assert len(position.pending_orders) == 0  # Order 3 cancelled

    # Verify no new position created
    active_positions = sim.get_active_positions()
    assert len(active_positions) == 0
