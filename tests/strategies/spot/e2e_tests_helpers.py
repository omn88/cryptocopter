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
