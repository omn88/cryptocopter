import logging
import pytest
from transitions.extensions.asyncio import AsyncMachine
from src.common.symbol_info import SymbolInfo
from src.gui.hpfront import HpFront
from src.identifiers.spot import (
    Event,
    EventName,
    HPConfig,
    HpNewPosition,
    State,
    StateInfo,
    TickerUpdate,
)
from src.strategies.hp_manager import HpStrategy
from src.strategy_executor import StrategyExecutor
from tests.spot import get_new_orders
from tests.strategies.spot.hp_manager_helpers import wait_for_condition


logger = logging.getLogger("hp_e2e_test")


@pytest.mark.database_integration
async def test_default_buy_scenario(frontend_backend_setup):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)

    assert len(back.strategies) == 0

    hp = HpNewPosition(
        HPConfig(
            symbol_info=SymbolInfo(symbol="BTCUSDT", precision=2, price_precision=2),
            price_low=1000,
            price_high=1400,
            order_trigger=1.0,
            budget=1000,
        ),
        state_info=StateInfo(),
    )

    front.config_queue.put_nowait(hp)
    logger.info("HP New added to the queue: %s", hp)

    await wait_for_condition(condition_func=lambda: len(back.strategies) == 1)

    assert not back.config_queue.qsize()
    assert len(back.strategies) == 1
    strategy = back.strategies["1000"]

    assert isinstance(strategy, HpStrategy)
    assert strategy.state == State.NEW

    buy_pos = strategy.buy
    assert len(buy_pos.orders) == 3

    strategy.client.create_order.side_effect = get_new_orders(
        price_low=buy_pos.config.price_low,
        price_high=buy_pos.config.price_high,
        number_of_orders=3,
    )

    ticker_event = Event(name=EventName.TICKER, content=TickerUpdate(last_price=1410))
    strategy.worker_queue.put_nowait(ticker_event)
    logger.info("Put event to the worker: %s", ticker_event)

    await wait_for_condition(condition_func=lambda: strategy.state == State.BUYING)

    assert len(strategy.buy.orders) == 3

    assert strategy.state == State.BUYING
    assert buy_pos.state_info.state == State.NEW

    logger.info("Active records: %s", front.active_records)
    logger.info("Idle records: %s", front.idle_records)

    await wait_for_condition(condition_func=lambda: front.active_records)

    strategy.db.stop_worker()
    strategy.stop_event.set()

    logger.info("DONE")
