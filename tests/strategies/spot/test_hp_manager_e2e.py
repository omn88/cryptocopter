import asyncio
import logging
import pytest
from src.common.symbol_info import SymbolInfo
from src.gui.hpmanager import HpManager
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


logger = logging.getLogger("hp_e2e_test")


@pytest.mark.database_integration
async def test_default_buy_scenario(frontend_backend_setup):
    front, back = frontend_backend_setup
    assert isinstance(front, HpManager)
    assert isinstance(back, StrategyExecutor)

    # ui_task = asyncio.create_task(front.update_ui())

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

    await asyncio.sleep(0.3)

    assert not back.config_queue.qsize()
    assert len(back.id_to_system) == 1
    ts = back.id_to_system["1000"]
    assert ts.strategy.state == State.NEW
    assert isinstance(ts, TradingSystem)

    buy_pos = ts.strategy.buy_position
    assert len(ts.strategy.buy_position.orders) == 3

    ts.strategy.client.create_order.side_effect = get_new_orders(
        price_low=ts.strategy.buy_position.config.price_low,
        price_high=ts.strategy.buy_position.config.price_high,
        number_of_orders=3
    )

    ticker_event = Event(name=EventName.TICKER, content=TickerUpdate(last_price=1410))
    ts.strategy.core_queue.put_nowait(ticker_event)
    logger.info("Put event to the worker: %s", ticker_event)
    await asyncio.sleep(1)

    assert len(ts.strategy.buy_position.orders) == 3

    assert ts.strategy.state == State.BUYING
    assert ts.strategy.buy_position.state_info.state == State.NEW

    logger.info("DONE")

    # ui_task.cancel()
    # try:
    #     await ui_task
    # except asyncio.CancelledError:
    #     logger.info("UI update task was cancelled successfully.")
