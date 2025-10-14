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
from src.database.models import OrderStatus
from src.common.identifiers import Event, EventName, ExecutionReport, Order, State
from src.strategy_executor import StrategyExecutor
from src.gui.hp_manager.hpfront import HpFront
from tests.helpers import get_new_order
from tests.strategies.hp_manager_helpers import (
    wait_for_condition,
    wait_for_active_buy_positions,
    wait_for_no_idle_buy_positions,
    get_buy_positions,
    get_sell_positions,
)
from tests.strategies.hp_simulator import HPSimulator
from tests.strategies.crash_recovery import CrashRecoveryHelper

logger = logging.getLogger("hp_e2e_test")


async def test_recovery_get_default_buy_position(crash_recovery_factory):
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


async def test_recovery_default_buy_position_send_orders(crash_recovery_factory):
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


async def test_recovery_cancel_default_position_untouched(crash_recovery_factory):
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


async def test_recovery_cancel_default_position_untouched_then_resend_orders(
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


async def test_recovery_default_position_order_filled_partially(
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


async def test_recovery_default_position_first_order_filled_partially_then_cancel(
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


async def test_recovery_default_position_buy_order_filled(crash_recovery_factory):
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


async def test_recovery_default_position_first_order_filled_partially_then_cancel_then_resend(
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

    await wait_for_condition(
        lambda: strategy.buy.buy_order.status == ORDER_STATUS_CANCELED
    )
    assert strategy.buy.buy_order.realized_quantity == 0.12

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT

    await wait_for_condition(
        lambda: front.hp_list_data[0]["state"] == "PARTIALLY_BOUGHT"
    )

    item = front.hp_list_data[0]
    assert item["hp_id"] == "1000"
    assert item["coin"] == "BTCUSD"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.12"
    assert item["quantity_usd"] == "168.0"
    assert item["sell_price"] == "0.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "PARTIALLY_BOUGHT"

    logger.info("HP List after the update: %s", front.hp_list_data)

    # Reopen position
    strategy.client.create_order.side_effect = [
        get_new_order(order=strategy.buy.buy_order)
    ]
    sim.new_price(price=1414)

    await wait_for_condition(lambda: strategy.buy.buy_order.status == ORDER_STATUS_NEW)

    logger.info("Orders after reopening: %s", strategy.buy.buy_order)

    assert strategy.buy.buy_order.realized_quantity == 0.12

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING

    await wait_for_condition(lambda: front.hp_list_data[0]["state"] == "BUYING")

    # === SIMULATE CRASH ===
    await simulate_crash(front, back)

    # === PHASE 2: SIMULATE APPLICATION RESTART ===
    new_front, new_back = create_pair("_recovery")
    assert isinstance(new_front, HpFront)
    assert isinstance(new_back, StrategyExecutor)

    # Verify DB state before recovery
    positions_before_recovery = await new_front.db.get_active_positions()
    assert len(positions_before_recovery) == 1
    db_position = positions_before_recovery[0]
    assert db_position.hp_id == "1000"
    assert db_position.status.value in ("PARTIALLY_BOUGHT", "PARTIALLY_FILLED")
    assert db_position.symbol == "BTCUSDC"
    assert db_position.buy_price == 1400.0
    assert db_position.budget == 1000.0
    assert db_position.strategy_state == "BUYING"

    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)

    logger.info("Orders in the DB: %s", db_orders)
    assert len(db_orders) == 2
    new_orders = [o for o in db_orders if o.status.value == ORDER_STATUS_NEW]
    canceled_orders = [o for o in db_orders if o.status.value == ORDER_STATUS_CANCELED]
    assert len(new_orders) == 1
    assert len(canceled_orders) == 1

    # Use CrashRecoveryHelper to mock exchange queries during recovery
    recovery_helper = CrashRecoveryHelper(new_front, new_back)
    new_back.client.get_order.side_effect = recovery_helper.mock_orders_from_db(
        db_orders
    )

    # === MANUALLY TRIGGER CRASH RECOVERY ===
    await new_back.recover_positions_from_crash()

    # === POST-RECOVERY ASSERTIONS ===
    await wait_for_condition(lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies
    recovered_strategy = new_back.strategies["1000"]
    assert recovered_strategy.state == State.BUYING
    assert recovered_strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert isinstance(recovered_strategy.buy.buy_order, Order)
    assert recovered_strategy.buy.data.config.symbol.name == "BTCUSDC"
    assert recovered_strategy.buy.buy_order.realized_quantity == 0.12


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


async def test_recovery_cancel_unfilled_sell_orders(crash_recovery_factory):
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


async def test_recovery_resend_unfilled_sell_orders(crash_recovery_factory):
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


async def test_recovery_sell_position_first_order_filled_partially(
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


async def test_recovery_cancel_sell_position_first_order_filled_partially(
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


async def test_recovery_resend_sell_position_first_order_filled_partially(
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


async def test_recovery_cancel_unfilled_sell_orders_for_partially_bought_position(
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

    strategy.client.create_order.side_effect = [
        get_new_order(order=strategy.buy.buy_order)
    ]
    sim.new_price(price=1212)

    # Wait for order to be resent and state to transition to BUYING
    await wait_for_condition(condition_func=lambda: strategy.state == State.BUYING)

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
    )

    # Single buy order should be NEW (resent) with partial realized quantity
    assert strategy.buy.buy_order.status == ORDER_STATUS_NEW
    assert strategy.buy.buy_order.realized_quantity == 0.12
    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT

    # --- Check completeness ---
    # StateInfo.completeness is automatically calculated by StateInfo.get_completeness()
    # which rounds to 2 decimal places
    completeness = strategy.buy.data.state_info.completeness
    print(f"[TEST] Completeness after all buy orders filled: {completeness}")

    # Simulate crash after all buy orders are filled
    await simulate_crash(front, back)

    # PHASE 2: Simulate application restart and recovery after all buys filled
    new_front, new_back = create_pair("_recovery")
    assert isinstance(new_front, HpFront)
    assert isinstance(new_back, StrategyExecutor)
    db_positions = await new_front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    recovery_helper = CrashRecoveryHelper(new_front, new_back)
    new_back.client.get_order.side_effect = recovery_helper.mock_orders_from_db(
        db_orders
    )
    await new_back.recover_positions_from_crash()

    # After recovery, assert buy order is NEW (resent) and state is BUYING
    await wait_for_condition(lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies
    recovered_strategy = new_back.strategies["1000"]
    assert recovered_strategy.buy.buy_order.status == ORDER_STATUS_NEW
    assert recovered_strategy.buy.buy_order.realized_quantity == 0.12
    assert recovered_strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert recovered_strategy.state == State.BUYING

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


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

    # Assert in-memory state before crash
    strategy = back.strategies["1000"]
    sell_order = strategy.sell.current_position.sell_order
    assert sell_order.status == ORDER_STATUS_PARTIALLY_FILLED
    assert sell_order.realized_quantity > 0.0

    # Assert buy order: single order that was partially filled then canceled
    buy_order = strategy.buy.buy_order
    assert isinstance(buy_order, Order)
    # The order was partially filled then canceled
    assert buy_order.status == ORDER_STATUS_CANCELED
    assert buy_order.realized_quantity == 0.12

    # Ensure DB is updated before crash
    db_positions = await front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    db_orders = await front.db.get_orders_by_position_id(db_position.id)
    db_sell_orders = [
        o for o in db_orders if getattr(o.side, "value", o.side) == "SELL"
    ]
    assert len(db_sell_orders) == 1
    db_sell_order = db_sell_orders[0]
    assert db_sell_order.status.value == ORDER_STATUS_PARTIALLY_FILLED
    assert db_sell_order.realized_quantity > 0.0

    # Simulate crash
    await simulate_crash(front, back)

    # Simulate recovery
    new_front, new_back = create_pair("_recovery")
    db_positions = await new_front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    recovery_helper = CrashRecoveryHelper(new_front, new_back)
    new_back.client.get_order.side_effect = recovery_helper.mock_orders_from_db(
        db_orders
    )
    await new_back.recover_positions_from_crash()

    # Assert post-recovery state
    await wait_for_condition(lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies
    recovered_strategy = new_back.strategies["1000"]
    recovered_sell_order = recovered_strategy.sell.current_position.sell_order
    assert recovered_sell_order.status == ORDER_STATUS_PARTIALLY_FILLED
    assert recovered_sell_order.realized_quantity > 0.0

    # Assert buy order after recovery: single order with canceled status
    recovered_buy_order = recovered_strategy.buy.buy_order
    assert isinstance(recovered_buy_order, Order)
    # In single-order system, the order should be CANCELED with partial realized quantity
    assert recovered_buy_order.status == ORDER_STATUS_CANCELED

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


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

    # Wait for state transition after price trigger
    await wait_for_condition(
        condition_func=lambda: strategy.state == State.PART_SOLD_PART_BOUGHT
    )

    assert strategy.buy.buy_order.status == ORDER_STATUS_CANCELED
    assert strategy.buy.buy_order.realized_quantity == 0.12
    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PART_SOLD_PART_BOUGHT

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "PART_SOLD_PART_BOUGHT"
    )

    # Reopen Buy position
    strategy.client.create_order.side_effect = [
        get_new_order(order=strategy.buy.buy_order)
    ]

    sim.new_price(price=1412)

    # Wait for state transition after price trigger
    await wait_for_condition(condition_func=lambda: strategy.state == State.BUYING)

    assert strategy.buy.buy_order.status == ORDER_STATUS_NEW
    assert strategy.buy.buy_order.realized_quantity == 0.12
    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT

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

    # Simulate crash
    await simulate_crash(front, back)

    # Simulate recovery
    new_front, new_back = create_pair("_recovery")
    db_positions = await new_front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    recovery_helper = CrashRecoveryHelper(new_front, new_back)
    new_back.client.get_order.side_effect = recovery_helper.mock_orders_from_db(
        db_orders
    )
    await new_back.recover_positions_from_crash()

    # Assert post-recovery state
    await wait_for_condition(lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies
    recovered_strategy = new_back.strategies["1000"]

    # Single order system - verify recovered order
    recovered_buy_order = recovered_strategy.buy.buy_order
    assert isinstance(recovered_buy_order, Order)
    assert recovered_buy_order.status == ORDER_STATUS_CANCELED
    assert recovered_buy_order.realized_quantity > 0.0

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


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

    await wait_for_condition(
        condition_func=lambda: strategy.buy.buy_order.status == ORDER_STATUS_CANCELED
    )

    # Assert sell order is canceled and partially realized
    sell_order = strategy.sell.current_position.sell_order
    assert (
        sell_order.status == ORDER_STATUS_CANCELED
    ), f"Expected sell order to be CANCELED, got {sell_order.status}"
    assert (
        sell_order.realized_quantity > 0.0
    ), f"Expected sell order to have realized quantity > 0, got {sell_order.realized_quantity}"

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

    db_sell_orders = [
        o for o in db_orders if getattr(o.side, "value", o.side) == "SELL"
    ]
    assert len(db_sell_orders) == 1
    db_sell_order = db_sell_orders[0]
    assert (
        db_sell_order.status.value == ORDER_STATUS_CANCELED
    ), f"Expected DB sell order to be CANCELED, got {db_sell_order.status.value}"
    assert (
        db_sell_order.realized_quantity > 0.0
    ), f"Expected DB sell order to have realized quantity > 0, got {db_sell_order.realized_quantity}"

    # Simulate crash
    await simulate_crash(front, back)

    # Simulate recovery
    new_front, new_back = create_pair("_recovery")
    db_positions = await new_front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    recovery_helper = CrashRecoveryHelper(new_front, new_back)
    new_back.client.get_order.side_effect = recovery_helper.mock_orders_from_db(
        db_orders
    )
    await new_back.recover_positions_from_crash()

    # Assert post-recovery state
    await wait_for_condition(lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies
    recovered_strategy = new_back.strategies["1000"]

    # Single order system - verify recovered order
    recovered_buy_order = recovered_strategy.buy.buy_order
    assert isinstance(recovered_buy_order, Order)
    assert recovered_buy_order.status == ORDER_STATUS_CANCELED
    assert recovered_buy_order.realized_quantity > 0.0

    # Assert recovered sell order is canceled and partially realized
    recovered_sell_order = recovered_strategy.sell.current_position.sell_order
    assert (
        recovered_sell_order.status == ORDER_STATUS_CANCELED
    ), f"Expected recovered sell order to be CANCELED, got {recovered_sell_order.status}"
    assert (
        recovered_sell_order.realized_quantity > 0.0
    ), f"Expected recovered sell order to have realized quantity > 0, got {recovered_sell_order.realized_quantity}"

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


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

    # Reopen buy position (simulate price trigger)
    strategy = back.strategies["1000"]
    strategy.client.create_order.side_effect = [
        get_new_order(order=strategy.buy.buy_order)
    ]
    sim.new_price(price=1412)

    # Wait for state transition after reopening buy
    await wait_for_condition(condition_func=lambda: strategy.state == State.BUYING)

    # Wait for the new order to be created (reopened order has new ID)
    await wait_for_condition(
        condition_func=lambda: strategy.buy.buy_order.status == ORDER_STATUS_NEW
    )

    full_qty = 0.71429
    remaining_qty = full_qty - 0.12  # 0.59429

    price = 1400.0
    # Send FILLED ExecutionReport with the correct (reopened) order_id
    exc_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,  # Mark as FILLED
        order_id=strategy.buy.buy_order.order_id,  # Use current order_id (after reopen)
        last_executed_quantity=remaining_qty,
        last_executed_price=price,
        cumulative_filled_quantity=full_qty,
    )
    strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))

    # Wait for full fill and state transition
    await wait_for_condition(
        condition_func=lambda: strategy.buy.buy_order.status == ORDER_STATUS_FILLED
    )

    # Wait for parent state to transition to PARTIALLY_SOLD (buy is complete, partial sell remains)
    await wait_for_condition(
        condition_func=lambda: strategy.state == State.PARTIALLY_SOLD
    )

    # All buy orders should now be filled
    assert strategy.buy.buy_order.status == ORDER_STATUS_FILLED
    assert (
        strategy.buy.buy_order.realized_quantity == 0.71429
    )  # Full order quantity filled
    assert strategy.buy.data.state_info.state == State.BOUGHT  # Buy order is complete
    assert strategy.state == State.PARTIALLY_SOLD  # Parent tracks the partial sell
    assert strategy.sell.current_position.state_info.state == State.PARTIALLY_SOLD

    db_positions = await front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    logger.info("db position: %s", db_position)

    # Simulate crash after all buy orders are filled
    await simulate_crash(front, back)

    # PHASE 2: Simulate application restart and recovery after all buys filled
    new_front, new_back = create_pair("_recovery")
    assert isinstance(new_front, HpFront)
    assert isinstance(new_back, StrategyExecutor)
    db_positions = await new_front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    recovery_helper = CrashRecoveryHelper(new_front, new_back)
    new_back.client.get_order.side_effect = recovery_helper.mock_orders_from_db(
        db_orders
    )
    await new_back.recover_positions_from_crash()

    # After recovery, assert all buy orders are filled and state is BOUGHT
    await wait_for_condition(lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies
    recovered_strategy = new_back.strategies["1000"]
    assert recovered_strategy.buy.buy_order.status == ORDER_STATUS_FILLED
    assert recovered_strategy.buy.data.state_info.state == State.BOUGHT

    # Wait for state transition to PARTIALLY_SOLD to complete after recovery
    await wait_for_condition(lambda: recovered_strategy.state == State.PARTIALLY_SOLD)
    assert recovered_strategy.state == State.PARTIALLY_SOLD

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


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

    # Ensure DB is updated before crash
    db_positions = await front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    db_orders = await front.db.get_orders_by_position_id(db_position.id)
    db_sell_orders = [
        o for o in db_orders if getattr(o.side, "value", o.side) == "SELL"
    ]
    assert len(db_sell_orders) == 1
    db_sell_order = db_sell_orders[0]
    assert db_sell_order.status.value == ORDER_STATUS_FILLED
    assert db_sell_order.realized_quantity > 0.0

    # Assert state is SOLD_PART_BOUGHT and buy state is BOUGHT
    assert (
        strategy.state == State.SOLD_PART_BOUGHT
    ), f"Expected strategy state to be SOLD_PART_BOUGHT, got {strategy.state}"
    assert (
        strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    ), f"Expected buy state to be PARTIALLY BOUGHT, got {strategy.buy.data.state_info.state}"

    # Simulate crash
    await simulate_crash(front, back)

    # Simulate recovery
    new_front, new_back = create_pair("_recovery")
    db_positions = await new_front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    recovery_helper = CrashRecoveryHelper(new_front, new_back)
    new_back.client.get_order.side_effect = recovery_helper.mock_orders_from_db(
        db_orders
    )
    await new_back.recover_positions_from_crash()

    # Assert post-recovery state
    await wait_for_condition(lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies
    recovered_strategy = new_back.strategies["1000"]
    recovered_sell_order = recovered_strategy.sell.current_position.sell_order
    assert recovered_sell_order.status == ORDER_STATUS_FILLED
    assert recovered_sell_order.realized_quantity > 0.0

    # Single order system - verify recovered buy order
    recovered_buy_order = recovered_strategy.buy.buy_order
    assert isinstance(recovered_buy_order, Order)
    assert recovered_buy_order.status == ORDER_STATUS_CANCELED

    # Assert state is SOLD_PART_BOUGHT and buy state is BOUGHT
    assert (
        recovered_strategy.state == State.SOLD_PART_BOUGHT
    ), f"Expected strategy state to be SOLD_PART_BOUGHT, got {recovered_strategy.state}"
    assert (
        recovered_strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    ), f"Expected buy state to be PARTIALLY BOUGHT, got {recovered_strategy.buy.data.state_info.state}"

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


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

    # Assert state is SOLD_PART_BOUGHT and buy state is PARTIALLY_BOUGHT
    assert (
        strategy.state == State.SOLD_PART_BOUGHT
    ), f"Expected strategy state to be SOLD_PART_BOUGHT, got {strategy.state}"
    assert (
        strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    ), f"Expected buy state to be PARTIALLY_BOUGHT, got {strategy.buy.data.state_info.state}"

    # Reopen Buy position (simulate price trigger)
    strategy.client.create_order.side_effect = [
        get_new_order(order=strategy.buy.buy_order)
    ]
    sim.new_price(price=1412)

    await wait_for_condition(condition_func=lambda: strategy.state == State.BUYING)

    assert strategy.buy.buy_order.realized_quantity == 0.12

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
    )

    price = 1400.0
    # Send FILLED ExecutionReport with the correct (reopened) order_id
    exc_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,  # Mark as FILLED
        order_id=strategy.buy.buy_order.order_id,  # Use current order_id (after reopen)
        last_executed_quantity=strategy.buy.buy_order.quantity
        - strategy.buy.buy_order.realized_quantity,  # Fill the remaining qty
        last_executed_price=price,
        cumulative_filled_quantity=strategy.buy.buy_order.quantity,  # Full quantity filled
    )
    strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))

    # Wait for full fill and state transition
    await wait_for_condition(
        condition_func=lambda: strategy.buy.buy_order.status == ORDER_STATUS_FILLED
    )

    # Wait for parent state to transition to PARTIALLY_SOLD (buy is complete, partial sell remains)
    await wait_for_condition(
        condition_func=lambda: strategy.state == State.PARTIALLY_SOLD
    )

    # Wait for buy state to be updated to BOUGHT (happens in "after" callback)
    await wait_for_condition(
        condition_func=lambda: strategy.buy.data.state_info.state == State.BOUGHT
    )

    # All buy orders should now be filled
    assert strategy.buy.data.state_info.state == State.BOUGHT
    assert strategy.state == State.PARTIALLY_SOLD

    # Simulate crash after all buy orders are filled
    await simulate_crash(front, back)

    # PHASE 2: Simulate application restart and recovery
    new_front, new_back = create_pair("_recovery")
    db_positions = await new_front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    recovery_helper = CrashRecoveryHelper(new_front, new_back)
    new_back.client.get_order.side_effect = recovery_helper.mock_orders_from_db(
        db_orders
    )
    await new_back.recover_positions_from_crash()

    # After recovery, assert buy order is filled and state is BOUGHT
    recovered_strategy = new_back.strategies["1000"]
    assert recovered_strategy.buy.buy_order.status == ORDER_STATUS_FILLED
    assert recovered_strategy.buy.data.state_info.state == State.BOUGHT
    assert recovered_strategy.state == State.PARTIALLY_SOLD

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


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

    # Simulate crash
    await simulate_crash(front, back)

    # Simulate recovery
    new_front, new_back = create_pair("_recovery")
    assert isinstance(new_front, HpFront)
    assert isinstance(new_back, StrategyExecutor)
    db_positions = await new_front.db.get_active_positions()
    assert len(db_positions) == 1, "Should have one hop after recovery"
    db_orders = []
    for db_position in db_positions:
        db_orders.extend(await new_front.db.get_orders_by_position_id(db_position.id))
    recovery_helper = CrashRecoveryHelper(new_front, new_back)
    new_back.client.get_order.side_effect = recovery_helper.mock_orders_from_db(
        db_orders
    )
    await new_back.recover_positions_from_crash()

    # Assert sell_positions structure after recovery

    await wait_for_condition(lambda: len(new_back.strategies) == 1)
    assert (
        "1000" in new_back.strategies
    ), "Recovered strategies should contain only '1000'"
    recovered_strategy = new_back.strategies["1000"]
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

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


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

    # Simulate crash
    await simulate_crash(front, back)

    # Simulate recovery
    new_front, new_back = create_pair("_recovery")
    assert isinstance(new_front, HpFront)
    assert isinstance(new_back, StrategyExecutor)
    db_positions = await new_front.db.get_active_positions()
    assert len(db_positions) == 1, "Should have one hop after recovery"
    db_orders = []
    for db_position in db_positions:
        db_orders.extend(await new_front.db.get_orders_by_position_id(db_position.id))
    recovery_helper = CrashRecoveryHelper(new_front, new_back)
    new_back.client.get_order.side_effect = recovery_helper.mock_orders_from_db(
        db_orders
    )
    await new_back.recover_positions_from_crash()

    # Assert that the first sell position has an order in NEW or SUBMITTED state after recovery
    await wait_for_condition(lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies
    recovered_strategy = new_back.strategies["1000"]
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

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


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

    # Simulate crash
    await simulate_crash(front, back)

    # Simulate recovery
    new_front, new_back = create_pair("_recovery")
    assert isinstance(new_front, HpFront)
    assert isinstance(new_back, StrategyExecutor)
    db_positions = await new_front.db.get_active_positions()
    assert len(db_positions) == 1, "Should have one hop after recovery"
    db_orders = []
    for db_position in db_positions:
        db_orders.extend(await new_front.db.get_orders_by_position_id(db_position.id))
    recovery_helper = CrashRecoveryHelper(new_front, new_back)
    new_back.client.get_order.side_effect = recovery_helper.mock_orders_from_db(
        db_orders
    )
    await new_back.recover_positions_from_crash()

    # Assert that the first sell position has a partially filled order after recovery
    await wait_for_condition(lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies
    recovered_strategy = new_back.strategies["1000"]
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

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


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

    # Simulate crash
    await simulate_crash(front, back)

    # Simulate recovery
    new_front, new_back = create_pair("_recovery")
    assert isinstance(new_front, HpFront)
    assert isinstance(new_back, StrategyExecutor)
    db_positions = await new_front.db.get_active_positions()
    assert len(db_positions) == 1, "Should have one hop after recovery"
    db_orders = []
    for db_position in db_positions:
        db_orders.extend(await new_front.db.get_orders_by_position_id(db_position.id))
    recovery_helper = CrashRecoveryHelper(new_front, new_back)
    new_back.client.get_order.side_effect = recovery_helper.mock_orders_from_db(
        db_orders
    )
    await new_back.recover_positions_from_crash()

    # Assert that the first sell position has a filled order after recovery
    await wait_for_condition(lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies
    recovered_strategy = new_back.strategies["1000"]
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

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


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

    # Simulate crash
    await simulate_crash(front, back)

    # Simulate recovery
    new_front, new_back = create_pair("_recovery")
    assert isinstance(new_front, HpFront)
    assert isinstance(new_back, StrategyExecutor)
    db_positions = await new_front.db.get_active_positions()
    assert len(db_positions) == 1, "Should have one hop after recovery"
    db_orders = []
    for db_position in db_positions:
        db_orders.extend(await new_front.db.get_orders_by_position_id(db_position.id))
    recovery_helper = CrashRecoveryHelper(new_front, new_back)
    new_back.client.get_order.side_effect = recovery_helper.mock_orders_from_db(
        db_orders
    )
    await new_back.recover_positions_from_crash()

    # Assert after recovery: two sell positions, second is current
    await wait_for_condition(lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies
    recovered_strategy = new_back.strategies["1000"]
    recovered_sell_positions = recovered_strategy.sell.sell_positions
    assert (
        len(recovered_sell_positions) == 2
    ), f"Expected 2 sell positions after recovery, got {len(recovered_sell_positions)}"
    recovered_second_sell_position = recovered_sell_positions[1]
    assert (
        recovered_strategy.sell.current_position is recovered_second_sell_position
    ), f"Expected current_position to be the second leg after recovery, got {recovered_strategy.sell.current_position.config.hp_id}"

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


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

    # Simulate crash
    await simulate_crash(front, back)

    # Simulate recovery
    new_front, new_back = create_pair("_recovery")
    db_positions = await new_front.db.get_active_positions()
    assert len(db_positions) == 1, "Should have one hop after recovery"
    db_orders = []
    for db_position in db_positions:
        db_orders.extend(await new_front.db.get_orders_by_position_id(db_position.id))
    recovery_helper = CrashRecoveryHelper(new_front, new_back)
    new_back.client.get_order.side_effect = recovery_helper.mock_orders_from_db(
        db_orders
    )
    await new_back.recover_positions_from_crash()

    # Assert after recovery: two sell positions, second is current, and second leg is PARTIALLY_FILLED
    await wait_for_condition(lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies
    recovered_strategy = new_back.strategies["1000"]
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

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


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

    # Simulate crash
    await simulate_crash(front, back)

    # Simulate recovery
    new_front, new_back = create_pair("_recovery")
    db_positions = await new_front.db.get_active_positions()
    assert len(db_positions) == 1, "Should have one hop after recovery"
    db_orders = []
    for db_position in db_positions:
        db_orders.extend(await new_front.db.get_orders_by_position_id(db_position.id))
    recovery_helper = CrashRecoveryHelper(new_front, new_back)
    new_back.client.get_order.side_effect = recovery_helper.mock_orders_from_db(
        db_orders
    )
    await new_back.recover_positions_from_crash()

    # Assert after recovery: both legs are FILLED
    await wait_for_condition(lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies
    recovered_strategy = new_back.strategies["1000"]
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

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


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
    item = front.hp_list_data[0]
    assert item["buy_price"] == str(buy_price)
    assert item["quantity"] == str(quantity)
    assert item["quantity_usd"] == str(round(quantity * buy_price, 2))
    assert item["sell_price"] == str(sell_price)
    assert item["expected_return"] == "200.0"
    assert item["state"] == "BOUGHT"

    # === SIMULATE CRASH ===
    await simulate_crash(front, back)

    # === PHASE 2: SIMULATE APPLICATION RESTART ===
    new_front, new_back = create_pair("_recovery")
    assert isinstance(new_front, HpFront)
    assert isinstance(new_back, StrategyExecutor)

    new_sim = HPSimulator(front=new_front, back=new_back)

    # Verify database has the position data before recovery
    db_positions = await new_front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    recovery_helper = CrashRecoveryHelper(new_front, new_back)
    new_back.client.get_order.side_effect = recovery_helper.mock_orders_from_db(
        db_orders
    )

    # === MANUALLY TRIGGER CRASH RECOVERY ===
    await new_back.recover_positions_from_crash()

    # === DETAILED POST-RECOVERY ASSERTIONS ===
    await wait_for_condition(lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies
    recovered_strategy = new_back.strategies["1000"]
    assert recovered_strategy.sell.current_position.config.coin == "DYM"
    assert recovered_strategy.sell.current_position.config.sell_price == sell_price
    assert recovered_strategy.state == State.BOUGHT
    assert recovered_strategy.sell.current_position.config.symbol.is_convert_only

    # Wait for frontend to reflect the convert-only position
    await wait_for_condition(condition_func=lambda: new_front.hp_list_data)
    item = new_front.hp_list_data[0]
    assert item["buy_price"] == str(buy_price)
    assert item["quantity"] == str(quantity)
    assert item["quantity_usd"] == str(round(quantity * buy_price, 2))
    assert item["sell_price"] == str(sell_price)
    assert item["expected_return"] == "200.0"
    assert item["state"] == "BOUGHT"

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

    # Wait for conversion to be reflected in frontend

    await wait_for_condition(lambda: new_front.hp_list_data[0]["state"] == "SOLD")
    item = new_front.hp_list_data[0]

    logger.info("Item: %s", item)
    assert item["state"] == "SOLD"
    assert item["quantity"] == "100.0"
    assert item["realized_quantity"] == "100.0"
    assert item["quantity_usd"] == "1000.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["buy_price"] == str(buy_price)
    assert item["sell_price"] == str(sell_price)
    assert item["expected_return"] == "200.0"
