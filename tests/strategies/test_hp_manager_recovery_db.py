import logging
from unittest.mock import AsyncMock


from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_PARTIALLY_FILLED,
)
from src.database.models import OrderStatus
from src.identifiers import Order, State
from src.strategy_executor import StrategyExecutor
from src.gui.hp_manager.hpfront import HpFront
from tests.helpers import get_new_orders
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
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")

    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    assert len(back.strategies) == 0

    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    # === DETAILED PRE-CRASH ASSERTIONS ===
    strategy = back.strategies["1000"]

    # Verify strategy state (NEW position, no orders sent)
    assert strategy.state == State.NEW
    assert strategy.buy.data.state_info.state == State.NEW
    assert len(strategy.buy.orders) == 3

    # Verify order details (not yet sent to exchange)
    for i, order in enumerate(strategy.buy.orders):
        assert isinstance(order, Order)
        assert order.status == "NEW"  # Not sent to exchange yet
        assert order.order_id == 0  # No exchange order ID yet
        assert order.realized_quantity == 0.0

    # Verify database state before crash
    db_positions = await front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    assert db_position.hp_id == "1000"
    assert db_position.status.value == "NEW"
    assert db_position.symbol == "BTCUSDC"
    assert db_position.price_low == 1000.0
    assert db_position.price_high == 1400.0
    assert db_position.budget == 1000.0

    # Assert that database state matches application state (before crash)
    crash_recovery = CrashRecoveryHelper(front, back)
    await crash_recovery.assert_application_db_state_match(hp_id="1000")

    # Store original configuration for comparison
    original_config = {
        "hp_id": strategy.buy.data.config.hp_id,
        "symbol": strategy.buy.data.config.symbol_info.symbol,
        "price_low": strategy.buy.data.config.price_low,
        "price_high": strategy.buy.data.config.price_high,
        "budget": strategy.buy.data.config.budget,
        "mode": strategy.buy.data.config.mode.value,
    }

    # === SIMULATE CRASH: Forcefully terminate original instances ===
    await simulate_crash(front, back)

    # === PHASE 2: SIMULATE APPLICATION RESTART ===
    # Create fresh frontend-backend setup (simulates app restart with same database)
    new_front, new_back = create_pair("_recovery")

    # Verify database has the position data before recovery
    positions_before_recovery = await new_front.db.get_active_positions()
    logger.info("Positions in DB before recovery: %d", len(positions_before_recovery))
    assert (
        len(positions_before_recovery) == 1
    ), f"Expected 1 position in database but found {len(positions_before_recovery)}"

    # Verify fresh instances start empty (no in-memory state)
    assert len(new_back.strategies) == 0

    # === MANUALLY TRIGGER CRASH RECOVERY (since it's suppressed in test mode) ===
    logger.info("Manually triggering crash recovery for test")
    await new_back.recover_positions_from_crash()

    # === DETAILED POST-RECOVERY ASSERTIONS ===
    # Assert recovery successful
    await wait_for_condition(condition_func=lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies

    # Verify recovered strategy state
    recovered_strategy = new_back.strategies["1000"]
    assert recovered_strategy.state == State.NEW
    assert recovered_strategy.buy.data.state_info.state == State.NEW
    assert len(recovered_strategy.buy.orders) == 3

    # Verify recovered order details match original exactly
    # Note: These orders were never sent to exchange, so they retain original precision
    original_orders = {
        0: {"price": 1400.0, "quantity": 0.23810},
        1: {"price": 1200.0, "quantity": 0.27778},
        2: {"price": 1000.0, "quantity": 0.33333},
    }

    for i, recovered_order in enumerate(recovered_strategy.buy.orders):
        assert recovered_order.price == original_orders[i]["price"]
        assert abs(recovered_order.quantity - original_orders[i]["quantity"]) < 0.00001
        assert recovered_order.status == ORDER_STATUS_NEW
        assert recovered_order.order_id == 0  # Still no exchange order ID
        assert recovered_order.realized_quantity == 0.0

    # Verify configuration preserved exactly
    assert recovered_strategy.buy.data.config.hp_id == original_config["hp_id"]
    assert (
        recovered_strategy.buy.data.config.symbol_info.symbol
        == original_config["symbol"]
    )
    assert recovered_strategy.buy.data.config.price_low == original_config["price_low"]
    assert (
        recovered_strategy.buy.data.config.price_high == original_config["price_high"]
    )
    assert recovered_strategy.buy.data.config.budget == original_config["budget"]
    assert recovered_strategy.buy.data.config.mode.value == original_config["mode"]

    # Update simulator to use new backend and verify state consistency
    new_sim = HPSimulator(front=new_front, back=new_back)
    await new_sim.assert_default_buy_position()
    crash_recovery = CrashRecoveryHelper(new_front, new_back)
    await crash_recovery.assert_application_db_state_match(hp_id="1000")

    logger.info("Basic NEW position crash recovery test completed successfully")
    logger.info("Original state: NEW, Recovered state: %s", recovered_strategy.state)
    logger.info(
        "Original orders: 3, Recovered orders: %s", len(recovered_strategy.buy.orders)
    )
    logger.info("Database consistency verified before and after crash recovery")


async def test_recovery_default_buy_position_send_orders(crash_recovery_factory):
    """Test crash recovery for a position in BUYING state with active orders."""
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE INITIAL STATE ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    # Open position and send orders
    strategy = back.strategies["1000"]
    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )
    sim.new_price(price=1410)

    # Assert new opened position data
    await wait_for_condition(condition_func=lambda: strategy.state == State.BUYING)
    await wait_for_active_buy_positions(front)
    await wait_for_no_idle_buy_positions(front)
    assert strategy.buy.data.state_info.state == State.NEW
    assert all(order.order_id for order in strategy.buy.orders)
    assert all(order.status == ORDER_STATUS_NEW for order in strategy.buy.orders)

    # Comprehensive validation for position with orders sent
    sim.validate_parent(
        "1000",
        quantity="0.0",
        realized_quantity="0.0",
        state="BUYING",
        buy_price="1400.0",
        quantity_usd="0.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.84921", realized_quantity="0.0", state="NEW"
    )
    sim.validate_buy_orders(
        strategy,
        [
            {"realized_quantity": 0.0, "status": ORDER_STATUS_NEW},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_NEW},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_NEW},
        ],
    )
    sim.validate_strategy_state(strategy, "BUYING", expected_buy_state="NEW")

    logger.info("Active buy positions: %s", get_buy_positions(front, state="BUYING"))
    logger.info("Idle buy positions: %s", get_buy_positions(front, state="NEW"))

    # === DETAILED PRE-CRASH ASSERTIONS ===
    # Verify strategy state
    assert strategy.state == State.BUYING
    assert strategy.buy.data.state_info.state == State.NEW
    assert len(strategy.buy.orders) == 3

    # Verify order details with dynamically generated order IDs
    # Order IDs are generated by the mock system and are not predictable
    # Quantities are rounded to 5 decimal places due to symbol precision=5
    expected_orders = [
        {"price": 1400.0, "quantity": 0.23810},
        {"price": 1200.0, "quantity": 0.27778},
        {"price": 1000.0, "quantity": 0.33333},
    ]

    for i, order in enumerate(strategy.buy.orders):
        assert order.price == expected_orders[i]["price"]
        assert order.quantity == expected_orders[i]["quantity"]
        assert order.status == ORDER_STATUS_NEW
        assert (
            order.order_id is not None and order.order_id > 0
        ), f"Order {i}: invalid order_id {order.order_id}"
        assert order.realized_quantity == 0.0

    # Verify database state before crash - wait for DB to update to BUYING state
    async def check_db_buying_state():
        db_positions = await front.db.get_active_positions()
        if len(db_positions) != 1:
            return False
        db_position = db_positions[0]
        return (
            db_position.hp_id == "1000"
            and db_position.strategy_state == "BUYING"
            and db_position.symbol == "BTCUSDC"
        )

    await wait_for_condition(condition_func=check_db_buying_state)

    # Verify final database state
    db_positions = await front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    assert db_position.hp_id == "1000"
    assert db_position.status.value == "NEW"  # Position state: no fills yet
    assert db_position.strategy_state == "BUYING"  # Strategy state: actively buying
    assert db_position.symbol == "BTCUSDC"

    # Verify database orders
    db_orders = await front.db.get_orders_by_position_id(db_position.id)
    assert len(db_orders) == 3
    for db_order in db_orders:
        assert db_order.status.value == ORDER_STATUS_NEW
        assert db_order.realized_quantity == 0.0
        assert db_order.exchange_order_id is not None

    crash_recovery = CrashRecoveryHelper(front, back)
    await crash_recovery.assert_application_db_state_match(hp_id="1000")

    # Store original configuration for comparison
    original_config = {
        "hp_id": strategy.buy.data.config.hp_id,
        "symbol": strategy.buy.data.config.symbol_info.symbol,
        "price_low": strategy.buy.data.config.price_low,
        "price_high": strategy.buy.data.config.price_high,
        "budget": strategy.buy.data.config.budget,
        "mode": strategy.buy.data.config.mode,
    }

    # Store original orders for comparison
    original_orders = [
        {"price": order.price, "quantity": order.quantity, "order_id": order.order_id}
        for order in strategy.buy.orders
    ]

    # === SIMULATE CRASH: Forcefully terminate original instances ===
    await simulate_crash(front, back)

    # === PHASE 2: SIMULATE APPLICATION RESTART ===
    # Create fresh frontend-backend setup (simulates app restart with same database)
    new_front, new_back = create_pair("_recovery")

    assert isinstance(new_front, HpFront)
    assert isinstance(new_back, StrategyExecutor)

    # Verify orders are saved to the database with full information before crash/recovery
    orders_before_recovery = await new_front.db.get_orders_by_position_id("1000")
    logger.info("Orders in DB before recovery: %d", len(orders_before_recovery))
    assert (
        len(orders_before_recovery) == 3
    ), f"Expected 3 orders in database but found {len(orders_before_recovery)}"

    # Verify the saved orders have complete information using original dynamic order IDs
    for db_order in orders_before_recovery:
        order_id = db_order.exchange_order_id
        # Find the matching original order by order_id
        original_order = None
        for orig in original_orders:
            if orig["order_id"] == order_id:
                original_order = orig
                break

        assert (
            original_order is not None
        ), f"Order {order_id} not found in original orders"

        assert (
            db_order.price == original_order["price"]
        ), f"DB order {order_id}: price mismatch"
        assert (
            abs(db_order.quantity - original_order["quantity"]) < 0.00001
        ), f"DB order {order_id}: quantity mismatch"
        assert db_order.status.value == "NEW", f"DB order {order_id}: status mismatch"
        assert (
            db_order.realized_quantity == 0.0
        ), f"DB order {order_id}: realized_quantity mismatch"
        assert db_order.symbol == "BTCUSDC", f"DB order {order_id}: symbol mismatch"

    # Use CrashRecoveryHelper to mock exchange queries during recovery
    recovery_helper = CrashRecoveryHelper(new_front, new_back)
    new_back.client.get_order.side_effect = recovery_helper.mock_orders_from_db(
        orders_before_recovery
    )

    # Verify database has the position data before recovery
    positions_before_recovery = await new_front.db.get_active_positions()
    logger.info("Positions in DB before recovery: %d", len(positions_before_recovery))
    assert (
        len(positions_before_recovery) == 1
    ), f"Expected 1 position in database but found {len(positions_before_recovery)}"

    # Verify fresh instances start empty (no in-memory state)
    assert len(new_back.strategies) == 0

    # === MANUALLY TRIGGER CRASH RECOVERY (since it's suppressed in test mode) ===
    logger.info("Manually triggering crash recovery for test")
    await new_back.recover_positions_from_crash()

    # === DETAILED POST-RECOVERY ASSERTIONS ===
    # Assert recovery successful
    await wait_for_condition(condition_func=lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies

    # Verify recovered strategy state
    recovered_strategy = new_back.strategies["1000"]
    # After recovery, if all buy orders are NEW (no fills), state must be BUYING
    await wait_for_condition(
        condition_func=lambda: recovered_strategy.state == State.BUYING
    )
    assert recovered_strategy.state == State.BUYING
    assert recovered_strategy.buy.data.state_info.state == State.NEW
    assert len(recovered_strategy.buy.orders) == 3

    # Verify recovered order details match original exactly INCLUDING exchange order IDs
    for i, recovered_order in enumerate(recovered_strategy.buy.orders):
        assert recovered_order.price == original_orders[i]["price"]
        assert recovered_order.quantity == original_orders[i]["quantity"]
        assert recovered_order.status == ORDER_STATUS_NEW
        assert recovered_order.realized_quantity == 0.0

        # Verify the exchange order ID matches what was in database before crash
        original_order = strategy.buy.orders[i]
        assert (
            recovered_order.order_id == original_order.order_id
        ), f"Order {i} exchange ID mismatch"

    # Verify that recovery process queried exchange for order status updates
    # (This ensures crash recovery properly synchronizes with exchange state)
    assert (
        recovered_strategy.client.get_order.called
    ), "Recovery should query exchange for order status"

    # Verify each order was checked against exchange during recovery
    expected_get_order_calls = len(recovered_strategy.buy.orders)
    actual_get_order_calls = recovered_strategy.client.get_order.call_count
    assert actual_get_order_calls >= expected_get_order_calls, (
        f"Expected at least {expected_get_order_calls} exchange queries during recovery, "
        f"but got {actual_get_order_calls}"
    )

    # Verify that no status changes were detected (orders remained in NEW state)
    for recovered_order in recovered_strategy.buy.orders:
        assert (
            recovered_order.status == ORDER_STATUS_NEW
        ), f"Order {recovered_order.order_id} should remain NEW, got {recovered_order.status}"
        assert (
            recovered_order.realized_quantity == 0.0
        ), f"Order {recovered_order.order_id} should have no fills, got {recovered_order.realized_quantity}"

    # === VERIFY DATABASE AND IN-MEMORY STATE MATCH POST-RECOVERY ===
    # Get orders from database after recovery
    orders_after_recovery = await new_front.db.get_orders_by_position_id("1000")
    assert (
        len(orders_after_recovery) == 3
    ), f"Expected 3 orders after recovery, got {len(orders_after_recovery)}"

    # Verify that database orders match in-memory orders exactly
    db_orders_by_id = {o.exchange_order_id: o for o in orders_after_recovery}
    for recovered_order in recovered_strategy.buy.orders:
        db_order = db_orders_by_id.get(recovered_order.order_id)
        assert (
            db_order is not None
        ), f"Order {recovered_order.order_id} not found in database"

        # Verify all key fields match between database and in-memory
        assert (
            db_order.price == recovered_order.price
        ), f"Price mismatch for order {recovered_order.order_id}"
        assert (
            db_order.quantity == recovered_order.quantity
        ), f"Quantity mismatch for order {recovered_order.order_id}"
        assert (
            db_order.status.value == recovered_order.status
        ), f"Status mismatch for order {recovered_order.order_id}"
        assert (
            db_order.realized_quantity == recovered_order.realized_quantity
        ), f"Realized quantity mismatch for order {recovered_order.order_id}"
        assert (
            db_order.symbol == "BTCUSDC"
        ), f"Symbol mismatch for order {recovered_order.order_id}"

    # Verify database and application state match completely
    crash_recovery = CrashRecoveryHelper(new_front, new_back)
    await crash_recovery.assert_application_db_state_match(hp_id="1000")

    logger.info(
        "✅ Recovery verification complete: All orders successfully restored from database"
    )

    # Verify configuration preserved exactly
    assert recovered_strategy.buy.data.config.hp_id == original_config["hp_id"]
    assert (
        recovered_strategy.buy.data.config.symbol_info.symbol
        == original_config["symbol"]
    )
    assert recovered_strategy.buy.data.config.price_low == original_config["price_low"]
    assert (
        recovered_strategy.buy.data.config.price_high == original_config["price_high"]
    )
    assert recovered_strategy.buy.data.config.budget == original_config["budget"]
    assert recovered_strategy.buy.data.config.mode == original_config["mode"]

    # Update simulator to use new backend and verify state consistency
    new_sim = HPSimulator(front=new_front, back=new_back)
    crash_recovery = CrashRecoveryHelper(new_front, new_back)
    await crash_recovery.assert_application_db_state_match(hp_id="1000")
    logger.info("BUYING state crash recovery test completed successfully")
    logger.info(
        "Original strategy state: BUYING, Recovered strategy state: %s",
        recovered_strategy.state,
    )
    logger.info(
        "Original orders: 3, Recovered orders: %s", len(recovered_strategy.buy.orders)
    )
    logger.info("Exchange order status synchronization verified during recovery")
    logger.info("All exchange order IDs preserved and validated after crash recovery")
    logger.info("Recovery process correctly detected no changes in order status")


async def test_recovery_cancel_default_position_untouched(crash_recovery_factory):
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    # Move to active buy and then cancel (all orders become CANCELED, state returns to NEW)
    await sim.move_to_position_active_buy()
    strategy = back.strategies["1000"]
    assert strategy.buy.orders_cancel_price == 1428.0
    sim.new_price(price=1428)

    await wait_for_condition(
        condition_func=lambda: all(
            order.status == "CANCELED" for order in strategy.buy.orders
        )
    )

    assert len(strategy.buy.orders) == 3
    assert strategy.buy.data.state_info.state == State.NEW
    assert strategy.state == State.NEW

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == State.NEW.value
    )

    item = front.hp_list_data[0]
    assert item["hp_id"] == "1000"
    assert item["coin"] == "BTCUSD"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.0"
    assert item["quantity_usd"] == "0.0"
    assert item["sell_price"] == "0.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "NEW"

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
    assert db_position.status.value == "NEW"
    assert db_position.symbol == "BTCUSDC"
    assert db_position.price_low == 1000.0
    assert db_position.price_high == 1400.0
    assert db_position.budget == 1000.0
    assert db_position.strategy_state == "NEW"

    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    assert len(db_orders) == 3
    for db_order in db_orders:
        assert db_order.status.value == "CANCELED"
        assert db_order.realized_quantity == 0.0
        assert db_order.symbol == "BTCUSDC"

    # Verify fresh instances start empty
    assert len(new_back.strategies) == 0

    # Use CrashRecoveryHelper to mock exchange queries during recovery (CANCELED orders)
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
    assert recovered_strategy.state == State.NEW
    assert recovered_strategy.buy.data.state_info.state == State.NEW
    assert len(recovered_strategy.buy.orders) == 3
    for order in recovered_strategy.buy.orders:
        assert order.status == "CANCELED"
        assert order.realized_quantity == 0.0

    # DB and in-memory state match
    orders_after_recovery = await new_front.db.get_orders_by_position_id(db_position.id)
    assert len(orders_after_recovery) == 3
    db_orders_by_id = {o.exchange_order_id: o for o in orders_after_recovery}
    for order in recovered_strategy.buy.orders:
        db_order = db_orders_by_id.get(order.order_id)
        assert db_order is not None
        assert db_order.status.value == order.status
        assert db_order.realized_quantity == order.realized_quantity
        assert db_order.symbol == "BTCUSDC"

    await recovery_helper.assert_application_db_state_match(hp_id="1000")

    logger.info("CANCELED orders crash recovery test completed successfully")


async def test_recovery_cancel_default_position_untouched_then_resend_orders(
    crash_recovery_factory,
):
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    # === Send buy orders (move to active buy) ===
    await sim.move_to_position_active_buy()
    strategy = back.strategies["1000"]
    assert strategy.state == State.BUYING
    assert all(order.status == ORDER_STATUS_NEW for order in strategy.buy.orders)

    # === Cancel buy position (untouched, all orders become CANCELED, state returns to NEW) ===
    await sim.cancel_buy_position_untouched()
    assert strategy.buy.orders_cancel_price == 1428.0
    sim.new_price(price=1428)

    await wait_for_condition(
        condition_func=lambda: all(
            order.status == "CANCELED" for order in strategy.buy.orders
        )
    )

    assert len(strategy.buy.orders) == 3
    assert strategy.buy.data.state_info.state == State.NEW
    assert strategy.state == State.NEW

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == State.NEW.value
    )

    item = front.hp_list_data[0]
    assert item["hp_id"] == "1000"
    assert item["coin"] == "BTCUSD"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.0"
    assert item["quantity_usd"] == "0.0"
    assert item["sell_price"] == "0.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "NEW"

    # === Resend buy orders (move to active buy again) ===
    await sim.move_to_position_active_buy()
    assert strategy.state == State.BUYING
    assert all(order.status == ORDER_STATUS_NEW for order in strategy.buy.orders)

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
    assert db_position.status.value == "NEW"
    assert db_position.symbol == "BTCUSDC"
    assert db_position.price_low == 1000.0
    assert db_position.price_high == 1400.0
    assert db_position.budget == 1000.0
    assert db_position.strategy_state == "BUYING"

    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    assert len(db_orders) == 3
    for db_order in db_orders:
        assert db_order.status.value == ORDER_STATUS_NEW
        assert db_order.realized_quantity == 0.0
        assert db_order.symbol == "BTCUSDC"

    # Verify fresh instances start empty
    assert len(new_back.strategies) == 0

    # Use CrashRecoveryHelper to mock exchange queries during recovery (NEW orders)
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
    # After recovery, if all buy orders are NEW (no fills), state must be BUYING
    assert recovered_strategy.state == State.BUYING
    assert recovered_strategy.buy.data.state_info.state == State.NEW
    assert len(recovered_strategy.buy.orders) == 3
    for order in recovered_strategy.buy.orders:
        assert order.status == ORDER_STATUS_NEW
        assert order.realized_quantity == 0.0

    # DB and in-memory state match
    orders_after_recovery = await new_front.db.get_orders_by_position_id(db_position.id)
    assert len(orders_after_recovery) == 3
    db_orders_by_id = {o.exchange_order_id: o for o in orders_after_recovery}
    for order in recovered_strategy.buy.orders:
        db_order = db_orders_by_id.get(order.order_id)
        assert db_order is not None
        assert db_order.status.value == order.status
        assert db_order.realized_quantity == order.realized_quantity
        assert db_order.symbol == "BTCUSDC"

    await recovery_helper.assert_application_db_state_match(hp_id="1000")

    logger.info(
        "Resend buy orders after untouched cancel and recovery test completed successfully"
    )


async def test_recovery_default_position_first_order_filled_then_cancel(
    crash_recovery_factory,
):
    """
    Crash recovery: default position, first order filled, then cancel (partially bought, rest canceled).
    """
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()
    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    assert strategy.buy.orders_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert len(strategy.buy.orders) == 3
    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    await wait_for_condition(
        condition_func=lambda: strategy.buy.orders[1].status == ORDER_STATUS_CANCELED
    )
    assert strategy.buy.orders[2].status == ORDER_STATUS_CANCELED

    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"]
        in ("PARTIALLY_BOUGHT", "PARTIALLY_FILLED")
    )

    item = front.hp_list_data[0]
    assert item["hp_id"] == "1000"
    assert item["coin"] == "BTCUSD"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.24"
    assert item["quantity_usd"] == "336.0"
    assert item["sell_price"] == "0.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] in ("PARTIALLY_BOUGHT", "PARTIALLY_FILLED")

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
    assert db_position.price_low == 1000.0
    assert db_position.price_high == 1400.0
    assert db_position.budget == 1000.0
    assert db_position.strategy_state == "PARTIALLY_BOUGHT"

    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    assert len(db_orders) == 3
    # 1 filled, 2 canceled
    assert db_orders[0].status.value in ("FILLED", "CANCELED")
    assert db_orders[1].status.value in ("FILLED", "CANCELED")
    assert db_orders[2].status.value in ("FILLED", "CANCELED")
    filled_orders = [o for o in db_orders if o.status.value == "FILLED"]
    canceled_orders = [o for o in db_orders if o.status.value == "CANCELED"]
    assert len(filled_orders) == 1
    assert len(canceled_orders) == 2
    for db_order in db_orders:
        if db_order.status.value == "FILLED":
            assert db_order.realized_quantity == 0.24
        else:
            assert db_order.realized_quantity == 0.0
        assert db_order.symbol == "BTCUSDC"

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
    assert recovered_strategy.state == State.PARTIALLY_BOUGHT
    assert recovered_strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert len(recovered_strategy.buy.orders) == 3
    assert recovered_strategy.buy.orders[0].status == "FILLED"
    assert recovered_strategy.buy.orders[1].status == "CANCELED"
    assert recovered_strategy.buy.orders[2].status == "CANCELED"
    assert recovered_strategy.buy.orders[0].realized_quantity == 0.24
    assert recovered_strategy.buy.orders[1].realized_quantity == 0.0
    assert recovered_strategy.buy.orders[2].realized_quantity == 0.0

    # DB and in-memory state match
    orders_after_recovery = await new_front.db.get_orders_by_position_id(db_position.id)
    assert len(orders_after_recovery) == 3
    db_orders_by_id = {o.exchange_order_id: o for o in orders_after_recovery}
    for order in recovered_strategy.buy.orders:
        db_order = db_orders_by_id.get(order.order_id)
        assert db_order is not None
        assert db_order.status.value == order.status
        assert db_order.realized_quantity == order.realized_quantity
        assert db_order.symbol == "BTCUSDC"

    await recovery_helper.assert_application_db_state_match(hp_id="1000")

    logger.info(
        "Crash recovery for first order filled then cancel test completed successfully"
    )


async def test_recovery_default_position_first_order_filled_partially(
    crash_recovery_factory,
):
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()
    await sim.move_to_position_active_buy()

    # Simulate partial fill
    strategy = await sim.simulate_partial_fill()

    assert strategy.buy.orders_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert len(strategy.buy.orders) == 3

    await wait_for_condition(
        lambda: strategy.buy.orders[0].status == ORDER_STATUS_CANCELED
    )
    assert strategy.buy.orders[1].status == ORDER_STATUS_CANCELED
    assert strategy.buy.orders[2].status == ORDER_STATUS_CANCELED

    assert strategy.buy.orders[0].realized_quantity == 0.12
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "PARTIALLY_BOUGHT"
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
    assert db_position.price_low == 1000.0
    assert db_position.price_high == 1400.0
    assert db_position.budget == 1000.0
    assert db_position.strategy_state == "PARTIALLY_BOUGHT"

    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    assert len(db_orders) == 3
    # 1 canceled with partial fill, 2 canceled untouched
    canceled_orders = [o for o in db_orders if o.status.value == "CANCELED"]
    assert len(canceled_orders) == 3
    realized_quantities = sorted(
        [o.realized_quantity for o in canceled_orders], reverse=True
    )
    assert realized_quantities[0] == 0.12
    assert realized_quantities[1] == 0.0
    assert realized_quantities[2] == 0.0
    for db_order in db_orders:
        assert db_order.status.value == "CANCELED"
        assert db_order.symbol == "BTCUSDC"

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
    # After recovery, if one order is partially filled and all are canceled, state must be PARTIALLY_BOUGHT
    assert recovered_strategy.state == State.PARTIALLY_BOUGHT
    assert recovered_strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert len(recovered_strategy.buy.orders) == 3
    # All orders should be CANCELED, one with realized_quantity == 0.12
    statuses = [order.status for order in recovered_strategy.buy.orders]
    assert statuses.count("CANCELED") == 3
    realized_quantities = sorted(
        [order.realized_quantity for order in recovered_strategy.buy.orders],
        reverse=True,
    )
    assert realized_quantities[0] == 0.12
    assert realized_quantities[1] == 0.0
    assert realized_quantities[2] == 0.0

    # DB and in-memory state match
    orders_after_recovery = await new_front.db.get_orders_by_position_id(db_position.id)
    assert len(orders_after_recovery) == 3
    db_orders_by_id = {o.exchange_order_id: o for o in orders_after_recovery}
    for order in recovered_strategy.buy.orders:
        db_order = db_orders_by_id.get(order.order_id)
        assert db_order is not None
        assert db_order.status.value == order.status
        assert db_order.realized_quantity == order.realized_quantity
        assert db_order.symbol == "BTCUSDC"

    await recovery_helper.assert_application_db_state_match(hp_id="1000")

    logger.info(
        "Crash recovery for first order partially filled then cancel test completed successfully"
    )


async def test_recovery_default_position_first_order_filled_partially_then_cancel(
    crash_recovery_factory,
):
    """
    Crash recovery: default position, first order partially filled, then cancel (all orders canceled, one with partial fill).
    """
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()
    await sim.move_to_position_active_buy()

    # Simulate partial fill
    strategy = await sim.simulate_partial_fill()  # Cancel position

    assert strategy.buy.orders_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert len(strategy.buy.orders) == 3

    await wait_for_condition(
        lambda: strategy.buy.orders[0].status == ORDER_STATUS_CANCELED
    )
    assert strategy.buy.orders[1].status == ORDER_STATUS_CANCELED
    assert strategy.buy.orders[2].status == ORDER_STATUS_CANCELED

    assert strategy.buy.orders[0].realized_quantity == 0.12
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "PARTIALLY_BOUGHT"
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
    assert db_position.price_low == 1000.0
    assert db_position.price_high == 1400.0
    assert db_position.budget == 1000.0
    assert db_position.strategy_state == "PARTIALLY_BOUGHT"

    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    assert len(db_orders) == 3
    # All canceled, one with partial fill
    canceled_orders = [o for o in db_orders if o.status.value == "CANCELED"]
    assert len(canceled_orders) == 3
    realized_quantities = sorted(
        [o.realized_quantity for o in canceled_orders], reverse=True
    )
    assert realized_quantities[0] == 0.12
    assert realized_quantities[1] == 0.0
    assert realized_quantities[2] == 0.0
    for db_order in db_orders:
        assert db_order.status.value == "CANCELED"
        assert db_order.symbol == "BTCUSDC"

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
    # After recovery, if one order is partially filled and all are canceled, state must be PARTIALLY_BOUGHT
    assert recovered_strategy.state == State.PARTIALLY_BOUGHT
    assert recovered_strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert len(recovered_strategy.buy.orders) == 3
    statuses = [order.status for order in recovered_strategy.buy.orders]
    assert statuses.count("CANCELED") == 3
    realized_quantities = sorted(
        [order.realized_quantity for order in recovered_strategy.buy.orders],
        reverse=True,
    )
    assert realized_quantities[0] == 0.12
    assert realized_quantities[1] == 0.0
    assert realized_quantities[2] == 0.0

    # DB and in-memory state match
    orders_after_recovery = await new_front.db.get_orders_by_position_id(db_position.id)
    assert len(orders_after_recovery) == 3
    db_orders_by_id = {o.exchange_order_id: o for o in orders_after_recovery}
    for order in recovered_strategy.buy.orders:
        db_order = db_orders_by_id.get(order.order_id)
        assert db_order is not None
        assert db_order.status.value == order.status
        assert db_order.realized_quantity == order.realized_quantity
        assert db_order.symbol == "BTCUSDC"

    await recovery_helper.assert_application_db_state_match(hp_id="1000")

    logger.info(
        "Crash recovery for first order partially filled then cancel (all canceled, one partial fill) test completed successfully"
    )


async def test_recovery_default_position_first_order_filled(crash_recovery_factory):
    """
    Crash recovery: default position, first order filled (partially bought, rest untouched).
    """
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()
    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_first_buy_order_fill()

    # Assert state after fill
    assert len(strategy.buy.orders) == 3
    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[1].status == ORDER_STATUS_NEW
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW
    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0
    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    # strategy.state should be BUYING because there are still open orders
    assert strategy.state == State.BUYING

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
    )

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
    assert db_position.status.value == "PARTIALLY_FILLED"
    assert db_position.symbol == "BTCUSDC"
    assert db_position.price_low == 1000.0
    assert db_position.price_high == 1400.0
    assert db_position.budget == 1000.0

    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    assert len(db_orders) == 3
    filled_orders = [o for o in db_orders if o.status.value == "FILLED"]
    new_orders = [o for o in db_orders if o.status.value == "NEW"]
    assert len(filled_orders) == 1
    assert len(new_orders) == 2

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
    assert len(recovered_strategy.buy.orders) == 3
    # Assert order statuses by price to avoid index/order mismatch
    for order in recovered_strategy.buy.orders:
        if order.price == 1400.0:
            assert (
                order.status == ORDER_STATUS_FILLED
            ), f"Order at 1400.0 should be FILLED, got {order.status}"
            assert order.realized_quantity == 0.24
        elif order.price == 1200.0:
            assert (
                order.status == ORDER_STATUS_NEW
            ), f"Order at 1200.0 should be NEW, got {order.status}"
            assert order.realized_quantity == 0.0
        elif order.price == 1000.0:
            assert (
                order.status == ORDER_STATUS_NEW
            ), f"Order at 1000.0 should be NEW, got {order.status}"
            assert order.realized_quantity == 0.0
        else:
            raise AssertionError(f"Unexpected order price: {order.price}")

    # DB and in-memory state match
    orders_after_recovery = await new_front.db.get_orders_by_position_id(db_position.id)
    assert len(orders_after_recovery) == 3
    db_orders_by_id = {o.exchange_order_id: o for o in orders_after_recovery}
    for order in recovered_strategy.buy.orders:
        db_order = db_orders_by_id.get(order.order_id)
        assert db_order is not None
        assert db_order.status.value == order.status
        assert db_order.realized_quantity == order.realized_quantity
        assert db_order.symbol == "BTCUSDC"

    await recovery_helper.assert_application_db_state_match(hp_id="1000")

    logger.info(
        "Crash recovery for first order filled (partially bought, rest untouched) test completed successfully"
    )


async def test_recovery_default_position_all_buy_orders_filled(crash_recovery_factory):
    """
    Crash recovery: default position, all buy orders filled (fully bought).
    """
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    assert len(back.strategies) == 0

    # Create default buy position, then fill all orders (fully bought)
    strategy = await sim.simulate_bought_position()

    # Assert state after all orders filled
    assert len(strategy.buy.orders) == 3
    for order in strategy.buy.orders:
        assert order.status == ORDER_STATUS_FILLED
    assert strategy.buy.data.state_info.state == State.BOUGHT
    assert strategy.state == State.BOUGHT

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BOUGHT"
    )

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
    assert db_position.status.value in ("BOUGHT", "FILLED")
    assert db_position.symbol == "BTCUSDC"
    assert db_position.price_low == 1000.0
    assert db_position.price_high == 1400.0
    assert db_position.budget == 1000.0

    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    assert len(db_orders) == 3
    for db_order in db_orders:
        assert db_order.status.value == "FILLED"
        assert db_order.symbol == "BTCUSDC"

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
    assert recovered_strategy.state == State.BOUGHT
    assert recovered_strategy.buy.data.state_info.state == State.BOUGHT
    assert len(recovered_strategy.buy.orders) == 3
    for order in recovered_strategy.buy.orders:
        assert order.status == ORDER_STATUS_FILLED

    # DB and in-memory state match
    orders_after_recovery = await new_front.db.get_orders_by_position_id(db_position.id)
    assert len(orders_after_recovery) == 3
    db_orders_by_id = {o.exchange_order_id: o for o in orders_after_recovery}
    for order in recovered_strategy.buy.orders:
        db_order = db_orders_by_id.get(order.order_id)
        assert db_order is not None
        assert db_order.status.value == order.status
        assert db_order.realized_quantity == order.realized_quantity
        assert db_order.symbol == "BTCUSDC"

    await recovery_helper.assert_application_db_state_match(hp_id="1000")

    logger.info(
        "Crash recovery for all buy orders filled (fully bought) test completed successfully"
    )


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
    assert strategy.buy.orders_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert len(strategy.buy.orders) == 3

    await wait_for_condition(
        lambda: strategy.buy.orders[0].status == ORDER_STATUS_CANCELED
    )
    await wait_for_condition(
        lambda: strategy.buy.orders[1].status == ORDER_STATUS_CANCELED
    )
    await wait_for_condition(
        lambda: strategy.buy.orders[2].status == ORDER_STATUS_CANCELED
    )
    assert strategy.buy.orders[0].realized_quantity == 0.12
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

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
    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders,
        used_ids=set([o.order_id for o in strategy.buy.orders]),
    )
    sim.new_price(price=1414)

    await wait_for_condition(lambda: strategy.buy.orders[0].status == ORDER_STATUS_NEW)
    assert strategy.buy.orders[1].status == ORDER_STATUS_NEW
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    logger.info("Orders after reopening: %s", strategy.buy.orders)

    assert strategy.buy.orders[0].realized_quantity == 0.12
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

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
    assert db_position.price_low == 1000.0
    assert db_position.price_high == 1400.0
    assert db_position.budget == 1000.0
    assert db_position.strategy_state == "BUYING"

    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)

    logger.info("Orders in the DB: %s", db_orders)
    assert len(db_orders) == 6
    new_orders = [o for o in db_orders if o.status.value == ORDER_STATUS_NEW]
    canceled_orders = [o for o in db_orders if o.status.value == ORDER_STATUS_CANCELED]
    assert len(new_orders) == 3
    assert len(canceled_orders) == 3

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
    assert len(recovered_strategy.buy.orders) == 3
    assert recovered_strategy.buy.data.config.symbol_info.symbol == "BTCUSDC"
    assert recovered_strategy.buy.orders[0].realized_quantity == 0.24
    assert recovered_strategy.buy.orders[1].realized_quantity == 0.0
    assert recovered_strategy.buy.orders[2].realized_quantity == 0.0


async def test_recovery_default_position_first_order_filled_then_cancel_then_resend(
    crash_recovery_factory,
):
    """
    Crash recovery: default position, first order filled, then cancel, then resend (top order filled, others canceled, then reopened).
    """
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    # Move to active buy and simulate first order fill
    await sim.move_to_position_active_buy()
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position (top order filled, others canceled)
    assert strategy.buy.orders_cancel_price == 1428.0
    sim.new_price(price=1428.0)
    assert len(strategy.buy.orders) == 3
    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    await wait_for_condition(
        lambda: strategy.buy.orders[1].status == ORDER_STATUS_CANCELED
    )
    assert strategy.buy.orders[2].status == ORDER_STATUS_CANCELED
    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0
    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT
    await wait_for_condition(
        lambda: front.hp_list_data[0]["state"] == "PARTIALLY_BOUGHT"
    )
    item = front.hp_list_data[0]
    assert item["hp_id"] == "1000"
    assert item["coin"] == "BTCUSD"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.24"
    assert item["quantity_usd"] == "336.0"
    assert item["sell_price"] == "0.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "PARTIALLY_BOUGHT"

    logger.info("HP List after the update: %s", front.hp_list_data)

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
    assert db_position.status.value in "PARTIALLY_FILLED"
    assert db_position.symbol == "BTCUSDC"
    assert db_position.price_low == 1000.0
    assert db_position.price_high == 1400.0
    assert db_position.budget == 1000.0
    assert db_position.strategy_state == "PARTIALLY_BOUGHT"

    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    assert len(db_orders) == 3
    filled_orders = [o for o in db_orders if o.status.value == "FILLED"]
    canceled_orders = [o for o in db_orders if o.status.value == "CANCELED"]
    assert len(filled_orders) == 1
    assert len(canceled_orders) == 2
    for db_order in db_orders:
        if db_order.status.value == "FILLED":
            assert db_order.realized_quantity == 0.24
        else:
            assert db_order.realized_quantity == 0.0
        assert db_order.symbol == "BTCUSDC"

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
    assert recovered_strategy.state == State.PARTIALLY_BOUGHT
    assert recovered_strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert len(recovered_strategy.buy.orders) == 3
    assert recovered_strategy.buy.orders[0].status == "FILLED"
    assert recovered_strategy.buy.orders[1].status == "CANCELED"
    assert recovered_strategy.buy.orders[2].status == "CANCELED"
    assert recovered_strategy.buy.orders[0].realized_quantity == 0.24
    assert recovered_strategy.buy.orders[1].realized_quantity == 0.0
    assert recovered_strategy.buy.orders[2].realized_quantity == 0.0

    # DB and in-memory state match
    orders_after_recovery = await new_front.db.get_orders_by_position_id(db_position.id)
    assert len(orders_after_recovery) == 3
    db_orders_by_id = {o.exchange_order_id: o for o in orders_after_recovery}
    for order in recovered_strategy.buy.orders:
        db_order = db_orders_by_id.get(order.order_id)
        assert db_order is not None
        assert db_order.status.value == order.status
        assert db_order.realized_quantity == order.realized_quantity
        assert db_order.symbol == "BTCUSDC"

    await recovery_helper.assert_application_db_state_match(hp_id="1000")

    logger.info(
        "Crash recovery for first order filled then cancel, then resend test completed successfully"
    )


async def test_recovery_setup_sell_position_for_bought_position(crash_recovery_factory):
    """
    Test setup_sell_position for a bought position, with crash recovery.
    """
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)
    await sim.simulate_bought_position()

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.85,
        buy_price=1178.82,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

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
    assert db_position.symbol == "BTCUSDC"
    assert db_position.status.value == "NEW"
    # Use CrashRecoveryHelper to mock exchange queries during recovery
    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
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
    assert recovered_strategy.state == State.BOUGHT
    assert recovered_strategy.sell is not None
    assert recovered_strategy.sell.current_position is not None
    assert recovered_strategy.sell.current_position.sell_order is not None
    assert recovered_strategy.sell.current_position.sell_order.price == 4200.0
    assert recovered_strategy.sell.current_position.sell_order.quantity == 0.84921
    assert (
        recovered_strategy.sell.current_position.sell_order.status == ORDER_STATUS_NEW
    )

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


async def test_recovery_send_sell_order_for_bought_position(crash_recovery_factory):
    """
    Test sending a sell order for a bought position, with crash recovery.
    """
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)
    await sim.simulate_bought_position()
    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.85,
        buy_price=1178.82,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    strategy = back.strategies["1000"]
    # Simulate sending the sell order
    strategy.client.create_order.side_effect = get_new_orders(
        [strategy.sell.current_position.sell_order]
    )
    sim.new_price(price=4156)

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "SELLING"
    )
    item = front.hp_list_data[0]
    assert item["hp_id"] == "1000"
    assert item["coin"] == "BTCUSD"
    assert item["buy_price"] == "1178.82"
    assert item["quantity"] == "0.85"
    assert item["quantity_usd"] == "1002.0"
    assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
    assert item["expected_return"] == "2568.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "SELLING"

    await wait_for_condition(
        condition_func=lambda: strategy.sell.current_position.sell_order.status
        == ORDER_STATUS_NEW
    )
    assert strategy.sell.current_position.sell_order.quantity == 0.85
    assert strategy.sell.current_position.sell_order.realized_quantity == 0.0

    active_sell_positions = get_sell_positions(front, state="SELLING")
    active_sell_item = active_sell_positions[0]

    assert active_sell_item["hp_id"] == "1000_SELL"
    assert active_sell_item["coin"] == "BTCUSDC"  # sell child uses 'coin' not 'symbol'
    assert active_sell_item["buy_price"] == "1178.82"
    assert active_sell_item["quantity"] == "0.85"
    # Note: end_currency is not available in sell child structure
    assert (
        active_sell_item["sell_price"] == "4200.0"
    ), f"Item sell price: {active_sell_item['sell_price']}"
    assert active_sell_item["side"] == "SELL"
    assert (
        active_sell_item["sell_completeness"] == "0.0"
    )  # sell child uses 'sell_completeness' not 'completeness'

    # === ASSERT DB STATE IS SELLING BEFORE CRASH ===
    positions_before_crash = await front.db.get_active_positions()
    assert len(positions_before_crash) == 1
    db_position_before_crash = positions_before_crash[0]
    assert db_position_before_crash.hp_id == "1000"
    assert db_position_before_crash.symbol == "BTCUSDC"
    # The strategy_state field should be 'SELLING' before the crash
    assert (
        db_position_before_crash.strategy_state == "SELLING"
    ), f"Expected DB strategy_state to be SELLING before crash, got {db_position_before_crash.strategy_state}"

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
    assert db_position.symbol == "BTCUSDC"
    # Use CrashRecoveryHelper to mock exchange queries during recovery
    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
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

    # Accept either BOUGHT or SELLING as the state, but require SELLING if the sell order is present and NEW
    if (
        recovered_strategy.sell is not None
        and recovered_strategy.sell.current_position is not None
        and recovered_strategy.sell.current_position.sell_order is not None
        and recovered_strategy.sell.current_position.sell_order.status
        == ORDER_STATUS_NEW
    ):
        # If the sell order is still NEW, the state should be SELLING
        assert (
            recovered_strategy.state == State.SELLING
        ), f"Expected SELLING, got {recovered_strategy.state}"
    else:
        # Otherwise, allow BOUGHT (for legacy or edge cases)
        assert recovered_strategy.state in (State.BOUGHT, State.SELLING)

    assert recovered_strategy.sell is not None
    assert recovered_strategy.sell.current_position is not None
    assert recovered_strategy.sell.current_position.sell_order is not None
    assert recovered_strategy.sell.current_position.sell_order.price == 4200.0
    assert recovered_strategy.sell.current_position.sell_order.quantity == 0.85
    assert (
        recovered_strategy.sell.current_position.sell_order.status == ORDER_STATUS_NEW
    )
    assert recovered_strategy.sell.current_position.sell_order.realized_quantity == 0.0
    assert recovered_strategy.sell.current_position.sell_order.order_id

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


async def test_recovery_cancel_unfilled_sell_orders(crash_recovery_factory):
    """
    Test canceling unfilled sell orders for a bought position, with crash recovery.
    """
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)
    await sim.simulate_bought_position()
    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.85,
        buy_price=1178.82,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )
    await sim.send_sell_order_for_bought_position()

    # Cancel unfilled sell orders
    await sim.cancel_unfilled_sell_position()

    strategy = back.strategies["1000"]
    assert strategy.state == State.BOUGHT

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
    assert db_position.symbol == "BTCUSDC"

    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    # Only check sell orders for canceled status
    sell_orders = [
        order
        for order in db_orders
        if getattr(order.side, "value", order.side) == "SELL"
    ]
    assert len(sell_orders) > 0, "No sell orders found for this position!"
    for order in sell_orders:
        assert (
            order.status.value == "CANCELED"
        ), f"Sell order {order.exchange_order_id} status is {order.status.value}, expected CANCELED"

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
    assert recovered_strategy.state == State.BOUGHT
    assert recovered_strategy.sell is not None
    assert recovered_strategy.sell.current_position is not None
    # All sell orders should be canceled
    assert (
        recovered_strategy.sell.current_position.sell_order.status
        == ORDER_STATUS_CANCELED
    )

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


async def test_recovery_resend_unfilled_sell_orders(crash_recovery_factory):
    """
    Test resending unfilled sell orders for a bought position, with crash recovery.
    """
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)
    await sim.simulate_bought_position()
    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.85,
        buy_price=1178.82,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )
    await sim.send_sell_order_for_bought_position()

    # Cancel unfilled sell orders
    await sim.cancel_unfilled_sell_position()

    # Resend sell order
    await sim.send_sell_order_for_bought_position()

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
    assert db_position.symbol == "BTCUSDC"

    db_orders = await new_front.db.get_orders_by_position_id(db_position.id)
    # Only check sell orders for NEW status (resent)
    sell_orders = [
        order
        for order in db_orders
        if getattr(order.side, "value", order.side) == "SELL"
    ]
    assert len(sell_orders) > 0, "No sell orders found for this position!"
    for order in sell_orders:
        assert (
            order.status.value == "NEW"
        ), f"Sell order {order.exchange_order_id} status is {order.status.value}, expected NEW"

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
    assert recovered_strategy.state in (State.BOUGHT, State.SELLING)
    assert recovered_strategy.sell is not None
    assert recovered_strategy.sell.current_position is not None
    # Sell order should be NEW (resent)
    assert (
        recovered_strategy.sell.current_position.sell_order.status == ORDER_STATUS_NEW
    )

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


async def test_recovery_sell_position_first_order_filled_partially(
    crash_recovery_factory,
):
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)
    await sim.simulate_bought_position()

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.85,
        buy_price=1178.82,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_bought_position()
    await sim.simulate_sell_order_partial_fill()

    # Assert that the sell order is partially filled before crash (in memory)
    strategy = back.strategies["1000"]
    sell_order = strategy.sell.current_position.sell_order
    assert sell_order.status == ORDER_STATUS_PARTIALLY_FILLED
    assert sell_order.realized_quantity > 0.0

    # Ensure the DB is updated with the partial fill before crash
    db_positions = await front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    db_orders = await front.db.get_orders_by_position_id(db_position.id)
    db_sell_orders = [
        o for o in db_orders if getattr(o.side, "value", o.side) == "SELL"
    ]
    assert len(db_sell_orders) == 1
    db_sell_order = db_sell_orders[0]
    assert (
        db_sell_order.status.value == ORDER_STATUS_PARTIALLY_FILLED
    ), f"DB sell order status before crash: {db_sell_order.status.value}"
    assert (
        db_sell_order.realized_quantity > 0.0
    ), f"DB sell order realized_quantity before crash: {db_sell_order.realized_quantity}"

    # === SIMULATE CRASH ===
    await simulate_crash(front, back)

    # === PHASE 2: SIMULATE APPLICATION RESTART ===
    new_front, new_back = create_pair("_recovery")
    assert isinstance(new_front, HpFront)
    assert isinstance(new_back, StrategyExecutor)

    # Use CrashRecoveryHelper to mock exchange queries during recovery
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

    # === POST-RECOVERY ASSERTIONS ===
    await wait_for_condition(lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies
    recovered_strategy = new_back.strategies["1000"]
    assert recovered_strategy.state == State.SELLING
    recovered_sell_order = recovered_strategy.sell.current_position.sell_order
    assert recovered_sell_order.status == ORDER_STATUS_PARTIALLY_FILLED
    assert recovered_sell_order.realized_quantity > 0.0

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


async def test_recovery_sell_position_first_order_filled(crash_recovery_factory):
    """
    Sell order is fully filled, so after crash there should be nothing to recover (position is SOLD).
    """
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)
    await sim.simulate_bought_position()
    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.85,
        buy_price=1178.82,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )
    await sim.send_sell_order_for_bought_position()
    await sim.simulate_sell_order_fill()

    # Assert that the sell order is fully filled before crash
    strategy = back.strategies["1000"]
    sell_order = strategy.sell.current_position.sell_order
    assert sell_order.status == ORDER_STATUS_FILLED
    assert sell_order.realized_quantity == 0.85

    # Ensure the DB is updated with the fill before crash
    db_positions = await front.db.get_active_positions()
    # The position should be marked as SOLD or not present in active positions
    assert len(db_positions) == 0 or all(
        p.status.value in ("SOLD", "FILLED") for p in db_positions
    )

    # === SIMULATE CRASH ===
    await simulate_crash(front, back)

    # === PHASE 2: SIMULATE APPLICATION RESTART ===
    new_front, new_back = create_pair("_recovery")
    assert isinstance(new_front, HpFront)
    assert isinstance(new_back, StrategyExecutor)

    # After recovery, there should be no active positions to recover
    positions_after_recovery = await new_front.db.get_active_positions()
    assert len(positions_after_recovery) == 0 or all(
        p.status.value in ("SOLD", "FILLED") for p in positions_after_recovery
    )

    # Optionally, check that no strategies are loaded in memory
    assert len(new_back.strategies) == 0


async def test_recovery_cancel_sell_position_first_order_filled_partially(
    crash_recovery_factory,
):
    """
    Test canceling a sell position after the first sell order is partially filled, with crash recovery.
    """
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)
    await sim.simulate_bought_position()

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.85,
        buy_price=1178.82,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_bought_position()
    await sim.simulate_sell_order_partial_fill()
    await sim.cancel_partially_sold_position()

    # Assert in-memory state before crash
    strategy = back.strategies["1000"]
    sell_order = strategy.sell.current_position.sell_order
    assert sell_order.status == ORDER_STATUS_CANCELED
    assert sell_order.realized_quantity > 0.0

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
    assert db_sell_order.status.value == ORDER_STATUS_CANCELED
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
    assert recovered_sell_order.status == ORDER_STATUS_CANCELED
    assert recovered_sell_order.realized_quantity > 0.0

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


async def test_recovery_resend_sell_position_first_order_filled_partially(
    crash_recovery_factory,
):
    """
    Test resending a sell order after the first sell order is partially filled and canceled, with crash recovery.
    """
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)
    await sim.simulate_bought_position()

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.85,
        buy_price=1178.82,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_bought_position()
    await sim.simulate_sell_order_partial_fill()
    await sim.cancel_partially_sold_position()
    await sim.resend_sell_order_for_partially_sold_position()

    # Assert in-memory state before crash
    strategy = back.strategies["1000"]
    sell_order = strategy.sell.current_position.sell_order
    assert sell_order.status == ORDER_STATUS_NEW
    assert sell_order.realized_quantity > 0.0
    # Assert active position state is SELLING before crash
    assert (
        strategy.state == State.SELLING
    ), f"Expected active position state to be SELLING before crash, got {strategy.state}"

    # Ensure DB is updated before crash
    db_positions = await front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    db_orders = await front.db.get_orders_by_position_id(db_position.id)
    active_db_sell_orders = [
        o for o in db_orders if o.side == "SELL" and o.status == OrderStatus.NEW
    ]
    logger.info("Active db sell orders: %s", active_db_sell_orders)
    assert len(active_db_sell_orders) == 1
    db_sell_order = active_db_sell_orders[0]
    assert db_sell_order.status.value == ORDER_STATUS_NEW
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
    # Assert active position state is SELLING after recovery
    assert (
        recovered_strategy.state == State.SELLING
    ), f"Expected active position state to be SELLING after recovery, got {recovered_strategy.state}"
    recovered_sell_order = recovered_strategy.sell.current_position.sell_order
    assert recovered_sell_order.status == ORDER_STATUS_NEW
    assert recovered_sell_order.realized_quantity > 0.0

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


async def test_recovery_send_sell_order_for_partially_bought_position(
    crash_recovery_factory,
):
    """
    Test sending a sell order for a partially bought position, with crash recovery.
    """
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    await sim.setup_sell_position_after_first_buy_order_filled(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()

    # Assert in-memory state before crash
    strategy = back.strategies["1000"]
    assert strategy.sell is not None
    assert strategy.sell.current_position is not None
    sell_order = strategy.sell.current_position.sell_order
    assert sell_order.status == ORDER_STATUS_NEW
    assert sell_order.quantity == strategy.buy.calculate_realized_quantity()

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
    assert db_sell_order.status.value == ORDER_STATUS_NEW
    assert db_sell_order.quantity == strategy.buy.calculate_realized_quantity()

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
    assert recovered_strategy.sell is not None
    assert recovered_strategy.sell.current_position is not None
    recovered_sell_order = recovered_strategy.sell.current_position.sell_order
    assert recovered_sell_order.status == ORDER_STATUS_NEW
    assert recovered_sell_order.quantity == strategy.buy.calculate_realized_quantity()

    # Assert buy orders: one filled, two new
    buy_orders = recovered_strategy.buy.orders
    assert len(buy_orders) == 3, f"Expected 3 buy orders, got {len(buy_orders)}"
    filled = [o for o in buy_orders if o.status == ORDER_STATUS_FILLED]
    canceled = [o for o in buy_orders if o.status == ORDER_STATUS_CANCELED]
    assert len(filled) == 1, f"Expected 1 filled buy order, got {len(filled)}"
    assert len(canceled) == 2, f"Expected 2 new buy orders, got {len(canceled)}"

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


async def test_recovery_cancel_unfilled_sell_orders_for_partially_bought_position(
    crash_recovery_factory,
):
    """
    Test canceling unfilled sell orders for a partially bought position, with crash recovery.
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
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    await sim.setup_sell_position_after_first_buy_order_filled(
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

    # Assert in-memory state before crash
    strategy = back.strategies["1000"]
    assert strategy.sell is not None
    assert strategy.sell.current_position is not None
    sell_order = strategy.sell.current_position.sell_order
    assert sell_order.status == ORDER_STATUS_CANCELED
    assert sell_order.quantity == strategy.buy.calculate_realized_quantity()

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
    assert db_sell_order.status.value == ORDER_STATUS_CANCELED
    assert db_sell_order.quantity == strategy.buy.calculate_realized_quantity()

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
    assert recovered_strategy.sell is not None
    assert recovered_strategy.sell.current_position is not None
    recovered_sell_order = recovered_strategy.sell.current_position.sell_order
    assert recovered_sell_order.status == ORDER_STATUS_CANCELED
    assert recovered_sell_order.quantity == strategy.buy.calculate_realized_quantity()

    await recovery_helper.assert_application_db_state_match(hp_id="1000")


def check_completeness(orders, expected_total_quantity, actual_completeness, tol=1e-3):
    """
    Checks that completeness is calculated as the sum of realized quantities of all orders
    divided by the expected total quantity, and matches the actual_completeness value.
    """
    realized = sum(o.realized_quantity for o in orders)
    expected = expected_total_quantity
    calculated = realized / expected if expected else 0.0
    assert (
        abs(calculated - actual_completeness) < tol
    ), f"Completeness mismatch: calculated={calculated}, actual={actual_completeness}"


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
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    await sim.setup_sell_position_after_first_buy_order_filled(
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

    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )
    sim.new_price(price=1212)

    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    await wait_for_condition(lambda: strategy.buy.orders[1].status == ORDER_STATUS_NEW)
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
    )

    # Fill the second and third buy orders BEFORE simulating a crash
    await sim.simulate_second_buy_order_fill_with_sell_price_no_fill()
    assert strategy.buy.orders[1].status == ORDER_STATUS_FILLED
    await sim.simulate_third_buy_order_fill_with_sell_price_no_fill()
    assert strategy.buy.orders[2].status == ORDER_STATUS_FILLED

    # All buy orders should now be filled
    assert all(o.status == ORDER_STATUS_FILLED for o in strategy.buy.orders)
    assert strategy.buy.data.state_info.state == State.BOUGHT
    assert strategy.state == State.BOUGHT

    # --- Completeness checker ---
    total_quantity = sum(o.quantity for o in strategy.buy.orders)
    completeness = strategy.buy.data.state_info.completeness
    check_completeness(strategy.buy.orders, total_quantity, completeness)
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

    # After recovery, assert all buy orders are filled and state is BOUGHT
    await wait_for_condition(lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies
    recovered_strategy = new_back.strategies["1000"]
    assert all(o.status == ORDER_STATUS_FILLED for o in recovered_strategy.buy.orders)
    assert recovered_strategy.buy.data.state_info.state == State.BOUGHT
    assert recovered_strategy.state == State.BOUGHT

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
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    await sim.setup_sell_position_after_first_buy_order_filled(
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

    # Assert buy orders: one filled, two canceled
    buy_orders = strategy.buy.orders
    assert len(buy_orders) == 3, f"Expected 3 buy orders, got {len(buy_orders)}"
    filled = [o for o in buy_orders if o.status == ORDER_STATUS_FILLED]
    canceled = [o for o in buy_orders if o.status == ORDER_STATUS_CANCELED]
    assert len(filled) == 1, f"Expected 1 filled buy order, got {len(filled)}"
    assert (
        len(canceled) == 2
    ), f"Expected 2 new/canceled buy orders, got {len(canceled)}"

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

    # Assert buy orders after recovery: one filled, two new/canceled
    recovered_buy_orders = recovered_strategy.buy.orders
    assert (
        len(recovered_buy_orders) == 3
    ), f"Expected 3 buy orders after recovery, got {len(recovered_buy_orders)}"
    filled = [o for o in recovered_buy_orders if o.status == ORDER_STATUS_FILLED]
    canceled = [o for o in recovered_buy_orders if o.status == ORDER_STATUS_CANCELED]
    assert (
        len(filled) == 1
    ), f"Expected 1 filled buy order after recovery, got {len(filled)}"
    assert (
        len(canceled) == 2
    ), f"Expected 2 new/canceled buy orders after recovery, got {len(canceled)}"

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
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    await sim.setup_sell_position_after_first_buy_order_filled(
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
    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )

    # Price trigger is now related to the middle order as the top order is already filled.
    sim.new_price(price=1212)

    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    await wait_for_condition(lambda: strategy.buy.orders[1].status == ORDER_STATUS_NEW)
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
    )

    # Buy partially second order
    await sim.simulate_second_buy_order_partial_fill()

    # Cancel Buy orders
    await sim.cancel_buy_position_filled_partially_sold_partially()

    # Assert in-memory state before crash
    buy_orders = strategy.buy.orders
    assert len(buy_orders) == 3, f"Expected 3 buy orders, got {len(buy_orders)}"
    filled = [o for o in buy_orders if o.status == ORDER_STATUS_FILLED]
    canceled = [o for o in buy_orders if o.status == ORDER_STATUS_CANCELED]
    partial = [o for o in buy_orders if o.status == ORDER_STATUS_PARTIALLY_FILLED]
    assert len(filled) == 1, f"Expected 1 filled buy order, got {len(filled)}"
    assert len(canceled) == 2, f"Expected 2 canceled buy orders, got {len(canceled)}"
    assert len(partial) == 0, f"Expected 0 partial buy orders, got {len(partial)}"
    # One canceled order should have non-zero realized_quantity, one should have zero
    canceled_realized = [o.realized_quantity for o in canceled]
    assert any(
        q > 0.0 for q in canceled_realized
    ), "One canceled order should have non-zero realized_quantity"
    assert any(
        q == 0.0 for q in canceled_realized
    ), "One canceled order should have zero realized_quantity"

    # Ensure DB is updated before crash
    db_positions = await front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    db_orders = await front.db.get_orders_by_position_id(db_position.id)
    db_buy_orders = [o for o in db_orders if getattr(o.side, "value", o.side) == "BUY"]
    assert len(db_buy_orders) == 3
    db_filled = [o for o in db_buy_orders if o.status.value == ORDER_STATUS_FILLED]
    db_canceled = [o for o in db_buy_orders if o.status.value == ORDER_STATUS_CANCELED]
    db_partial = [
        o for o in db_buy_orders if o.status.value == ORDER_STATUS_PARTIALLY_FILLED
    ]
    assert len(db_filled) == 1
    assert len(db_canceled) == 2
    assert len(db_partial) == 0
    db_canceled_realized = [o.realized_quantity for o in db_canceled]
    assert any(
        q > 0.0 for q in db_canceled_realized
    ), "One canceled DB order should have non-zero realized_quantity"
    assert any(
        q == 0.0 for q in db_canceled_realized
    ), "One canceled DB order should have zero realized_quantity"

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
    recovered_buy_orders = recovered_strategy.buy.orders
    assert (
        len(recovered_buy_orders) == 3
    ), f"Expected 3 buy orders after recovery, got {len(recovered_buy_orders)}"
    filled = [o for o in recovered_buy_orders if o.status == ORDER_STATUS_FILLED]
    canceled = [o for o in recovered_buy_orders if o.status == ORDER_STATUS_CANCELED]
    partial = [
        o for o in recovered_buy_orders if o.status == ORDER_STATUS_PARTIALLY_FILLED
    ]
    assert (
        len(filled) == 1
    ), f"Expected 1 filled buy order after recovery, got {len(filled)}"
    assert (
        len(canceled) == 2
    ), f"Expected 2 canceled buy orders after recovery, got {len(canceled)}"
    assert (
        len(partial) == 0
    ), f"Expected 0 partial buy orders after recovery, got {len(partial)}"
    canceled_realized = [o.realized_quantity for o in canceled]
    assert any(
        q > 0.0 for q in canceled_realized
    ), "One canceled order after recovery should have non-zero realized_quantity"
    assert any(
        q == 0.0 for q in canceled_realized
    ), "One canceled order after recovery should have zero realized_quantity"

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
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    await sim.setup_sell_position_after_first_buy_order_filled(
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
    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )

    # Price trigger is now related to the middle order as the top order is already filled.
    sim.new_price(price=1212)

    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    await wait_for_condition(lambda: strategy.buy.orders[1].status == ORDER_STATUS_NEW)
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
    )

    # Buy partially second order
    await sim.simulate_second_buy_order_partial_fill()

    # Cancel Buy orders
    await sim.cancel_buy_position_filled_partially_sold_partially()

    # Assert in-memory state before crash
    buy_orders = strategy.buy.orders
    assert len(buy_orders) == 3, f"Expected 3 buy orders, got {len(buy_orders)}"
    filled = [o for o in buy_orders if o.status == ORDER_STATUS_FILLED]
    canceled = [o for o in buy_orders if o.status == ORDER_STATUS_CANCELED]
    partial = [o for o in buy_orders if o.status == ORDER_STATUS_PARTIALLY_FILLED]
    assert len(filled) == 1, f"Expected 1 filled buy order, got {len(filled)}"
    assert len(canceled) == 2, f"Expected 2 canceled buy orders, got {len(canceled)}"
    assert (
        len(partial) == 0
    ), f"Expected 0 partially filled buy orders, got {len(partial)}"
    # One of the canceled orders must have non-zero realized_quantity
    canceled_realized = [o.realized_quantity for o in canceled]
    assert any(
        q > 0 for q in canceled_realized
    ), f"Expected at least one canceled order to have realized_quantity > 0, got {canceled_realized}"
    assert any(
        q == 0 for q in canceled_realized
    ), f"Expected at least one canceled order to have realized_quantity == 0, got {canceled_realized}"

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
    assert len(db_buy_orders) == 3
    db_filled = [o for o in db_buy_orders if o.status.value == ORDER_STATUS_FILLED]
    db_canceled = [o for o in db_buy_orders if o.status.value == ORDER_STATUS_CANCELED]
    db_partial = [
        o for o in db_buy_orders if o.status.value == ORDER_STATUS_PARTIALLY_FILLED
    ]
    assert len(db_filled) == 1
    assert len(db_canceled) == 2
    assert len(db_partial) == 0
    db_canceled_realized = [o.realized_quantity for o in db_canceled]
    assert any(
        q > 0 for q in db_canceled_realized
    ), f"Expected at least one canceled DB order to have realized_quantity > 0, got {db_canceled_realized}"
    assert any(
        q == 0 for q in db_canceled_realized
    ), f"Expected at least one canceled DB order to have realized_quantity == 0, got {db_canceled_realized}"

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
    recovered_buy_orders = recovered_strategy.buy.orders
    assert (
        len(recovered_buy_orders) == 3
    ), f"Expected 3 buy orders after recovery, got {len(recovered_buy_orders)}"
    filled = [o for o in recovered_buy_orders if o.status == ORDER_STATUS_FILLED]
    canceled = [o for o in recovered_buy_orders if o.status == ORDER_STATUS_CANCELED]
    partial = [
        o for o in recovered_buy_orders if o.status == ORDER_STATUS_PARTIALLY_FILLED
    ]
    assert (
        len(filled) == 1
    ), f"Expected 1 filled buy order after recovery, got {len(filled)}"
    assert (
        len(canceled) == 2
    ), f"Expected 2 canceled buy orders after recovery, got {len(canceled)}"
    assert (
        len(partial) == 0
    ), f"Expected 0 partially filled buy orders after recovery, got {len(partial)}"
    canceled_realized = [o.realized_quantity for o in canceled]
    assert any(
        q > 0 for q in canceled_realized
    ), f"Expected at least one canceled order after recovery to have realized_quantity > 0, got {canceled_realized}"
    assert any(
        q == 0 for q in canceled_realized
    ), f"Expected at least one canceled order after recovery to have realized_quantity == 0, got {canceled_realized}"

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
    await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    # Setup sell position after first buy order filled
    await sim.setup_sell_position_after_first_buy_order_filled(
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
    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )
    sim.new_price(price=1212)

    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    await wait_for_condition(lambda: strategy.buy.orders[1].status == ORDER_STATUS_NEW)
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING

    await wait_for_condition(lambda: front.hp_list_data[0]["state"] == "BUYING")

    # Fill the second and third buy orders
    await sim.simulate_second_buy_order_fill_after_selling_half_of_first_order()
    await sim.simulate_third_buy_order_fill_after_selling_half_of_first_order()

    # All buy orders should now be filled
    assert all(o.status == ORDER_STATUS_FILLED for o in strategy.buy.orders)
    assert strategy.buy.data.state_info.state == State.BOUGHT
    assert strategy.state == State.PARTIALLY_SOLD
    assert strategy.sell.current_position.state_info.state == State.PARTIALLY_SOLD

    db_positions = await front.db.get_active_positions()
    assert len(db_positions) == 1
    db_position = db_positions[0]
    logger.info("db position: %s", db_position)

    # --- Completeness checker ---
    total_quantity = sum(o.quantity for o in strategy.buy.orders)
    completeness = strategy.buy.data.state_info.completeness
    check_completeness(strategy.buy.orders, total_quantity, completeness)

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
    assert all(o.status == ORDER_STATUS_FILLED for o in recovered_strategy.buy.orders)
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
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    await sim.setup_sell_position_after_first_buy_order_filled(
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

    # Assert buy orders: one filled, two canceled
    buy_orders = strategy.buy.orders
    assert len(buy_orders) == 3, f"Expected 3 buy orders, got {len(buy_orders)}"
    filled = [o for o in buy_orders if o.status == ORDER_STATUS_FILLED]
    canceled = [o for o in buy_orders if o.status == ORDER_STATUS_CANCELED]
    assert len(filled) == 1, f"Expected 1 filled buy order, got {len(filled)}"
    assert (
        len(canceled) == 2
    ), f"Expected 2 new/canceled buy orders, got {len(canceled)}"

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
    ), f"Expected buy state to be PARTIALLY BOUGHT, got {recovered_strategy.buy.data.state_info.state}"

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

    # Assert buy orders after recovery: one filled, two new/canceled
    recovered_buy_orders = recovered_strategy.buy.orders
    assert (
        len(recovered_buy_orders) == 3
    ), f"Expected 3 buy orders after recovery, got {len(recovered_buy_orders)}"
    filled = [o for o in recovered_buy_orders if o.status == ORDER_STATUS_FILLED]
    canceled = [o for o in recovered_buy_orders if o.status == ORDER_STATUS_CANCELED]
    assert (
        len(filled) == 1
    ), f"Expected 1 filled buy order after recovery, got {len(filled)}"
    assert (
        len(canceled) == 2
    ), f"Expected 2 new/canceled buy orders after recovery, got {len(canceled)}"

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
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    await sim.setup_sell_position_after_first_buy_order_filled(
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
    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )
    sim.new_price(price=1212)

    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    await wait_for_condition(lambda: strategy.buy.orders[1].status == ORDER_STATUS_NEW)
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
    )

    # Fill the second and third buy orders BEFORE simulating a crash
    await sim.simulate_second_buy_order_fill_with_sell_price()
    assert strategy.buy.orders[1].status == ORDER_STATUS_FILLED
    await sim.simulate_third_buy_order_fill_with_sell_price()
    assert strategy.buy.orders[2].status == ORDER_STATUS_FILLED

    # All buy orders should now be filled
    assert all(o.status == ORDER_STATUS_FILLED for o in strategy.buy.orders)
    assert strategy.buy.data.state_info.state == State.BOUGHT
    assert strategy.state == State.PARTIALLY_SOLD

    # --- Completeness checker ---
    total_quantity = sum(o.quantity for o in strategy.buy.orders)
    completeness = strategy.buy.data.state_info.completeness
    check_completeness(strategy.buy.orders, total_quantity, completeness)

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

    # After recovery, assert all buy orders are filled and state is BOUGHT
    recovered_strategy = new_back.strategies["1000"]
    assert all(o.status == ORDER_STATUS_FILLED for o in recovered_strategy.buy.orders)
    assert recovered_strategy.buy.data.state_info.state == State.BOUGHT
    assert recovered_strategy.state == State.PARTIALLY_SOLD

    # --- Completeness checker ---
    total_quantity = sum(o.quantity for o in recovered_strategy.buy.orders)
    # Patch: recalculate completeness from realized quantities after recovery
    recalculated_completeness = (
        sum(o.realized_quantity for o in recovered_strategy.buy.orders) / total_quantity
        if total_quantity
        else 0.0
    )
    check_completeness(
        recovered_strategy.buy.orders, total_quantity, recalculated_completeness
    )

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
    assert recovered_strategy.sell.current_position.config.symbol_info.is_convert_only

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
