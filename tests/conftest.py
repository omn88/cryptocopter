import asyncio
import logging
from unittest.mock import AsyncMock
import pytest
from pytest_mock import MockerFixture
from logging_config import StrategyLogger

from src.common.identifiers.common import Event, EventName
from src.common.identifiers.spot import StrategyConfig as ConfigSpot
from src.common.identifiers.futures import (
    Signal,
    SignalUpdate,
    StrategyConfig as ConfigFutures,
)
from src.df_handler.futures import DfHandler
from src.gui.gui_handler.futures import GuiHandler
from src.strategies.futures.base import BaseFuturesStrategy
from src.strategies.futures.rsi_basic import RsiBasic
from src.strategies.futures.rsi_extended import RsiExtended
from src.strategies.futures.rsi_special import RsiSpecial
from src.workers.trading_state_machine import TradingStateMachine

from tests.data.sample_dataframes import raw_data_generate

logger = logging.getLogger("conftest")


@pytest.fixture
def mock_AsyncClient(mocker: MockerFixture) -> AsyncMock:
    # Mock the AsyncClient.
    mocked_AsyncClient = mocker.patch("binance.AsyncClient")
    # Create an async mock for the instance methods.
    mocked_async_client = AsyncMock()
    # Assign the instance to the mocked AsyncClient when used in a context manager.
    mocked_AsyncClient.return_value.__aenter__.return_value = mocked_async_client
    return mocked_async_client

@pytest.fixture
async def spot(mock_AsyncClient):

    logger = StrategyLogger(name="RBASE_BTCUSDT", strategy_info="RBASE_BTCUSDT")


    # config = ConfigSpot(
    #     system_id="1234", symbol="BTCUSDT", side=
    # )


@pytest.fixture
async def base(mock_AsyncClient):
    config = ConfigFutures(
        symbol="BTCUSDT",
        name="RE_BTCUSDT",
        number_of_orders=4,
        budget=400,
    )
    logger = StrategyLogger(name="RBASE_BTCUSDT", strategy_info="RBASE_BTCUSDT")
    df_handler = DfHandler(client=mock_AsyncClient, config=config, logger=logger)

    df_handler.raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df_handler.df = df_handler.insert_to_pandas()

    state_machine = TradingStateMachine(
        strategy=BaseFuturesStrategy(
            client=mock_AsyncClient,
            balance=1000,
            df_handler=df_handler,
            config=config,
            gui_handler=GuiHandler(
                main_ui_queue=asyncio.Queue(), ui_queue=asyncio.Queue(), logger=logger
            ),
            logger=logger,
        )
    )

    state_machine.strategy.df_handler.df["Signal"] = 0
    state_machine.strategy.df_handler.df["Position"] = state_machine.strategy.state

    await state_machine.strategy.queue.put(
        Event(name=EventName.SIGNAL, content=SignalUpdate(signal=Signal.NULL, price=0))
    )

    yield state_machine

    await state_machine.strategy.client.close_connection()


@pytest.fixture
async def basic_rsi(mock_AsyncClient):
    config = ConfigFutures(
                symbol="BTCUSDT",
                name="RB_BTCUSDT",
                number_of_orders=4,
                budget=400,
            )
    logger = StrategyLogger(name="RB_BTCUSDT", strategy_info="RB_BTCUSDT")
    df_handler = DfHandler(client=mock_AsyncClient, config=config, logger=logger)
    df_handler.raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df_handler.df = df_handler.insert_to_pandas()
    df_handler.df = df_handler.rsi_indicator_apply(df=df_handler.df)

    state_machine = TradingStateMachine(
        strategy=RsiBasic(
            client=mock_AsyncClient,
            balance=1000,
            df_handler=df_handler,
            gui_handler=GuiHandler(
                main_ui_queue=asyncio.Queue(), ui_queue=asyncio.Queue(), logger=logger
            ),
            config=config,
            logger=logger,
        )
    )

    await state_machine.strategy.df_handler.determine_start_position(
        queue=state_machine.strategy.queue
    )

    yield state_machine

    await state_machine.strategy.client.close_connection()


@pytest.fixture
async def extended_rsi(mock_AsyncClient):
    config = ConfigFutures(
        symbol="BTCUSDT",
        name="RE_BTCUSDT",
        number_of_orders=4,
        budget=400,
    )
    logger = StrategyLogger(name="RE_BTCUSDT", strategy_info="RE_BTCUSDT")
    df_handler = DfHandler(client=mock_AsyncClient, config=config, logger=logger)
    df_handler.raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df_handler.df = df_handler.insert_to_pandas()
    df_handler.df = df_handler.rsi_indicator_apply(df=df_handler.df)

    logger = StrategyLogger(name="RE_BTCUSDT", strategy_info="RE_BTCUSDT")

    state_machine = TradingStateMachine(
        strategy=RsiExtended(
            client=mock_AsyncClient,
            balance=1000,
            df_handler=df_handler,
            gui_handler=GuiHandler(
                main_ui_queue=asyncio.Queue(), ui_queue=asyncio.Queue(), logger=logger
            ),
            config=config,
            logger=logger,
        )
    )

    await state_machine.strategy.df_handler.determine_start_position(
        queue=state_machine.strategy.queue
    )
    yield state_machine

    await state_machine.strategy.client.close_connection()


@pytest.fixture
async def special_rsi(mock_AsyncClient):
    config = ConfigFutures(
        symbol="BTCUSDT",
        name="RS_BTCUSDT",
        number_of_orders=4,
        budget=400,
    )
    logger = StrategyLogger(name="RS_BTCUSDT", strategy_info="RS_BTCUSDT")
    df_handler = DfHandler(client=mock_AsyncClient, config=config, logger=logger)
    df_handler.raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df_handler.df = df_handler.insert_to_pandas()
    df_handler.df = df_handler.rsi_indicator_apply(df=df_handler.df)

    state_machine = TradingStateMachine(
        strategy=RsiSpecial(
            client=mock_AsyncClient,
            balance=1000,
            df_handler=df_handler,
            gui_handler=GuiHandler(
                main_ui_queue=asyncio.Queue(), ui_queue=asyncio.Queue(), logger=logger
            ),
            logger=logger,
            config=config,
        )
    )

    await state_machine.strategy.df_handler.determine_start_position(
        queue=state_machine.strategy.queue
    )

    yield state_machine

    await state_machine.strategy.client.close_connection()
