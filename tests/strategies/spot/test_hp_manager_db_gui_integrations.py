import datetime
import logging

from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_CANCELED,
)
import pytest

from src.common.identifiers.common import PositionSide
from src.common.symbol_info import SymbolInfo
from src.strategies.spot.hp_manager import HpManager, STAGNATION_LIMIT
from src.common.identifiers.spot import State
from tests.spot import get_cancel_order, get_new_orders
from tests.strategies.spot.hp_manager_db_gui_integrations import (
    assert_db_price_level_content,
    db_and_gui_assertions,
    get_strategy_config,
    process_ticker,
    simulate_order_filled,
    simulate_order_partially_filled,
)

logger = logging.getLogger("test_hp_manager_gui_db_integrations")


@pytest.mark.database_integration
async def test_default_buy_scenario(trading_system_factory):
    trading_system = await trading_system_factory(
        get_strategy_config(side=PositionSide.LONG)
    )
    trading_system.model.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.model.config.price_low,
        price_high=trading_system.model.config.price_high,
    )

    # Set initial condition
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price() == 1414

    # Simulate price outside of the threshold
    await process_ticker(strategy=strategy, last_price=1415)
    assert strategy.state == State.NEW

    # Simulate price on the edge of threshold, opening position
    await process_ticker(strategy=strategy, last_price=1414)
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=0,
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    # Simulate first order filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[2],
    )

    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    # Simulate second order being filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[1],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    # Simulate last order being filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[0],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    # Retrieve all orders filled signal from the queue and close the position.
    assert strategy.queue.qsize() == 1
    event = await strategy.queue.get()
    strategy.signal_update = event.content
    await strategy.process_signal()

    assert strategy.state == State.CLOSED
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )


@pytest.mark.database_integration
async def test_default_sell_scenario(trading_system_factory):
    trading_system = await trading_system_factory(
        get_strategy_config(side=PositionSide.SHORT)
    )
    trading_system.model.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.model.config.price_low,
        price_high=trading_system.model.config.price_high,
    )

    # Set initial condition
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price() == 990
    await process_ticker(strategy=strategy, last_price=989)
    assert strategy.state == State.NEW

    # Simulate process_signal triggering
    await process_ticker(strategy=strategy, last_price=990)
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    # Simulate first order filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[0],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    # Simulate second order being filled
    # Simulate first order filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[1],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    # Simulate last order being filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[2],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    # Retrieve all orders filled signal from the queue and close the position.
    assert strategy.queue.qsize() == 1
    event = await strategy.queue.get()
    strategy.signal_update = event.content
    await strategy.process_signal()
    assert strategy.state == State.CLOSED
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )


@pytest.mark.database_integration
async def test_stagnation_buy_position(trading_system_factory):
    trading_system = await trading_system_factory(
        get_strategy_config(side=PositionSide.LONG)
    )
    trading_system.model.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.model.config.price_low,
        price_high=trading_system.model.config.price_high,
    )
    trading_system.model.client.cancel_order.side_effect = get_cancel_order()
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price() == 1414

    await process_ticker(strategy=strategy, last_price=1400)
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    time_date = datetime.datetime.strptime(
        strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
    )
    time_date -= datetime.timedelta(hours=8)
    strategy.position_handler.next_monitor_position_time = time_date.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # Simulate reaching the stagnation limit
    for _ in range(STAGNATION_LIMIT):
        await strategy.process_ticker()
        await db_and_gui_assertions(
            strategy=strategy,
            completeness=round(
                sum(
                    order.realized_quantity
                    for order in strategy.position_handler.orders
                )
                / sum(order.quantity for order in strategy.position_handler.orders),
                2,
            ),
            stagnation_counter=strategy.position_handler.stagnation_counter,
            stagnation_limit=STAGNATION_LIMIT,
        )

    assert strategy.position_handler.stagnation_counter >= STAGNATION_LIMIT

    logger.info("Stagnation Limit achieved but the price is still within the area")

    await process_ticker(strategy=strategy, last_price=1429)

    assert strategy.state == State.STAGNATED
    assert strategy.position_handler.stagnation_counter == 0

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") == ORDER_STATUS_CANCELED

    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    await process_ticker(strategy=strategy, last_price=1500)
    await assert_db_price_level_content(
        db=strategy.position_handler.db, config=strategy.config, state=strategy.state
    )

    await process_ticker(strategy=strategy, last_price=1400)
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") == ORDER_STATUS_NEW
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )


@pytest.mark.database_integration
async def test_stagnation_sell_position(trading_system_factory):
    trading_system = await trading_system_factory(
        get_strategy_config(side=PositionSide.SHORT)
    )
    trading_system.model.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.model.config.price_low,
        price_high=trading_system.model.config.price_high,
    )
    trading_system.model.client.cancel_order.side_effect = get_cancel_order()
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price() == 990

    await process_ticker(strategy=strategy, last_price=1000)
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    time_date = datetime.datetime.strptime(
        strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
    )
    time_date -= datetime.timedelta(hours=8)
    strategy.position_handler.next_monitor_position_time = time_date.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # Simulate reaching the stagnation limit
    for _ in range(STAGNATION_LIMIT):
        await strategy.process_ticker()
        await db_and_gui_assertions(
            strategy=strategy,
            completeness=round(
                sum(
                    order.realized_quantity
                    for order in strategy.position_handler.orders
                )
                / sum(order.quantity for order in strategy.position_handler.orders),
                2,
            ),
            stagnation_counter=strategy.position_handler.stagnation_counter,
            stagnation_limit=STAGNATION_LIMIT,
        )

    assert strategy.position_handler.stagnation_counter >= STAGNATION_LIMIT

    logger.info("Stagnation Limit achieved but the price is still within the area")

    await process_ticker(strategy=strategy, last_price=979)

    assert strategy.state == State.STAGNATED
    assert strategy.position_handler.stagnation_counter == 0

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") == ORDER_STATUS_CANCELED

    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    await process_ticker(strategy=strategy, last_price=900)
    await assert_db_price_level_content(
        db=strategy.position_handler.db, config=strategy.config, state=strategy.state
    )

    await process_ticker(strategy=strategy, last_price=1000)
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") == ORDER_STATUS_NEW

    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )


@pytest.mark.database_integration
async def test_order_reopen_with_filled_orders_buy(trading_system_factory):
    trading_system = await trading_system_factory(
        get_strategy_config(side=PositionSide.LONG)
    )
    trading_system.model.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.model.config.price_low,
        price_high=trading_system.model.config.price_high,
    )
    trading_system.model.client.cancel_order.side_effect = get_cancel_order()
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price() == 1414

    await process_ticker(strategy=strategy, last_price=1400)
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    # Simulate first order filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[0],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    time_date = datetime.datetime.strptime(
        strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
    )
    time_date -= datetime.timedelta(hours=8)
    strategy.position_handler.next_monitor_position_time = time_date.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # Simulate reaching the stagnation limit
    for _ in range(STAGNATION_LIMIT):
        await strategy.process_ticker()
        await db_and_gui_assertions(
            strategy=strategy,
            completeness=round(
                sum(
                    order.realized_quantity
                    for order in strategy.position_handler.orders
                )
                / sum(order.quantity for order in strategy.position_handler.orders),
                2,
            ),
            stagnation_counter=strategy.position_handler.stagnation_counter,
            stagnation_limit=STAGNATION_LIMIT,
        )

    assert strategy.position_handler.stagnation_counter >= STAGNATION_LIMIT

    logger.info("Stagnation Limit achieved but the price is still within the area")

    await process_ticker(strategy=strategy, last_price=1429)

    assert strategy.state == State.STAGNATED
    assert strategy.position_handler.stagnation_counter == 0

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") in [ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED]

    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    await process_ticker(strategy=strategy, last_price=1500)
    await assert_db_price_level_content(
        db=strategy.position_handler.db, config=strategy.config, state=strategy.state
    )

    await process_ticker(strategy=strategy, last_price=1400)
    assert strategy.state == State.OPEN
    assert all(
        order.status in [ORDER_STATUS_NEW, ORDER_STATUS_FILLED]
        for order in strategy.position_handler.orders
    )

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") in [
            ORDER_STATUS_NEW,
            ORDER_STATUS_FILLED,
        ]

    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )
    logger.info("All valid orders reopened.")


@pytest.mark.database_integration
async def test_order_reopen_with_filled_orders_sell(trading_system_factory):
    trading_system = await trading_system_factory(
        get_strategy_config(side=PositionSide.SHORT)
    )
    trading_system.model.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.model.config.price_low,
        price_high=trading_system.model.config.price_high,
    )
    trading_system.model.client.cancel_order.side_effect = get_cancel_order()
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price() == 990

    await process_ticker(strategy=strategy, last_price=1000)
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    # Simulate first order filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[0],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    time_date = datetime.datetime.strptime(
        strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
    )
    time_date -= datetime.timedelta(hours=8)
    strategy.position_handler.next_monitor_position_time = time_date.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # Simulate reaching the stagnation limit
    for _ in range(STAGNATION_LIMIT):
        await strategy.process_ticker()
        await db_and_gui_assertions(
            strategy=strategy,
            completeness=round(
                sum(
                    order.realized_quantity
                    for order in strategy.position_handler.orders
                )
                / sum(order.quantity for order in strategy.position_handler.orders),
                2,
            ),
            stagnation_counter=strategy.position_handler.stagnation_counter,
            stagnation_limit=STAGNATION_LIMIT,
        )
    assert strategy.position_handler.stagnation_counter >= STAGNATION_LIMIT

    logger.info("Stagnation Limit achieved but the price is still within the area")

    await process_ticker(strategy=strategy, last_price=979)

    assert strategy.state == State.STAGNATED
    assert strategy.position_handler.stagnation_counter == 0

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") in [ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED]

    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    await process_ticker(strategy=strategy, last_price=900)
    await assert_db_price_level_content(
        db=strategy.position_handler.db, config=strategy.config, state=strategy.state
    )

    await process_ticker(strategy=strategy, last_price=1000)
    assert strategy.state == State.OPEN
    assert all(
        order.status in [ORDER_STATUS_NEW, ORDER_STATUS_FILLED]
        for order in strategy.position_handler.orders
    )

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") in [
            ORDER_STATUS_NEW,
            ORDER_STATUS_FILLED,
        ]

    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )
    logger.info("All valid orders reopened.")


@pytest.mark.database_integration
async def test_order_reopen_with_partially_filled_orders_buy(trading_system_factory):
    trading_system = await trading_system_factory(
        get_strategy_config(side=PositionSide.LONG)
    )
    trading_system.model.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.model.config.price_low,
        price_high=trading_system.model.config.price_high,
    )
    trading_system.model.client.cancel_order.side_effect = get_cancel_order()
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price() == 1414

    await process_ticker(strategy=strategy, last_price=1400)
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    # Simulate first order filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[0],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    # Simulate first order filled
    await simulate_order_partially_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[1],
        last_realized_quantity=round(
            strategy.position_handler.orders[1].quantity / 2, 4
        ),
    )

    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    time_date = datetime.datetime.strptime(
        strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
    )
    time_date -= datetime.timedelta(hours=8)
    strategy.position_handler.next_monitor_position_time = time_date.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # Simulate reaching the stagnation limit
    for _ in range(STAGNATION_LIMIT):
        await strategy.process_ticker()
        await db_and_gui_assertions(
            strategy=strategy,
            completeness=round(
                sum(
                    order.realized_quantity
                    for order in strategy.position_handler.orders
                )
                / sum(order.quantity for order in strategy.position_handler.orders),
                2,
            ),
            stagnation_counter=strategy.position_handler.stagnation_counter,
            stagnation_limit=STAGNATION_LIMIT,
        )
    assert strategy.position_handler.stagnation_counter >= STAGNATION_LIMIT

    logger.info("Stagnation Limit achieved but the price is still within the area")

    await process_ticker(strategy=strategy, last_price=1429)

    assert strategy.state == State.STAGNATED
    assert strategy.position_handler.stagnation_counter == 0

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") in [ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED]

    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    await process_ticker(strategy=strategy, last_price=1500)
    await assert_db_price_level_content(
        db=strategy.position_handler.db, config=strategy.config, state=strategy.state
    )

    await process_ticker(strategy=strategy, last_price=1400)
    assert strategy.state == State.OPEN
    assert all(
        order.status in [ORDER_STATUS_NEW, ORDER_STATUS_FILLED]
        for order in strategy.position_handler.orders
    )

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") in [
            ORDER_STATUS_NEW,
            ORDER_STATUS_FILLED,
        ]

    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )
    logger.info("All valid orders reopened.")


@pytest.mark.database_integration
async def test_order_reopen_with_partially_filled_orders_sell(trading_system_factory):
    trading_system = await trading_system_factory(
        get_strategy_config(side=PositionSide.SHORT)
    )
    trading_system.model.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.model.config.price_low,
        price_high=trading_system.model.config.price_high,
    )
    trading_system.model.client.cancel_order.side_effect = get_cancel_order()
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price() == 990

    await process_ticker(strategy=strategy, last_price=1000)
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    # Simulate first order filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[0],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    # Simulate first order filled
    await simulate_order_partially_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[1],
        last_realized_quantity=round(
            strategy.position_handler.orders[1].quantity / 2, 4
        ),
    )

    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    time_date = datetime.datetime.strptime(
        strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
    )
    time_date -= datetime.timedelta(hours=8)
    strategy.position_handler.next_monitor_position_time = time_date.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # Simulate reaching the stagnation limit
    for _ in range(STAGNATION_LIMIT):
        await strategy.process_ticker()
        await db_and_gui_assertions(
            strategy=strategy,
            completeness=round(
                sum(
                    order.realized_quantity
                    for order in strategy.position_handler.orders
                )
                / sum(order.quantity for order in strategy.position_handler.orders),
                2,
            ),
            stagnation_counter=strategy.position_handler.stagnation_counter,
            stagnation_limit=STAGNATION_LIMIT,
        )
    assert strategy.position_handler.stagnation_counter >= STAGNATION_LIMIT

    logger.info("Stagnation Limit achieved but the price is still within the area")

    await process_ticker(strategy=strategy, last_price=979)

    assert strategy.state == State.STAGNATED
    assert strategy.position_handler.stagnation_counter == 0

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") in [ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED]

    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )

    await process_ticker(strategy=strategy, last_price=900)
    await assert_db_price_level_content(
        db=strategy.position_handler.db, config=strategy.config, state=strategy.state
    )

    await process_ticker(strategy=strategy, last_price=1000)
    assert strategy.state == State.OPEN
    assert all(
        order.status in [ORDER_STATUS_NEW, ORDER_STATUS_FILLED]
        for order in strategy.position_handler.orders
    )

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") in [
            ORDER_STATUS_NEW,
            ORDER_STATUS_FILLED,
        ]

    await db_and_gui_assertions(
        strategy=strategy,
        completeness=round(
            sum(order.realized_quantity for order in strategy.position_handler.orders)
            / sum(order.quantity for order in strategy.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )
    logger.info("All valid orders reopened.")


@pytest.mark.database_integration
async def test_multiple_trading_systems(trading_system_factory):
    # Set initial condition for trading system 1
    trading_system1 = await trading_system_factory(
        get_strategy_config(side=PositionSide.LONG)
    )
    trading_system1.model.client.create_order.side_effect = get_new_orders(
        price_low=trading_system1.model.config.price_low,
        price_high=trading_system1.model.config.price_high,
    )
    strategy1 = trading_system1.model
    assert isinstance(strategy1, HpManager)
    assert strategy1.calculate_trigger_send_orders_price() == 1414

    # Set initial condition for trading system 2
    trading_system2 = await trading_system_factory(
        get_strategy_config(
            side=PositionSide.LONG,
            symbol_info=SymbolInfo(symbol="ETHUSDT", precision=2, price_precision=2),
            system_id="5678",
            price_low=300,
            price_high=420,
        )
    )
    trading_system2.model.client.create_order.side_effect = get_new_orders(
        price_low=trading_system2.model.config.price_low,
        price_high=trading_system2.model.config.price_high,
    )
    strategy2 = trading_system2.model
    assert isinstance(strategy2, HpManager)
    assert strategy2.calculate_trigger_send_orders_price() == 424.2

    # Simulate price outside of the threshold
    await process_ticker(strategy=strategy1, last_price=1415)
    assert strategy1.state == State.NEW
    await process_ticker(strategy=strategy2, last_price=425)
    assert strategy2.state == State.NEW

    # Simulate price on the edge of threshold, opening position
    await process_ticker(strategy=strategy1, last_price=1414)
    assert strategy1.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy1.position_handler.orders
    )
    await db_and_gui_assertions(
        strategy=strategy1,
        completeness=round(
            sum(order.realized_quantity for order in strategy1.position_handler.orders)
            / sum(order.quantity for order in strategy1.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy1.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )
    # Strategy2
    await process_ticker(strategy=strategy2, last_price=424)
    assert strategy1.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy2.position_handler.orders
    )
    await db_and_gui_assertions(
        strategy=strategy2,
        completeness=round(
            sum(order.realized_quantity for order in strategy2.position_handler.orders)
            / sum(order.quantity for order in strategy2.position_handler.orders),
            2,
        ),
        stagnation_counter=strategy2.position_handler.stagnation_counter,
        stagnation_limit=STAGNATION_LIMIT,
    )
