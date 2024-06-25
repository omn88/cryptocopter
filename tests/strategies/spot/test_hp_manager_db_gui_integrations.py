from datetime import timedelta
import logging

import aiomysql
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_FILLED,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_CANCELED,
)
import pytest

from src.common.database import Database
from src.common.identifiers.common import PositionSide, PositionStatus
from src.gui.identifiers.spot import PositionData
from src.strategies.spot.hp_manager import HpManager, STAGNATION_LIMIT
from src.common.identifiers.spot import ExecutionReport, TickerUpdate, State
from tests.spot import get_buy_orders, get_cancel_order, get_sell_orders


logger = logging.getLogger("test_hp_manager_gui_db_integrations")


async def assert_db_price_level_content(
    db: Database, system_id: str, side: PositionSide, status: PositionStatus
):
    async with db.pool.acquire() as conn:
        async with conn.cursor(aiomysql.cursors.DictCursor) as cur:
            await cur.execute(
                "SELECT * FROM price_levels WHERE price_level_id=%s AND is_current=TRUE",
                (system_id,),
            )
            result = await cur.fetchone()

            logger.info("Result: %s", result)
            assert result is not None, "Price level not found in the database"
            assert result.get("symbol") == "BTCUSDT"
            assert result.get("side") == side.value
            assert result.get("price_low") == 1000.0
            assert result.get("price_high") == 1400.0
            assert result.get("status") == status.value
            assert result.get("budget") == 1000
            assert result.get("order_trigger") == 1.0


async def assert_gui_position_data_content(
    gui_handler, orders_filled, orders_total, orders_opened, side, status
):
    # Verify GUI queue content
    logger.info("GUI queue size: %s", gui_handler.qsize())
    gui_msg = await gui_handler.get()
    assert gui_msg
    logger.info("GUI msg: %s", gui_msg)
    assert isinstance(gui_msg, PositionData)

    assert gui_msg.symbol == "BTCUSDT"
    assert gui_msg.side == side
    assert gui_msg.status == status
    assert gui_msg.price_low == 1000
    assert gui_msg.price_high == 1400
    assert gui_msg.order_trigger == 1.0
    assert gui_msg.orders_filled == orders_filled
    assert gui_msg.orders_total == orders_total
    assert gui_msg.orders_opened == orders_opened
    assert gui_msg.budget == 1000


async def process_ticker(strategy: HpManager, last_price: float):
    logger.info("Processing ticker with last price: %s", last_price)
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    await strategy.process_ticker()  # type: ignore


@pytest.mark.database_integration
async def test_default_buy_scenario(spot_buy_with_gui_and_db):
    spot_buy_with_gui_and_db.strategy.client.create_order.side_effect = get_buy_orders()

    # Set initial condition
    strategy = spot_buy_with_gui_and_db.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.trigger_orders_price == 1414

    # Simulate price outside of the threshold
    await process_ticker(strategy=strategy, last_price=1415)
    assert strategy.state == State.NEW

    # Simulate position opening
    await process_ticker(strategy=strategy, last_price=1414)
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    status = PositionStatus.OPEN
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=status,
        side=strategy.config.side,
    )
    await assert_gui_position_data_content(
        gui_handler=strategy.position_handler.gui_handler,
        orders_filled=0,
        orders_opened=3,
        orders_total=3,
        side=strategy.config.side,
        status=status,
    )

    # Simulate first order being filled
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.position_handler.orders[0].order_id,
    )
    await strategy.process_order()
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=PositionStatus.OPEN,
        side=strategy.config.side,
    )
    await assert_gui_position_data_content(
        gui_handler=strategy.position_handler.gui_handler,
        orders_filled=1,
        orders_opened=2,
        orders_total=3,
        side=strategy.config.side,
        status=status,
    )

    # Simulate second order being filled
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.position_handler.orders[1].order_id,
    )
    await strategy.process_order()
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=PositionStatus.OPEN,
        side=strategy.config.side,
    )
    await assert_gui_position_data_content(
        gui_handler=strategy.position_handler.gui_handler,
        orders_filled=2,
        orders_opened=1,
        orders_total=3,
        side=strategy.config.side,
        status=status,
    )

    # Simulate last order being filled
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.position_handler.orders[2].order_id,
    )
    await strategy.process_order()
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=PositionStatus.OPEN,
        side=strategy.config.side,
    )
    await assert_gui_position_data_content(
        gui_handler=strategy.position_handler.gui_handler,
        orders_filled=3,
        orders_opened=0,
        orders_total=3,
        side=strategy.config.side,
        status=status,
    )

    # Retrieve all orders filled signal from the queue and close the position.
    assert strategy.queue.qsize() == 1
    event = await strategy.queue.get()
    strategy.signal_update = event.content
    await strategy.process_signal()

    assert strategy.state == State.CLOSED
    status = PositionStatus.CLOSED
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=status,
        side=strategy.config.side,
    )
    await assert_gui_position_data_content(
        gui_handler=strategy.position_handler.gui_handler,
        orders_filled=3,
        orders_opened=0,
        orders_total=3,
        side=strategy.config.side,
        status=status,
    )


@pytest.mark.database_integration
async def test_default_sell_scenario(spot_sell_with_gui_and_db):
    spot_sell_with_gui_and_db.strategy.client.create_order.side_effect = (
        get_sell_orders()
    )

    # Set initial condition
    strategy = spot_sell_with_gui_and_db.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.trigger_orders_price == 990
    await process_ticker(strategy=strategy, last_price=989)
    assert strategy.state == State.NEW

    # Simulate process_signal triggering
    await process_ticker(strategy=strategy, last_price=990)
    assert strategy.state == State.OPEN
    status = PositionStatus.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=status,
        side=strategy.config.side,
    )
    await assert_gui_position_data_content(
        gui_handler=strategy.position_handler.gui_handler,
        orders_filled=0,
        orders_opened=3,
        orders_total=3,
        side=strategy.config.side,
        status=status,
    )

    # Simulate first order being filled
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.position_handler.orders[0].order_id,
    )
    await strategy.process_order()
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=status,
        side=strategy.config.side,
    )
    await assert_gui_position_data_content(
        gui_handler=strategy.position_handler.gui_handler,
        orders_filled=1,
        orders_opened=2,
        orders_total=3,
        side=strategy.config.side,
        status=status,
    )

    # Simulate second order being filled
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.position_handler.orders[1].order_id,
    )
    await strategy.process_order()
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=status,
        side=strategy.config.side,
    )
    await assert_gui_position_data_content(
        gui_handler=strategy.position_handler.gui_handler,
        orders_filled=2,
        orders_opened=1,
        orders_total=3,
        side=strategy.config.side,
        status=status,
    )

    # Simulate last order being filled
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.position_handler.orders[2].order_id,
    )
    await strategy.process_order()
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=PositionStatus.OPEN,
        side=strategy.config.side,
    )
    await assert_gui_position_data_content(
        gui_handler=strategy.position_handler.gui_handler,
        orders_filled=3,
        orders_opened=0,
        orders_total=3,
        side=strategy.config.side,
        status=status,
    )

    # Retrieve all orders filled signal from the queue and close the position.
    assert strategy.queue.qsize() == 1
    event = await strategy.queue.get()
    strategy.signal_update = event.content
    await strategy.process_signal()
    assert strategy.state == State.CLOSED
    status = PositionStatus.CLOSED
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=status,
        side=strategy.config.side,
    )
    await assert_gui_position_data_content(
        gui_handler=strategy.position_handler.gui_handler,
        orders_filled=3,
        orders_opened=0,
        orders_total=3,
        side=strategy.config.side,
        status=status,
    )


@pytest.mark.database_integration
async def test_stagnation_buy_position(spot_buy_with_gui_and_db):
    spot_buy_with_gui_and_db.strategy.client.create_order.side_effect = get_buy_orders()
    spot_buy_with_gui_and_db.strategy.client.cancel_order.side_effect = (
        get_cancel_order()
    )
    strategy = spot_buy_with_gui_and_db.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.trigger_orders_price == 1414

    await process_ticker(strategy=strategy, last_price=1400)
    assert strategy.state == State.OPEN
    status = PositionStatus.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=status,
        side=strategy.config.side,
    )
    await assert_gui_position_data_content(
        gui_handler=strategy.position_handler.gui_handler,
        orders_filled=0,
        orders_opened=3,
        orders_total=3,
        side=strategy.config.side,
        status=status,
    )

    # Simulate stagnation counter increase
    assert strategy.position_handler.stagnation_counter == 0
    strategy.position_handler.next_monitor_position_time -= timedelta(hours=8)

    # Simulate reaching the stagnation limit
    for _ in range(STAGNATION_LIMIT):
        await strategy.process_ticker()

    assert strategy.position_handler.stagnation_counter >= STAGNATION_LIMIT

    logger.info("Stagnation Limit achieved but the price is still within the area")

    await process_ticker(strategy=strategy, last_price=1415)

    assert strategy.state == State.STAGNATED
    status = PositionStatus.STAGNATED

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 3
    for order in orders:
        assert order.get("status") == ORDER_STATUS_CANCELED

    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=status,
        side=strategy.config.side,
    )
    await assert_gui_position_data_content(
        gui_handler=strategy.position_handler.gui_handler,
        orders_filled=0,
        orders_opened=0,
        orders_total=3,
        side=strategy.config.side,
        status=status,
    )

    await process_ticker(strategy=strategy, last_price=1500)
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=status,
        side=strategy.config.side,
    )

    await process_ticker(strategy=strategy, last_price=1400)
    assert strategy.state == State.OPEN
    status = PositionStatus.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    orders = await strategy.db.fetch_orders_for_price_level(
        price_level_id=strategy.config.system_id
    )

    assert len(orders) == 6
    for order in orders:
        assert order.get("status") in [ORDER_STATUS_NEW, ORDER_STATUS_CANCELED]

    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=status,
        side=strategy.config.side,
    )
    await assert_gui_position_data_content(
        gui_handler=strategy.position_handler.gui_handler,
        orders_filled=0,
        orders_opened=3,
        orders_total=3,
        side=strategy.config.side,
        status=status,
    )
