import asyncio
import logging

from binance.enums import ORDER_STATUS_NEW
from src.identifiers import Order, State
from src.strategy_executor import StrategyExecutor
from src.gui.hpfront import HpFront
from tests.spot import get_new_orders
from tests.strategies.spot.hp_manager_helpers import wait_for_condition
from tests.strategies.spot.hp_simulator import HPSimulator

logger = logging.getLogger("hp_e2e_test")


async def test_get_default_buy_position_crash_recovery(crash_recovery_factory):
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE ORIGINAL SETUP ===
    front, back = create_pair("_original")

    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    assert len(back.strategies) == 0

    # Create and assert default buy position in memory
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
    await sim.assert_application_db_state_match(hp_id="1000")

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
    await new_sim.assert_application_db_state_match(hp_id="1000")

    logger.info("Basic NEW position crash recovery test completed successfully")
    logger.info("Original state: NEW, Recovered state: %s", recovered_strategy.state)
    logger.info(
        "Original orders: 3, Recovered orders: %s", len(recovered_strategy.buy.orders)
    )
    logger.info("Database consistency verified before and after crash recovery")


async def test_default_buy_position_send_orders_recovery(crash_recovery_factory):
    """Test crash recovery for a position in BUYING state with active orders."""
    create_pair, simulate_crash = crash_recovery_factory

    # === PHASE 1: CREATE INITIAL STATE ===
    front, back = create_pair("_original")
    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)

    # Create default buy position and send orders
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    # Open position and send orders
    strategy = back.strategies["1000"]
    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )
    sim.new_price(price=1410)

    # Assert position is actively buying
    await wait_for_condition(condition_func=lambda: strategy.state == State.BUYING)
    await wait_for_condition(condition_func=lambda: front.active_records_buy)

    # === DETAILED PRE-CRASH ASSERTIONS ===
    # Verify strategy state
    assert strategy.state == State.BUYING
    assert strategy.buy.data.state_info.state == State.NEW
    assert len(strategy.buy.orders) == 3

    # Verify order details with expected order IDs
    # Order IDs are calculated as: round(price_low * price_high / 3.14) + index
    # For prices [1000, 1200, 1400]: round(1000 * 1400 / 3.14) = 445860
    # Quantities are rounded to 2 decimal places due to symbol precision=2
    original_orders = {
        0: {"price": 1400.0, "quantity": 0.24, "order_id": 445860},
        1: {"price": 1200.0, "quantity": 0.28, "order_id": 445861},
        2: {"price": 1000.0, "quantity": 0.33, "order_id": 445862},
    }

    for i, order in enumerate(strategy.buy.orders):
        assert order.price == original_orders[i]["price"]
        assert order.quantity == original_orders[i]["quantity"]
        assert order.status == ORDER_STATUS_NEW
        assert (
            order.order_id == original_orders[i]["order_id"]
        ), f"Order {i}: expected ID {original_orders[i]['order_id']}, got {order.order_id}"
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

    await sim.assert_application_db_state_match(hp_id="1000")

    # Store original configuration for comparison
    original_config = {
        "hp_id": strategy.buy.data.config.hp_id,
        "symbol": strategy.buy.data.config.symbol_info.symbol,
        "price_low": strategy.buy.data.config.price_low,
        "price_high": strategy.buy.data.config.price_high,
        "budget": strategy.buy.data.config.budget,
        "mode": strategy.buy.data.config.mode,
    }

    # === SIMULATE CRASH: Forcefully terminate original instances ===
    await simulate_crash(front, back)

    # === PHASE 2: SIMULATE APPLICATION RESTART ===
    # Create fresh frontend-backend setup (simulates app restart with same database)
    new_front, new_back = create_pair("_recovery")

    assert isinstance(new_front, HpFront)
    assert isinstance(new_back, StrategyExecutor)

    # Verify database has the position data before recovery
    positions_before_recovery = await new_front.db.get_active_positions()
    logger.info("Positions in DB before recovery: %d", len(positions_before_recovery))
    assert (
        len(positions_before_recovery) == 1
    ), f"Expected 1 position in database but found {len(positions_before_recovery)}"

    # Verify fresh instances start empty (no in-memory state)
    assert len(new_back.strategies) == 0

    # === DETAILED POST-RECOVERY ASSERTIONS ===
    # Assert recovery successful
    await wait_for_condition(condition_func=lambda: len(new_back.strategies) == 1)
    assert "1000" in new_back.strategies

    # Verify recovered strategy state
    recovered_strategy = new_back.strategies["1000"]
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
        assert recovered_order.order_id is not None  # Must have exchange order ID
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
    await new_sim.assert_application_db_state_match(hp_id="1000")
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


# async def test_cancel_default_position_untouched(frontend_backend_setup):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)

#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     await sim.move_to_position_active_buy()
#     strategy = back.strategies["1000"]

#     assert strategy.buy.orders_cancel_price == 1428.0
#     sim.new_price(price=1428)

#     await wait_for_condition(
#         condition_func=lambda: all(
#             order.status == ORDER_STATUS_CANCELED for order in strategy.buy.orders
#         )
#     )

#     assert len(strategy.buy.orders) == 3
#     assert strategy.buy.data.state_info.state == State.NEW
#     assert strategy.state == State.NEW

#     await wait_for_condition(
#         condition_func=lambda: front.hp_list_data[0]["state"] == State.NEW.value
#     )

#     item = front.hp_list_data[0]
#     assert item["hp_id"] == "1000"
#     assert item["coin"] == "BTCUSD"
#     assert item["buy_price"] == "1400.0"
#     assert item["quantity"] == "0.0"
#     assert item["quantity_usd"] == "0.0"
#     assert item["sell_price"] == "0.0"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "NEW"


# async def test_cancel_default_position_untouched_then_resend_orders(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)

#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     await sim.move_to_position_active_buy()

#     await sim.cancel_buy_position_untouched()

#     # Path 1: Resend buy orders
#     await sim.move_to_position_active_buy()


# async def test_default_position_first_order_filled_then_cancel(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)

#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     await sim.move_to_position_active_buy()

#     # Simulate first buy order fill
#     strategy = (
#         await sim.simulate_first_buy_order_fill()
#     )  # Cancel partially bought position

#     assert strategy.buy.orders_cancel_price == 1428.0
#     sim.new_price(price=1428.0)

#     assert len(strategy.buy.orders) == 3

#     assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED

#     await wait_for_condition(
#         condition_func=lambda: strategy.buy.orders[1].status == ORDER_STATUS_CANCELED
#     )
#     assert strategy.buy.orders[2].status == ORDER_STATUS_CANCELED

#     assert strategy.buy.orders[0].realized_quantity == 0.24
#     assert strategy.buy.orders[1].realized_quantity == 0.0
#     assert strategy.buy.orders[2].realized_quantity == 0.0

#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
#     assert strategy.state == State.PARTIALLY_BOUGHT

#     await wait_for_condition(
#         condition_func=lambda: front.hp_list_data[0]["state"] == "PARTIALLY_BOUGHT"
#     )

#     item = front.hp_list_data[0]
#     assert item["hp_id"] == "1000"
#     assert item["coin"] == "BTCUSD"
#     assert item["buy_price"] == "1400.0"
#     assert item["quantity"] == "0.24"
#     assert item["quantity_usd"] == "336.0"
#     assert item["sell_price"] == "0.0"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "PARTIALLY_BOUGHT"

#     logger.info("HP List after the update: %s", front.hp_list_data)


# async def test_default_position_first_order_filled_partially(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)

#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     await sim.move_to_position_active_buy()

#     # Simulate partial fill
#     strategy = await sim.simulate_partial_fill()


# async def test_default_position_first_order_filled_partially_then_cancel(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)

#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     await sim.move_to_position_active_buy()

#     # Simulate partial fill
#     strategy = await sim.simulate_partial_fill()  # Cancel position

#     assert strategy.buy.orders_cancel_price == 1428.0
#     sim.new_price(price=1428.0)

#     assert len(strategy.buy.orders) == 3

#     await wait_for_condition(
#         lambda: strategy.buy.orders[0].status == ORDER_STATUS_CANCELED
#     )
#     assert strategy.buy.orders[1].status == ORDER_STATUS_CANCELED
#     assert strategy.buy.orders[2].status == ORDER_STATUS_CANCELED

#     assert strategy.buy.orders[0].realized_quantity == 0.12
#     assert strategy.buy.orders[1].realized_quantity == 0.0
#     assert strategy.buy.orders[2].realized_quantity == 0.0

#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
#     assert strategy.state == State.PARTIALLY_BOUGHT

#     await wait_for_condition(
#         condition_func=lambda: front.hp_list_data[0]["state"] == "PARTIALLY_BOUGHT"
#     )

#     item = front.hp_list_data[0]
#     assert item["hp_id"] == "1000"
#     assert item["coin"] == "BTCUSD"
#     assert item["buy_price"] == "1400.0"
#     assert item["quantity"] == "0.12"
#     assert item["quantity_usd"] == "168.0"
#     assert item["sell_price"] == "0.0"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "PARTIALLY_BOUGHT"

#     logger.info("HP List after the update: %s", front.hp_list_data)


# async def test_default_position_first_order_filled(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     await sim.move_to_position_active_buy()

#     # Simulate first order fill
#     strategy = await sim.simulate_first_buy_order_fill()


# async def test_default_position_all_buy_orders_filled(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     await sim.simulate_bought_position()


# async def test_default_position_first_order_filled_partially_then_cancel_then_resend(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     # Path 0: Default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     # Path 1: Send buy orders
#     await sim.move_to_position_active_buy()
#     # Simulate partial fill    # Simulate partial fill
#     strategy = await sim.simulate_partial_fill()

#     # Cancel position
#     assert strategy.buy.orders_cancel_price == 1428.0
#     sim.new_price(price=1428.0)

#     assert len(strategy.buy.orders) == 3

#     await wait_for_condition(
#         lambda: strategy.buy.orders[0].status == ORDER_STATUS_CANCELED
#     )
#     await wait_for_condition(
#         lambda: strategy.buy.orders[1].status == ORDER_STATUS_CANCELED
#     )
#     await wait_for_condition(
#         lambda: strategy.buy.orders[2].status == ORDER_STATUS_CANCELED
#     )

#     assert strategy.buy.orders[0].realized_quantity == 0.12
#     assert strategy.buy.orders[1].realized_quantity == 0.0
#     assert strategy.buy.orders[2].realized_quantity == 0.0

#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
#     assert strategy.state == State.PARTIALLY_BOUGHT

#     await wait_for_condition(
#         condition_func=lambda: front.hp_list_data[0]["state"] == "PARTIALLY_BOUGHT"
#     )

#     item = front.hp_list_data[0]
#     assert item["hp_id"] == "1000"
#     assert item["coin"] == "BTCUSD"
#     assert item["buy_price"] == "1400.0"
#     assert item["quantity"] == "0.12"
#     assert item["quantity_usd"] == "168.0"
#     assert item["sell_price"] == "0.0"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "PARTIALLY_BOUGHT"

#     logger.info("HP List after the update: %s", front.hp_list_data)

#     # Reopen position
#     strategy.client.create_order.side_effect = get_new_orders(
#         orders=strategy.buy.orders
#     )
#     sim.new_price(price=1414)

#     await wait_for_condition(lambda: strategy.buy.orders[0].status == ORDER_STATUS_NEW)
#     assert strategy.buy.orders[1].status == ORDER_STATUS_NEW
#     assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

#     assert strategy.buy.orders[0].realized_quantity == 0.12
#     assert strategy.buy.orders[1].realized_quantity == 0.0
#     assert strategy.buy.orders[2].realized_quantity == 0.0

#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
#     assert strategy.state == State.BUYING

#     await wait_for_condition(
#         condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
#     )


# async def test_default_position_first_order_filled_then_cancel_then_resend(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     await sim.move_to_position_active_buy()  # Simulate first buy order fill
#     strategy = await sim.simulate_first_buy_order_fill()

#     # Cancel partially bought position
#     assert strategy.buy.orders_cancel_price == 1428.0
#     sim.new_price(price=1428.0)

#     assert len(strategy.buy.orders) == 3

#     assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED

#     await wait_for_condition(
#         condition_func=lambda: strategy.buy.orders[1].status == ORDER_STATUS_CANCELED
#     )
#     assert strategy.buy.orders[2].status == ORDER_STATUS_CANCELED

#     assert strategy.buy.orders[0].realized_quantity == 0.24
#     assert strategy.buy.orders[1].realized_quantity == 0.0
#     assert strategy.buy.orders[2].realized_quantity == 0.0

#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
#     assert strategy.state == State.PARTIALLY_BOUGHT

#     await wait_for_condition(
#         condition_func=lambda: front.hp_list_data[0]["state"] == "PARTIALLY_BOUGHT"
#     )

#     item = front.hp_list_data[0]
#     assert item["hp_id"] == "1000"
#     assert item["coin"] == "BTCUSD"
#     assert item["buy_price"] == "1400.0"
#     assert item["quantity"] == "0.24"
#     assert item["quantity_usd"] == "336.0"
#     assert item["sell_price"] == "0.0"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "PARTIALLY_BOUGHT"

#     logger.info("HP List after the update: %s", front.hp_list_data)

#     # Reopen position
#     strategy.client.create_order.side_effect = get_new_orders(
#         orders=strategy.buy.orders
#     )

#     # Price trigger is now related to the middle order as the top order is already filled.
#     sim.new_price(price=1212)

#     assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
#     await wait_for_condition(lambda: strategy.buy.orders[1].status == ORDER_STATUS_NEW)
#     assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

#     assert strategy.buy.orders[0].realized_quantity == 0.24
#     assert strategy.buy.orders[1].realized_quantity == 0.0
#     assert strategy.buy.orders[2].realized_quantity == 0.0

#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
#     assert strategy.state == State.BUYING

#     await wait_for_condition(
#         condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
#     )


# async def test_setup_sell_position_for_bought_position(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)
#     await sim.simulate_bought_position()

#     await sim.setup_sell_position(
#         hp_id="1000",
#         symbol="BTCUSDC",
#         quantity=0.85,
#         buy_price=1178.82,
#         sell_price=4200.0,
#         end_currency="USDC",
#         coin="BTC",
#     )


# async def test_send_sell_order_for_bought_position(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)
#     await sim.simulate_bought_position()
#     await sim.setup_sell_position(
#         hp_id="1000",
#         symbol="BTCUSDC",
#         quantity=0.85,
#         buy_price=1178.82,
#         sell_price=4200.0,
#         end_currency="USDC",
#         coin="BTC",
#     )

#     strategy = back.strategies["1000"]

#     strategy.client.create_order.side_effect = get_new_orders(
#         [strategy.sell.current_position.sell_order]
#     )
#     sim.new_price(price=4156)

#     await wait_for_condition(
#         condition_func=lambda: front.hp_list_data[0]["state"] == "SELLING"
#     )
#     item = front.hp_list_data[0]
#     assert item["hp_id"] == "1000"
#     assert item["coin"] == "BTCUSD"
#     assert item["buy_price"] == "1178.82"
#     assert item["quantity"] == "0.85"
#     assert item["quantity_usd"] == "1002.0"
#     assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
#     assert item["expected_return"] == "2568.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "SELLING"

#     await wait_for_condition(
#         condition_func=lambda: strategy.sell.current_position.sell_order.status
#         == ORDER_STATUS_NEW
#     )
#     assert strategy.sell.current_position.sell_order.quantity == 0.85
#     assert strategy.sell.current_position.sell_order.realized_quantity == 0.0

#     active_sell_item = front.active_records_sell[0]

#     assert active_sell_item["hp_id"] == "1000"
#     assert active_sell_item["symbol"] == "BTCUSDC"
#     assert active_sell_item["buy_price"] == "1178.82"
#     assert active_sell_item["quantity"] == "0.85"
#     assert active_sell_item["end_currency"] == "USDC"
#     assert (
#         active_sell_item["sell_price"] == "4200.0"
#     ), f"Item sell price: {item['sell_price']}"
#     assert active_sell_item["side"] == "SELL"
#     assert active_sell_item["completeness"] == "0.0"


# async def test_cancel_unfilled_sell_orders(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)
#     await sim.simulate_bought_position()

#     await sim.setup_sell_position(
#         hp_id="1000",
#         symbol="BTCUSDC",
#         quantity=0.85,
#         buy_price=1178.82,
#         sell_price=4200.0,
#         end_currency="USDC",
#         coin="BTC",
#     )

#     await sim.send_sell_order_for_bought_position()

#     # Cancel unfilled sell orders
#     await sim.cancel_unfilled_sell_position()


# async def test_resend_unfilled_sell_orders(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)
#     await sim.simulate_bought_position()

#     await sim.setup_sell_position(
#         hp_id="1000",
#         symbol="BTCUSDC",
#         quantity=0.85,
#         buy_price=1178.82,
#         sell_price=4200.0,
#         end_currency="USDC",
#         coin="BTC",
#     )

#     await sim.send_sell_order_for_bought_position()

#     # Cancel unfilled sell orders
#     await sim.cancel_unfilled_sell_position()

#     await sim.send_sell_order_for_bought_position()


# async def test_sell_position_first_order_filled_partially(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)
#     await sim.simulate_bought_position()

#     await sim.setup_sell_position(
#         hp_id="1000",
#         symbol="BTCUSDC",
#         quantity=0.85,
#         buy_price=1178.82,
#         sell_price=4200.0,
#         end_currency="USDC",
#         coin="BTC",
#     )

#     await sim.send_sell_order_for_bought_position()

#     await sim.simulate_sell_order_partial_fill()


# async def test_sell_position_first_order_filled(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)
#     await sim.simulate_bought_position()

#     await sim.setup_sell_position(
#         hp_id="1000",
#         symbol="BTCUSDC",
#         quantity=0.85,
#         buy_price=1178.82,
#         sell_price=4200.0,
#         end_currency="USDC",
#         coin="BTC",
#     )

#     await sim.send_sell_order_for_bought_position()

#     await sim.simulate_sell_order_fill()


# async def test_cancel_sell_position_first_order_filled_partially(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)
#     await sim.simulate_bought_position()

#     await sim.setup_sell_position(
#         hp_id="1000",
#         symbol="BTCUSDC",
#         quantity=0.85,
#         buy_price=1178.82,
#         sell_price=4200.0,
#         end_currency="USDC",
#         coin="BTC",
#     )

#     await sim.send_sell_order_for_bought_position()

#     await sim.simulate_sell_order_partial_fill()

#     await sim.cancel_partially_sold_position()


# async def test_resend_sell_position_first_order_filled_partially(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)
#     await sim.simulate_bought_position()

#     await sim.setup_sell_position(
#         hp_id="1000",
#         symbol="BTCUSDC",
#         quantity=0.85,
#         buy_price=1178.82,
#         sell_price=4200.0,
#         end_currency="USDC",
#         coin="BTC",
#     )

#     await sim.send_sell_order_for_bought_position()

#     await sim.simulate_sell_order_partial_fill()

#     await sim.cancel_partially_sold_position()

#     await sim.resend_sell_order_for_partially_sold_position()


# async def test_send_sell_order_for_partially_bought_position(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     await sim.move_to_position_active_buy()

#     # Simulate first buy order fill
#     strategy = await sim.simulate_first_buy_order_fill()

#     # Cancel partially bought position
#     await sim.cancel_buy_position_after_first_order_filled()

#     await sim.setup_sell_position_after_first_buy_order_filled(
#         hp_id="1000",
#         symbol="BTCUSDC",
#         quantity=strategy.buy.calculate_realized_quantity(),
#         buy_price=strategy.buy.calculate_avg_buy_price(),
#         sell_price=4200.0,
#         end_currency="USDC",
#         coin="BTC",
#     )

#     await sim.send_sell_order_for_part_bought_position()


# async def test_cancel_unfilled_sell_orders_for_partially_bought_position(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     await sim.move_to_position_active_buy()

#     # Simulate first buy order fill
#     strategy = await sim.simulate_first_buy_order_fill()

#     # Cancel partially bought position
#     await sim.cancel_buy_position_after_first_order_filled()

#     await sim.setup_sell_position_after_first_buy_order_filled(
#         hp_id="1000",
#         symbol="BTCUSDC",
#         quantity=strategy.buy.calculate_realized_quantity(),
#         buy_price=strategy.buy.calculate_avg_buy_price(),
#         sell_price=4200.0,
#         end_currency="USDC",
#         coin="BTC",
#     )

#     await sim.send_sell_order_for_part_bought_position()

#     await sim.cancel_unfilled_sell_position_from_part_filled_buy()


# async def test_fill_orders_for_previously_partially_bought_position(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     await sim.move_to_position_active_buy()

#     # Simulate first buy order fill
#     strategy = await sim.simulate_first_buy_order_fill()

#     # Cancel partially bought position
#     await sim.cancel_buy_position_after_first_order_filled()

#     await sim.setup_sell_position_after_first_buy_order_filled(
#         hp_id="1000",
#         symbol="BTCUSDC",
#         quantity=strategy.buy.calculate_realized_quantity(),
#         buy_price=strategy.buy.calculate_avg_buy_price(),
#         sell_price=4200.0,
#         end_currency="USDC",
#         coin="BTC",
#     )

#     await sim.send_sell_order_for_part_bought_position()

#     await sim.cancel_unfilled_sell_position_from_part_filled_buy()

#     strategy.client.create_order.side_effect = get_new_orders(
#         orders=strategy.buy.orders
#     )

#     # Price trigger is now related to the middle order as the top order is already filled.
#     sim.new_price(price=1212)

#     assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
#     await wait_for_condition(lambda: strategy.buy.orders[1].status == ORDER_STATUS_NEW)
#     assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

#     assert strategy.buy.orders[0].realized_quantity == 0.24
#     assert strategy.buy.orders[1].realized_quantity == 0.0
#     assert strategy.buy.orders[2].realized_quantity == 0.0

#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
#     assert strategy.state == State.BUYING

#     await wait_for_condition(
#         condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
#     )

#     await sim.simulate_second_buy_order_fill_with_sell_price()
#     await sim.simulate_third_buy_order_fill_with_sell_price()


# async def test_sell_partially_partially_bought_position(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     await sim.move_to_position_active_buy()

#     # Simulate first buy order fill
#     strategy = await sim.simulate_first_buy_order_fill()

#     # Cancel partially bought position
#     await sim.cancel_buy_position_after_first_order_filled()

#     await sim.setup_sell_position_after_first_buy_order_filled(
#         hp_id="1000",
#         symbol="BTCUSDC",
#         quantity=strategy.buy.calculate_realized_quantity(),
#         buy_price=strategy.buy.calculate_avg_buy_price(),
#         sell_price=4200.0,
#         end_currency="USDC",
#         coin="BTC",
#     )

#     await sim.send_sell_order_for_part_bought_position()

#     await sim.simulate_sell_order_partial_fill_from_part_bought()


# async def test_buy_partially_partially_sold_position(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     await sim.move_to_position_active_buy()

#     # Simulate first buy order fill
#     strategy = await sim.simulate_first_buy_order_fill()

#     # Cancel partially bought position
#     await sim.cancel_buy_position_after_first_order_filled()

#     await sim.setup_sell_position_after_first_buy_order_filled(
#         hp_id="1000",
#         symbol="BTCUSDC",
#         quantity=strategy.buy.calculate_realized_quantity(),
#         buy_price=strategy.buy.calculate_avg_buy_price(),
#         sell_price=4200.0,
#         end_currency="USDC",
#         coin="BTC",
#     )

#     await sim.send_sell_order_for_part_bought_position()

#     await sim.simulate_sell_order_partial_fill_from_part_bought()

#     # Cancel Sell position
#     await sim.cancel_sell_position_filled_partially()

#     # Reopen Buy position
#     strategy.client.create_order.side_effect = get_new_orders(
#         orders=strategy.buy.orders
#     )

#     # Price trigger is now related to the middle order as the top order is already filled.
#     sim.new_price(price=1212)

#     assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
#     await wait_for_condition(lambda: strategy.buy.orders[1].status == ORDER_STATUS_NEW)
#     assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

#     assert strategy.buy.orders[0].realized_quantity == 0.24
#     assert strategy.buy.orders[1].realized_quantity == 0.0
#     assert strategy.buy.orders[2].realized_quantity == 0.0

#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
#     assert strategy.state == State.BUYING

#     await wait_for_condition(
#         condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
#     )

#     # Buy partially second order
#     await sim.simulate_second_buy_order_partial_fill()


# async def test_cancel_buy_to_part_sold_part_bought(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     await sim.move_to_position_active_buy()

#     # Simulate first buy order fill
#     strategy = await sim.simulate_first_buy_order_fill()

#     # Cancel partially bought position
#     await sim.cancel_buy_position_after_first_order_filled()

#     await sim.setup_sell_position_after_first_buy_order_filled(
#         hp_id="1000",
#         symbol="BTCUSDC",
#         quantity=strategy.buy.calculate_realized_quantity(),
#         buy_price=strategy.buy.calculate_avg_buy_price(),
#         sell_price=4200.0,
#         end_currency="USDC",
#         coin="BTC",
#     )

#     await sim.send_sell_order_for_part_bought_position()

#     await sim.simulate_sell_order_partial_fill_from_part_bought()

#     # Cancel Sell position
#     await sim.cancel_sell_position_filled_partially()

#     # Reopen Buy position
#     strategy.client.create_order.side_effect = get_new_orders(
#         orders=strategy.buy.orders
#     )

#     # Price trigger is now related to the middle order as the top order is already filled.
#     sim.new_price(price=1212)

#     assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
#     await wait_for_condition(lambda: strategy.buy.orders[1].status == ORDER_STATUS_NEW)
#     assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

#     assert strategy.buy.orders[0].realized_quantity == 0.24
#     assert strategy.buy.orders[1].realized_quantity == 0.0
#     assert strategy.buy.orders[2].realized_quantity == 0.0

#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
#     assert strategy.state == State.BUYING

#     await wait_for_condition(
#         condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
#     )

#     # Buy partially second order
#     await sim.simulate_second_buy_order_partial_fill()

#     # Cancel Buy orders
#     await sim.cancel_buy_position_filled_partially_sold_partially()


# async def test_buy_fully_partially_sold_position(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     await sim.move_to_position_active_buy()

#     # Simulate first buy order fill
#     strategy = await sim.simulate_first_buy_order_fill()

#     # Cancel partially bought position
#     await sim.cancel_buy_position_after_first_order_filled()

#     await sim.setup_sell_position_after_first_buy_order_filled(
#         hp_id="1000",
#         symbol="BTCUSDC",
#         quantity=strategy.buy.calculate_realized_quantity(),
#         buy_price=strategy.buy.calculate_avg_buy_price(),
#         sell_price=4200.0,
#         end_currency="USDC",
#         coin="BTC",
#     )

#     await sim.send_sell_order_for_part_bought_position()

#     await sim.simulate_sell_order_partial_fill_from_part_bought()

#     # Cancel Sell position
#     await sim.cancel_sell_position_filled_partially()

#     # Reopen Buy position
#     strategy.client.create_order.side_effect = get_new_orders(
#         orders=strategy.buy.orders
#     )

#     # Price trigger is now related to the middle order as the top order is already filled.
#     sim.new_price(price=1212)

#     assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
#     await wait_for_condition(lambda: strategy.buy.orders[1].status == ORDER_STATUS_NEW)
#     assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

#     assert strategy.buy.orders[0].realized_quantity == 0.24
#     assert strategy.buy.orders[1].realized_quantity == 0.0
#     assert strategy.buy.orders[2].realized_quantity == 0.0

#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
#     assert strategy.state == State.BUYING

#     await wait_for_condition(
#         condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
#     )

#     await sim.simulate_second_buy_order_fill_after_selling_half_of_first_order()
#     await sim.simulate_third_buy_order_fill_after_selling_half_of_first_order()


# async def test_sell_fully_partially_bought_position(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     await sim.move_to_position_active_buy()

#     # Simulate first buy order fill
#     strategy = await sim.simulate_first_buy_order_fill()

#     # Cancel partially bought position
#     await sim.cancel_buy_position_after_first_order_filled()

#     await sim.setup_sell_position_after_first_buy_order_filled(
#         hp_id="1000",
#         symbol="BTCUSDC",
#         quantity=strategy.buy.calculate_realized_quantity(),
#         buy_price=strategy.buy.calculate_avg_buy_price(),
#         sell_price=4200.0,
#         end_currency="USDC",
#         coin="BTC",
#     )

#     await sim.send_sell_order_for_part_bought_position()

#     await sim.simulate_sell_order_fill_from_part_bought()


# async def test_buy_fully_partially_bought_position_when_sold_position(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     await sim.move_to_position_active_buy()

#     # Simulate first buy order fill
#     strategy = await sim.simulate_first_buy_order_fill()

#     # Cancel partially bought position
#     await sim.cancel_buy_position_after_first_order_filled()

#     await sim.setup_sell_position_after_first_buy_order_filled(
#         hp_id="1000",
#         symbol="BTCUSDC",
#         quantity=strategy.buy.calculate_realized_quantity(),
#         buy_price=strategy.buy.calculate_avg_buy_price(),
#         sell_price=4200.0,
#         end_currency="USDC",
#         coin="BTC",
#     )

#     await sim.send_sell_order_for_part_bought_position()

#     await sim.simulate_sell_order_fill_from_part_bought()

#     # Reopen Buy position
#     strategy.client.create_order.side_effect = get_new_orders(
#         orders=strategy.buy.orders
#     )

#     # Price trigger is now related to the middle order as the top order is already filled.
#     sim.new_price(price=1212)

#     assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
#     await wait_for_condition(lambda: strategy.buy.orders[1].status == ORDER_STATUS_NEW)
#     assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

#     assert strategy.buy.orders[0].realized_quantity == 0.24
#     assert strategy.buy.orders[1].realized_quantity == 0.0
#     assert strategy.buy.orders[2].realized_quantity == 0.0

#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
#     assert strategy.state == State.BUYING

#     await wait_for_condition(
#         condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
#     )


# async def test_start_new_sell_position_for_two_hop_trade(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     await sim.open_first_sell_position_from_two_hop_trade()


# async def test_send_order_for_first_sell_position_in_two_hop_trade(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     await sim.open_first_sell_position_from_two_hop_trade()

#     await sim.send_orders_for_first_position_from_two_hop_trade()


# async def test_fill_partially_first_sell_position_in_two_hop_trade(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     await sim.open_first_sell_position_from_two_hop_trade()

#     await sim.send_orders_for_first_position_from_two_hop_trade()

#     await sim.simulate_sell_order_partial_fill_in_first_hop()


# async def test_fill_first_sell_position_in_two_hop_trade(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     await sim.open_first_sell_position_from_two_hop_trade()

#     await sim.send_orders_for_first_position_from_two_hop_trade()

#     await sim.simulate_sell_order_fill_in_first_hop()


# async def test_start_second_sell_position_in_two_hop_trade(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     await sim.open_first_sell_position_from_two_hop_trade()

#     await sim.send_orders_for_first_position_from_two_hop_trade()

#     await sim.simulate_sell_order_fill_in_first_hop()

#     await sim.open_second_sell_position_from_two_hop_trade()


# async def test_partial_fill_second_sell_position_in_two_hop_trade(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     await sim.open_first_sell_position_from_two_hop_trade()

#     await sim.send_orders_for_first_position_from_two_hop_trade()

#     await sim.simulate_sell_order_fill_in_first_hop()

#     await sim.open_second_sell_position_from_two_hop_trade()

#     await sim.simulate_sell_order_partial_fill_in_second_hop()


# async def test_fill_second_sell_position_in_two_hop_trade(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     await sim.open_first_sell_position_from_two_hop_trade()

#     await sim.send_orders_for_first_position_from_two_hop_trade()

#     await sim.simulate_sell_order_fill_in_first_hop()

#     await sim.open_second_sell_position_from_two_hop_trade()

#     await sim.simulate_sell_order_fill_in_second_hop()


# async def test_no_sell_orders_send_if_buy_position_not_realized(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     strategy = back.strategies["1000"]
#     sell_config = HPSellData(
#         config=HPSellConfig(
#             hp_id="1000",
#             coin="BTC",
#             buy_price=0.0,
#             sell_price=4200.0,
#             quantity=0.0,
#             symbol_info=SymbolInfo(symbol="BTCUSDC", precision=2, price_precision=2),
#         ),
#         state_info=StateInfo(side=PositionSide.SHORT),
#     )
#     front.config_queue.put_nowait(sell_config)
#     logger.info("Sell config added to the queue: %s", sell_config.config)

#     await wait_for_condition(
#         condition_func=lambda: front.hp_list_data[0]["sell_price"] == "4200.0"
#     )

#     item = front.hp_list_data[0]
#     assert item["hp_id"] == "1000"
#     assert item["coin"] == "BTCUSD"
#     assert item["buy_price"] == "0.0", item["buy_price"]
#     assert item["quantity"] == "0.0"
#     assert item["quantity_usd"] == "0.0"
#     assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "NEW"

#     await wait_for_condition(
#         condition_func=lambda: back.strategies["1000"].sell.current_position.sell_order
#     )

#     sim.new_price(price=4200.0)

#     await asyncio.sleep(0.1)

#     item = front.hp_list_data[0]
#     assert item["hp_id"] == "1000"
#     assert item["coin"] == "BTCUSD"
#     assert item["buy_price"] == "0.0", item["buy_price"]
#     assert item["quantity"] == "0.0"
#     assert item["quantity_usd"] == "0.0"
#     assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "NEW"


# async def test_sell_orders_send_if_buy_position_realized_partially(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     strategy = back.strategies["1000"]
#     sell_config = HPSellData(
#         config=HPSellConfig(
#             hp_id="1000",
#             coin="BTC",
#             buy_price=0.0,
#             sell_price=4200.0,
#             quantity=0.0,
#             symbol_info=SymbolInfo(symbol="BTCUSDC", precision=2, price_precision=2),
#         ),
#         state_info=StateInfo(side=PositionSide.SHORT),
#     )
#     front.config_queue.put_nowait(sell_config)
#     logger.info("Sell config added to the queue: %s", sell_config.config)

#     await wait_for_condition(
#         condition_func=lambda: front.hp_list_data[0]["sell_price"] == "4200.0"
#     )

#     item = front.hp_list_data[0]
#     assert item["hp_id"] == "1000"
#     assert item["coin"] == "BTCUSD"
#     assert item["buy_price"] == "0.0", item["buy_price"]
#     assert item["quantity"] == "0.0"
#     assert item["quantity_usd"] == "0.0"
#     assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "NEW"

#     await wait_for_condition(
#         condition_func=lambda: back.strategies["1000"].sell.current_position.sell_order
#     )

#     await sim.move_to_position_active_buy()  # Simulate partial fill
#     strategy = await sim.simulate_partial_fill_with_sell_price()

#     # Cancel position
#     assert strategy.buy.orders_cancel_price == 1428.0
#     sim.new_price(price=1428.0)

#     assert len(strategy.buy.orders) == 3

#     await wait_for_condition(
#         lambda: strategy.buy.orders[0].status == ORDER_STATUS_CANCELED
#     )
#     await wait_for_condition(
#         lambda: strategy.buy.orders[1].status == ORDER_STATUS_CANCELED
#     )
#     await wait_for_condition(
#         lambda: strategy.buy.orders[2].status == ORDER_STATUS_CANCELED
#     )

#     assert strategy.buy.orders[0].realized_quantity == 0.12
#     assert strategy.buy.orders[1].realized_quantity == 0.0
#     assert strategy.buy.orders[2].realized_quantity == 0.0

#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
#     assert strategy.state == State.PARTIALLY_BOUGHT

#     await wait_for_condition(
#         condition_func=lambda: front.hp_list_data[0]["state"] == "PARTIALLY_BOUGHT"
#     )

#     item = front.hp_list_data[0]
#     assert item["hp_id"] == "1000"
#     assert item["coin"] == "BTCUSD"
#     assert item["buy_price"] == "1400.0"
#     assert item["quantity"] == "0.12"
#     assert item["quantity_usd"] == "168.0"
#     assert item["sell_price"] == "4200.0"
#     assert item["expected_return"] == "336.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "PARTIALLY_BOUGHT"

#     logger.info("HP List after the update: %s", front.hp_list_data)

#     strategy.client.create_order.side_effect = get_new_orders(
#         orders=[strategy.sell.current_position.sell_order]
#     )
#     sim.new_price(price=4200.0)

#     await wait_for_condition(
#         condition_func=lambda: front.hp_list_data[0]["state"] == "SELLING"
#     )

#     item = front.hp_list_data[0]
#     assert item["hp_id"] == "1000"
#     assert item["coin"] == "BTCUSD"
#     assert item["buy_price"] == "1400.0"
#     assert item["quantity"] == "0.12"
#     assert item["quantity_usd"] == "168.0"
#     assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
#     assert item["expected_return"] == "336.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "SELLING"

#     await wait_for_condition(
#         condition_func=lambda: strategy.sell.current_position.sell_order.status
#         == ORDER_STATUS_NEW
#     )
#     assert strategy.sell.current_position.sell_order.quantity == 0.12
#     assert strategy.sell.current_position.sell_order.realized_quantity == 0.0

#     active_sell_item = front.active_records_sell[0]

#     assert active_sell_item["hp_id"] == "1000"
#     assert active_sell_item["symbol"] == "BTCUSDC"
#     assert active_sell_item["buy_price"] == "1400.0"
#     assert active_sell_item["quantity"] == "0.12"
#     assert active_sell_item["end_currency"] == "USDC"
#     assert (
#         active_sell_item["sell_price"] == "4200.0"
#     ), f"Item sell price: {item['sell_price']}"
#     assert active_sell_item["side"] == "SELL"
#     assert active_sell_item["completeness"] == "0.0"
