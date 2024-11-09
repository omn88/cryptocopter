import logging
import queue
import time
from typing import Dict, List

import aiomysql
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_FILLED,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_CANCELED,
)
from transitions.extensions.asyncio import AsyncMachine
from src.common.database import Database
from src.common.identifiers.common import Mode, PositionSide
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import PositionData
from src.strategies.spot.hp_manager import HpManager
from src.gui.hpmanager import HpManager as HPGUI
from src.common.identifiers.spot import (
    Event,
    EventName,
    ExecutionReport,
    HPConfig,
    SignalUpdate,
    StateInfo,
    TickerUpdate,
    State,
    Order,
    UiState,
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
        assert gui_msg.state_info.completeness == completeness
        assert gui_msg.state_info.stagnation_counter == state_info.stagnation_counter
        assert gui_msg.state_info.stagnation_limit == state_info.stagnation_limit
        assert gui_msg.order_cancel == 2 * config.order_trigger

    except queue.Empty:
        time.sleep(0.1)


async def process_ticker(strategy: HpManager, last_price: float):
    logger.info("Processing ticker with last price: %s", last_price)
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    await strategy.process_ticker()  # type: ignore[attr-defined]  # type: ignore


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
    await strategy.process_order()  # type: ignore[attr-defined]


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
    await strategy.process_order()  # type: ignore[attr-defined]  # type: ignore


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


def get_default_buy_position(trading_system_factory, hp_list) -> AsyncMachine:
    trading_system = trading_system_factory(
        hp_config=HPConfig(
            hp_id="1000",
            symbol_info=SymbolInfo(symbol="BTCUSDT", precision=2, price_precision=2),
            price_low=1000,
            price_high=1400,
            order_trigger=1.0,
            budget=1000,
        ),
        hp_list=hp_list,
    )

    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy.client.create_order.side_effect = get_new_orders(
        price_low=strategy.buy_position.config.price_low,
        price_high=strategy.buy_position.config.price_high,
    )
    assert strategy.buy_position.config.hp_id == "1000"
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
    assert strategy.buy_position.state_info.completeness == 0
    assert strategy.buy_position.state_info.ui_state == UiState.NEW

    assert strategy.calculate_trigger_send_orders_price_buy() == 1414

    assert len(strategy.buy_position.orders) == 3
    assert strategy.buy_position.orders[0].quantity == 0.24
    assert strategy.buy_position.orders[1].quantity == 0.28
    assert strategy.buy_position.orders[2].quantity == 0.33

    assert strategy.sell_position.config.hp_id == "1000"
    assert strategy.sell_position.config.price_low == 0
    assert strategy.sell_position.config.price_high == 0
    assert strategy.sell_position.config.order_trigger == 0
    assert strategy.sell_position.config.budget == 0
    assert strategy.sell_position.config.mode == Mode.DCA
    assert strategy.sell_position.config.symbol_info.symbol == "BTCUSDT"

    assert strategy.sell_position.state_info.side == PositionSide.SHORT

    assert strategy.sell_position.state_info.stagnation_counter == 0
    assert strategy.sell_position.state_info.stagnation_limit == 8
    assert strategy.sell_position.state_info.state == State.NEW
    assert strategy.state == State.NEW
    assert len(strategy.sell_position.orders) == 0

    return trading_system


def assert_default_buy_position_data(
    strategy: HpManager, content: PositionData
) -> HpManager:
    config = content.config
    assert isinstance(config, HPConfig)

    assert config.hp_id == "1000"
    assert config.price_low == 1000
    assert config.price_high == 1400
    assert config.budget == 1000
    assert config.order_trigger == 1.0
    assert config.mode == Mode.DCA
    assert config.symbol_info.symbol == "BTCUSDT"
    assert config.symbol_info.precision == 2
    assert config.symbol_info.price_precision == 2

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.NEW
    assert state_info.stagnation_counter == 0
    assert state_info.stagnation_limit == 8
    assert state_info.side == PositionSide.LONG
    assert not state_info.next_monitor_time

    assert content.state_info.ui_state == UiState.NEW
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 0.00
    assert content.recovering is False

    assert strategy.buy_position.ui_queue.qsize() == 0

    return strategy


def assert_default_active_position_data(
    strategy: HpManager, content: PositionData
) -> HpManager:
    config = content.config
    assert isinstance(config, HPConfig)

    assert config.hp_id == "1000"
    assert config.price_low == 1000
    assert config.price_high == 1400
    assert config.budget == 1000
    assert config.order_trigger == 1.0
    assert config.mode == Mode.DCA
    assert config.symbol_info.symbol == "BTCUSDT"
    assert config.symbol_info.precision == 2
    assert config.symbol_info.price_precision == 2

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.NEW
    assert state_info.stagnation_counter == 0
    assert state_info.stagnation_limit == 8
    assert state_info.side == PositionSide.LONG
    assert state_info.next_monitor_time

    assert content.state_info.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 0.00
    assert content.recovering is False

    assert strategy.buy_position.ui_queue.qsize() == 0

    return strategy


def assert_default_hp_list_item(hp_list):
    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "0.0"
    assert item["quantity"] == "0.0"
    assert item["quantity_usdt"] == "0.0"
    assert item["sell_price"] == "0.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "NEW"


async def move_to_buy_position_active(
    strategy: HpManager, trigger_price: float
) -> HpManager:
    assert strategy.calculate_trigger_send_orders_price_buy() == trigger_price
    strategy.ticker_update = TickerUpdate(last_price=trigger_price)

    assert strategy.conditions_for_sending_buy_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    logger.info("State: %s", strategy.state)
    assert strategy.state == State.BUYING
    assert len(strategy.buy_position.orders) == 3

    return strategy


async def simulate_partial_fill(
    strategy: HpManager, hp_gui: HPGUI, hp_list: List
) -> HpManager:
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=445860,
        last_executed_quantity=0.12,
        last_executed_price=1400,
        cumulative_filled_quantity=0.12,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy_position.orders)
    assert strategy.buy_position.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert strategy.buy_position.orders[1].status == ORDER_STATUS_NEW
    assert strategy.buy_position.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.state_info.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 0.14
    assert strategy.buy_position.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.12"
    assert item["quantity_usdt"] == "168.0"
    assert item["sell_price"] == "0.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "BUYING"

    logger.info("HP List after the update: %s", hp_list)

    return strategy


async def simulate_first_buy_order_fill(
    strategy: HpManager, hp_gui: HPGUI, hp_list: List[Dict]
) -> HpManager:
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445860,
        last_executed_quantity=0.1,
        last_executed_price=1400,
        cumulative_filled_quantity=0.24,
        price=1400.0,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy_position.orders)
    assert strategy.buy_position.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[1].status == ORDER_STATUS_NEW
    assert strategy.buy_position.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.state_info.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 0.28

    assert strategy.buy_position.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.24"
    assert item["quantity_usdt"] == "336.0"
    assert item["sell_price"] == "0.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "BUYING"

    logger.info("HP List after the update: %s", hp_list)

    return strategy


async def simulate_second_buy_order_fill(strategy: HpManager) -> HpManager:
    # Simulate full order fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445861,
        last_executed_quantity=0.28,
        last_executed_price=1400,
        cumulative_filled_quantity=0.28,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy_position.orders)
    assert strategy.buy_position.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[1].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.state_info.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 0.61

    assert strategy.buy_position.ui_queue.qsize() == 0

    return strategy


async def simulate_third_buy_order_partial_fill(strategy: HpManager) -> HpManager:
    # Simulate partial order fill of order which is rebuy after first time two first orders were fillled and this is the last one.
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=445864,
        last_executed_quantity=0.18,
        last_executed_price=1400,
        cumulative_filled_quantity=0.18,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy_position.orders)
    assert strategy.buy_position.orders[2].status == ORDER_STATUS_PARTIALLY_FILLED

    return strategy


async def simulate_third_buy_order_fill(strategy: HpManager) -> HpManager:
    # Simulate full order fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445862,
        last_executed_quantity=0.33,
        last_executed_price=1400,
        cumulative_filled_quantity=0.33,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy_position.orders)
    assert strategy.buy_position.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[1].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[2].status == ORDER_STATUS_FILLED

    assert strategy.core_queue.qsize() == 1
    event = strategy.core_queue.get_nowait()

    assert isinstance(event, Event)
    assert event.name == EventName.SIGNAL
    assert isinstance(event.content, SignalUpdate)

    strategy.signal_update = event.content

    await strategy.process_signal()  # type: ignore[attr-defined]

    assert strategy.buy_position.state_info.state == State.BOUGHT
    assert strategy.state == State.BOUGHT

    assert strategy.core_queue.qsize() == 0

    return strategy


async def cancel_partially_bought_position_first_order_filled_partially(
    strategy: HpManager, hp_gui: HPGUI, hp_list: List[Dict]
) -> HpManager:
    strategy.buy_position.state_info.stagnation_counter = (
        strategy.buy_position.state_info.stagnation_limit
    )

    assert strategy.buy_position.state_info.next_monitor_time

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
    strategy.ticker_update = TickerUpdate(last_price=1428.0)

    assert not strategy.conditions_for_cancelling_unfilled_buy_orders()
    assert strategy.conditions_for_cancelling_partially_bought_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.buy_position.orders) == 3

    assert strategy.buy_position.orders[0].quantity == 0.24
    assert strategy.buy_position.orders[1].quantity == 0.28
    assert strategy.buy_position.orders[2].quantity == 0.33

    assert strategy.buy_position.orders[0].realized_quantity == 0.12
    assert strategy.buy_position.orders[1].realized_quantity == 0.0
    assert strategy.buy_position.orders[2].realized_quantity == 0.0

    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.state_info.ui_state == UiState.STAGNATED
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 0.14

    assert strategy.buy_position.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.12"
    assert item["quantity_usdt"] == "168.0"
    assert item["sell_price"] == "0.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "PARTIALLY_BOUGHT"

    logger.info("HP List after the update: %s", hp_list)

    return strategy


async def cancel_partially_bought_position_first_order_filled(
    strategy: HpManager, hp_gui: HPGUI, hp_list: List[Dict]
) -> HpManager:
    strategy.buy_position.state_info.stagnation_counter = (
        strategy.buy_position.state_info.stagnation_limit
    )

    assert strategy.buy_position.state_info.next_monitor_time

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
    strategy.ticker_update = TickerUpdate(last_price=1428.0)

    assert not strategy.conditions_for_cancelling_unfilled_buy_orders()
    assert strategy.conditions_for_cancelling_partially_bought_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.buy_position.orders) == 3

    assert strategy.buy_position.orders[0].quantity == 0.24
    assert strategy.buy_position.orders[1].quantity == 0.28
    assert strategy.buy_position.orders[2].quantity == 0.33

    assert strategy.buy_position.orders[0].realized_quantity == 0.24
    assert strategy.buy_position.orders[1].realized_quantity == 0.0
    assert strategy.buy_position.orders[2].realized_quantity == 0.0

    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.state_info.ui_state == UiState.STAGNATED
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 0.28

    assert strategy.buy_position.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.24"
    assert item["quantity_usdt"] == "336.0"
    assert item["sell_price"] == "0.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "PARTIALLY_BOUGHT"

    logger.info("HP List after the update: %s", hp_list)

    return strategy


async def cancel_partially_bought_position_two_orders_filled(
    strategy: HpManager,
) -> HpManager:
    strategy.buy_position.state_info.stagnation_counter = (
        strategy.buy_position.state_info.stagnation_limit
    )

    assert strategy.buy_position.state_info.next_monitor_time

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
    strategy.ticker_update = TickerUpdate(last_price=1428.0)

    assert not strategy.conditions_for_cancelling_unfilled_buy_orders()
    assert strategy.conditions_for_cancelling_partially_bought_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.buy_position.orders) == 3

    assert strategy.buy_position.orders[0].quantity == 0.24
    assert strategy.buy_position.orders[1].quantity == 0.28
    assert strategy.buy_position.orders[2].quantity == 0.33

    assert strategy.buy_position.orders[0].realized_quantity == 0.24
    assert strategy.buy_position.orders[1].realized_quantity == 0.28
    assert strategy.buy_position.orders[2].realized_quantity == 0.0

    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.state_info.ui_state == UiState.STAGNATED
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 0.61

    assert strategy.buy_position.ui_queue.qsize() == 0

    return strategy


async def simulate_cancel_sell_position(strategy: HpManager) -> HpManager:
    assert strategy.state == State.SELLING
    strategy.sell_position.state_info.stagnation_counter = (
        strategy.sell_position.state_info.stagnation_limit
    )

    strategy.sell_position.state_info.generate_next_monitor_time()

    assert strategy.calculate_trigger_cancel_orders_price_sell() == 4116.0
    strategy.ticker_update = TickerUpdate(last_price=4116.0)
    assert (
        strategy.conditions_for_cancelling_unfilled_sell_orders_from_partially_bought_position()
    )

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.sell_position.orders) == 1

    logger.info("Orders: %s", strategy.sell_position.orders)
    assert all(
        order.status == ORDER_STATUS_CANCELED for order in strategy.sell_position.orders
    )
    assert strategy.sell_position.state_info.state == State.NEW
    assert strategy.state == State.PARTIALLY_BOUGHT

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.NEW
    assert content.state_info.side == PositionSide.SHORT
    assert content.state_info.ui_state == UiState.STAGNATED
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 0.00
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0

    return strategy


async def simulate_bought_position(strategy: HpManager) -> HpManager:
    strategy = await move_to_buy_position_active(strategy=strategy, trigger_price=1414)

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    strategy = assert_default_buy_position_data(strategy=strategy, content=content)
    strategy = await simulate_first_buy_order_fill(strategy=strategy)

    strategy = await simulate_second_buy_order_fill(strategy=strategy)

    strategy = await simulate_third_buy_order_fill(strategy=strategy)

    assert strategy.buy_position.ui_queue.qsize() == 2
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.BOUGHT
    assert state_info.next_monitor_time

    assert content.state_info.ui_state == UiState.CLOSED
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 1.00

    assert strategy.buy_position.ui_queue.qsize() == 1

    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.BOUGHT
    assert state_info.next_monitor_time

    assert content.state_info.ui_state == UiState.CLOSED
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 1.00

    return strategy


async def simulate_partially_bought_position(strategy: HpManager) -> HpManager:
    strategy = await move_to_buy_position_active(strategy=strategy, trigger_price=1414)

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    strategy = assert_default_buy_position_data(strategy=strategy, content=content)
    strategy = await simulate_first_buy_order_fill(strategy=strategy)

    strategy = await simulate_second_buy_order_fill(strategy=strategy)

    strategy = await cancel_partially_bought_position_two_orders_filled(
        strategy=strategy
    )

    return strategy


async def simulate_move_to_sell_from_partially_bought_position(
    strategy: HpManager,
) -> HpManager:
    assert strategy.state == State.PARTIALLY_BOUGHT

    strategy.sell_position.config = HPConfig(
        hp_id=strategy.buy_position.config.hp_id,
        symbol_info=strategy.buy_position.config.symbol_info,
        price_low=4200,
        price_high=4200,
        order_trigger=1.0,
        budget=round(
            sum(order.realized_quantity for order in strategy.buy_position.orders), 2
        ),
        mode=Mode.SINGLE,
    )
    strategy.sell_position.state_info = StateInfo(side=PositionSide.SHORT)
    strategy.sell_position.orders = (
        strategy.sell_position.order_handler.prepare_sell_orders(
            config=strategy.sell_position.config,
            buy_orders=strategy.buy_position.orders,
            sell_orders=strategy.sell_position.orders,
        )
    )

    assert strategy.sell_position.config.hp_id == "1000"
    assert strategy.sell_position.config.price_low == 4200
    assert strategy.sell_position.config.price_high == 4200
    assert strategy.sell_position.config.order_trigger == 1
    assert strategy.sell_position.config.budget == 0.52
    assert strategy.sell_position.config.mode == Mode.SINGLE
    assert strategy.sell_position.config.symbol_info.symbol == "BTCUSDT"

    assert strategy.sell_position.state_info.side == PositionSide.SHORT
    assert strategy.sell_position.state_info.state == State.NEW
    assert strategy.sell_position.state_info.stagnation_counter == 0
    assert strategy.sell_position.state_info.stagnation_limit == 8

    assert len(strategy.sell_position.orders) == 1
    assert strategy.sell_position.orders[0].quantity == 0.52
    assert strategy.sell_position.orders[0].status == ORDER_STATUS_NEW

    assert strategy.calculate_trigger_send_orders_price_sell() == 4158
    assert strategy.state == State.PARTIALLY_BOUGHT

    strategy.ticker_update = TickerUpdate(last_price=4158.0)
    assert strategy.conditions_for_sending_sell_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.SELLING
    assert strategy.sell_position.state_info.state == State.NEW

    assert strategy.sell_position.orders[0].quantity == 0.52
    assert strategy.sell_position.orders[0].realized_quantity == 0.0

    assert strategy.sell_position.orders[0].status == ORDER_STATUS_NEW

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.NEW
    assert content.state_info.side == PositionSide.SHORT
    assert content.state_info.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 0.00
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0

    return strategy


async def move_to_sell_position_active(strategy: HpManager) -> HpManager:
    strategy.sell_position.config = HPConfig(
        hp_id=strategy.buy_position.config.hp_id,
        symbol_info=strategy.buy_position.config.symbol_info,
        price_low=4200,
        price_high=4200,
        order_trigger=1.0,
        budget=round(
            sum(order.realized_quantity for order in strategy.buy_position.orders), 2
        ),
        mode=Mode.SINGLE,
    )
    strategy.client.create_order.side_effect = get_new_orders(
        price_low=strategy.sell_position.config.price_low,
        price_high=strategy.sell_position.config.price_high,
    )
    strategy.sell_position.state_info = StateInfo(side=PositionSide.SHORT)
    strategy.sell_position.orders = (
        strategy.sell_position.order_handler.prepare_sell_orders(
            config=strategy.sell_position.config,
            buy_orders=strategy.buy_position.orders,
            sell_orders=strategy.sell_position.orders,
        )
    )

    assert strategy.sell_position.config.hp_id == "1000"
    assert strategy.sell_position.config.price_low == 4200
    assert strategy.sell_position.config.price_high == 4200
    assert strategy.sell_position.config.order_trigger == 1
    assert strategy.sell_position.config.budget == 0.85
    assert strategy.sell_position.config.mode == Mode.SINGLE
    assert strategy.sell_position.config.symbol_info.symbol == "BTCUSDT"

    assert strategy.sell_position.state_info.side == PositionSide.SHORT
    assert strategy.sell_position.state_info.state == State.NEW
    assert strategy.sell_position.state_info.stagnation_counter == 0
    assert strategy.sell_position.state_info.stagnation_limit == 8

    assert len(strategy.sell_position.orders) == 1
    assert strategy.sell_position.orders[0].quantity == 0.85
    assert strategy.sell_position.orders[0].status == ORDER_STATUS_NEW
    assert strategy.calculate_trigger_send_orders_price_sell() == 4158
    assert strategy.state == State.BOUGHT

    strategy.ticker_update = TickerUpdate(last_price=4158.0)
    assert strategy.conditions_for_sending_sell_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.SELLING
    assert strategy.sell_position.state_info.state == State.NEW

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.NEW
    assert state_info.stagnation_counter == 0
    assert state_info.stagnation_limit == 8
    assert content.state_info.side == PositionSide.SHORT
    assert content.state_info.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 0.00
    assert content.recovering is False

    assert strategy.buy_position.ui_queue.qsize() == 0

    return strategy


async def simulate_first_sell_order_fill(strategy: HpManager) -> HpManager:
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=5617834,
        last_executed_quantity=0.1,
        last_executed_price=4200,
        cumulative_filled_quantity=0.85,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.sell_position.orders)
    assert strategy.sell_position.orders[0].status == ORDER_STATUS_FILLED

    return strategy


async def simulate_partial_fill_sell(strategy: HpManager) -> HpManager:
    # Simulate partial fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=5617834,
        last_executed_quantity=0.425,
        last_executed_price=4200,
        cumulative_filled_quantity=0.425,
    )
    await strategy.process_order()  # type: ignore[attr-defined]

    logger.info("Orders: %s", strategy.buy_position.orders)
    assert strategy.sell_position.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert strategy.state == State.SELLING
    assert strategy.sell_position.state_info.state == State.PARTIALLY_SOLD

    assert strategy.sell_position.ui_queue.qsize() == 1

    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_SOLD
    assert content.state_info.side == PositionSide.SHORT
    assert content.state_info.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 0.5
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0

    return strategy


async def move_to_partially_sold(strategy: HpManager) -> HpManager:
    strategy.sell_position.state_info.stagnation_counter = (
        strategy.sell_position.state_info.stagnation_limit
    )

    strategy.sell_position.state_info.generate_next_monitor_time()

    assert strategy.calculate_trigger_cancel_orders_price_sell() == 4116.0
    strategy.ticker_update = TickerUpdate(last_price=4116.0)
    assert strategy.conditions_for_cancelling_partially_sold_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.sell_position.orders) == 1

    logger.info("Orders: %s", strategy.sell_position.orders)
    assert all(
        order.status == ORDER_STATUS_CANCELED for order in strategy.sell_position.orders
    )
    assert strategy.sell_position.state_info.state == State.PARTIALLY_SOLD
    assert strategy.state == State.PARTIALLY_SOLD

    assert strategy.sell_position.ui_queue.qsize() == 1

    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_SOLD
    assert content.state_info.side == PositionSide.SHORT
    assert content.state_info.ui_state == UiState.STAGNATED
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 0.5
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0

    return strategy


async def cancel_sell_position_part_bought_part_sold(strategy: HpManager) -> HpManager:
    strategy.sell_position.state_info.stagnation_counter = (
        strategy.sell_position.state_info.stagnation_limit
    )
    strategy.sell_position.state_info.generate_next_monitor_time()
    assert strategy.calculate_trigger_cancel_orders_price_sell() == 4116.0
    strategy.ticker_update = TickerUpdate(last_price=4116.0)
    assert (
        strategy.conditions_for_cancelling_partially_sold_and_bought_orders_sell_position()
    )
    assert not strategy.conditions_for_cancelling_partially_sold_orders()
    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.sell_position.state_info.state == State.PARTIALLY_SOLD
    assert strategy.state == State.SELLING

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.PART_SOLD_PART_BOUGHT
    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.sell_position.state_info.state == State.PARTIALLY_SOLD

    logger.info(
        "There is %s events in the queue", strategy.sell_position.ui_queue.qsize()
    )

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_SOLD
    assert content.state_info.side == PositionSide.SHORT
    assert content.state_info.ui_state == UiState.STAGNATED
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 0.5
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0

    return strategy


async def reopen_buy_part_bought_part_sold(strategy: HpManager) -> HpManager:
    assert strategy.calculate_trigger_send_orders_price_buy() == 1010
    strategy.ticker_update = TickerUpdate(last_price=1010)

    assert not strategy.conditions_for_sending_buy_orders()
    assert (
        strategy.conditions_for_resending_buy_orders_from_part_sold_and_bought_orders()
    )
    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.BUYING
    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.sell_position.state_info.state == State.PARTIALLY_SOLD

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_BOUGHT
    assert content.state_info.side == PositionSide.LONG
    assert content.state_info.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 0.61
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0

    return strategy


async def cancel_untouched_buy_position(strategy: HpManager) -> HpManager:
    strategy.buy_position.state_info.stagnation_counter = (
        strategy.buy_position.state_info.stagnation_limit
    )

    strategy.buy_position.state_info.generate_next_monitor_time()

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
    strategy.ticker_update = TickerUpdate(last_price=1428.0)
    assert strategy.conditions_for_cancelling_unfilled_buy_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.buy_position.orders) == 3
    assert all(
        order.status == ORDER_STATUS_CANCELED for order in strategy.buy_position.orders
    )
    assert strategy.buy_position.state_info.state == State.NEW
    assert strategy.state == State.NEW

    return strategy


def assert_cancelled_untouched_position(
    strategy: HpManager, content: PositionData
) -> HpManager:
    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.NEW
    assert state_info.stagnation_counter == 0
    assert state_info.stagnation_limit == 8
    assert state_info.side == PositionSide.LONG
    assert state_info.next_monitor_time

    assert content.state_info.ui_state == UiState.STAGNATED
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 0.00
    assert content.recovering is False

    assert strategy.buy_position.ui_queue.qsize() == 0

    return strategy


async def buy_fully_last_order(strategy: HpManager) -> HpManager:
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445864,
        last_executed_quantity=0.1,
        last_executed_price=1000,
        cumulative_filled_quantity=0.33,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy_position.orders)
    assert strategy.buy_position.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[1].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[2].status == ORDER_STATUS_FILLED

    logger.info("In queue: %s", strategy.buy_position.ui_queue.qsize())

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)
    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.stagnation_counter == 0
    assert state_info.stagnation_limit == 8
    assert state_info.side == PositionSide.LONG
    assert state_info.next_monitor_time

    assert content.state_info.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.state_info.completeness == 1.0
    assert content.recovering is False

    assert strategy.buy_position.ui_queue.qsize() == 0

    return strategy
