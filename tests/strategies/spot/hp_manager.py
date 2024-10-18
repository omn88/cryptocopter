import logging
import queue
import time

import aiomysql
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_FILLED,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_PARTIALLY_FILLED,
)

from src.common.database import Database
from src.common.identifiers.common import Mode, PositionSide
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import PositionData
from src.strategies.spot.hp_manager import HpManager
from src.common.identifiers.spot import (
    ExecutionReport,
    HPConfig,
    StateInfo,
    TickerUpdate,
    State,
    Order,
)
from tests.spot import get_new_orders

logger = logging.getLogger("hp_db_gui")


async def assert_db_price_level_content(db: Database, config: HPConfig, state: State):
    assert db.pool is not None
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


def assert_gui_position_data_content(
    ui_queue: queue.Queue,
    config: HPConfig,
    state_info: StateInfo,
    completeness: float,
):
    try:
        logger.info("GUI queue size: %s", ui_queue.qsize())
        gui_msg = ui_queue.get_nowait()
        assert gui_msg
        logger.info("GUI msg: %s", gui_msg)
        assert isinstance(gui_msg, PositionData)

        assert gui_msg.config.symbol_info.symbol == config.symbol_info.symbol
        assert gui_msg.state_info.side == state_info.side
        assert gui_msg.state_info.state == state_info.state
        assert gui_msg.config.price_low == config.price_low
        assert gui_msg.config.price_high == config.price_high
        assert gui_msg.config.order_trigger == config.order_trigger
        assert gui_msg.config.budget == config.budget
        assert gui_msg.completeness == completeness
        assert gui_msg.state_info.stagnation_counter == state_info.stagnation_counter
        assert gui_msg.state_info.stagnation_limit == state_info.stagnation_limit
        assert gui_msg.order_cancel == 2 * config.order_trigger

    except queue.Empty:
        time.sleep(0.1)


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
):
    db = strategy.buy_position.db
    db.run_db_task(
        assert_db_price_level_content(
            db=strategy.buy_position.db,
            config=strategy.buy_position.config,
            state=strategy.state,
        )
    )
    assert_gui_position_data_content(
        ui_queue=strategy.buy_position.ui_queue,
        config=strategy.buy_position.config,
        state_info=strategy.buy_position.state_info,
        completeness=completeness,
    )


def get_default_buy_position(trading_system_factory) -> HpManager:
    trading_system = trading_system_factory(
        hp_config=HPConfig(
            hp_id=1000,
            symbol_info=SymbolInfo(symbol="BTCUSDT", precision=2, price_precision=2),
            price_low=1000,
            price_high=1400,
            order_trigger=1.0,
            budget=1000,
        ),
        state_info=StateInfo(),
    )

    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    assert strategy.buy_position.config.hp_id == 1000
    assert strategy.buy_position.config.price_low == 1000
    assert strategy.buy_position.config.price_high == 1400
    assert strategy.buy_position.config.order_trigger == 1
    assert strategy.buy_position.config.budget == 1000
    assert strategy.buy_position.config.mode == Mode.DCA
    assert strategy.buy_position.config.symbol_info.symbol == "BTCUSDT"

    assert strategy.buy_position.state_info.side == PositionSide.LONG
    assert strategy.buy_position.state_info.state == State.NEW
    assert strategy.buy_position.state_info.stagnation_counter == 0
    assert strategy.buy_position.state_info.stagnation_limit == 8

    assert strategy.calculate_trigger_send_orders_price_buy() == 1414
    assert strategy.state == State.NEW
    assert len(strategy.buy_position.orders) == 3

    assert strategy.sell_position.config.hp_id == 1000
    assert strategy.sell_position.config.price_low == 0
    assert strategy.sell_position.config.price_high == 0
    assert strategy.sell_position.config.order_trigger == 0
    assert strategy.sell_position.config.budget == 0
    assert strategy.sell_position.config.mode == Mode.DCA
    assert strategy.sell_position.config.symbol_info.symbol == "BTCUSDT"

    assert strategy.sell_position.state_info.side == PositionSide.SHORT
    assert strategy.sell_position.state_info.state == State.NEW
    assert strategy.sell_position.state_info.stagnation_counter == 0
    assert strategy.sell_position.state_info.stagnation_limit == 8

    assert len(strategy.sell_position.orders) == 0

    return strategy


async def move_to_buy_position_active(strategy: HpManager) -> HpManager:
    strategy.client.create_order.side_effect = get_new_orders(
        price_low=strategy.buy_position.config.price_low,
        price_high=strategy.buy_position.config.price_high,
    )

    assert strategy.calculate_trigger_send_orders_price_buy() == 1414
    strategy.ticker_update = TickerUpdate(last_price=1414)
    await strategy.process_ticker()

    assert strategy.buy_position.state_info.state == State.BUYING
    assert strategy.state == State.BUYING
    assert len(strategy.buy_position.orders) == 3

    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.buy_position.orders
    )

    return strategy
