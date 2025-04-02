import asyncio
import logging
import queue
import time
from typing import Dict, List, Tuple

from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_FILLED,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_CANCELED,
)
from src.gui.identifiers.spot import HPGuiDataBuy, HPGuiDataSell
from src.identifiers.common import Mode, PositionSide
from src.common.symbol_info import SymbolInfo
from src.strategies.hp_manager import HpStrategy
from src.gui.hpfront import HpFront
from src.identifiers.spot import (
    Event,
    EventName,
    ExecutionReport,
    HPBuyConfig,
    HPSellConfig,
    SignalUpdate,
    StateInfo,
    TickerUpdate,
    State,
    Order,
    UiState,
)
from tests.spot import get_new_orders, get_sell_order


logger = logging.getLogger("hp_helpers")


async def wait_for_condition(
    condition_func, timeout: float = 3.0, interval: float = 0.05
):
    """
    Waits for a given condition function to return True, otherwise raises an AssertionError after timeout.

    :param condition_func: A callable (sync or async) that returns True when the condition is met.
    :param timeout: Maximum time to wait for the condition.
    :param interval: Time between each condition check.
    :raises AssertionError: If the condition is not met within the timeout.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        if asyncio.iscoroutinefunction(condition_func):
            result = await condition_func()
        else:
            result = condition_func()

        if result:
            return  # Condition met, exit successfully
        await asyncio.sleep(interval)  # Wait before rechecking

    raise AssertionError(f"Condition not met within {timeout} seconds")


def assert_gui_position_data_content_buy(
    ui_queue: queue.Queue,
    config: HPBuyConfig,
    state_info: StateInfo,
    completeness: float,
):
    try:
        logger.info("GUI queue size: %s", ui_queue.qsize())
        gui_msg = ui_queue.get_nowait()
        assert gui_msg
        logger.info("GUI msg: %s", gui_msg)
        assert isinstance(gui_msg, HPGuiDataBuy)

        msg_config = gui_msg.data.config
        msg_state_info = gui_msg.data.state_info

        assert msg_config.symbol_info.symbol == config.symbol_info.symbol
        assert msg_state_info.side == state_info.side
        assert msg_state_info.state == state_info.state
        assert msg_config.price_low == config.price_low
        assert msg_config.price_high == config.price_high
        assert msg_config.order_trigger == config.order_trigger
        assert msg_config.budget == config.budget
        assert msg_state_info.completeness == completeness
        assert msg_state_info.stagnation_counter == state_info.stagnation_counter
        assert msg_state_info.stagnation_limit == state_info.stagnation_limit

    except queue.Empty:
        time.sleep(0.1)


async def process_ticker(strategy: HpStrategy, last_price: float):
    logger.info("Processing ticker with last price: %s", last_price)
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    await strategy.process_ticker()  # type: ignore[attr-defined]  # type: ignore


async def simulate_order_filled(strategy: HpStrategy, order: Order):
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
    strategy: HpStrategy, order: Order, last_realized_quantity: float
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
    strategy: HpStrategy,
    completeness: float,
):
    db = strategy.buy.db
    db.assert_db_buy_price_level_content(
        config=strategy.buy.data.config,
        state_info=strategy.buy.data.state_info,
    )
    assert_gui_position_data_content_buy(
        ui_queue=strategy.ui_queue,
        config=strategy.buy.data.config,
        state_info=strategy.buy.data.state_info,
        completeness=completeness,
    )


def get_default_buy_position(trading_system_factory) -> HpStrategy:
    strategy = trading_system_factory(
        hp_config=HPBuyConfig(
            hp_id="0",
            symbol_info=SymbolInfo(symbol="BTCUSDT", precision=5, price_precision=2),
            price_low=1000,
            price_high=1400,
            order_trigger=1.0,
            budget=1000,
        ),
    )

    assert isinstance(strategy, HpStrategy)
    buy_cfg = strategy.buy.data.config
    assert isinstance(buy_cfg, HPBuyConfig)
    strategy.client.create_order.side_effect = get_new_orders(
        price_low=buy_cfg.price_low,
        price_high=buy_cfg.price_high,
    )
    assert buy_cfg.hp_id == "1000"
    assert buy_cfg.price_low == 1000
    assert buy_cfg.price_high == 1400
    assert buy_cfg.order_trigger == 1
    assert buy_cfg.budget == 1000
    assert buy_cfg.mode == Mode.DCA
    assert buy_cfg.symbol_info.symbol == "BTCUSDT"

    assert strategy.buy.data.state_info.side == PositionSide.LONG
    assert strategy.buy.data.state_info.state == State.NEW
    assert strategy.buy.data.state_info.stagnation_counter == 0
    assert strategy.buy.data.state_info.stagnation_limit == 8
    assert strategy.buy.data.state_info.completeness == 0
    assert strategy.buy.data.state_info.ui_state == UiState.NEW

    assert strategy.calculate_trigger_send_orders_price_buy() == 1414

    assert len(strategy.buy.orders) == 3
    assert strategy.buy.orders[0].quantity == 0.2381
    assert strategy.buy.orders[1].quantity == 0.27778
    assert strategy.buy.orders[2].quantity == 0.33333

    assert strategy.sell.data.config.hp_id == "0"
    assert strategy.sell.data.config.sell_price == 0
    assert strategy.sell.data.config.symbol_info.symbol == "BTCUSDT"

    assert strategy.sell.data.state_info.side == PositionSide.SHORT

    assert strategy.sell.data.state_info.stagnation_counter == 0
    assert strategy.sell.data.state_info.stagnation_limit == 8
    assert strategy.sell.data.state_info.state == State.NEW
    assert strategy.state == State.NEW
    assert len(strategy.sell.orders) == 0

    return strategy


def assert_default_buy_position_data(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> Tuple[HpStrategy, List[Dict]]:
    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    config = content.data.config
    assert isinstance(config, HPBuyConfig)

    assert config.hp_id == "1000"
    assert config.price_low == 1000
    assert config.price_high == 1400
    assert config.budget == 1000
    assert config.order_trigger == 1.0
    assert config.order_cancel == 2.0
    assert config.mode == Mode.DCA
    assert config.symbol_info.symbol == "BTCUSDT"
    assert config.symbol_info.precision == 5
    assert config.symbol_info.price_precision == 2

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.NEW
    assert state_info.stagnation_counter == 0
    assert state_info.stagnation_limit == 8
    assert state_info.side == PositionSide.LONG
    assert state_info.next_monitor_time
    assert state_info.ui_state == UiState.NEW
    assert state_info.completeness == 0.00

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)
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

    return strategy, hp_list


async def move_to_buy_position_active(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict], trigger_price: float
) -> Tuple[HpStrategy, List[Dict]]:
    assert strategy.calculate_trigger_send_orders_price_buy() == trigger_price
    strategy.ticker_update = TickerUpdate(last_price=trigger_price)

    assert strategy.conditions_for_sending_buy_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    logger.info("State: %s", strategy.state)
    assert strategy.state == State.BUYING
    assert len(strategy.buy.orders) == 3

    assert strategy.buy.data.state_info.state == State.NEW
    assert all(order.status == ORDER_STATUS_NEW for order in strategy.buy.orders)
    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    config = content.data.config
    assert isinstance(config, HPBuyConfig)

    assert config.hp_id == "1000"
    assert config.price_low == 1000
    assert config.price_high == 1400
    assert config.budget == 1000
    assert config.order_trigger == 1.0
    assert config.order_cancel == 2.0
    assert config.mode == Mode.DCA
    assert config.symbol_info.symbol == "BTCUSDT"
    assert config.symbol_info.precision == 5
    assert config.symbol_info.price_precision == 2

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.NEW
    assert state_info.stagnation_counter == 0
    assert state_info.stagnation_limit == 8
    assert state_info.side == PositionSide.LONG
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.OPEN
    assert state_info.completeness == 0.00

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)
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
    assert item["state"] == "BUYING"

    return strategy, hp_list


async def simulate_partial_fill(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List
) -> HpStrategy:
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
    logger.info("Orders: %s", strategy.buy.orders)
    assert strategy.buy.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert strategy.buy.orders[1].status == ORDER_STATUS_NEW
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.OPEN
    assert content.data.config.order_cancel == 2.0
    assert state_info.completeness == 0.14
    assert strategy.ui_queue.qsize() == 0

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
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict], order_id: int
) -> Tuple[HpStrategy, List[Dict]]:
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=order_id,
        last_executed_quantity=0.24,
        last_executed_price=1400,
        cumulative_filled_quantity=0.24,
        price=1400.0,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy.orders)
    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[1].status == ORDER_STATUS_NEW
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.OPEN
    assert content.data.config.order_cancel == 2.0
    assert state_info.completeness == 0.28

    assert strategy.ui_queue.qsize() == 0

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

    return strategy, hp_list


async def simulate_second_buy_order_fill(
    strategy: HpStrategy,
    hp_gui: HpFront,
    hp_list: List[Dict],
    order_id: int,
    sell_price: str = "0.0",
) -> Tuple[HpStrategy, List[Dict]]:
    # Simulate full order fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=order_id,
        last_executed_quantity=0.28,
        last_executed_price=1200,
        cumulative_filled_quantity=0.28,
        price=1200,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy.orders)
    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[1].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.OPEN
    assert content.data.config.order_cancel == 2.0
    assert state_info.completeness == 0.61

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1292.31"
    assert item["quantity"] == "0.52"
    assert item["quantity_usdt"] == "672.0"
    assert item["sell_price"] == sell_price
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "BUYING"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def simulate_third_buy_order_fill(
    strategy: HpStrategy,
    hp_gui: HpFront,
    hp_list: List[Dict],
    order_id: int,
    sell_price: str = "0.0",
) -> Tuple[HpStrategy, List[Dict]]:
    # Simulate full order fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=order_id,
        last_executed_quantity=0.33,
        last_executed_price=1000,
        cumulative_filled_quantity=0.33,
        price=1000,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy.orders)
    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[1].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[2].status == ORDER_STATUS_FILLED

    assert strategy.worker_queue.qsize() == 1
    event = strategy.worker_queue.get_nowait()

    assert isinstance(event, Event)
    assert event.name == EventName.SIGNAL
    assert isinstance(event.content, SignalUpdate)

    strategy.signal_update = event.content

    await strategy.process_signal()  # type: ignore[attr-defined]

    assert strategy.buy.data.state_info.state == State.BOUGHT
    assert strategy.state == State.BOUGHT

    assert strategy.worker_queue.qsize() == 0

    assert strategy.ui_queue.qsize() == 2
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.BOUGHT
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.CLOSED
    assert content.data.config.order_cancel == 2.0
    assert state_info.completeness == 1.00

    assert strategy.ui_queue.qsize() == 1

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1178.82"
    assert item["quantity"] == "0.85"
    assert item["quantity_usdt"] == "1002.0"
    assert item["sell_price"] == sell_price
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "BUYING"

    logger.info("HP List after the update: %s", hp_list)

    assert strategy.ui_queue.qsize() == 1

    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.BOUGHT
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.CLOSED
    assert content.data.config.order_cancel == 2.0
    assert state_info.completeness == 1.00

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1178.82"
    assert item["quantity"] == "0.85"
    assert item["quantity_usdt"] == "1002.0"
    assert item["sell_price"] == sell_price
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "BOUGHT"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def simulate_second_buy_order_fill_after_selling_half_of_first_order(
    strategy: HpStrategy,
    hp_gui: HpFront,
    hp_list: List[Dict],
    order_id: int,
    sell_price: str = "0.0",
) -> Tuple[HpStrategy, List[Dict]]:
    # Simulate full order fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=order_id,
        last_executed_quantity=0.28,
        last_executed_price=1200,
        cumulative_filled_quantity=0.28,
        price=1200,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy.orders)
    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[1].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.OPEN
    assert content.data.config.order_cancel == 2.0
    assert state_info.completeness == 0.61

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1260.0"
    assert item["quantity"] == "0.4", f"{item['quantity']}"
    assert item["quantity_usdt"] == "504.0", f"{item['quantity_usdt']}"
    assert item["sell_price"] == sell_price
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "BUYING"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def simulate_third_buy_order_fill_after_selling_half_of_first_order(
    strategy: HpStrategy,
    hp_gui: HpFront,
    hp_list: List[Dict],
    order_id: int,
    sell_price: str = "0.0",
) -> Tuple[HpStrategy, List[Dict]]:
    # Simulate full order fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=order_id,
        last_executed_quantity=0.33,
        last_executed_price=1000,
        cumulative_filled_quantity=0.33,
        price=1000,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy.orders)
    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[1].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[2].status == ORDER_STATUS_FILLED

    assert strategy.worker_queue.qsize() == 1
    event = strategy.worker_queue.get_nowait()

    assert isinstance(event, Event)
    assert event.name == EventName.SIGNAL
    assert isinstance(event.content, SignalUpdate)

    strategy.signal_update = event.content

    await strategy.process_signal()  # type: ignore[attr-defined]

    assert strategy.buy.data.state_info.state == State.BOUGHT
    assert strategy.state == State.PARTIALLY_SOLD

    assert strategy.worker_queue.qsize() == 0

    assert strategy.ui_queue.qsize() == 2
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.BOUGHT
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.CLOSED
    assert content.data.config.order_cancel == 2.0
    assert state_info.completeness == 1.00

    assert strategy.ui_queue.qsize() == 1

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1142.47"
    assert item["quantity"] == "0.73"
    assert item["quantity_usdt"] == "834.0"
    assert item["sell_price"] == sell_price
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "BUYING"

    logger.info("HP List after the update: %s", hp_list)

    assert strategy.ui_queue.qsize() == 1

    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.BOUGHT
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.CLOSED
    assert content.data.config.order_cancel == 2.0
    assert state_info.completeness == 1.00

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1142.47"
    assert item["quantity"] == "0.73"
    assert item["quantity_usdt"] == "834.0"
    assert item["sell_price"] == sell_price
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "PARTIALLY_SOLD"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def simulate_second_buy_order_fill_after_selling_first_order(
    strategy: HpStrategy,
    hp_gui: HpFront,
    hp_list: List[Dict],
    order_id: int,
    sell_price: str = "0.0",
) -> Tuple[HpStrategy, List[Dict]]:
    # Simulate full order fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=order_id,
        last_executed_quantity=0.28,
        last_executed_price=1200,
        cumulative_filled_quantity=0.28,
        price=1200,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy.orders)
    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[1].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.OPEN
    assert content.data.config.order_cancel == 2.0
    assert state_info.completeness == 0.61

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1200.0"
    assert item["quantity"] == "0.28"
    assert item["quantity_usdt"] == "336.0"
    assert item["sell_price"] == sell_price
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "BUYING"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def simulate_third_buy_order_fill_after_selling_first_order(
    strategy: HpStrategy,
    hp_gui: HpFront,
    hp_list: List[Dict],
    order_id: int,
    sell_price: str = "0.0",
) -> Tuple[HpStrategy, List[Dict]]:
    # Simulate full order fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=order_id,
        last_executed_quantity=0.33,
        last_executed_price=1000,
        cumulative_filled_quantity=0.33,
        price=1000,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy.orders)
    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[1].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[2].status == ORDER_STATUS_FILLED

    assert strategy.worker_queue.qsize() == 1
    event = strategy.worker_queue.get_nowait()

    assert isinstance(event, Event)
    assert event.name == EventName.SIGNAL
    assert isinstance(event.content, SignalUpdate)

    strategy.signal_update = event.content

    await strategy.process_signal()  # type: ignore[attr-defined]

    assert strategy.buy.data.state_info.state == State.BOUGHT
    assert strategy.state == State.PARTIALLY_SOLD

    assert strategy.worker_queue.qsize() == 0

    assert strategy.ui_queue.qsize() == 2
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.BOUGHT
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.CLOSED
    assert content.data.config.order_cancel == 2.0
    assert state_info.completeness == 1.00

    assert strategy.ui_queue.qsize() == 1

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1091.8"
    assert item["quantity"] == "0.61"
    assert item["quantity_usdt"] == "666.0"
    assert item["sell_price"] == sell_price
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "BUYING"

    logger.info("HP List after the update: %s", hp_list)

    assert strategy.ui_queue.qsize() == 1

    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.BOUGHT
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.CLOSED
    assert content.data.config.order_cancel == 2.0
    assert state_info.completeness == 1.00

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1091.8"
    assert item["quantity"] == "0.61"
    assert item["quantity_usdt"] == "666.0"
    assert item["sell_price"] == sell_price
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "PARTIALLY_SOLD"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def resend_part_bought_first_order_filled(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> Tuple[HpStrategy, List[Dict]]:
    assert strategy.calculate_trigger_send_orders_price_buy() == 1212
    strategy.ticker_update = TickerUpdate(last_price=1212)
    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING
    assert len(strategy.buy.orders) == 3

    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[1].status == ORDER_STATUS_NEW
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy.orders[0].quantity == 0.2381
    assert strategy.buy.orders[1].quantity == 0.27778
    assert strategy.buy.orders[2].quantity == 0.33333

    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.OPEN
    assert content.data.config.order_cancel == 2.0
    assert state_info.completeness == 0.28

    assert strategy.ui_queue.qsize() == 0

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

    return strategy, hp_list


async def resend_part_bought_first_order_filled_with_sell_price(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> Tuple[HpStrategy, List[Dict]]:
    assert strategy.calculate_trigger_send_orders_price_buy() == 1212
    strategy.ticker_update = TickerUpdate(last_price=1212)
    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING
    assert len(strategy.buy.orders) == 3

    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[1].status == ORDER_STATUS_NEW
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy.orders[0].quantity == 0.2381
    assert strategy.buy.orders[1].quantity == 0.27778
    assert strategy.buy.orders[2].quantity == 0.33333

    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.data.state_info.ui_state == UiState.OPEN
    assert content.data.config.order_cancel == 2.0
    assert state_info.completeness == 0.28

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.24"
    assert item["quantity_usdt"] == "336.0"
    assert item["sell_price"] == "4200"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "BUYING"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def simulate_second_buy_order_partial_fill(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> Tuple[HpStrategy, List[Dict]]:
    # Simulate partial order fill of order which is rebuy after first time two first orders were fillled and this is the last one.
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=445864,
        last_executed_quantity=0.14,
        last_executed_price=1200,
        cumulative_filled_quantity=0.14,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy.orders)
    assert strategy.buy.orders[1].status == ORDER_STATUS_PARTIALLY_FILLED

    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[1].status == ORDER_STATUS_PARTIALLY_FILLED
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.side == PositionSide.LONG
    assert state_info.ui_state == UiState.OPEN
    assert content.data.config.order_cancel == 2.0
    assert state_info.completeness == 0.45

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1292.31"
    assert item["quantity"] == "0.26", f"{item['quantity']}"
    assert item["quantity_usdt"] == "336.0", f"{item['quantity_usdt']}"
    assert item["sell_price"] == "4200"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "BUYING"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def cancel_partially_bought_position_first_order_filled_partially(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> HpStrategy:
    strategy.buy.data.state_info.stagnation_counter = (
        strategy.buy.data.state_info.stagnation_limit
    )

    assert strategy.buy.data.state_info.next_monitor_time

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
    strategy.ticker_update = TickerUpdate(last_price=1428.0)

    assert not strategy.conditions_for_cancelling_unfilled_buy_orders()
    assert strategy.conditions_for_cancelling_partially_bought_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.buy.orders) == 3

    assert strategy.buy.orders[0].quantity == 0.2381
    assert strategy.buy.orders[1].quantity == 0.27778
    assert strategy.buy.orders[2].quantity == 0.33333

    assert strategy.buy.orders[0].realized_quantity == 0.12
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.STAGNATED
    assert state_info.completeness == 0.14

    assert strategy.ui_queue.qsize() == 0

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


async def resend_part_bought_first_order_filled_partially(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> HpStrategy:
    assert strategy.calculate_trigger_send_orders_price_buy() == 1414
    strategy.ticker_update = TickerUpdate(last_price=1414)

    await strategy.process_ticker()  # type: ignore[attr-defined]

    logger.info("State: %s", strategy.state)
    assert strategy.state == State.BUYING
    assert len(strategy.buy.orders) == 3

    assert strategy.buy.orders[0].quantity == 0.2381
    assert strategy.buy.orders[1].quantity == 0.27778
    assert strategy.buy.orders[2].quantity == 0.33333

    assert strategy.buy.orders[0].realized_quantity == 0.12
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.OPEN
    assert content.data.config.order_cancel == 2.0
    assert state_info.completeness == 0.14

    assert strategy.ui_queue.qsize() == 0

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


async def cancel_partially_bought_position_first_order_filled(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> HpStrategy:
    strategy.buy.data.state_info.stagnation_counter = (
        strategy.buy.data.state_info.stagnation_limit
    )

    assert strategy.buy.data.state_info.next_monitor_time

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
    strategy.ticker_update = TickerUpdate(last_price=1428.0)

    assert not strategy.conditions_for_cancelling_unfilled_buy_orders()
    assert strategy.conditions_for_cancelling_partially_bought_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.buy.orders) == 3

    assert strategy.buy.orders[0].quantity == 0.2381
    assert strategy.buy.orders[1].quantity == 0.27778
    assert strategy.buy.orders[2].quantity == 0.33333

    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.STAGNATED
    assert content.data.config.order_cancel == 2.0
    assert state_info.completeness == 0.28

    assert strategy.ui_queue.qsize() == 0

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


async def send_sell_orders_for_partially_bought_position(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> Tuple[HpStrategy, List[Dict]]:
    buy_realized_quantity = round(
        sum(order.realized_quantity for order in strategy.buy.orders), 2
    )
    sell_realized_quantity = round(
        sum(order.realized_quantity for order in strategy.sell.orders), 2
    )

    strategy.sell.data.config = HPSellConfig(
        hp_id=strategy.buy.data.config.hp_id,
        symbol_info=strategy.buy.data.config.symbol_info,
        sell_price=4200,
        quantity=buy_realized_quantity,
    )
    strategy.sell.data.state_info = StateInfo(side=PositionSide.SHORT)
    strategy.sell.orders = strategy.sell.prepare_orders(
        config=strategy.sell.data.config,
        buy_realized_quantity=buy_realized_quantity,
        sell_realized_quantity=sell_realized_quantity,
    )

    assert strategy.sell.data.config.hp_id == "1000"
    assert strategy.sell.data.config.sell_price == 4200
    assert strategy.sell.data.config.symbol_info.symbol == "BTCUSDT"

    assert strategy.sell.data.state_info.side == PositionSide.SHORT
    assert strategy.sell.data.state_info.state == State.NEW
    assert strategy.sell.data.state_info.stagnation_counter == 0
    assert strategy.sell.data.state_info.stagnation_limit == 8

    assert len(strategy.sell.orders) == 1
    assert strategy.sell.orders[0].quantity == 0.24
    assert strategy.sell.orders[0].status == ORDER_STATUS_NEW

    assert strategy.calculate_trigger_send_orders_price_sell() == 4032
    assert strategy.state == State.PARTIALLY_BOUGHT

    strategy.ticker_update = TickerUpdate(last_price=4032.0)
    assert strategy.conditions_for_sending_sell_orders_for_partially_bought_position()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.SELLING
    assert strategy.sell.data.state_info.state == State.NEW

    assert strategy.sell.orders[0].quantity == 0.24
    assert strategy.sell.orders[0].realized_quantity == 0.0

    assert strategy.sell.orders[0].status == ORDER_STATUS_NEW

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.NEW
    assert state_info.side == PositionSide.SHORT
    assert state_info.ui_state == UiState.OPEN
    assert state_info.completeness == 0.00

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.24"
    assert item["quantity_usdt"] == "336.0"
    assert item["sell_price"] == "4200"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "SELLING"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def sell_partially_partially_bought_position(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> Tuple[HpStrategy, List[Dict]]:
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=445863,
        last_executed_quantity=0.12,
        last_executed_price=4200,
        cumulative_filled_quantity=0.12,
    )
    await strategy.process_order()  # type: ignore[attr-defined]

    logger.info("Orders: %s", strategy.sell.orders)
    assert strategy.sell.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert strategy.sell.orders[0].quantity == 0.24
    assert strategy.sell.orders[0].realized_quantity == 0.12
    assert strategy.state == State.SELLING
    assert strategy.sell.data.state_info.state == State.PARTIALLY_SOLD

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_SOLD
    assert state_info.side == PositionSide.SHORT
    assert state_info.ui_state == UiState.OPEN
    assert state_info.completeness == 0.5

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.12"
    assert item["quantity_usdt"] == "168.0"
    assert item["sell_price"] == "4200"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "SELLING"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def cancel_unfilled_sell_orders_for_partially_bought_position(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> Tuple[HpStrategy, List[Dict]]:
    strategy.sell.data.state_info.stagnation_counter = (
        strategy.sell.data.state_info.stagnation_limit
    )

    strategy.sell.data.state_info.generate_next_monitor_time()

    assert strategy.calculate_trigger_cancel_orders_price_sell() == 3864.0
    strategy.ticker_update = TickerUpdate(last_price=3864.0)
    assert (
        strategy.conditions_for_cancelling_unfilled_sell_orders_from_partially_bought_position()
    )

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.sell.orders) == 1

    logger.info("Orders: %s", strategy.sell.orders)
    assert all(order.status == ORDER_STATUS_CANCELED for order in strategy.sell.orders)
    assert strategy.sell.data.state_info.state == State.NEW
    assert strategy.state == State.PARTIALLY_BOUGHT

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.NEW
    assert state_info.side == PositionSide.SHORT
    assert state_info.ui_state == UiState.STAGNATED
    assert state_info.completeness == 0.00

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.24"
    assert item["quantity_usdt"] == "336.0"
    assert item["sell_price"] == "4200"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "PARTIALLY_BOUGHT"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def simulate_cancel_sell_position(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> Tuple[HpStrategy, List[Dict]]:
    strategy.sell.data.state_info.stagnation_counter = (
        strategy.sell.data.state_info.stagnation_limit
    )

    strategy.sell.data.state_info.generate_next_monitor_time()

    assert strategy.calculate_trigger_cancel_orders_price_sell() == 3864.0
    strategy.ticker_update = TickerUpdate(last_price=3864.0)
    assert strategy.conditions_for_cancelling_partially_sold_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.sell.orders) == 1

    logger.info("Orders: %s", strategy.sell.orders)
    assert all(order.status == ORDER_STATUS_CANCELED for order in strategy.sell.orders)
    assert strategy.sell.data.state_info.state == State.PARTIALLY_SOLD
    assert strategy.state == State.PARTIALLY_SOLD

    assert strategy.ui_queue.qsize() == 1

    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_SOLD
    assert state_info.side == PositionSide.SHORT
    assert state_info.ui_state == UiState.STAGNATED
    assert state_info.completeness == 0.5

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1178.82"
    assert item["quantity"] == "0.425"
    assert item["quantity_usdt"] == "501.0"
    assert item["sell_price"] == "4200.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "PARTIALLY_SOLD"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def simulate_resend_sell_position(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> Tuple[HpStrategy, List[Dict]]:
    assert strategy.calculate_trigger_send_orders_price_sell() == 4032.0
    assert strategy.state == State.PARTIALLY_SOLD
    assert strategy.sell.data.state_info.state == State.PARTIALLY_SOLD

    strategy.ticker_update = TickerUpdate(last_price=4032.0)
    assert not strategy.conditions_for_sending_sell_orders()
    assert strategy.conditions_for_resending_partially_sold_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.SELLING
    assert strategy.sell.data.state_info.state == State.PARTIALLY_SOLD

    assert strategy.ui_queue.qsize() == 1

    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_SOLD
    assert state_info.side == PositionSide.SHORT
    assert state_info.ui_state == UiState.OPEN
    assert state_info.completeness == 0.5

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1178.82"
    assert item["quantity"] == "0.425"
    assert item["quantity_usdt"] == "501.0"
    assert item["sell_price"] == "4200.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "SELLING"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def simulate_bought_position(
    trading_system_factory, hp_gui: HpFront, hp_list: List[Dict]
) -> Tuple[HpStrategy, List[Dict]]:
    # Path 0: Default buy position
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )
    # Simulate full order fill
    strategy, hp_list = await simulate_first_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445860
    )

    # Simulate full order fill
    strategy, hp_list = await simulate_second_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445861
    )

    # Simulate full order fill
    strategy, hp_list = await simulate_third_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445862
    )

    return strategy, hp_list


async def send_sell_orders_for_bought_position(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> Tuple[HpStrategy, List[Dict]]:
    buy_realized_quantity = round(
        sum(order.realized_quantity for order in strategy.buy.orders), 2
    )
    sell_realized_quantity = round(
        sum(order.realized_quantity for order in strategy.sell.orders), 2
    )
    strategy.sell.data.config = HPSellConfig(
        hp_id=strategy.buy.data.config.hp_id,
        symbol_info=strategy.buy.data.config.symbol_info,
        sell_price=4200.0,
        quantity=buy_realized_quantity,
    )
    strategy.sell.data.state_info = StateInfo(side=PositionSide.SHORT)
    strategy.sell.orders = strategy.sell.prepare_orders(
        config=strategy.sell.data.config,
        buy_realized_quantity=buy_realized_quantity,
        sell_realized_quantity=sell_realized_quantity,
    )

    assert strategy.sell.data.config.hp_id == "1000"
    assert strategy.sell.data.config.sell_price == 4200.0
    assert strategy.sell.data.config.symbol_info.symbol == "BTCUSDT"

    assert strategy.sell.data.state_info.side == PositionSide.SHORT
    assert strategy.sell.data.state_info.state == State.NEW
    assert strategy.sell.data.state_info.stagnation_counter == 0
    assert strategy.sell.data.state_info.stagnation_limit == 8

    assert len(strategy.sell.orders) == 1
    assert strategy.sell.orders[0].quantity == buy_realized_quantity
    assert strategy.sell.orders[0].status == ORDER_STATUS_NEW

    assert strategy.calculate_trigger_send_orders_price_sell() == 4032
    assert strategy.state == State.BOUGHT

    strategy.ticker_update = TickerUpdate(last_price=4032.0)
    assert strategy.conditions_for_sending_sell_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.SELLING
    assert strategy.sell.data.state_info.state == State.NEW

    assert strategy.sell.orders[0].quantity == 0.85
    assert strategy.sell.orders[0].realized_quantity == 0.0

    assert strategy.sell.orders[0].status == ORDER_STATUS_NEW

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.NEW
    assert state_info.stagnation_counter == 0
    assert state_info.stagnation_limit == 8
    assert state_info.side == PositionSide.SHORT
    assert state_info.ui_state == UiState.OPEN
    assert state_info.completeness == 0.00

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1178.82"
    assert item["quantity"] == "0.85"
    assert item["quantity_usdt"] == "1002.0"
    assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "SELLING"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def simulate_move_to_sell_from_partially_bought_position(
    strategy: HpStrategy,
) -> HpStrategy:
    assert strategy.state == State.PARTIALLY_BOUGHT

    buy_realized_quantity = round(
        sum(order.realized_quantity for order in strategy.buy.orders), 2
    )
    sell_realized_quantity = round(
        sum(order.realized_quantity for order in strategy.sell.orders), 2
    )

    strategy.sell.data.config = HPSellConfig(
        hp_id=strategy.buy.data.config.hp_id,
        symbol_info=strategy.buy.data.config.symbol_info,
        sell_price=4200,
        quantity=buy_realized_quantity,
    )
    strategy.sell.data.state_info = StateInfo(side=PositionSide.SHORT)
    strategy.sell.orders = strategy.sell.prepare_orders(
        config=strategy.sell.data.config,
        buy_realized_quantity=buy_realized_quantity,
        sell_realized_quantity=sell_realized_quantity,
    )

    assert strategy.sell.data.config.hp_id == "1000"
    assert strategy.sell.data.config.sell_price == 4200
    assert strategy.sell.data.config.symbol_info.symbol == "BTCUSDT"

    assert strategy.sell.data.state_info.side == PositionSide.SHORT
    assert strategy.sell.data.state_info.state == State.NEW
    assert strategy.sell.data.state_info.stagnation_counter == 0
    assert strategy.sell.data.state_info.stagnation_limit == 8

    assert len(strategy.sell.orders) == 1
    assert strategy.sell.orders[0].quantity == 0.52
    assert strategy.sell.orders[0].status == ORDER_STATUS_NEW

    assert strategy.calculate_trigger_send_orders_price_sell() == 4158
    assert strategy.state == State.PARTIALLY_BOUGHT

    strategy.ticker_update = TickerUpdate(last_price=4158.0)
    assert strategy.conditions_for_sending_sell_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.SELLING
    assert strategy.sell.data.state_info.state == State.NEW

    assert strategy.sell.orders[0].quantity == 0.52
    assert strategy.sell.orders[0].realized_quantity == 0.0

    assert strategy.sell.orders[0].status == ORDER_STATUS_NEW

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)

    assert isinstance(content, HPGuiDataSell)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.NEW
    assert state_info.side == PositionSide.SHORT
    assert state_info.ui_state == UiState.OPEN
    assert state_info.completeness == 0.00

    assert strategy.ui_queue.qsize() == 0

    return strategy


async def move_to_sell_position_active(strategy: HpStrategy) -> HpStrategy:
    buy_realized_quantity = round(
        sum(order.realized_quantity for order in strategy.buy.orders), 2
    )
    sell_realized_quantity = round(
        sum(order.realized_quantity for order in strategy.sell.orders), 2
    )
    strategy.sell.data.config = HPSellConfig(
        hp_id=strategy.buy.data.config.hp_id,
        symbol_info=strategy.buy.data.config.symbol_info,
        sell_price=4200,
    )
    strategy.client.create_order.side_effect = get_sell_order(
        sell_price=strategy.sell.data.config.sell_price
    )
    strategy.sell.data.state_info = StateInfo(side=PositionSide.SHORT)
    strategy.sell.orders = strategy.sell.prepare_orders(
        config=strategy.sell.data.config,
        buy_realized_quantity=buy_realized_quantity,
        sell_realized_quantity=sell_realized_quantity,
    )

    assert strategy.sell.data.config.hp_id == "1000"
    assert strategy.sell.data.config.sell_price == 4200
    assert strategy.sell.data.config.symbol_info.symbol == "BTCUSDT"

    assert strategy.sell.data.state_info.side == PositionSide.SHORT
    assert strategy.sell.data.state_info.state == State.NEW
    assert strategy.sell.data.state_info.stagnation_counter == 0
    assert strategy.sell.data.state_info.stagnation_limit == 8

    assert len(strategy.sell.orders) == 1
    assert strategy.sell.orders[0].quantity == 0.85
    assert strategy.sell.orders[0].status == ORDER_STATUS_NEW
    assert strategy.calculate_trigger_send_orders_price_sell() == 4158
    assert strategy.state == State.BOUGHT

    strategy.ticker_update = TickerUpdate(last_price=4158.0)
    assert strategy.conditions_for_sending_sell_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.SELLING
    assert strategy.sell.data.state_info.state == State.NEW

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.NEW
    assert state_info.stagnation_counter == 0
    assert state_info.stagnation_limit == 8
    assert state_info.side == PositionSide.SHORT
    assert state_info.ui_state == UiState.OPEN
    assert state_info.completeness == 0.00

    assert strategy.ui_queue.qsize() == 0

    return strategy


async def simulate_first_sell_order_fill(strategy: HpStrategy) -> HpStrategy:
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
    logger.info("Orders: %s", strategy.sell.orders)
    assert strategy.sell.orders[0].status == ORDER_STATUS_FILLED

    return strategy


async def simulate_partial_fill_sell(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> Tuple[HpStrategy, List[Dict]]:
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=445863,
        last_executed_quantity=0.425,
        last_executed_price=4200,
        cumulative_filled_quantity=0.425,
    )
    await strategy.process_order()  # type: ignore[attr-defined]

    logger.info("Orders: %s", strategy.sell.orders)
    assert strategy.sell.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert strategy.state == State.SELLING
    assert strategy.sell.data.state_info.state == State.PARTIALLY_SOLD

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_SOLD
    assert state_info.side == PositionSide.SHORT
    assert state_info.ui_state == UiState.OPEN
    assert state_info.completeness == 0.5

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1178.82"
    assert item["quantity"] == "0.425", f"hp quant: {item['quantity']}"
    assert item["quantity_usdt"] == "501.0"
    assert item["sell_price"] == "4200.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "SELLING"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def move_to_partially_sold(strategy: HpStrategy) -> HpStrategy:
    strategy.sell.data.state_info.stagnation_counter = (
        strategy.sell.data.state_info.stagnation_limit
    )

    strategy.sell.data.state_info.generate_next_monitor_time()

    assert strategy.calculate_trigger_cancel_orders_price_sell() == 4116.0
    strategy.ticker_update = TickerUpdate(last_price=4116.0)
    assert strategy.conditions_for_cancelling_partially_sold_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.sell.orders) == 1

    logger.info("Orders: %s", strategy.sell.orders)
    assert all(order.status == ORDER_STATUS_CANCELED for order in strategy.sell.orders)
    assert strategy.sell.data.state_info.state == State.PARTIALLY_SOLD
    assert strategy.state == State.PARTIALLY_SOLD

    assert strategy.ui_queue.qsize() == 1

    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_SOLD
    assert state_info.side == PositionSide.SHORT
    assert state_info.ui_state == UiState.STAGNATED
    assert state_info.completeness == 0.5

    assert strategy.ui_queue.qsize() == 0

    return strategy


async def cancel_sell_position_part_bought_part_sold(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> Tuple[HpStrategy, List[Dict]]:
    strategy.sell.data.state_info.stagnation_counter = (
        strategy.sell.data.state_info.stagnation_limit
    )
    strategy.sell.data.state_info.generate_next_monitor_time()
    assert strategy.calculate_trigger_cancel_orders_price_sell() == 3864.0
    strategy.ticker_update = TickerUpdate(last_price=3864.0)
    assert (
        strategy.conditions_for_cancelling_partially_sold_and_bought_orders_sell_position()
    )
    assert not strategy.conditions_for_cancelling_partially_sold_orders()
    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.sell.data.state_info.state == State.PARTIALLY_SOLD
    assert strategy.state == State.SELLING

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.PART_SOLD_PART_BOUGHT
    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.sell.data.state_info.state == State.PARTIALLY_SOLD

    logger.info("There is %s events in the queue", strategy.ui_queue.qsize())

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_SOLD
    assert state_info.side == PositionSide.SHORT
    assert state_info.ui_state == UiState.STAGNATED
    assert state_info.completeness == 0.5

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.12"
    assert item["quantity_usdt"] == "168.0"
    assert item["sell_price"] == "4200"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "PART_SOLD_PART_BOUGHT"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def reopen_buy_part_bought_part_sold(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> Tuple[HpStrategy, List[Dict]]:
    assert strategy.calculate_trigger_send_orders_price_buy() == 1212
    strategy.ticker_update = TickerUpdate(last_price=1212)

    assert not strategy.conditions_for_sending_buy_orders()
    assert (
        strategy.conditions_for_resending_buy_orders_from_part_sold_and_bought_orders()
    )
    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.BUYING
    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.sell.data.state_info.state == State.PARTIALLY_SOLD

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    config = content.data.config
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.side == PositionSide.LONG
    assert state_info.ui_state == UiState.OPEN
    assert config.order_cancel == 2.0
    assert state_info.completeness == 0.28

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.12"
    assert item["quantity_usdt"] == "168.0"
    assert item["sell_price"] == "4200"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "BUYING"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def reopen_buy_part_bought_sold(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> Tuple[HpStrategy, List[Dict]]:
    assert strategy.calculate_trigger_send_orders_price_buy() == 1212
    strategy.ticker_update = TickerUpdate(last_price=1212)

    assert not strategy.conditions_for_sending_buy_orders()
    assert strategy.conditions_for_resending_buy_orders_for_sold_position()
    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.BUYING
    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.sell.data.state_info.state == State.SOLD

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    config = content.data.config
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.side == PositionSide.LONG
    assert state_info.ui_state == UiState.OPEN
    assert config.order_cancel == 2.0
    assert state_info.completeness == 0.28

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.0"
    assert item["quantity_usdt"] == "0.0"
    assert item["sell_price"] == "4200"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "BUYING"

    logger.info("HP List after the update: %s", hp_list)

    return strategy, hp_list


async def cancel_untouched_buy_position(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> Tuple[HpStrategy, List[Dict]]:
    strategy.buy.data.state_info.stagnation_counter = (
        strategy.buy.data.state_info.stagnation_limit
    )

    strategy.buy.data.state_info.generate_next_monitor_time()

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
    strategy.ticker_update = TickerUpdate(last_price=1428.0)
    assert strategy.conditions_for_cancelling_unfilled_buy_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.buy.orders) == 3
    assert all(order.status == ORDER_STATUS_CANCELED for order in strategy.buy.orders)
    assert strategy.buy.data.state_info.state == State.NEW
    assert strategy.state == State.NEW

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.NEW
    assert state_info.stagnation_counter == 0
    assert state_info.stagnation_limit == 8
    assert state_info.side == PositionSide.LONG
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.STAGNATED
    assert content.data.config.order_cancel == 2.0
    assert state_info.completeness == 0.00

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)
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

    return strategy, hp_list


async def cancel_untouched_sell_position(
    strategy: HpStrategy, hp_gui: HpFront, hp_list: List[Dict]
) -> HpStrategy:
    strategy.sell.data.state_info.stagnation_counter = (
        strategy.sell.data.state_info.stagnation_limit
    )

    strategy.sell.data.state_info.generate_next_monitor_time()

    assert strategy.calculate_trigger_cancel_orders_price_sell() == 3864.0
    strategy.ticker_update = TickerUpdate(last_price=3864.0)
    assert strategy.conditions_for_cancelling_unfilled_sell_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.sell.orders) == 1

    logger.info("Orders: %s", strategy.sell.orders)
    assert all(order.status == ORDER_STATUS_CANCELED for order in strategy.sell.orders)
    assert strategy.sell.data.state_info.state == State.NEW
    assert strategy.state == State.BOUGHT

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)

    state_info = content.data.state_info
    config = content.data.config
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.NEW
    assert state_info.side == PositionSide.SHORT
    assert state_info.ui_state == UiState.STAGNATED
    assert state_info.completeness == 0.00

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 1
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1178.82"
    assert item["quantity"] == "0.85"
    assert item["quantity_usdt"] == "1002.0"
    assert item["sell_price"] == "4200.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "BOUGHT"

    logger.info("HP List after the update: %s", hp_list)

    return strategy


async def buy_fully_last_order(strategy: HpStrategy) -> HpStrategy:
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
    logger.info("Orders: %s", strategy.buy.orders)
    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[1].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[2].status == ORDER_STATUS_FILLED

    logger.info("In queue: %s", strategy.ui_queue.qsize())

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    config = content.data.config
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.stagnation_counter == 0
    assert state_info.stagnation_limit == 8
    assert state_info.side == PositionSide.LONG
    assert state_info.next_monitor_time

    assert state_info.ui_state == UiState.OPEN
    assert config.order_cancel == 2.0
    assert state_info.completeness == 1.0

    assert strategy.ui_queue.qsize() == 0

    return strategy
