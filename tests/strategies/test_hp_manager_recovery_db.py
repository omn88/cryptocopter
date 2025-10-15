import asyncio
import logging
from unittest.mock import AsyncMock


from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_CANCELED,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_PARTIALLY_FILLED,
)
from src.common.identifiers import Event, EventName, ExecutionReport, Order, State
from src.strategy_executor import StrategyExecutor
from src.gui.hp_manager.hpfront import HpFront
from tests.helpers import get_new_order
from tests.strategies.hp_manager_helpers import wait_for_condition
from tests.strategies.hp_simulator import HPSimulator


logger = logging.getLogger("hp_e2e_test")


async def test_recovery_buy_position(crash_recovery_factory):
    """Test crash recovery for a NEW position (no orders sent yet)."""
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)

    # Create default buy position (no orders sent)
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)
    await sim.assert_recovered_state(recovered, State.NEW, State.NEW, None)
    await sim.assert_db_state_matches_memory("1000")


async def test_recovery_buy_position_send_order(crash_recovery_factory):
    """Test crash recovery for a position in BUYING state with active orders."""
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)

    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()
    await sim.move_to_position_active_buy()

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)
    await sim.assert_recovered_state(
        recovered,
        State.BUYING,
        expected_buy_state=State.NEW,
        expected_order_status=ORDER_STATUS_NEW,
    )
    sim.assert_exchange_synced(recovered, min_calls=1)
    await sim.assert_db_state_matches_memory("1000")


async def test_recovery_cancel_buy_position_untouched(crash_recovery_factory):
    """Test crash recovery for a position with CANCELED orders."""
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)

    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()
    await sim.move_to_position_active_buy()
    await sim.cancel_buy_position_untouched()

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)
    await sim.assert_recovered_state(recovered, State.NEW, State.NEW, None)
    await sim.assert_db_state_matches_memory("1000")


async def test_recovery_cancel_buy_position_untouched_then_resend(
    crash_recovery_factory,
):
    """Test crash recovery for position cancelled untouched then orders resent."""
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)

    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()
    await sim.move_to_position_active_buy()
    await sim.cancel_buy_position_untouched()
    await sim.move_to_position_active_buy()

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)
    await sim.assert_recovered_state(
        recovered,
        State.BUYING,
        expected_buy_state=State.NEW,
        expected_order_status=ORDER_STATUS_NEW,
    )
    sim.assert_exchange_synced(recovered, min_calls=1)
    await sim.assert_db_state_matches_memory("1000")


async def test_recovery_buy_position_partial_fill(
    crash_recovery_factory,
):
    """Test crash recovery for partially filled order then auto-cancelled."""
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)

    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()
    await sim.move_to_position_active_buy()
    await sim.simulate_partial_fill()
    await sim.cancel_buy_position_after_order_partial_fill()

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)
    await sim.assert_recovered_state(
        recovered, State.PARTIALLY_BOUGHT, expected_buy_state=State.PARTIALLY_BOUGHT
    )
    await sim.assert_db_state_matches_memory("1000")


async def test_recovery_buy_position_partial_fill_then_cancel(
    crash_recovery_factory,
):
    """Test crash recovery for partially filled order that was then cancelled."""
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)

    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()
    await sim.move_to_position_active_buy()
    await sim.simulate_partial_fill()
    await sim.cancel_buy_position_after_order_partial_fill()

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)
    await sim.assert_recovered_state(
        recovered, State.PARTIALLY_BOUGHT, State.PARTIALLY_BOUGHT, None
    )
    await sim.assert_db_state_matches_memory("1000")


async def test_recovery_buy_position_bought(crash_recovery_factory):
    """Test crash recovery for fully bought position (all buy orders filled)."""
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)

    await sim.simulate_bought_position()

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)
    await sim.assert_recovered_state(
        recovered,
        State.BOUGHT,
        expected_buy_state=State.BOUGHT,
        expected_order_status=ORDER_STATUS_FILLED,
    )
    await sim.assert_db_state_matches_memory("1000")


async def test_recovery_buy_position_partial_fill_then_cancel_then_resend(
    crash_recovery_factory,
):
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    assert len(back.strategies) == 0

    # Path 0: Default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    # Path 1: Send buy orders
    await sim.move_to_position_active_buy()
    # Simulate partial fill
    strategy = await sim.simulate_partial_fill()

    # Cancel position
    assert strategy.buy.order_cancel_price == 1428.0
    sim.new_price(price=1428.0)
    assert isinstance(strategy.buy.buy_order, Order)
    await sim.assert_partially_bought_state(strategy, realized_qty=0.12)

    sim.validate_parent(
        quantity="0.12",
        state="PARTIALLY_BOUGHT",
        buy_price="1400.0",
        quantity_usd="168.0",
        sell_price="0.0",
        expected_return="0.0",
    )

    # Reopen position
    await sim.resend_buy_order_after_cancel(strategy, trigger_price=1414)
    logger.info("Orders after reopening: %s", strategy.buy.buy_order)
    await sim.assert_buying_state_with_partial(strategy, realized_qty=0.12)

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)

    await sim.assert_recovered_state(
        recovered, State.BUYING, expected_buy_state=State.PARTIALLY_BOUGHT
    )
    assert recovered.buy.buy_order.realized_quantity == 0.12


async def test_recovery_setup_sell_position_for_bought_position(crash_recovery_factory):
    """Test crash recovery for a BOUGHT position with sell setup."""
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)

    await sim.simulate_bought_position()
    await sim.setup_sell_position(
        "1000", "BTCUSDC", 0.71429, 1400.0, 4200.0, "USDC", "BTC"
    )

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)

    assert recovered.state == State.BOUGHT
    assert recovered.sell.current_position.sell_order.price == 4200.0
    await sim.assert_db_state_matches_memory("1000")


async def test_recovery_send_sell_order_for_bought_position(crash_recovery_factory):
    """Test crash recovery for bought position with sell order sent."""
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)

    await sim.simulate_bought_position()
    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.71429,
        buy_price=1400.0,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )
    await sim.send_sell_order_for_bought_position()

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)
    await sim.assert_recovered_state(
        recovered, State.SELLING, expected_order_status=ORDER_STATUS_NEW
    )
    await sim.assert_db_state_matches_memory("1000")


async def test_recovery_cancel_unfilled_sell_order(crash_recovery_factory):
    """Test crash recovery for cancelled sell orders."""
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)

    await sim.simulate_bought_position()
    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.71429,
        buy_price=1400.0,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )
    await sim.send_sell_order_for_bought_position()
    await sim.cancel_unfilled_sell_position()

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)
    await sim.assert_recovered_state(
        recovered, State.BOUGHT, expected_order_status=ORDER_STATUS_CANCELED
    )
    await sim.assert_db_state_matches_memory("1000")


async def test_recovery_resend_unfilled_sell_order(crash_recovery_factory):
    """Test crash recovery for resent sell orders after cancellation."""
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)

    await sim.simulate_bought_position()
    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.71429,
        buy_price=1400.0,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )
    await sim.send_sell_order_for_bought_position()
    await sim.cancel_unfilled_sell_position()
    await sim.send_sell_order_for_bought_position()

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)
    await sim.assert_recovered_state(
        recovered, State.SELLING, expected_order_status=ORDER_STATUS_NEW
    )
    await sim.assert_db_state_matches_memory("1000")


async def test_recovery_sell_position_partial_fill(
    crash_recovery_factory,
):
    """Test crash recovery for sell position with partially filled order."""
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)

    await sim.simulate_bought_position()
    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.71429,
        buy_price=1400.0,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )
    await sim.send_sell_order_for_bought_position()
    await sim.simulate_sell_order_partial_fill()

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)
    await sim.assert_recovered_state(
        recovered, State.SELLING, expected_order_status=ORDER_STATUS_PARTIALLY_FILLED
    )
    await sim.assert_db_state_matches_memory("1000")


async def test_recovery_cancel_sell_position_after_partial_fill(
    crash_recovery_factory,
):
    """Test crash recovery for cancelled partially filled sell order."""
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)

    await sim.simulate_bought_position()
    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.71429,
        buy_price=1400.0,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )
    await sim.send_sell_order_for_bought_position()
    await sim.simulate_sell_order_partial_fill()
    await sim.cancel_partially_sold_position()

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)
    await sim.assert_recovered_state(
        recovered, State.SELLING, expected_order_status=ORDER_STATUS_CANCELED
    )
    await sim.assert_db_state_matches_memory("1000")


async def test_recovery_resend_sell_position_after_partial_fill(
    crash_recovery_factory,
):
    """Test crash recovery for resent partially filled sell order."""
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)

    await sim.simulate_bought_position()
    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.71429,
        buy_price=1400.0,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )
    await sim.send_sell_order_for_bought_position()
    await sim.simulate_sell_order_partial_fill()
    await sim.cancel_partially_sold_position()
    await sim.resend_sell_order_for_partially_sold_position()

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)
    await sim.assert_recovered_state(
        recovered, State.SELLING, expected_order_status=ORDER_STATUS_NEW
    )
    await sim.assert_db_state_matches_memory("1000")


async def test_recovery_send_sell_order_for_partially_bought_position(
    crash_recovery_factory,
):
    """Test crash recovery for sell order on partially bought position."""
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)

    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()
    await sim.move_to_position_active_buy()
    strategy = await sim.simulate_partial_fill()
    await sim.cancel_buy_position_after_order_partial_fill()
    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )
    await sim.send_sell_order_for_part_bought_position()

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)
    await sim.assert_recovered_state(
        recovered, State.SELLING, expected_order_status=ORDER_STATUS_NEW
    )
    await sim.assert_db_state_matches_memory("1000")


async def test_recovery_cancel_unfilled_sell_order_for_partially_bought_position(
    crash_recovery_factory,
):
    """Test crash recovery for cancelled sell order on partially bought position."""
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)

    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()
    await sim.move_to_position_active_buy()
    strategy = await sim.simulate_partial_fill()
    await sim.cancel_buy_position_after_order_partial_fill()
    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )
    await sim.send_sell_order_for_part_bought_position()
    await sim.cancel_unfilled_sell_position_from_part_filled_buy()

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)
    await sim.assert_recovered_state(
        recovered, State.PARTIALLY_BOUGHT, expected_order_status=ORDER_STATUS_CANCELED
    )
    await sim.assert_db_state_matches_memory("1000")


async def test_recovery_fill_orders_for_previously_partially_bought_position(
    crash_recovery_factory,
):
    """
    Refactored: Fill remaining buy orders for a previously partially bought position, with crash recovery.
    """
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_partial_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_order_partial_fill()

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()
    await sim.cancel_unfilled_sell_position_from_part_filled_buy()

    # Price trigger is now related to the middle order as the top order is already filled.
    await sim.resend_buy_order_after_cancel(strategy, trigger_price=1412)
    await sim.assert_buying_state_with_partial(strategy, realized_qty=0.12)

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)

    await sim.assert_recovered_state(
        recovered, State.BUYING, expected_buy_state=State.PARTIALLY_BOUGHT
    )
    assert recovered.buy.buy_order.realized_quantity == 0.12
    await sim.assert_db_state_matches_memory()


async def test_recovery_sell_partially_partially_bought_position(
    crash_recovery_factory,
):
    """
    Test selling a partially bought position, with crash recovery.
    """
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_partial_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_order_partial_fill()

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()

    await sim.simulate_sell_order_partial_fill_from_part_bought()

    # Assert state before crash
    strategy = back.strategies["1000"]
    await sim.assert_sell_order_state(
        strategy, ORDER_STATUS_PARTIALLY_FILLED, realized_qty=0.06
    )
    await sim.assert_buy_order_state(strategy, ORDER_STATUS_CANCELED, realized_qty=0.12)

    # Crash and recover
    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)

    # Assert recovered state
    await sim.assert_sell_order_state(
        recovered, ORDER_STATUS_PARTIALLY_FILLED, realized_qty=0.06
    )
    await sim.assert_buy_order_state(
        recovered, ORDER_STATUS_CANCELED, realized_qty=0.12
    )
    await sim.assert_db_state_matches_memory()


async def test_recovery_buy_partially_partially_sold_position(crash_recovery_factory):
    """
    Test reopening buy after partially selling a partially bought position, with crash recovery.
    """
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_partial_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_order_partial_fill()

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()

    await sim.simulate_sell_order_partial_fill_from_part_bought()

    # Cancel Sell position
    await sim.cancel_sell_position_filled_partially()
    await sim.assert_part_sold_part_bought_state(strategy, realized_qty=0.06)

    # Reopen Buy position
    await sim.resend_buy_order_after_cancel(strategy, trigger_price=1412)
    await sim.assert_buying_state_with_partial(strategy, realized_qty=0.12)

    strategy.client.create_order.side_effect = [
        get_new_order(order=strategy.buy.buy_order)
    ]
    sim.new_price(price=1410.0)

    # Assert new opened position data
    await wait_for_condition(condition_func=lambda: strategy.state == State.BUYING)

    # Verify the reopened order is in NEW status
    assert strategy.buy.buy_order.status == ORDER_STATUS_NEW
    assert (
        strategy.buy.buy_order.realized_quantity == 0.12
    )  # Carries forward from previous order

    # Simulate first buy order fill on the reopened order
    # Parent realized_quantity should be 0.06 (the amount that was sold from the original partially bought position)
    strategy = await sim.simulate_partial_fill(last=0.14, cumulative=0.26, sold=0.06)

    await wait_for_condition(
        condition_func=lambda: strategy.buy.buy_order.realized_quantity == 0.26
    )

    assert strategy.buy.buy_order.status == ORDER_STATUS_PARTIALLY_FILLED
    assert strategy.buy.buy_order.realized_quantity == 0.26
    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT

    assert strategy.buy.order_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert strategy.buy.buy_order is not None

    assert strategy.buy.buy_order.status == ORDER_STATUS_PARTIALLY_FILLED

    # Wait for state transition to complete
    await wait_for_condition(
        condition_func=lambda: strategy.state == State.PART_SOLD_PART_BOUGHT
    )

    # Assert in-memory state before crash - single order system
    buy_order = strategy.buy.buy_order
    assert isinstance(buy_order, Order)
    # In single-order system, the order should be CANCELED with partial realized quantity
    assert buy_order.status == ORDER_STATUS_CANCELED
    assert buy_order.realized_quantity > 0.0

    # Ensure DB is updated before crash
    db_positions = await front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    db_orders = await front.db.get_orders_by_position_id(db_position.id)
    db_buy_orders = [o for o in db_orders if getattr(o.side, "value", o.side) == "BUY"]
    assert len(db_buy_orders) == 2
    db_filled = [o for o in db_buy_orders if o.status.value == ORDER_STATUS_FILLED]
    db_canceled = [o for o in db_buy_orders if o.status.value == ORDER_STATUS_CANCELED]
    db_partial = [
        o for o in db_buy_orders if o.status.value == ORDER_STATUS_PARTIALLY_FILLED
    ]
    assert len(db_filled) == 0
    assert len(db_canceled) == 2
    assert len(db_partial) == 0

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)

    # Single order system - verify recovered order
    recovered_buy_order = recovered.buy.buy_order
    assert isinstance(recovered_buy_order, Order)
    assert recovered_buy_order.status == ORDER_STATUS_CANCELED
    assert recovered_buy_order.realized_quantity > 0.0

    await sim.assert_db_state_matches_memory()


async def test_recovery_cancel_buy_to_part_sold_part_bought(crash_recovery_factory):
    """
    Test canceling buy after reopening from a part-sold/part-bought state, with crash recovery.
    """
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_partial_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_order_partial_fill()

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()

    await sim.simulate_sell_order_partial_fill_from_part_bought()

    # Cancel Sell position
    await sim.cancel_sell_position_filled_partially()

    # Reopen Buy position
    strategy.client.create_order.side_effect = [
        get_new_order(order=strategy.buy.buy_order)
    ]

    sim.new_price(price=1412)

    # Wait for state transition to BUYING
    await wait_for_condition(condition_func=lambda: strategy.state == State.BUYING)

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
    )

    # Buy partially second order
    await sim.simulate_partial_fill(last=0.14, cumulative=0.26, sold=0.06)

    assert strategy.buy.order_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    # Wait for buy order to be canceled with correct realized quantity
    await wait_for_condition(
        condition_func=lambda: strategy.buy.buy_order.status == ORDER_STATUS_CANCELED
    )
    await wait_for_condition(
        condition_func=lambda: strategy.buy.buy_order.realized_quantity == 0.26
    )

    # Give database extra time to complete the CANCELED status update before crash
    await asyncio.sleep(0.1)

    # Assert state before crash: both buy and sell orders canceled with partial fills
    await sim.assert_part_sold_part_bought_state(strategy, realized_qty=0.06)
    await sim.assert_buy_order_state(strategy, ORDER_STATUS_CANCELED, realized_qty=0.26)

    # Crash and recover
    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)

    # Assert recovered state
    await sim.assert_buy_order_state(
        recovered, ORDER_STATUS_CANCELED, realized_qty=0.26
    )
    await sim.assert_sell_order_state(
        recovered, ORDER_STATUS_CANCELED, realized_qty=0.06
    )
    await sim.assert_db_state_matches_memory()


async def test_recovery_buy_fully_partially_sold_position(crash_recovery_factory):
    """
    Test buying a fully partially sold position, with crash recovery.
    """
    create_pair, simulate_crash = crash_recovery_factory
    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    await sim.simulate_partial_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_order_partial_fill()

    # Setup sell position after first buy order filled
    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=sim.back.strategies["1000"].buy.calculate_realized_quantity(),
        buy_price=sim.back.strategies["1000"].buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )
    await sim.send_sell_order_for_part_bought_position()
    await sim.simulate_sell_order_partial_fill_from_part_bought()
    await sim.cancel_sell_position_filled_partially()

    # Reopen buy position and fill remaining quantity
    strategy = back.strategies["1000"]
    await sim.resend_buy_order_after_cancel(strategy, trigger_price=1412)
    await wait_for_condition(lambda: strategy.state == State.BUYING)
    await sim.fill_remaining_buy_order(strategy)

    # Wait for parent state to transition to PARTIALLY_SOLD
    await wait_for_condition(lambda: strategy.state == State.PARTIALLY_SOLD)

    # Verify final state before crash
    assert strategy.buy.buy_order.status == ORDER_STATUS_FILLED
    assert strategy.buy.buy_order.realized_quantity == 0.71429
    assert strategy.buy.data.state_info.state == State.BOUGHT
    assert strategy.state == State.PARTIALLY_SOLD
    assert strategy.sell.current_position.state_info.state == State.PARTIALLY_SOLD

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)

    # After recovery, assert all buy orders are filled and state is BOUGHT
    assert recovered.buy.buy_order.status == ORDER_STATUS_FILLED
    assert recovered.buy.data.state_info.state == State.BOUGHT

    # Wait for state transition to PARTIALLY_SOLD to complete after recovery
    await wait_for_condition(lambda: recovered.state == State.PARTIALLY_SOLD)
    assert recovered.state == State.PARTIALLY_SOLD

    await sim.assert_db_state_matches_memory()


async def test_recovery_sell_fully_partially_bought_position(crash_recovery_factory):
    """
    Test selling a fully partially bought position, with crash recovery.
    """
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_partial_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_order_partial_fill()

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()

    await sim.simulate_sell_order_fill_from_part_bought()

    # Assert in-memory state before crash
    strategy = back.strategies["1000"]
    sell_order = strategy.sell.current_position.sell_order
    assert sell_order.status == ORDER_STATUS_FILLED
    assert sell_order.realized_quantity > 0.0

    # Assert buy order: single order that should be CANCELED after partial fill
    buy_order = strategy.buy.buy_order
    assert isinstance(buy_order, Order)
    # In single-order system, verify the order status
    assert buy_order.status == ORDER_STATUS_CANCELED

    # Assert state before crash
    await sim.assert_sell_order_state(strategy, ORDER_STATUS_FILLED, realized_qty=0.12)
    await sim.assert_buy_order_state(strategy, ORDER_STATUS_CANCELED, realized_qty=0.12)
    assert strategy.state == State.SOLD_PART_BOUGHT
    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT

    # Crash and recover
    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)

    # Assert recovered state
    await sim.assert_sell_order_state(recovered, ORDER_STATUS_FILLED, realized_qty=0.12)
    await sim.assert_buy_order_state(
        recovered, ORDER_STATUS_CANCELED, realized_qty=0.12
    )
    assert recovered.state == State.SOLD_PART_BOUGHT
    assert recovered.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    await sim.assert_db_state_matches_memory()


async def test_recovery_buy_fully_partially_bought_position_when_sold_position(
    crash_recovery_factory,
):
    """
    Test reopening buy after a full sell from a partially bought position, with crash recovery.
    After recovery and full buy, state should be BOUGHT, not BUYING.
    """
    create_pair, simulate_crash = crash_recovery_factory
    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_partial_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_order_partial_fill()

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()

    await sim.simulate_sell_order_fill_from_part_bought()

    # Verify state before reopening buy
    assert strategy.state == State.SOLD_PART_BOUGHT
    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT

    # Reopen buy position and fill remaining quantity
    await sim.resend_buy_order_after_cancel(strategy, trigger_price=1412)
    await wait_for_condition(lambda: strategy.state == State.BUYING)
    assert strategy.buy.buy_order.realized_quantity == 0.12
    await sim.fill_remaining_buy_order(strategy)

    # Wait for parent state transition to PARTIALLY_SOLD
    await wait_for_condition(lambda: strategy.state == State.PARTIALLY_SOLD)
    await wait_for_condition(lambda: strategy.buy.data.state_info.state == State.BOUGHT)

    # Verify final state before crash
    assert strategy.buy.data.state_info.state == State.BOUGHT
    assert strategy.state == State.PARTIALLY_SOLD

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)

    # After recovery, assert buy order is filled and state is BOUGHT
    assert recovered.buy.buy_order.status == ORDER_STATUS_FILLED
    assert recovered.buy.data.state_info.state == State.BOUGHT
    assert recovered.state == State.PARTIALLY_SOLD

    await sim.assert_db_state_matches_memory()


async def test_recovery_start_new_sell_position_for_two_hop_trade(
    crash_recovery_factory,
):
    """
    Refactored: Test starting a new sell position for a two-hop trade, with crash recovery and parent/child linkage assertions.
    """
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    await sim.open_first_sell_position_from_two_hop_trade()

    # Assert sell_positions structure before crash
    strategy = back.strategies["1000"]
    sell_positions = strategy.sell.sell_positions
    assert (
        len(sell_positions) == 2
    ), f"Expected 2 sell positions for two-hop trade, got {len(sell_positions)}"

    # Both sell positions should be children of the original hp_id
    hp_ids = [sp.config.hp_id for sp in sell_positions]
    assert all(
        sp.config.is_child for sp in sell_positions
    ), "All sell positions should have is_child=True"
    assert all(
        sp.config.parent_hp_id == "1000" for sp in sell_positions
    ), "All sell positions should have parent_hp_id='1000'"
    assert set(hp_ids) == {
        "1000a",
        "1000b",
    }, f"Sell positions should have hp_ids '1000a' and '1000b', got {hp_ids}"

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)

    # Assert sell_positions structure after recovery
    recovered_strategy = recovered
    recovered_sell_positions = recovered_strategy.sell.sell_positions
    assert (
        recovered_sell_positions is not None
    ), "Recovered strategy.sell.sell_positions should not be None"
    assert isinstance(
        recovered_sell_positions, list
    ), "Recovered strategy.sell.sell_positions should be a list"
    assert (
        len(recovered_sell_positions) == 2
    ), f"Expected 2 sell positions after recovery, got {len(recovered_sell_positions)}"

    rec_hp_ids = [sp.config.hp_id for sp in recovered_sell_positions]
    assert all(
        sp.config.is_child for sp in recovered_sell_positions
    ), "All recovered sell positions should have is_child=True"
    assert all(
        sp.config.parent_hp_id == "1000" for sp in recovered_sell_positions
    ), "All recovered sell positions should have parent_hp_id='1000'"
    assert set(rec_hp_ids) == {
        "1000a",
        "1000b",
    }, f"Recovered sell positions should have hp_ids '1000a' and '1000b', got {rec_hp_ids}"

    await sim.assert_db_state_matches_memory()


async def test_recovery_send_order_for_first_sell_position_in_two_hop_trade(
    crash_recovery_factory,
):
    """
    Refactored: Test sending order for the first sell position in a two-hop trade, with crash recovery.
    """
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    await sim.open_first_sell_position_from_two_hop_trade()
    await sim.send_orders_for_first_position_from_two_hop_trade()

    # Assert that the first sell position has an order in NEW or SUBMITTED state before crash
    strategy = back.strategies["1000"]
    sell_positions = strategy.sell.sell_positions
    assert (
        len(sell_positions) == 2
    ), f"Expected 2 sell positions, got {len(sell_positions)}"
    first_sell_position = sell_positions[0]
    sell_order = first_sell_position.sell_order
    assert sell_order is not None, "First sell position should have a sell order"
    assert (
        sell_order.status == ORDER_STATUS_NEW
    ), f"Sell order status should be NEW or SUBMITTED, got {sell_order.status}"

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)

    # Assert that the first sell position has an order in NEW or SUBMITTED state after recovery
    recovered_strategy = recovered
    recovered_sell_positions = recovered_strategy.sell.sell_positions
    assert (
        len(recovered_sell_positions) == 2
    ), f"Expected 2 sell positions after recovery, got {len(recovered_sell_positions)}"
    recovered_first_sell_position = recovered_sell_positions[0]
    recovered_sell_order = recovered_first_sell_position.sell_order
    assert (
        recovered_sell_order is not None
    ), "First sell position after recovery should have a sell order"
    assert (
        recovered_sell_order.status == ORDER_STATUS_NEW
    ), f"Sell order status after recovery should be NEW or SUBMITTED, got {recovered_sell_order.status}"
    assert (
        recovered_sell_order.order_id is not None
    ), "Sell order after recovery should have a valid order_id"

    await sim.assert_db_state_matches_memory()


async def test_recovery_fill_partially_first_sell_position_in_two_hop_trade(
    crash_recovery_factory,
):
    """
    Refactored: Test partial fill of the first sell position in a two-hop trade, with crash recovery.
    """
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    await sim.open_first_sell_position_from_two_hop_trade()
    await sim.send_orders_for_first_position_from_two_hop_trade()
    await sim.simulate_sell_order_partial_fill_in_first_hop()

    # Assert that the first sell position has a partially filled order before crash
    strategy = back.strategies["1000"]
    sell_positions = strategy.sell.sell_positions
    assert (
        len(sell_positions) == 2
    ), f"Expected 2 sell positions, got {len(sell_positions)}"
    first_sell_position = sell_positions[0]
    sell_order = first_sell_position.sell_order
    assert sell_order is not None, "First sell position should have a sell order"
    assert (
        sell_order.status == ORDER_STATUS_PARTIALLY_FILLED
    ), f"Sell order status should be PARTIALLY_FILLED, got {sell_order.status}"
    assert (
        sell_order.realized_quantity > 0.0
    ), "Sell order should have non-zero realized quantity"

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)

    # Assert that the first sell position has a partially filled order after recovery
    recovered_strategy = recovered
    recovered_sell_positions = recovered_strategy.sell.sell_positions
    assert (
        len(recovered_sell_positions) == 2
    ), f"Expected 2 sell positions after recovery, got {len(recovered_sell_positions)}"
    recovered_first_sell_position = recovered_sell_positions[0]
    recovered_sell_order = recovered_first_sell_position.sell_order
    assert (
        recovered_sell_order is not None
    ), "First sell position after recovery should have a sell order"
    assert (
        recovered_sell_order.status == ORDER_STATUS_PARTIALLY_FILLED
    ), f"Sell order status after recovery should be PARTIALLY_FILLED, got {recovered_sell_order.status}"
    assert (
        recovered_sell_order.realized_quantity > 0.0
    ), "Sell order after recovery should have non-zero realized quantity"

    await sim.assert_db_state_matches_memory()


async def test_recovery_fill_first_sell_position_in_two_hop_trade(
    crash_recovery_factory,
):
    """
    Refactored: Test full fill of the first sell position in a two-hop trade, with crash recovery.
    """
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    await sim.open_first_sell_position_from_two_hop_trade()
    await sim.send_orders_for_first_position_from_two_hop_trade()
    await sim.simulate_sell_order_fill_in_first_hop()

    # Assert that the first sell position has a filled order before crash
    strategy = back.strategies["1000"]
    sell_positions = strategy.sell.sell_positions
    assert (
        len(sell_positions) == 2
    ), f"Expected 2 sell positions, got {len(sell_positions)}"
    first_sell_position = sell_positions[0]
    sell_order = first_sell_position.sell_order
    assert sell_order is not None, "First sell position should have a sell order"

    await wait_for_condition(lambda: sell_order.status == ORDER_STATUS_FILLED)

    logger.info("Current sell order: %s", sell_order)
    assert (
        sell_order.realized_quantity > 0.0
    ), "Sell order should have non-zero realized quantity"

    # Assert that the second leg is the current sell position before crash
    second_sell_position = sell_positions[1]
    await wait_for_condition(
        lambda: strategy.sell.current_position is second_sell_position
    )
    assert (
        strategy.sell.current_position is second_sell_position
    ), f"Expected current_position to be the second leg before crash, got {strategy.sell.current_position.config.hp_id}"

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)

    # Assert that the first sell position has a filled order after recovery
    recovered_strategy = recovered
    recovered_sell_positions = recovered_strategy.sell.sell_positions
    assert (
        len(recovered_sell_positions) == 2
    ), f"Expected 2 sell positions after recovery, got {len(recovered_sell_positions)}"
    recovered_first_sell_position = recovered_sell_positions[0]
    recovered_sell_order = recovered_first_sell_position.sell_order
    assert (
        recovered_sell_order is not None
    ), "First sell position after recovery should have a sell order"
    assert (
        recovered_sell_order.status == ORDER_STATUS_FILLED
    ), f"Sell order status after recovery should be FILLED, got {recovered_sell_order.status}"
    assert (
        recovered_sell_order.realized_quantity > 0.0
    ), "Sell order after recovery should have non-zero realized quantity"

    # Assert that the second leg is the current sell position after recovery
    recovered_second_sell_position = recovered_sell_positions[1]
    assert (
        recovered_strategy.sell.current_position is recovered_second_sell_position
    ), f"Expected current_position to be the second leg after recovery, got {recovered_strategy.sell.current_position.config.hp_id}"

    await sim.assert_db_state_matches_memory()


async def test_recovery_start_second_sell_position_in_two_hop_trade(
    crash_recovery_factory,
):
    """
    Test starting the second sell position in a two-hop trade, with crash recovery.
    """
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    await sim.open_first_sell_position_from_two_hop_trade()
    await sim.send_orders_for_first_position_from_two_hop_trade()
    await sim.simulate_sell_order_fill_in_first_hop()
    logger.info("First sell position filled, now opening second sell position.")
    await sim.open_second_sell_position_from_two_hop_trade()

    # Assert before crash: two sell positions, second is current, and first leg is FILLED (in-memory)
    strategy = back.strategies["1000"]
    sell_positions = strategy.sell.sell_positions
    assert (
        len(sell_positions) == 2
    ), f"Expected 2 sell positions, got {len(sell_positions)}"
    first_sell_position = sell_positions[0]
    second_sell_position = sell_positions[1]
    assert (
        strategy.sell.current_position is second_sell_position
    ), f"Expected current_position to be the second leg before crash, got {strategy.sell.current_position.config.hp_id}"
    assert (
        first_sell_position.sell_order.status == ORDER_STATUS_FILLED
    ), f"Expected first leg's sell order to be FILLED before crash, got {first_sell_position.sell_order.status}"

    # Assert from DB: get orders by position id and log all for debug
    logger.info(
        "Going to check DB orders for first sell position: %s",
        first_sell_position.config.hp_id,
    )
    db_orders = await front.db.get_orders_by_position_id(
        first_sell_position.config.hp_id
    )
    logger.info(f"[TEST] DB orders for first sell position: %s", db_orders)
    assert (
        len(db_orders) == 1
    ), "Expected at least one order in DB for first sell position"
    for o in db_orders:
        logger.info(
            f"[TEST] DB order: id={getattr(o, 'id', None)}, position_id={getattr(o, 'position_id', None)}, side={getattr(o.side, 'value', o.side)}, status={getattr(o.status, 'value', o.status)}, symbol={getattr(o, 'symbol', None)}, realized_quantity={getattr(o, 'realized_quantity', None)}"
        )
    db_first_leg_sell_orders = [
        o for o in db_orders if getattr(o.side, "value", o.side) == "SELL"
    ]
    assert (
        len(db_first_leg_sell_orders) == 1
    ), f"Expected 1 first leg sell order in DB, got {len(db_first_leg_sell_orders)}"
    db_first_leg_sell_order = db_first_leg_sell_orders[0]
    logger.info(
        f"[TEST] DB first leg sell order status before crash: {db_first_leg_sell_order.status.value}, id={getattr(db_first_leg_sell_order, 'id', None)}"
    )
    print(
        f"[TEST] DB first leg sell order status before crash: {db_first_leg_sell_order.status.value}, id={getattr(db_first_leg_sell_order, 'id', None)}"
    )
    assert (
        db_first_leg_sell_order.status.value == ORDER_STATUS_FILLED
    ), f"Expected first leg's sell order to be FILLED in DB before crash, got {db_first_leg_sell_order.status.value}"

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)

    # Assert after recovery: two sell positions, second is current
    recovered_strategy = recovered
    recovered_sell_positions = recovered_strategy.sell.sell_positions
    assert (
        len(recovered_sell_positions) == 2
    ), f"Expected 2 sell positions after recovery, got {len(recovered_sell_positions)}"
    recovered_second_sell_position = recovered_sell_positions[1]
    assert (
        recovered_strategy.sell.current_position is recovered_second_sell_position
    ), f"Expected current_position to be the second leg after recovery, got {recovered_strategy.sell.current_position.config.hp_id}"

    await sim.assert_db_state_matches_memory()


async def test_recovery_partial_fill_second_sell_position_in_two_hop_trade(
    crash_recovery_factory,
):
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    await sim.open_first_sell_position_from_two_hop_trade()
    await sim.send_orders_for_first_position_from_two_hop_trade()
    await sim.simulate_sell_order_fill_in_first_hop()
    await sim.open_second_sell_position_from_two_hop_trade()
    await sim.simulate_sell_order_partial_fill_in_second_hop()

    # Assert before crash: two sell positions, second is current, and second leg is PARTIALLY_FILLED (in-memory)
    strategy = back.strategies["1000"]
    sell_positions = strategy.sell.sell_positions
    assert (
        len(sell_positions) == 2
    ), f"Expected 2 sell positions, got {len(sell_positions)}"
    first_sell_position = sell_positions[0]
    second_sell_position = sell_positions[1]
    assert (
        strategy.sell.current_position is second_sell_position
    ), f"Expected current_position to be the second leg before crash, got {strategy.sell.current_position.config.hp_id}"
    assert (
        second_sell_position.sell_order.status == ORDER_STATUS_PARTIALLY_FILLED
    ), f"Expected second leg's sell order to be PARTIALLY_FILLED before crash, got {second_sell_position.sell_order.status}"
    assert (
        second_sell_position.sell_order.realized_quantity > 0.0
    ), "Second leg's sell order should have non-zero realized quantity before crash"

    # Assert from DB: get orders by position id and log all for debug
    db_orders = await front.db.get_orders_by_position_id(
        second_sell_position.config.hp_id
    )
    assert (
        len(db_orders) >= 1
    ), "Expected at least one order in DB for second sell position"
    db_second_leg_sell_orders = [
        o for o in db_orders if getattr(o.side, "value", o.side) == "SELL"
    ]
    assert (
        len(db_second_leg_sell_orders) == 1
    ), f"Expected 1 second leg sell order in DB, got {len(db_second_leg_sell_orders)}"
    db_second_leg_sell_order = db_second_leg_sell_orders[0]
    assert (
        db_second_leg_sell_order.status.value == ORDER_STATUS_PARTIALLY_FILLED
    ), f"Expected second leg's sell order to be PARTIALLY_FILLED in DB before crash, got {db_second_leg_sell_order.status.value}"
    assert (
        db_second_leg_sell_order.realized_quantity > 0.0
    ), "Second leg's sell order in DB should have non-zero realized quantity before crash"

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)

    # Assert after recovery: two sell positions, second is current, and second leg is PARTIALLY_FILLED
    recovered_strategy = recovered
    recovered_sell_positions = recovered_strategy.sell.sell_positions
    assert (
        len(recovered_sell_positions) == 2
    ), f"Expected 2 sell positions after recovery, got {len(recovered_sell_positions)}"
    recovered_second_sell_position = recovered_sell_positions[1]
    assert (
        recovered_strategy.sell.current_position is recovered_second_sell_position
    ), f"Expected current_position to be the second leg after recovery, got {recovered_strategy.sell.current_position.config.hp_id}"
    assert (
        recovered_second_sell_position.sell_order.status
        == ORDER_STATUS_PARTIALLY_FILLED
    ), f"Expected second leg's sell order to be PARTIALLY_FILLED after recovery, got {recovered_second_sell_position.sell_order.status}"
    assert (
        recovered_second_sell_position.sell_order.realized_quantity > 0.0
    ), "Second leg's sell order should have non-zero realized quantity after recovery"

    await sim.assert_db_state_matches_memory()


async def test_recovery_fill_second_sell_position_in_two_hop_trade(
    crash_recovery_factory,
):
    """
    Test full fill of the second sell position in a two-hop trade, with crash recovery.
    After recovery, the second leg should be FILLED and nothing should be open.
    """
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    await sim.open_first_sell_position_from_two_hop_trade()
    await sim.send_orders_for_first_position_from_two_hop_trade()
    await sim.simulate_sell_order_fill_in_first_hop()
    await sim.open_second_sell_position_from_two_hop_trade()
    await sim.simulate_sell_order_fill_in_second_hop()

    # Assert before crash: both legs are FILLED
    strategy = back.strategies["1000"]
    sell_positions = strategy.sell.sell_positions
    assert (
        len(sell_positions) == 2
    ), f"Expected 2 sell positions, got {len(sell_positions)}"
    first_sell_position = sell_positions[0]
    second_sell_position = sell_positions[1]
    assert (
        first_sell_position.sell_order.status == ORDER_STATUS_FILLED
    ), f"First leg should be FILLED before crash, got {first_sell_position.sell_order.status}"
    assert (
        second_sell_position.sell_order.status == ORDER_STATUS_FILLED
    ), f"Second leg should be FILLED before crash, got {second_sell_position.sell_order.status}"
    assert (
        second_sell_position.sell_order.realized_quantity > 0.0
    ), "Second leg's sell order should have non-zero realized quantity before crash"

    _, _, recovered = await sim.crash_and_recover("1000", create_pair, simulate_crash)

    # Assert after recovery: both legs are FILLED
    recovered_strategy = recovered
    recovered_sell_positions = recovered_strategy.sell.sell_positions
    assert (
        len(recovered_sell_positions) == 2
    ), f"Expected 2 sell positions after recovery, got {len(recovered_sell_positions)}"
    recovered_second_sell_position = recovered_sell_positions[1]
    assert (
        recovered_second_sell_position.sell_order.status == ORDER_STATUS_FILLED
    ), f"Expected second leg's sell order to be FILLED after recovery, got {recovered_second_sell_position.sell_order.status}"
    assert (
        recovered_second_sell_position.sell_order.realized_quantity > 0.0
    ), "Second leg's sell order should have non-zero realized quantity after recovery"

    await sim.assert_db_state_matches_memory()


async def test_recovery_convert_only_position_crash(crash_recovery_factory):
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    assert len(back.strategies) == 0

    buy_price = 10.0
    sell_price = 12.0
    quantity = 100.0

    # Simulate convert-only position (DYM/USDC)
    await sim.simulate_convert_only_position(
        coin="DYM",
        buy_price=buy_price,
        sell_price=sell_price,
        quantity=quantity,
    )

    # Wait for frontend to reflect the convert-only position
    await wait_for_condition(condition_func=lambda: front.hp_list_data)

    # Validate UI state using helper method
    sim.validate_parent(
        quantity=str(quantity),
        state="BOUGHT",
        buy_price=str(buy_price),
        quantity_usd=str(round(quantity * buy_price, 2)),
        sell_price=str(sell_price),
        expected_return="200.0",
    )

    new_front, new_back, recovered_strategy = await sim.crash_and_recover(
        "1000", create_pair, simulate_crash
    )
    new_sim = HPSimulator(front=new_front, back=new_back)
    assert recovered_strategy.sell.current_position.config.coin == "DYM"
    assert recovered_strategy.sell.current_position.config.sell_price == sell_price
    assert recovered_strategy.state == State.BOUGHT
    assert recovered_strategy.sell.current_position.config.symbol.is_convert_only

    # Validate recovered position using helper
    await wait_for_condition(condition_func=lambda: new_front.hp_list_data)
    new_sim.validate_parent(
        quantity=str(quantity),
        state="BOUGHT",
        buy_price=str(buy_price),
        quantity_usd=str(round(quantity * buy_price, 2)),
        sell_price=str(sell_price),
        expected_return="200.0",
    )

    # Mock convert quote/accept methods on the client
    convert_quote_result = {
        "quoteId": "mock-quote-id",
        "fromAsset": "DYM",
        "toAsset": "USDC",
        "fromAmount": str(quantity),
        "toAmount": str(round(quantity * sell_price, 2)),
        "ratio": str(sell_price),
    }
    convert_accept_result = {
        "orderId": "mock-convert-order-id",
        "status": "SUCCESS",
        "filledAmount": str(quantity),
        "receivedAmount": str(round(quantity * sell_price, 2)),
    }
    recovered_strategy.client.convert_request_quote = AsyncMock(
        return_value=convert_quote_result
    )
    recovered_strategy.client.convert_accept_quote = AsyncMock(
        return_value=convert_accept_result
    )

    # Trigger conversion by price
    new_sim.new_price(price=12.0, symbol="DYMUSDT")

    # Validate conversion completed using helper
    await wait_for_condition(lambda: new_front.hp_list_data[0]["state"] == "SOLD")
    new_sim.validate_parent(
        quantity="100.0",
        realized_quantity="100.0",
        state="SOLD",
        buy_price=str(buy_price),
        quantity_usd="1000.0",
        sell_price=str(sell_price),
        expected_return="200.0",
    )
