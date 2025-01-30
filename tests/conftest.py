import os

from src.workers.broker_spot import BrokerSpot
from src.workers.strategy_executor import StrategyExecutor

# Use dummy window for Kivy in headless testing
os.environ["KIVY_WINDOW"] = "dummy"
import asyncio
import logging
import queue
from typing import AsyncGenerator, Dict, List
from unittest.mock import AsyncMock, MagicMock
from transitions.extensions.asyncio import AsyncMachine
import pytest
from unittest.mock import patch
from pytest_mock import MockerFixture
from decouple import Config, RepositoryEnv
from logging_config import StrategyLogger
from src.common.common import generate_hp_id
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import HPUpdate, PositionData
from src.common.database import Database
from src.common.identifiers.futures import (
    Event,
    EventName,
    Signal,
    SignalUpdate,
)
from src.common.identifiers.spot import HPConfig, SellConfig, State, StateInfo
from src.common.identifiers.futures import StrategyConfig as ConfigFutures
from src.df_handler.futures import DfHandler as DfHandlerFutures
from src.gui.gui_handler.futures import GuiHandler as GuiHandlerFutures
from src.strategies.futures.base import BaseFuturesStrategy
from src.strategies.futures.rsi_basic import RsiBasic
from src.strategies.futures.rsi_extended import RsiExtended
from src.strategies.futures.rsi_special import RsiSpecial
from src.strategies.spot.hp_manager import HpManager as StrategyHP
from src.gui.hpmanager import HpManager as HPGUI

from tests.data.sample_dataframes import raw_data_generate
from tests.spot import get_new_orders

logger = logging.getLogger("conftest")

DB_CONFIG_FILE = "config/.db_config"
config = Config(RepositoryEnv(DB_CONFIG_FILE))

logger.info("DB CONFIG: %s", config)


# @pytest.fixture(scope="session", autouse=True)
# def mock_env():
#     """Mock the environment variables to avoid missing .env issues."""
#     with patch("decouple.Config", return_value={"DUMMY_VAR": "test_value"}):
#         yield


@pytest.fixture
def mock_AsyncClient(mocker: MockerFixture) -> AsyncMock:
    # Mock the AsyncClient.
    mocked_AsyncClient = mocker.patch("binance.AsyncClient")
    # Create an async mock for the instance methods.
    mocked_async_client = AsyncMock()

    # Mock exchange info data.
    mock_exchange_info: Dict = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "filters": [{"filterType": "MIN_NOTIONAL", "minNotional": "10.0"}],
            },
            {
                "symbol": "ETHUSDT",
                "filters": [{"filterType": "MIN_NOTIONAL", "minNotional": "5.0"}],
            },
        ]
    }

    # Mock the get_exchange_info method to return the mock data.
    mocked_async_client.get_exchange_info.return_value = mock_exchange_info

    # Assign the instance to the mocked AsyncClient when used in a context manager.
    mocked_AsyncClient.return_value.__aenter__.return_value = mocked_async_client
    return mocked_async_client


@pytest.fixture
async def test_db():
    """Drop the test database, recreate it, and set up tables before running tests."""
    db = Database(
        host=config("DB_HOST"),
        port=int(config("DB_PORT")),
        user=config("DB_USER"),
        password=config("DB_PASSWORD"),
        name=config("DB_TEST_NAME"),
    )
    await db.initialize()

    try:
        logger.info(
            "Dropping and recreating the test database: %s", config("DB_TEST_NAME")
        )

        # Drop the existing test database
        db.run_db_task(db.drop_database())

        # Recreate and set up the database from scratch
        db.run_db_task(db.create_database_if_not_exists())
        db.run_db_task(db.create_pool())
        db.run_db_task(db.setup_tables())
        db.run_db_task(db.create_hp_list_table())

        yield db  # Provide the database instance for the test

    finally:
        db.run_db_task(db.close_pool())
        db.stop_worker()


@pytest.fixture
def strategy_executor_fixture(test_db):
    """
    Fixture to create and run a StrategyExecutor instance.

    - Starts the executor loop in a separate thread.
    - Mocks necessary dependencies.
    - Provides an initialized instance for testing.
    """

    # Mock dependencies
    mock_broker = MagicMock(spec=BrokerSpot)
    ui_queue = queue.Queue()
    strategy_logger = StrategyLogger(name="test_strategy_executor")
    balances = {"USDT": 10000}  # Mock balance
    symbols_info = {
        "BTCUSDT": SymbolInfo(symbol="BTCUSDT", precision=5, price_precision=2),
    }

    # Create the StrategyExecutor instance
    executor = StrategyExecutor(
        strategy_logger=strategy_logger,
        db=test_db,
        broker=mock_broker,
        ui_queue=ui_queue,
        symbols_info=symbols_info,
        balances=balances,
    )

    yield executor  # Provide the instance for the test

    # Cleanup: Ensure proper shutdown after the test
    executor.stop()


@pytest.fixture
async def frontend_backend_setup(
    hp_gui: HPGUI, strategy_executor_fixture: StrategyExecutor
):
    """
    Fixture to set up an integrated frontend-backend system.

    - Ensures frontend (HpManager) can send commands to backend (StrategyExecutor).
    - Provides a test scenario where state updates and order handling can be asserted.
    """

    # Ensure frontend has the correct reference to the backend's queue
    hp_gui.config_queue = strategy_executor_fixture.config_queue

    yield hp_gui, strategy_executor_fixture  # Provide both components

    # Cleanup is handled in individual fixtures (strategy_executor_fixture, hp_gui)


@pytest.fixture
def trading_system_factory(mock_AsyncClient):
    def create_trading_system(hp_config: HPConfig, balance: float = 10000):
        ui_queue: queue.Queue = queue.Queue()
        test_db = MagicMock()
        strategy = StrategyHP(
            client=mock_AsyncClient,
            balance=balance,
            config_queue=MagicMock(),
            buy_config=hp_config,
            ui_queue=ui_queue,
            logger=StrategyLogger(name="test"),
            db=test_db,
            core_queue=queue.Queue(),
            state_info=StateInfo(),
        )
        strategy.buy_position.config.hp_id = generate_hp_id(hp_list=[hp_config])
        strategy.buy_position.orders = (
            strategy.buy_position.order_handler.prepare_buy_orders(config=hp_config)
        )
        strategy.client.create_order.side_effect = get_new_orders(
            price_low=strategy.buy_position.config.price_low,
            price_high=strategy.buy_position.config.price_high,
        )

        state_machine = AsyncMachine(
            model=strategy,
            states=strategy.states,
            transitions=strategy.transitions,
            initial=strategy.state,
            send_event=True,
            queued=True,
        )

        ui_queue.put_nowait(
            PositionData(
                config=hp_config,
                state_info=strategy.buy_position.state_info,
                hp_update=HPUpdate(
                    hp_id=strategy.buy_position.config.hp_id,
                    asset=strategy.buy_position.config.symbol_info.symbol[:-4],
                    state=State.NEW,
                ),
            )
        )

        return state_machine

    return create_trading_system


@pytest.fixture
async def hp_gui(mock_AsyncClient) -> AsyncGenerator:
    with patch("kivy.base.EventLoop.ensure_window"):
        # Set up a mock HpManager instance
        mock_config_queue = MagicMock()
        mock_ui_queue = MagicMock()

        hp_manager = HPGUI(
            client=mock_AsyncClient,
            strategy_logger=MagicMock(),
            strategy_id="test_strategy",
            config_queue=mock_config_queue,
            db=MagicMock(),
            ui_queue=mock_ui_queue,
            symbols_info={
                "BTCUSDT": SymbolInfo(symbol="BTCUSDT", precision=5, price_precision=2)
            },
            test_mode=True,
        )

        yield hp_manager


@pytest.fixture
def trading_system_factory_db(mock_AsyncClient, test_db):
    def create_trading_system(hp_config: HPConfig, balance: float = 10000):
        ui_queue: queue.Queue = queue.Queue()
        strategy = StrategyHP(
            client=mock_AsyncClient,
            balance=balance,
            buy_config=hp_config,
            config_queue=MagicMock(),
            ui_queue=ui_queue,
            logger=StrategyLogger(name="test"),
            db=test_db,
            core_queue=queue.Queue(),
            state_info=StateInfo(),
        )
        # Trading State Machine initialization
        state_machine = AsyncMachine(
            model=strategy,
            states=strategy.states,
            transitions=strategy.transitions,
            initial=strategy.state,
            send_event=True,
            queued=True,
        )
        return state_machine

    return create_trading_system


@pytest.fixture
async def base(mock_AsyncClient):
    config = ConfigFutures(
        symbol="BTCUSDT",
        name="RE_BTCUSDT",
        number_of_orders=4,
        budget=400,
    )
    logger = StrategyLogger(name="RBASE_BTCUSDT")
    df_handler = DfHandlerFutures(client=mock_AsyncClient, config=config, logger=logger)

    df_handler.raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df_handler.df = df_handler.insert_to_pandas()

    strategy = BaseFuturesStrategy(
        client=mock_AsyncClient,
        balance=1000,
        df_handler=df_handler,
        config=config,
        gui_handler=GuiHandlerFutures(
            main_ui_queue=asyncio.Queue(), ui_queue=asyncio.Queue(), logger=logger
        ),
        logger=logger,
    )

    # Trading State Machine initialization
    state_machine = AsyncMachine(
        model=strategy,
        states=strategy.states,
        transitions=strategy.transitions,
        initial=strategy.state,
        send_event=True,
        queued=True,
    )

    state_machine.model.df_handler.df["Signal"] = 0
    state_machine.model.df_handler.df["Position"] = state_machine.model.state

    await state_machine.model.queue.put(
        Event(name=EventName.SIGNAL, content=SignalUpdate(signal=Signal.NULL, price=0))
    )

    yield state_machine

    await state_machine.model.client.close_connection()


@pytest.fixture
async def basic_rsi(mock_AsyncClient):
    config = ConfigFutures(
        symbol="BTCUSDT",
        name="RB_BTCUSDT",
        number_of_orders=4,
        budget=400,
    )
    logger = StrategyLogger(name="RB_BTCUSDT")
    df_handler = DfHandlerFutures(client=mock_AsyncClient, config=config, logger=logger)
    df_handler.raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df_handler.df = df_handler.insert_to_pandas()
    df_handler.df = df_handler.rsi_indicator_apply(df=df_handler.df)

    strategy = RsiBasic(
        client=mock_AsyncClient,
        balance=1000,
        df_handler=df_handler,
        gui_handler=GuiHandlerFutures(
            main_ui_queue=asyncio.Queue(), ui_queue=asyncio.Queue(), logger=logger
        ),
        config=config,
        logger=logger,
    )

    # Trading State Machine initialization
    state_machine = AsyncMachine(
        model=strategy,
        states=strategy.states,
        transitions=strategy.transitions,
        initial=strategy.state,
        send_event=True,
        queued=True,
    )

    await state_machine.model.df_handler.determine_start_position(
        queue=state_machine.model.queue
    )

    yield state_machine

    await state_machine.model.client.close_connection()


@pytest.fixture
async def extended_rsi(mock_AsyncClient):
    config = ConfigFutures(
        symbol="BTCUSDT",
        name="RE_BTCUSDT",
        number_of_orders=4,
        budget=400,
    )
    logger = StrategyLogger(name="RE_BTCUSDT")
    df_handler = DfHandlerFutures(client=mock_AsyncClient, config=config, logger=logger)
    df_handler.raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df_handler.df = df_handler.insert_to_pandas()
    df_handler.df = df_handler.rsi_indicator_apply(df=df_handler.df)

    logger = StrategyLogger(name="RE_BTCUSDT")

    strategy = RsiExtended(
        client=mock_AsyncClient,
        balance=1000,
        df_handler=df_handler,
        gui_handler=GuiHandlerFutures(
            main_ui_queue=asyncio.Queue(), ui_queue=asyncio.Queue(), logger=logger
        ),
        config=config,
        logger=logger,
    )

    # Trading State Machine initialization
    state_machine = AsyncMachine(
        model=strategy,
        states=strategy.states,
        transitions=strategy.transitions,
        initial=strategy.state,
        send_event=True,
        queued=True,
    )

    await state_machine.model.df_handler.determine_start_position(
        queue=state_machine.model.queue
    )
    yield state_machine

    await state_machine.model.client.close_connection()


@pytest.fixture
async def special_rsi(mock_AsyncClient):
    config = ConfigFutures(
        symbol="BTCUSDT",
        name="RS_BTCUSDT",
        number_of_orders=4,
        budget=400,
    )
    logger = StrategyLogger(name="RS_BTCUSDT")
    df_handler = DfHandlerFutures(client=mock_AsyncClient, config=config, logger=logger)
    df_handler.raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df_handler.df = df_handler.insert_to_pandas()
    df_handler.df = df_handler.rsi_indicator_apply(df=df_handler.df)

    strategy = RsiSpecial(
        client=mock_AsyncClient,
        balance=1000,
        df_handler=df_handler,
        gui_handler=GuiHandlerFutures(
            main_ui_queue=asyncio.Queue(), ui_queue=asyncio.Queue(), logger=logger
        ),
        logger=logger,
        config=config,
    )

    state_machine = AsyncMachine(
        model=strategy,
        states=strategy.states,
        transitions=strategy.transitions,
        initial=strategy.state,
        send_event=True,
        queued=True,
    )

    await state_machine.model.df_handler.determine_start_position(
        queue=state_machine.model.queue
    )

    yield state_machine

    await state_machine.model.client.close_connection()
