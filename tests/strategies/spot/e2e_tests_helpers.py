import logging
import queue
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_CANCELED,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_FILLED,
)
from src.common.symbol_info import SymbolInfo
from src.gui.hpfront import HpFront
from src.gui.identifiers.spot import HPGuiDataBuy
from src.identifiers.common import Mode, PositionSide
from src.identifiers.spot import (
    Event,
    EventName,
    ExecutionReport,
    HPBuyConfig,
    HPBuyData,
    State,
    StateInfo,
    TickerUpdate,
    UiState,
)
from src.strategies.hp_manager import HpStrategy
from src.strategy_executor import StrategyExecutor
from tests.spot import get_new_orders
from tests.strategies.spot.hp_manager_helpers import wait_for_condition

logger = logging.getLogger("e2e_helpers")


def simulate_new_price(worker_queue: queue.Queue, price: float):
    ticker_event = Event(name=EventName.TICKER, content=TickerUpdate(last_price=price))
    worker_queue.put_nowait(ticker_event)
    logger.info("Put event to the worker: %s", ticker_event)


def simulate_buy_position(
    config_queue: queue.Queue,
    symbol: str,
    mode: Mode = Mode.DCA,
    budget: float = 1000,
    price_low: float = 1000,
    price_high: float = 1400,
    order_trigger: float = 1.0,
):
    hp = HPBuyData(
        HPBuyConfig(
            hp_id="0",
            symbol_info=SymbolInfo(symbol=symbol, precision=2, price_precision=2),
            price_low=price_low,
            price_high=price_high,
            order_trigger=order_trigger,
            budget=budget,
            mode=mode,
        ),
        state_info=StateInfo(),
    )

    config_queue.put_nowait(hp)
    logger.info("HP Buy Data added to the queue: %s", hp)


async def assert_default_buy_position(front: HpFront, back: StrategyExecutor):
    await wait_for_condition(condition_func=lambda: len(back.strategies) == 1)
    assert not back.config_queue.qsize()
    assert len(back.strategies) == 1
    strategy = back.strategies["1000"]

    assert isinstance(strategy, HpStrategy)
    assert strategy.state == State.NEW
    assert len(strategy.buy.orders) == 3

    await wait_for_condition(condition_func=lambda: not front.active_records_buy)
    await wait_for_condition(condition_func=lambda: front.idle_records_buy)


async def move_to_position_active_buy(front: HpFront, back: StrategyExecutor):
    # Open position and send orders
    strategy = back.strategies["1000"]
    strategy.client.create_order.side_effect = get_new_orders(
        price_low=strategy.buy.data.config.price_low,
        price_high=strategy.buy.data.config.price_high,
        number_of_orders=3,
    )
    simulate_new_price(worker_queue=strategy.worker_queue, price=1410)

    # Assert new opened position data
    await wait_for_condition(condition_func=lambda: strategy.state == State.BUYING)
    await wait_for_condition(condition_func=lambda: front.active_records_buy)
    await wait_for_condition(condition_func=lambda: not front.idle_records_buy)
    assert strategy.buy.data.state_info.state == State.NEW
    assert all(order.order_id for order in strategy.buy.orders)
    assert all(order.status == ORDER_STATUS_NEW for order in strategy.buy.orders)

    logger.info("Active records: %s", front.active_records_buy)
    logger.info("Idle records: %s", front.idle_records_buy)


async def cancel_buy_position_untouched(front: HpFront, back: StrategyExecutor):
    strategy = back.strategies["1000"]
    strategy.buy.data.state_info.stagnation_counter = (
        strategy.buy.data.state_info.stagnation_limit
    )

    strategy.buy.data.state_info.generate_next_monitor_time()

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
    simulate_new_price(worker_queue=strategy.worker_queue, price=1428)

    await wait_for_condition(
        condition_func=lambda: all(
            order.status == ORDER_STATUS_CANCELED for order in strategy.buy.orders
        )
    )

    assert len(strategy.buy.orders) == 3
    assert strategy.buy.data.state_info.state == State.NEW
    assert strategy.state == State.NEW

    await wait_for_condition(condition_func=lambda: strategy.ui_queue.qsize() == 1)
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
    hp_list = front.update_hp_list(update=content.hp_update, hp_list=front.hp_list_data)
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


async def simulate_partial_fill(front: HpFront, back: StrategyExecutor) -> HpStrategy:
    strategy = back.strategies["1000"]

    exc_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=445860,
        last_executed_quantity=0.12,
        last_executed_price=1400,
        cumulative_filled_quantity=0.12,
    )
    strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
    logger.info("Put event to the worker: %s", exc_report)

    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy.orders)
    await wait_for_condition(
        condition_func=lambda: strategy.buy.orders[0].status
        == ORDER_STATUS_PARTIALLY_FILLED
    )
    assert strategy.buy.orders[1].status == ORDER_STATUS_NEW
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    await wait_for_condition(condition_func=lambda: strategy.ui_queue.qsize() == 1)
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

    front.hp_list_data = front.update_hp_list(
        update=content.hp_update, hp_list=front.hp_list_data
    )

    assert len(front.hp_list_data) == 1
    item = front.hp_list_data[0]
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

    logger.info("HP List after the update: %s", front.hp_list_data)

    return strategy


async def simulate_first_buy_order_fill(
    front: HpFront, back: StrategyExecutor
) -> HpStrategy:
    strategy = back.strategies["1000"]

    exc_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445860,
        last_executed_quantity=0.24,
        last_executed_price=1400,
        cumulative_filled_quantity=0.24,
        price=1400.0,
    )
    strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
    logger.info("Put event to the worker: %s", exc_report)

    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy.orders)
    await wait_for_condition(
        condition_func=lambda: strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    )
    assert strategy.buy.orders[1].status == ORDER_STATUS_NEW
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    await wait_for_condition(condition_func=lambda: strategy.ui_queue.qsize() == 1)
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

    front.hp_list_data = front.update_hp_list(
        update=content.hp_update, hp_list=front.hp_list_data
    )

    assert len(front.hp_list_data) == 1
    item = front.hp_list_data[0]
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

    logger.info("HP List after the update: %s", front.hp_list_data)

    return strategy


async def simulate_second_buy_order_fill(
    front: HpFront, back: StrategyExecutor, sell_price: str = "0.0"
) -> HpStrategy:
    strategy = back.strategies["1000"]

    exc_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445861,
        last_executed_quantity=0.28,
        last_executed_price=1200,
        cumulative_filled_quantity=0.28,
        price=1200,
    )
    strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
    logger.info("Put event to the worker: %s", exc_report)

    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy.orders)
    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    await wait_for_condition(
        condition_func=lambda: strategy.buy.orders[1].status == ORDER_STATUS_FILLED
    )
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    await wait_for_condition(condition_func=lambda: strategy.ui_queue.qsize() == 1)
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

    front.hp_list_data = front.update_hp_list(
        update=content.hp_update, hp_list=front.hp_list_data
    )

    assert len(front.hp_list_data) == 1
    item = front.hp_list_data[0]
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

    logger.info("HP List after the update: %s", front.hp_list_data)

    return strategy


async def simulate_third_buy_order_fill(
    front: HpFront, back: StrategyExecutor, sell_price: str = "0.0"
) -> HpStrategy:
    strategy = back.strategies["1000"]

    exc_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445862,
        last_executed_quantity=0.33,
        last_executed_price=1000,
        cumulative_filled_quantity=0.33,
        price=1000,
    )
    strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
    logger.info("Put event to the worker: %s", exc_report)

    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy.orders)
    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy.orders[1].status == ORDER_STATUS_FILLED
    await wait_for_condition(
        condition_func=lambda: strategy.buy.orders[2].status == ORDER_STATUS_FILLED
    )

    await wait_for_condition(condition_func=lambda: strategy.ui_queue.qsize() == 1)
    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.BOUGHT
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

    front.hp_list_data = front.update_hp_list(
        update=content.hp_update, hp_list=front.hp_list_data
    )

    assert len(front.hp_list_data) == 1
    item = front.hp_list_data[0]
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

    logger.info("HP List after the update: %s", front.hp_list_data)

    return strategy
