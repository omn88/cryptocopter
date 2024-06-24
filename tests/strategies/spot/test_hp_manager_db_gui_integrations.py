import logging

import aiomysql
from binance.enums import ORDER_STATUS_NEW, ORDER_STATUS_FILLED, ORDER_TYPE_LIMIT

from src.common.database import Database
from src.common.identifiers.common import PositionSide, PositionStatus
from src.gui.identifiers.spot import PositionData
from src.strategies.spot.hp_manager import (
    HpManager,
)  # Ensure this import matches your project structure
from src.common.identifiers.spot import ExecutionReport, TickerUpdate, State
from tests.spot import get_buy_orders, get_sell_orders


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


async def test_default_buy_scenario(spot_buy_with_gui_and_db):
    spot_buy_with_gui_and_db.strategy.client.create_order.side_effect = get_buy_orders()

    # Set initial condition
    strategy = spot_buy_with_gui_and_db.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.trigger_orders_price == 1414
    last_price = 1500
    logger.info(
        "Processing ticker with last price outside of threshold: %s", last_price
    )
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    # Simulate no state change
    await strategy.process_ticker()
    assert strategy.state == State.NEW

    # Simulate no state change but on the price edge
    last_price = 1415
    logger.info(
        "Processing ticker with last price on the edge of threshold: %s", last_price
    )
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()
    assert strategy.state == State.NEW

    # Simulate process_signal triggering
    last_price = 1414
    logger.info(
        "Processing ticker with last price touching the threshold: %s", last_price
    )
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()
    assert strategy.state == State.OPEN

    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    # Verify database state
    async with strategy.position_handler.db.pool.acquire() as conn:
        async with conn.cursor(aiomysql.cursors.DictCursor) as cur:
            await cur.execute(
                "SELECT * FROM price_levels WHERE price_level_id=%s AND is_current=TRUE",
                (strategy.config.system_id,),
            )
            result = await cur.fetchone()

            logger.info("Result: %s", result)
            assert result is not None, "Price level not found in the database"
            assert result.get("symbol") == "BTCUSDT"
            assert result.get("side") == PositionSide.LONG.value
            assert result.get("price_low") == 1000.0
            assert result.get("price_high") == 1400.0
            assert result.get("status") == PositionStatus.OPEN.value
            assert result.get("budget") == 1000
            assert result.get("order_trigger") == 1.0

    # Verify GUI queue content
    gui_msg = await strategy.position_handler.gui_handler.get()
    assert gui_msg
    logger.info("GUI msg: %s", gui_msg)
    assert isinstance(gui_msg, PositionData)

    assert gui_msg.symbol == "BTCUSDT"
    assert gui_msg.side == PositionSide.LONG
    assert gui_msg.status == PositionStatus.OPEN
    assert gui_msg.price_low == 1000
    assert gui_msg.price_high == 1400
    assert gui_msg.order_trigger == 1.0
    assert gui_msg.orders_filled == 0
    assert gui_msg.orders_total == 3
    assert gui_msg.orders_opened == 3
    assert gui_msg.budget == 1000

    # Simulate first order being filled
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.position_handler.orders[0].order_id,
    )
    # Simulate order confirmation
    await strategy.process_order()

    # Verify database state
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=PositionStatus.OPEN,
        side=strategy.config.side,
    )

    # Verify GUI queue content
    gui_msg = await strategy.position_handler.gui_handler.get()
    assert gui_msg
    logger.info("GUI msg: %s", gui_msg)
    assert isinstance(gui_msg, PositionData)

    assert gui_msg.symbol == "BTCUSDT"
    assert gui_msg.side == PositionSide.LONG
    assert gui_msg.status == PositionStatus.OPEN
    assert gui_msg.price_low == 1000
    assert gui_msg.price_high == 1400
    assert gui_msg.order_trigger == 1.0
    assert gui_msg.orders_filled == 1
    assert gui_msg.orders_total == 3
    assert gui_msg.orders_opened == 2
    assert gui_msg.budget == 1000

    # Simulate second order being filled
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.position_handler.orders[1].order_id,
    )
    # Simulate order confirmation
    await strategy.process_order()

    # Verify database state
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=PositionStatus.OPEN,
        side=strategy.config.side,
    )

    # Verify GUI queue content
    gui_msg = await strategy.position_handler.gui_handler.get()
    assert gui_msg
    logger.info("GUI msg: %s", gui_msg)
    assert isinstance(gui_msg, PositionData)

    assert gui_msg.symbol == "BTCUSDT"
    assert gui_msg.side == PositionSide.LONG
    assert gui_msg.status == PositionStatus.OPEN
    assert gui_msg.price_low == 1000
    assert gui_msg.price_high == 1400
    assert gui_msg.order_trigger == 1.0
    assert gui_msg.orders_filled == 2
    assert gui_msg.orders_total == 3
    assert gui_msg.orders_opened == 1
    assert gui_msg.budget == 1000

    # Simulate last order being filled
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.position_handler.orders[2].order_id,
    )
    # Simulate order confirmation
    await strategy.process_order()

    # Verify database state
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=PositionStatus.OPEN,
        side=strategy.config.side,
    )

    # Verify GUI queue content
    gui_msg = await strategy.position_handler.gui_handler.get()
    assert gui_msg
    logger.info("GUI msg: %s", gui_msg)
    assert isinstance(gui_msg, PositionData)

    assert gui_msg.symbol == "BTCUSDT"
    assert gui_msg.side == PositionSide.LONG
    assert gui_msg.status == PositionStatus.OPEN
    assert gui_msg.price_low == 1000
    assert gui_msg.price_high == 1400
    assert gui_msg.order_trigger == 1.0
    assert gui_msg.orders_filled == 3
    assert gui_msg.orders_total == 3
    assert gui_msg.orders_opened == 0
    assert gui_msg.budget == 1000

    assert strategy.queue.qsize() == 1
    event = await strategy.queue.get()
    strategy.signal_update = event.content
    await strategy.process_signal()

    assert strategy.state == State.CLOSED

    # Verify database state
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=PositionStatus.CLOSED,
        side=strategy.config.side,
    )

    # Verify GUI queue content
    gui_msg = await strategy.position_handler.gui_handler.get()
    assert gui_msg
    logger.info("GUI msg: %s", gui_msg)
    assert isinstance(gui_msg, PositionData)

    assert gui_msg.symbol == "BTCUSDT"
    assert gui_msg.side == PositionSide.LONG
    assert gui_msg.status == PositionStatus.CLOSED
    assert gui_msg.price_low == 1000
    assert gui_msg.price_high == 1400
    assert gui_msg.order_trigger == 1.0
    assert gui_msg.orders_filled == 3
    assert gui_msg.orders_total == 3
    assert gui_msg.orders_opened == 0
    assert gui_msg.budget == 1000


async def test_default_sell_scenario(spot_sell_with_gui_and_db):
    spot_sell_with_gui_and_db.strategy.client.create_order.side_effect = (
        get_sell_orders()
    )

    # Set initial condition
    strategy = spot_sell_with_gui_and_db.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.trigger_orders_price == 990
    last_price = 900
    logger.info(
        "Processing ticker with last price outside of threshold: %s", last_price
    )
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    # Simulate no state change
    await strategy.process_ticker()
    assert strategy.state == State.NEW

    # Simulate no state change but on the price edge
    last_price = 989
    logger.info(
        "Processing ticker with last price on the edge of threshold: %s", last_price
    )
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()
    assert strategy.state == State.NEW

    # Simulate process_signal triggering
    last_price = 990
    logger.info(
        "Processing ticker with last price touching the threshold: %s", last_price
    )
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()
    assert strategy.state == State.OPEN

    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    # Verify database state
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=PositionStatus.OPEN,
        side=strategy.config.side,
    )

    # Verify GUI queue content
    gui_msg = await strategy.position_handler.gui_handler.get()
    assert gui_msg
    logger.info("GUI msg: %s", gui_msg)
    assert isinstance(gui_msg, PositionData)

    assert gui_msg.symbol == "BTCUSDT"
    assert gui_msg.side == PositionSide.SHORT
    assert gui_msg.status == PositionStatus.OPEN
    assert gui_msg.price_low == 1000
    assert gui_msg.price_high == 1400
    assert gui_msg.order_trigger == 1.0
    assert gui_msg.orders_filled == 0
    assert gui_msg.orders_total == 3
    assert gui_msg.orders_opened == 3
    assert gui_msg.budget == 1000

    # Simulate first order being filled
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.position_handler.orders[0].order_id,
    )
    # Simulate order confirmation
    await strategy.process_order()

    # Verify database state
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=PositionStatus.OPEN,
        side=strategy.config.side,
    )

    # Verify GUI queue content
    gui_msg = await strategy.position_handler.gui_handler.get()
    assert gui_msg
    logger.info("GUI msg: %s", gui_msg)
    assert isinstance(gui_msg, PositionData)

    assert gui_msg.symbol == "BTCUSDT"
    assert gui_msg.side == PositionSide.SHORT
    assert gui_msg.status == PositionStatus.OPEN
    assert gui_msg.price_low == 1000
    assert gui_msg.price_high == 1400
    assert gui_msg.order_trigger == 1.0
    assert gui_msg.orders_filled == 1
    assert gui_msg.orders_total == 3
    assert gui_msg.orders_opened == 2
    assert gui_msg.budget == 1000

    # Simulate second order being filled
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.position_handler.orders[1].order_id,
    )
    # Simulate order confirmation
    await strategy.process_order()

    # Verify database state
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=PositionStatus.OPEN,
        side=strategy.config.side,
    )

    # Verify GUI queue content
    gui_msg = await strategy.position_handler.gui_handler.get()
    assert gui_msg
    logger.info("GUI msg: %s", gui_msg)
    assert isinstance(gui_msg, PositionData)

    assert gui_msg.symbol == "BTCUSDT"
    assert gui_msg.side == PositionSide.SHORT
    assert gui_msg.status == PositionStatus.OPEN
    assert gui_msg.price_low == 1000
    assert gui_msg.price_high == 1400
    assert gui_msg.order_trigger == 1.0
    assert gui_msg.orders_filled == 2
    assert gui_msg.orders_total == 3
    assert gui_msg.orders_opened == 1
    assert gui_msg.budget == 1000

    # Simulate last order being filled
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.position_handler.orders[2].order_id,
    )
    # Simulate order confirmation
    await strategy.process_order()

    # Verify database state
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=PositionStatus.OPEN,
        side=strategy.config.side,
    )

    # Verify GUI queue content
    gui_msg = await strategy.position_handler.gui_handler.get()
    assert gui_msg
    logger.info("GUI msg: %s", gui_msg)
    assert isinstance(gui_msg, PositionData)

    assert gui_msg.symbol == "BTCUSDT"
    assert gui_msg.side == PositionSide.SHORT
    assert gui_msg.status == PositionStatus.OPEN
    assert gui_msg.price_low == 1000
    assert gui_msg.price_high == 1400
    assert gui_msg.order_trigger == 1.0
    assert gui_msg.orders_filled == 3
    assert gui_msg.orders_total == 3
    assert gui_msg.orders_opened == 0
    assert gui_msg.budget == 1000

    assert strategy.queue.qsize() == 1
    event = await strategy.queue.get()
    strategy.signal_update = event.content
    await strategy.process_signal()

    assert strategy.state == State.CLOSED

    # Verify database state
    await assert_db_price_level_content(
        db=strategy.position_handler.db,
        system_id=strategy.config.system_id,
        status=PositionStatus.CLOSED,
        side=strategy.config.side,
    )

    # Verify GUI queue content
    gui_msg = await strategy.position_handler.gui_handler.get()
    assert gui_msg
    logger.info("GUI msg: %s", gui_msg)
    assert isinstance(gui_msg, PositionData)

    assert gui_msg.symbol == "BTCUSDT"
    assert gui_msg.side == PositionSide.SHORT
    assert gui_msg.status == PositionStatus.CLOSED
    assert gui_msg.price_low == 1000
    assert gui_msg.price_high == 1400
    assert gui_msg.order_trigger == 1.0
    assert gui_msg.orders_filled == 3
    assert gui_msg.orders_total == 3
    assert gui_msg.orders_opened == 0
    assert gui_msg.budget == 1000
