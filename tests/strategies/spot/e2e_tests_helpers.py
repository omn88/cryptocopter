import logging
import queue
from binance.enums import ORDER_TYPE_LIMIT, TIME_IN_FORCE_GTC, ORDER_STATUS_NEW
from src.common.symbol_info import SymbolInfo
from src.gui.hpfront import HpFront
from src.identifiers.common import Mode
from src.identifiers.spot import (
    Event,
    EventName,
    HPBuyConfig,
    HPBuyData,
    State,
    StateInfo,
    TickerUpdate,
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
