import asyncio
import logging
import pytest
from src.common.symbol_info import SymbolInfo
from src.gui.hpmanager import HpManager
from src.common.identifiers.spot import HPConfig, HpNew, State, StateInfo
from src.trading_system.spot import TradingSystem
from src.workers.strategy_executor import StrategyExecutor


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
    await asyncio.sleep(1)

    assert not back.config_queue.qsize()
    assert len(back.id_to_system) == 1
    ts = back.id_to_system["1000"]
    assert ts.strategy.state == State.NEW
    assert isinstance(ts, TradingSystem)

    buy_pos = ts.strategy.buy_position
    assert len(buy_pos.orders) == 3

    # ui_task.cancel()
    # try:
    #     await ui_task
    # except asyncio.CancelledError:
    #     logger.info("UI update task was cancelled successfully.")
