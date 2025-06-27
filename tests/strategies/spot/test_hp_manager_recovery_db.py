import logging
from src.strategy_executor import StrategyExecutor
from src.gui.hpfront import HpFront
from src.identifiers import State
from src.database.models import PositionType, PositionStatus
from tests.strategies.spot.hp_manager_helpers import wait_for_condition
from tests.strategies.spot.hp_simulator import HPSimulator

logger = logging.getLogger("hp_e2e_test")


async def simulate_application_crash(back: StrategyExecutor) -> None:
    """Simulate a complete application crash by clearing all in-memory state."""
    logger.info("=== SIMULATING APPLICATION CRASH ===")

    # Clear all strategies from executor (simulates app restart)
    back.strategies.clear()

    # The database should remain intact (persistent storage)
    # but all in-memory structures should be cleared
    logger.info("✓ All in-memory state cleared - simulating fresh application start")


async def verify_crash_simulation(back: StrategyExecutor, db) -> None:
    """Verify that the crash simulation properly cleared in-memory state."""
    # Verify strategies are cleared
    assert (
        len(back.strategies) == 0
    ), "Strategies should be cleared after crash simulation"

    # Database should still have positions (persistent storage survives crash)
    positions = await db.get_active_positions()
    assert len(positions) > 0, "Database positions should survive crash simulation"

    logger.info("✓ Crash simulation verified - in-memory cleared, database intact")


async def assert_application_db_state_match(
    back: StrategyExecutor, db, hp_id: str = "1000"
) -> None:
    """Assert that the in-memory application state matches the database state for a position."""
    logger.info("=== ASSERTING APPLICATION <-> DATABASE STATE MATCH for %s ===", hp_id)

    # Get the in-memory strategy
    strategy = back.strategies.get(hp_id)
    assert strategy is not None, f"Strategy {hp_id} not found in memory"

    # Get the corresponding position from database
    positions = await db.get_active_positions()
    db_position = None
    for pos in positions:
        if pos.hp_id == hp_id:
            db_position = pos
            break

    assert db_position is not None, f"Position {hp_id} not found in database"

    # Compare core identification fields
    assert (
        db_position.hp_id == strategy.buy.data.config.hp_id
    ), f"HP ID mismatch: DB={db_position.hp_id}, Memory={strategy.buy.data.config.hp_id}"

    assert (
        db_position.symbol == strategy.buy.data.config.symbol_info.symbol
    ), f"Symbol mismatch: DB={db_position.symbol}, Memory={strategy.buy.data.config.symbol_info.symbol}"

    assert (
        db_position.coin == strategy.buy.data.config.coin
    ), f"Coin mismatch: DB={db_position.coin}, Memory={strategy.buy.data.config.coin}"

    # Compare configuration fields
    assert (
        db_position.budget == strategy.buy.data.config.budget
    ), f"Budget mismatch: DB={db_position.budget}, Memory={strategy.buy.data.config.budget}"

    assert (
        db_position.price_low == strategy.buy.data.config.price_low
    ), f"Price low mismatch: DB={db_position.price_low}, Memory={strategy.buy.data.config.price_low}"

    assert (
        db_position.price_high == strategy.buy.data.config.price_high
    ), f"Price high mismatch: DB={db_position.price_high}, Memory={strategy.buy.data.config.price_high}"

    assert (
        db_position.order_trigger == strategy.buy.data.config.order_trigger
    ), f"Order trigger mismatch: DB={db_position.order_trigger}, Memory={strategy.buy.data.config.order_trigger}"

    assert (
        db_position.mode == strategy.buy.data.config.mode.value
    ), f"Mode mismatch: DB={db_position.mode}, Memory={strategy.buy.data.config.mode.value}"

    # Map state to status (simplified mapping for now)
    state_to_status_map = {
        State.NEW: PositionStatus.NEW,
        State.BUYING: PositionStatus.OPEN,
        State.PARTIALLY_BOUGHT: PositionStatus.PARTIALLY_FILLED,
        State.BOUGHT: PositionStatus.FILLED,
        # Add more mappings as needed
    }

    expected_status = state_to_status_map.get(strategy.state)
    if expected_status:
        assert (
            db_position.status == expected_status
        ), f"Status mismatch: DB={db_position.status}, Memory state={strategy.state} -> expected status={expected_status}"

    # Verify position type is BUY (for buy positions)
    assert (
        db_position.position_type == PositionType.BUY
    ), f"Position type should be BUY, got: {db_position.position_type}"

    logger.info("✓ Application and database state match verified successfully")

    # Log the matched fields for debugging
    logger.debug("Matched fields:")
    logger.debug("  HP ID: %s", db_position.hp_id)
    logger.debug("  Symbol: %s", db_position.symbol)
    logger.debug("  Coin: %s", db_position.coin)
    logger.debug("  Budget: %s", db_position.budget)
    logger.debug(
        "  Price range: %s - %s", db_position.price_low, db_position.price_high
    )
    logger.debug("  Order trigger: %s", db_position.order_trigger)
    logger.debug("  Mode: %s", db_position.mode)
    logger.debug("  Status: %s (from state: %s)", db_position.status, strategy.state)


async def test_get_default_buy_position(frontend_backend_setup):
    front, back = frontend_backend_setup

    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    assert len(back.strategies) == 0

    # Create and assert default buy position in memory
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    # Assert that there is exactly one position in the database
    db_positions = await front.db.get_active_positions()
    assert (
        len(db_positions) == 1
    ), f"Expected exactly 1 position in database, got {len(db_positions)}"

    # Assert that database state matches application state (before crash)
    await assert_application_db_state_match(back, front.db, hp_id="1000")

    # === SIMULATE APPLICATION CRASH ===
    await simulate_application_crash(back)
    await verify_crash_simulation(back, front.db)

    # === RECOVER FROM CRASH ===
    # Use the backend's built-in recovery method
    await back.recover_positions_from_crash()

    # Assert that there is still exactly one position in the database after recovery
    db_positions = await front.db.get_active_positions()
    assert (
        len(db_positions) == 1
    ), f"Expected exactly 1 position in database after recovery, got {len(db_positions)}"

    await wait_for_condition(condition_func=lambda: front.idle_records_buy)

    # Assert that the strategy was restored in memory
    assert (
        len(back.strategies) == 1
    ), f"Expected exactly 1 strategy in memory after recovery, got {len(back.strategies)}"
    assert "1000" in back.strategies, "Strategy 1000 should be restored in memory"

    await sim.assert_default_buy_position()

    # Assert that database state matches application state (after recovery)
    await assert_application_db_state_match(back, front.db, hp_id="1000")


# async def test_default_buy_position_send_orders(frontend_backend_setup):
#     front, back = frontend_backend_setup
#     sim = HPSimulator(front=front, back=back)
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)

#     assert len(back.strategies) == 0

#     # Get default buy position
#     sim.simulate_buy_position(symbol="BTCUSDC")
#     await sim.assert_default_buy_position()

#     # Open position and send orders
#     strategy = back.strategies["1000"]
#     strategy.client.create_order.side_effect = get_new_orders(
#         orders=strategy.buy.orders
#     )
#     sim.new_price(price=1410)

#     # Assert new opened position data
#     await wait_for_condition(condition_func=lambda: strategy.state == State.BUYING)
#     await wait_for_condition(condition_func=lambda: front.active_records_buy)
#     await wait_for_condition(condition_func=lambda: not front.idle_records_buy)
#     assert strategy.buy.data.state_info.state == State.NEW
#     assert all(order.order_id for order in strategy.buy.orders)
#     assert all(order.status == ORDER_STATUS_NEW for order in strategy.buy.orders)

#     logger.info("Active records: %s", front.active_records_buy)
#     logger.info("Idle records: %s", front.idle_records_buy)


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
