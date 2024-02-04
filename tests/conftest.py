import asyncio
import logging
from unittest.mock import AsyncMock
import pytest
from pytest_mock import MockerFixture
from logging_config import StrategyLogger

from src.common.identifiers import (
    Event,
    EventName,
    Signal,
    SignalUpdate,
    StrategyConfig,
)
from src.common.initialize_trading_environment import determine_start_position
from src.df_handler import DfHandler
from src.gui.asyncapp import AsyncApp
from src.gui.gui_handler import GuiHandler
from src.gui.strategytab import StrategyTab
from src.strategies.base import BaseStrategy
from src.strategies.rsi_special import RsiSpecial
from src.trading_system import TradingSystem
from src.workers.trading_state_machine import TradingStateMachine
from src.strategies.rsi_basic import RsiBasic
from src.strategies.rsi_extended import RsiExtended

# from src.strategies.rsi_special import RsiSpecial
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


@pytest.fixture()
async def base(mock_AsyncClient):
    config = StrategyConfig(
        symbol="BTCUSDT",
        name="RE_BTCUSDT",
        number_of_orders=4,
        budget=400,
    )
    logger = StrategyLogger(name="RBASE_BTCUSDT", strategy_info="RBASE_BTCUSDT")
    df_handler = DfHandler(client=mock_AsyncClient, config=config, logger=logger)

    df_handler.raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df_handler.df = df_handler.insert_to_pandas()

    logger = StrategyLogger(name="RBASE_BTCUSDT", strategy_info="RBASE_BTCUSDT")

    state_machine = TradingStateMachine(
        strategy=BaseStrategy(
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


@pytest.fixture()
async def basic_rsi(mock_AsyncClient):
    config = StrategyConfig(
        symbol="BTCUSDT",
        name="RE_BTCUSDT",
        number_of_orders=4,
        budget=400,
    )
    logger = StrategyLogger(name="RB_BTCUSDT", strategy_info="RB_BTCUSDT")
    df_handler = DfHandler(client=mock_AsyncClient, config=config, logger=logger)
    df_handler.raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df_handler.df = df_handler.insert_to_pandas()
    df_handler.df = df_handler.rsi_indicator_apply(df=df_handler.df)

    logger = StrategyLogger(name="RB_BTCUSDT", strategy_info="RB_BTCUSDT")

    state_machine = TradingStateMachine(
        strategy=RsiBasic(
            client=mock_AsyncClient,
            balance=1000,
            df_handler=df_handler,
            gui_handler=GuiHandler(
                main_ui_queue=asyncio.Queue(), ui_queue=asyncio.Queue(), logger=logger
            ),
            config=StrategyConfig(
                symbol="BTCUSDT",
                name="RB_BTCUSDT",
                number_of_orders=4,
                budget=400,
            ),
            logger=logger,
        )
    )

    await determine_start_position(
        df=state_machine.strategy.df_handler.df, queue=state_machine.strategy.queue
    )

    yield state_machine

    await state_machine.strategy.client.close_connection()


@pytest.fixture
async def extended_rsi(mock_AsyncClient):
    config = StrategyConfig(
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

    await determine_start_position(
        df=state_machine.strategy.df_handler.df, queue=state_machine.strategy.queue
    )
    yield state_machine

    await state_machine.strategy.client.close_connection()


@pytest.fixture
async def special_rsi(mock_AsyncClient):
    config = StrategyConfig(
        symbol="BTCUSDT",
        name="RE_BTCUSDT",
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

    await determine_start_position(
        df=state_machine.strategy.df_handler.df, queue=state_machine.strategy.queue
    )

    yield state_machine

    await state_machine.strategy.client.close_connection()


# @pytest.fixture
# async def trading_system():
#     return TradingSystem(
#         client=mock_AsyncClient,
#         strategy_name="TEST_NAME",
#         symbol="TEST_SYMBOL",
#         number_of_orders=4,
#         budget=400,
#         strategy_logger=StrategyLogger(name="TEST", strategy_info="TEST_INFO"),
#         gui_handler=GuiHandler()
#     )


# @pytest.fixture
# async def async_app(base):

#     async_app = AsyncApp(client=mock_AsyncClient)


#     return async_app


# @pytest.fixture
# def strategy_tab():
#     return StrategyTab(trading_system=trading_system)
