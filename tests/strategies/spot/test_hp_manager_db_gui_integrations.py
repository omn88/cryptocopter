import asyncio
from datetime import timedelta
import datetime
import logging

import aiomysql
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_FILLED,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_PARTIALLY_FILLED,
)
import pytest

from src.common.database import Database
from src.common.identifiers.common import Order, PositionSide
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import PositionData
from src.strategies.spot.hp_manager import HpManager, STAGNATION_LIMIT
from src.common.identifiers.spot import (
    ExecutionReport,
    StrategyConfig,
    TickerUpdate,
    State,
)
from tests.spot import get_cancel_order, get_new_orders


logger = logging.getLogger("test_hp_manager_gui_db_integrations")


async def assert_db_price_level_content(
    db: Database, config: StrategyConfig, state: State
):
    async with db.pool.acquire() as conn:
        async with conn.cursor(aiomysql.cursors.DictCursor) as cur:
            await cur.execute(
                "SELECT * FROM price_levels WHERE price_level_id=%s AND is_current=TRUE",
                (config.system_id,),
            )
            result = await cur.fetchone()

            logger.info("Result: %s", result)
            assert result is not None, "Price level not found in the database"
            assert result.get("symbol") == config.symbol_info.symbol
            assert result.get("side") == config.side.value
            assert result.get("price_low") == config.price_low
            assert result.get("price_high") == config.price_high
            assert result.get("state") == state.value
            assert result.get("budget") == config.budget
            assert result.get("order_trigger") == config.order_trigger


async def assert_gui_position_data_content(
    gui_handler: asyncio.Queue,
    orders_filled: int,
    orders_total: int,
    orders_opened: int,
    config: StrategyConfig,
    state: State,
):
    # Verify GUI queue content
    logger.info("GUI queue size: %s", gui_handler.qsize())
    gui_msg = await gui_handler.get()
    assert gui_msg
    logger.info("GUI msg: %s", gui_msg)
    assert isinstance(gui_msg, PositionData)

    assert gui_msg.config.symbol_info.symbol == config.symbol_info.symbol
    assert gui_msg.config.side == config.side
    assert gui_msg.state == state
    assert gui_msg.config.price_low == config.price_low
    assert gui_msg.config.price_high == config.price_high
    assert gui_msg.config.order_trigger == config.order_trigger
    assert gui_msg.orders_filled == orders_filled
    assert gui_msg.orders_total == orders_total
    assert gui_msg.orders_opened == orders_opened
    assert gui_msg.config.budget == config.budget


async def process_ticker(strategy: HpManager, last_price: float):
    logger.info("Processing ticker with last price: %s", last_price)
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    await strategy.process_ticker()  # type: ignore


async def simulate_order_filled(strategy: HpManager, order: Order):
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=order.order_id,
        price=order.price,
        quantity=order.quantity,
        cumulative_filled_quantity=order.quantity,
        last_executed_quantity=order.quantity,
    )
    await strategy.process_order()  # type: ignore


async def simulate_order_partially_filled(
    strategy: HpManager, order: Order, last_realized_quantity: float
):
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=order.order_id,
        price=order.price,
        quantity=order.quantity,
        last_executed_quantity=last_realized_quantity,
        cumulative_filled_quantity=last_realized_quantity,
    )
    await strategy.process_order()  # type: ignore


async def db_and_gui_assertions(
    strategy: HpManager, orders_filled: int, orders_opened: int, orders_total: int
):
    await assert_db_price_level_content(
        db=strategy.position_handler.db, config=strategy.config, state=strategy.state
    )
    await assert_gui_position_data_content(
        gui_handler=strategy.position_handler.gui_handler,
        orders_filled=orders_filled,
        orders_opened=orders_opened,
        orders_total=orders_total,
        config=strategy.config,
        state=strategy.state,
    )


def get_strategy_config(
    side: PositionSide,
    system_id: str = "1234",
    symbol_info: SymbolInfo = SymbolInfo(),
    price_low: float = 1000,
    price_high: float = 1400,
    order_trigger: float = 1.0,
    budget: float = 1000,
):
    return StrategyConfig(
        system_id=system_id,
        symbol_info=symbol_info,
        side=side,
        price_low=price_low,
        price_high=price_high,
        order_trigger=order_trigger,
        budget=budget,
        open_time="",
    )


@pytest.mark.database_integration
async def test_default_buy_scenario(trading_system_factory):
    trading_system = await trading_system_factory(
        get_strategy_config(side=PositionSide.LONG)
    )
    trading_system.strategy.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.strategy.config.price_low,
        price_high=trading_system.strategy.config.price_high,
    )

    # Set initial condition
    strategy = trading_system.strategy
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
        orders_filled=0,
        orders_opened=3,
        orders_total=3,
    )

    # Simulate first order filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[2],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=1,
        orders_opened=2,
        orders_total=3,
    )

    # Simulate second order being filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[1],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=2,
        orders_opened=1,
        orders_total=3,
    )

    # Simulate last order being filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[0],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=3,
        orders_opened=0,
        orders_total=3,
    )

    # Retrieve all orders filled signal from the queue and close the position.
    assert strategy.queue.qsize() == 1
    event = await strategy.queue.get()
    strategy.signal_update = event.content
    await strategy.process_signal()

    assert strategy.state == State.CLOSED
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=3,
        orders_opened=0,
        orders_total=3,
    )


@pytest.mark.database_integration
async def test_default_sell_scenario(trading_system_factory):
    trading_system = await trading_system_factory(
        get_strategy_config(side=PositionSide.SHORT)
    )
    trading_system.strategy.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.strategy.config.price_low,
        price_high=trading_system.strategy.config.price_high,
    )

    # Set initial condition
    strategy = trading_system.strategy
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
        orders_filled=0,
        orders_opened=3,
        orders_total=3,
    )

    # Simulate first order filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[0],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=1,
        orders_opened=2,
        orders_total=3,
    )

    # Simulate second order being filled
    # Simulate first order filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[1],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=2,
        orders_opened=1,
        orders_total=3,
    )

    # Simulate last order being filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[2],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=3,
        orders_opened=0,
        orders_total=3,
    )

    # Retrieve all orders filled signal from the queue and close the position.
    assert strategy.queue.qsize() == 1
    event = await strategy.queue.get()
    strategy.signal_update = event.content
    await strategy.process_signal()
    assert strategy.state == State.CLOSED
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=3,
        orders_opened=0,
        orders_total=3,
    )


@pytest.mark.database_integration
async def test_stagnation_buy_position(trading_system_factory):
    trading_system = await trading_system_factory(
        get_strategy_config(side=PositionSide.LONG)
    )
    trading_system.strategy.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.strategy.config.price_low,
        price_high=trading_system.strategy.config.price_high,
    )
    trading_system.strategy.client.cancel_order.side_effect = get_cancel_order()
    strategy = trading_system.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price() == 1414

    await process_ticker(strategy=strategy, last_price=1400)
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=0,
        orders_opened=3,
        orders_total=3,
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

    assert strategy.position_handler.stagnation_counter >= STAGNATION_LIMIT

    logger.info("Stagnation Limit achieved but the price is still within the area")

    await process_ticker(strategy=strategy, last_price=1429)

    assert strategy.state == State.STAGNATED

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") == ORDER_STATUS_CANCELED

    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=0,
        orders_opened=0,
        orders_total=3,
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
        orders_filled=0,
        orders_opened=3,
        orders_total=3,
    )


@pytest.mark.database_integration
async def test_stagnation_sell_position(trading_system_factory):
    trading_system = await trading_system_factory(
        get_strategy_config(side=PositionSide.SHORT)
    )
    trading_system.strategy.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.strategy.config.price_low,
        price_high=trading_system.strategy.config.price_high,
    )
    trading_system.strategy.client.cancel_order.side_effect = get_cancel_order()
    strategy = trading_system.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price() == 990

    await process_ticker(strategy=strategy, last_price=1000)
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=0,
        orders_opened=3,
        orders_total=3,
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

    assert strategy.position_handler.stagnation_counter >= STAGNATION_LIMIT

    logger.info("Stagnation Limit achieved but the price is still within the area")

    await process_ticker(strategy=strategy, last_price=979)

    assert strategy.state == State.STAGNATED

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") == ORDER_STATUS_CANCELED

    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=0,
        orders_opened=0,
        orders_total=3,
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
        orders_filled=0,
        orders_opened=3,
        orders_total=3,
    )


@pytest.mark.database_integration
async def test_order_reopen_with_filled_orders_buy(trading_system_factory):
    trading_system = await trading_system_factory(
        get_strategy_config(side=PositionSide.LONG)
    )
    trading_system.strategy.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.strategy.config.price_low,
        price_high=trading_system.strategy.config.price_high,
    )
    trading_system.strategy.client.cancel_order.side_effect = get_cancel_order()
    strategy = trading_system.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price() == 1414

    await process_ticker(strategy=strategy, last_price=1400)
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=0,
        orders_opened=3,
        orders_total=3,
    )

    # Simulate first order filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[0],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=1,
        orders_opened=2,
        orders_total=3,
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

    assert strategy.position_handler.stagnation_counter >= STAGNATION_LIMIT

    logger.info("Stagnation Limit achieved but the price is still within the area")

    await process_ticker(strategy=strategy, last_price=1429)

    assert strategy.state == State.STAGNATED

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") in [ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED]

    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=1,
        orders_opened=0,
        orders_total=3,
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
        orders_filled=0,
        orders_opened=2,
        orders_total=2,
    )
    logger.info("All valid orders reopened.")


@pytest.mark.database_integration
async def test_order_reopen_with_filled_orders_sell(trading_system_factory):
    trading_system = await trading_system_factory(
        get_strategy_config(side=PositionSide.SHORT)
    )
    trading_system.strategy.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.strategy.config.price_low,
        price_high=trading_system.strategy.config.price_high,
    )
    trading_system.strategy.client.cancel_order.side_effect = get_cancel_order()
    strategy = trading_system.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price() == 990

    await process_ticker(strategy=strategy, last_price=1000)
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=0,
        orders_opened=3,
        orders_total=3,
    )

    # Simulate first order filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[0],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=1,
        orders_opened=2,
        orders_total=3,
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

    assert strategy.position_handler.stagnation_counter >= STAGNATION_LIMIT

    logger.info("Stagnation Limit achieved but the price is still within the area")

    await process_ticker(strategy=strategy, last_price=979)

    assert strategy.state == State.STAGNATED

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") in [ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED]

    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=1,
        orders_opened=0,
        orders_total=3,
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
        orders_filled=0,
        orders_opened=2,
        orders_total=2,
    )
    logger.info("All valid orders reopened.")


@pytest.mark.database_integration
async def test_order_reopen_with_partially_filled_orders_buy(trading_system_factory):
    trading_system = await trading_system_factory(
        get_strategy_config(side=PositionSide.LONG)
    )
    trading_system.strategy.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.strategy.config.price_low,
        price_high=trading_system.strategy.config.price_high,
    )
    trading_system.strategy.client.cancel_order.side_effect = get_cancel_order()
    strategy = trading_system.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price() == 1414

    await process_ticker(strategy=strategy, last_price=1400)
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=0,
        orders_opened=3,
        orders_total=3,
    )

    # Simulate first order filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[0],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=1,
        orders_opened=2,
        orders_total=3,
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
        orders_filled=1,
        orders_opened=2,
        orders_total=3,
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

    assert strategy.position_handler.stagnation_counter >= STAGNATION_LIMIT

    logger.info("Stagnation Limit achieved but the price is still within the area")

    await process_ticker(strategy=strategy, last_price=1429)

    assert strategy.state == State.STAGNATED

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") in [ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED]

    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=1,
        orders_opened=0,
        orders_total=3,
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
        orders_filled=0,
        orders_opened=2,
        orders_total=2,
    )
    logger.info("All valid orders reopened.")


@pytest.mark.database_integration
async def test_order_reopen_with_partially_filled_orders_sell(trading_system_factory):
    trading_system = await trading_system_factory(
        get_strategy_config(side=PositionSide.SHORT)
    )
    trading_system.strategy.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.strategy.config.price_low,
        price_high=trading_system.strategy.config.price_high,
    )
    trading_system.strategy.client.cancel_order.side_effect = get_cancel_order()
    strategy = trading_system.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price() == 990

    await process_ticker(strategy=strategy, last_price=1000)
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=0,
        orders_opened=3,
        orders_total=3,
    )

    # Simulate first order filled
    await simulate_order_filled(
        strategy=strategy,
        order=strategy.position_handler.orders[0],
    )
    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=1,
        orders_opened=2,
        orders_total=3,
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
        orders_filled=1,
        orders_opened=2,
        orders_total=3,
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

    assert strategy.position_handler.stagnation_counter >= STAGNATION_LIMIT

    logger.info("Stagnation Limit achieved but the price is still within the area")

    await process_ticker(strategy=strategy, last_price=979)

    assert strategy.state == State.STAGNATED

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") in [ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED]

    await db_and_gui_assertions(
        strategy=strategy,
        orders_filled=1,
        orders_opened=0,
        orders_total=3,
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
        orders_filled=0,
        orders_opened=2,
        orders_total=2,
    )
    logger.info("All valid orders reopened.")


@pytest.mark.database_integration
async def test_multiple_trading_systems(trading_system_factory):
    # Set initial condition for trading system 1
    trading_system1 = await trading_system_factory(
        get_strategy_config(side=PositionSide.LONG)
    )
    trading_system1.strategy.client.create_order.side_effect = get_new_orders(
        price_low=trading_system1.strategy.config.price_low,
        price_high=trading_system1.strategy.config.price_high,
    )
    strategy1 = trading_system1.strategy
    assert isinstance(strategy1, HpManager)
    assert strategy1.calculate_trigger_send_orders_price() == 1414

    # Set initial condition for trading system 2
    trading_system2 = await trading_system_factory(
        get_strategy_config(
            side=PositionSide.LONG,
            symbol_info=SymbolInfo(symbol="ETHUSDT"),
            system_id="5678",
            price_low=300,
            price_high=420,
        )
    )
    trading_system2.strategy.client.create_order.side_effect = get_new_orders(
        price_low=trading_system2.strategy.config.price_low,
        price_high=trading_system2.strategy.config.price_high,
    )
    strategy2 = trading_system2.strategy
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
        orders_filled=0,
        orders_opened=3,
        orders_total=3,
    )
    # Strategy2
    await process_ticker(strategy=strategy2, last_price=424)
    assert strategy1.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy2.position_handler.orders
    )
    await db_and_gui_assertions(
        strategy=strategy2,
        orders_filled=0,
        orders_opened=3,
        orders_total=3,
    )

    # # Simulate first order filled
    # await simulate_order_filled(
    #     strategy=strategy,
    #     order=strategy.position_handler.orders[0],
    # )
    # await db_and_gui_assertions(
    #     strategy=strategy,
    #     orders_filled=1,
    #     orders_opened=2,
    #     orders_total=3,
    # )

    # # Simulate second order being filled
    # await simulate_order_filled(
    #     strategy=strategy,
    #     order=strategy.position_handler.orders[1],
    # )
    # await db_and_gui_assertions(
    #     strategy=strategy,
    #     orders_filled=2,
    #     orders_opened=1,
    #     orders_total=3,
    # )

    # # Simulate last order being filled
    # await simulate_order_filled(
    #     strategy=strategy,
    #     order=strategy.position_handler.orders[2],
    # )
    # await db_and_gui_assertions(
    #     strategy=strategy,
    #     orders_filled=3,
    #     orders_opened=0,
    #     orders_total=3,
    # )

    # # Retrieve all orders filled signal from the queue and close the position.
    # assert strategy.queue.qsize() == 1
    # event = await strategy.queue.get()
    # strategy.signal_update = event.content
    # await strategy.process_signal()

    # assert strategy.state == State.CLOSED
    # strategy.config.status = PositionStatus.CLOSED
    # await db_and_gui_assertions(
    #     strategy=strategy,
    #     orders_filled=3,
    #     orders_opened=0,
    #     orders_total=3,
    # )
