import asyncio
import logging
import pytest
from src.common.symbol_info import SymbolInfo
from src.gui.hpmanager import HpFront
from src.common.identifiers.spot import (
    Event,
    EventName,
    HPConfig,
    HpNew,
    State,
    StateInfo,
    TickerUpdate,
)
from src.trading_system.spot import TradingSystem
from src.workers.strategy_executor import StrategyExecutor
from tests.spot import get_new_orders
from tests.strategies.spot.hp_manager_helpers import wait_for_condition


logger = logging.getLogger("hp_e2e_test")


@pytest.mark.database_integration
async def test_default_buy_scenario(frontend_backend_setup):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)

    front.start_ui_loop()

    assert len(back.id_to_system) == 0

    hp = HpNew(
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

    await wait_for_condition(condition_func=lambda: len(back.id_to_system) == 1)

    assert not back.config_queue.qsize()
    assert len(back.id_to_system) == 1
    ts = back.id_to_system["1000"]
    assert ts.strategy.state == State.NEW
    assert isinstance(ts, TradingSystem)

    buy_pos = ts.strategy.buy_position
    assert len(buy_pos.orders) == 3

    ts.strategy.client.create_order.side_effect = get_new_orders(
        price_low=buy_pos.config.price_low,
        price_high=buy_pos.config.price_high,
        number_of_orders=3,
    )

    ticker_event = Event(name=EventName.TICKER, content=TickerUpdate(last_price=1410))
    ts.strategy.core_queue.put_nowait(ticker_event)
    logger.info("Put event to the worker: %s", ticker_event)

    await wait_for_condition(condition_func=lambda: ts.strategy.state == State.BUYING)

    assert len(ts.strategy.buy_position.orders) == 3

    assert ts.strategy.state == State.BUYING
    assert buy_pos.state_info.state == State.NEW

    logger.info("Active records: %s", front.active_records)
    logger.info("Idle records: %s", front.idle_records)

    await wait_for_condition(condition_func=lambda: front.active_records)

    logger.info("DONE")
