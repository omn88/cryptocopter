import asyncio
import logging
import queue

import aiomysql
from binance.enums import (
    ORDER_STATUS_FILLED,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_PARTIALLY_FILLED,
)

from src.common.database import Database
from src.common.identifiers.common import PositionSide
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import PositionData
from src.strategies.spot.hp_manager import HpManager
from src.common.identifiers.spot import (
    ExecutionReport,
    StrategyConfig,
    TickerUpdate,
    State,
    Order,
)

logger = logging.getLogger("hp_db_gui")


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
    ui_queue: queue.Queue,
    config: StrategyConfig,
    state: State,
    completeness: float,
    stagnation_counter: int,
    stagnation_limit: int,
):
    # Verify GUI queue content
    logger.info("GUI queue size: %s", ui_queue.qsize())
    gui_msg = ui_queue.get()
    assert gui_msg
    logger.info("GUI msg: %s", gui_msg)
    assert isinstance(gui_msg, PositionData)

    assert gui_msg.config.symbol_info.symbol == config.symbol_info.symbol
    assert gui_msg.config.side == config.side
    assert gui_msg.state == state
    assert gui_msg.config.price_low == config.price_low
    assert gui_msg.config.price_high == config.price_high
    assert gui_msg.config.order_trigger == config.order_trigger
    assert gui_msg.config.budget == config.budget
    assert gui_msg.completeness == completeness
    assert gui_msg.stagnation_counter == stagnation_counter
    assert gui_msg.stagnation_limit == stagnation_limit
    assert gui_msg.order_cancel == 2 * config.order_trigger


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
    strategy: HpManager,
    completeness: float,
    stagnation_counter: int,
    stagnation_limit: int,
):
    await assert_db_price_level_content(
        db=strategy.position_handler.db, config=strategy.config, state=strategy.state
    )
    await assert_gui_position_data_content(
        ui_queue=strategy.position_handler.ui_queue,
        config=strategy.config,
        state=strategy.state,
        completeness=completeness,
        stagnation_counter=stagnation_counter,
        stagnation_limit=stagnation_limit,
    )


def get_strategy_config(
    side: PositionSide,
    system_id: str = "1234",
    symbol_info: SymbolInfo = SymbolInfo(
        symbol="BTCUSDT", precision=2, price_precision=2
    ),
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
