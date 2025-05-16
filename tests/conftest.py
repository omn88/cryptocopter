import os

os.environ["KIVY_NO_CONSOLELOG"] = "1"
from src.gui.hpfront import HpFront
from src.broker import BrokerSpot
from src.identifiers.common import PositionSide
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.position_buy import HPPositionBuy
from src.position_sell import HPPositionSell
from src.strategy_executor import StrategyExecutor
from tests.strategies.spot.hp_manager_helpers import wait_for_condition

# Use dummy window for Kivy in headless testing
os.environ["KIVY_WINDOW"] = "dummy"
import asyncio
import warnings
import pytest
import logging
import queue
from typing import AsyncGenerator, Dict
from unittest.mock import AsyncMock, MagicMock
from transitions.extensions.asyncio import AsyncMachine
from unittest.mock import patch
from pytest_mock import MockerFixture
from decouple import Config, RepositoryEnv
from src.common.common import generate_hp_id
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import HPGuiDataBuy, HPUpdate
from src.database import Database
from src.identifiers.futures import (
    Event,
    EventName,
    Signal,
    SignalUpdate,
)
from src.identifiers.spot import (
    HPBuyConfig,
    HPBuyData,
    HPSellConfig,
    HPSellData,
    Order,
    SellPosition,
    State,
    StateInfo,
)
from src.identifiers.futures import StrategyConfig as ConfigFutures
from src.futures.df_handler.futures import DfHandler as DfHandlerFutures
from src.gui.gui_handler.futures import GuiHandler as GuiHandlerFutures
from src.futures.strategies.futures.base import BaseFuturesStrategy
from src.futures.strategies.futures.rsi_basic import RsiBasic
from src.futures.strategies.futures.rsi_extended import RsiExtended
from src.futures.strategies.futures.rsi_special import RsiSpecial
from src.strategies.hp_manager import HpStrategy

from tests.data.sample_dataframes import raw_data_generate
from tests.spot import get_new_orders

logger = logging.getLogger("conftest")

DB_CONFIG_FILE = "config/.db_config"
config = Config(RepositoryEnv(DB_CONFIG_FILE))

logger.info("DB CONFIG: %s", config)


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
                "symbol": "BTCUSDC",
                "filters": [{"filterType": "MIN_NOTIONAL", "minNotional": "10.0"}],
            },
            {
                "symbol": "ETHUSDT",
                "filters": [{"filterType": "MIN_NOTIONAL", "minNotional": "5.0"}],
            },
            {
                "symbol": "AXLUSDT",
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
def strategy_executor_fixture(test_db: Database, mock_AsyncClient):
    """
    Fixture to create and run a StrategyExecutor instance.

    - Starts the executor loop in a separate thread.
    - Mocks necessary dependencies.
    - Provides an initialized instance for testing.
    """

    # Mock dependencies
    mock_broker = MagicMock(spec=BrokerSpot)
    ui_queue: queue.Queue = queue.Queue()
    balances = {"USDC": 10000.0}  # Mock balance
    symbols_info = {
        "BTCUSDC": SymbolInfo(symbol="BTCUSDC", precision=5, price_precision=2),
        "BTCUSDT": SymbolInfo(symbol="BTCUSDC", precision=5, price_precision=2),
        "AXLUSDT": SymbolInfo(symbol="AXLUSDT", precision=5, price_precision=4),
        "AXLBTC": SymbolInfo(symbol="AXLBTC", precision=5, price_precision=8),
        "BTCPLN": SymbolInfo(symbol="BTCPLN", precision=5, price_precision=2),
    }

    # Create the StrategyExecutor instance
    price_resolver = UsdPriceResolver(
        client=mock_AsyncClient, symbols_info=symbols_info
    )
    price_resolver.latest_prices["BTCPLN"] = 320000.0
    price_resolver.latest_prices["BTCUSDC"] = 100000.0

    executor = StrategyExecutor(
        db=test_db,
        broker=mock_broker,
        ui_queue=ui_queue,
        symbols_info=symbols_info,
        balances=balances,
        test_mode=True,
        price_resolver=price_resolver,
    )
    executor.client = mock_AsyncClient

    yield executor  # Provide the instance for the test

    # Cleanup: Ensure proper shutdown after the test
    executor.stop()
    for handler in logging.root.handlers[:]:
        handler.close()
        logging.root.removeHandler(handler)


@pytest.fixture
async def frontend_backend_setup(
    hp_gui: HpFront, strategy_executor_fixture: StrategyExecutor
):
    """
    Fixture to set up an integrated frontend-backend system.

    - Ensures frontend (HpManager) can send commands to backend (StrategyExecutor).
    - Provides a test scenario where state updates and order handling can be asserted.
    """

    # Ensure frontend has the correct reference to the backend's queue
    hp_gui.config_queue = strategy_executor_fixture.config_queue
    strategy_executor_fixture.ui_queue = hp_gui.ui_queue
    hp_gui.symbols_info = strategy_executor_fixture.symbols_info
    yield hp_gui, strategy_executor_fixture  # Provide both components

    for strategy in strategy_executor_fixture.strategies.values():
        strategy.stop_event.set()
        await wait_for_condition(condition_func=lambda: not strategy.worker_active)

    # Cleanup is handled in individual fixtures (strategy_executor_fixture, hp_gui)


@pytest.fixture
async def test_db():
    """Drop the test database, recreate it, and set up tables before running tests."""

    # Suppress specific warnings related to database operations
    warnings.filterwarnings(
        "ignore", message="Can't create database 'e2e_test'; database exists"
    )
    warnings.filterwarnings("ignore", message="Table 'strategies' already exists")
    warnings.filterwarnings("ignore", message="Table 'buy_price_levels' already exists")
    warnings.filterwarnings(
        "ignore", message="Table 'sell_price_levels' already exists"
    )
    warnings.filterwarnings("ignore", message="Table 'hp_list' already exists")
    warnings.filterwarnings("ignore", message="Table 'orders' already exists")

    db = Database(
        host=config("DB_HOST"),
        port=int(config("DB_PORT")),
        user=config("DB_USER"),
        password=config("DB_PASSWORD"),
        name=config("DB_TEST_NAME"),
    )
    await db.initialize()

    logger.info("Dropping and recreating the test database: %s", config("DB_TEST_NAME"))

    # Drop the existing test database
    db.drop_database()

    # Recreate and set up the database from scratch
    db.create_database_if_not_exists()
    db.create_pool()
    db.setup_tables()

    yield db  # Provide the database instance for the test

    db.stop_worker()


@pytest.fixture
def trading_system_factory(mock_AsyncClient):
    def create_trading_system(
        hp_config: HPBuyConfig, balance: float = 10000
    ) -> HpStrategy:
        ui_queue: queue.Queue = queue.Queue()
        test_database = MagicMock()
        strategy = HpStrategy(
            client=mock_AsyncClient,
            balance=balance,
            config_queue=MagicMock(),
            ui_queue=ui_queue,
            db=test_database,
            worker_queue=queue.Queue(),
            buy_position=HPPositionBuy(
                client=mock_AsyncClient,
                db=test_database,
                data=HPBuyData(config=hp_config, state_info=StateInfo()),
            ),
            sell_position=HPPositionSell(
                sell_strategy=[],
                price_resolver=UsdPriceResolver(
                    client=mock_AsyncClient, symbols_info={}
                ),
                client=mock_AsyncClient,
                db=test_database,
                original_position=SellPosition(
                    config=HPSellConfig(symbol_info=SymbolInfo()),
                    state_info=StateInfo(side=PositionSide.SHORT),
                    sell_order=Order(quantity=0.0),
                ),
            ),
        )
        hp_config.hp_id = generate_hp_id(hp_list=[])
        strategy.buy.prepare_orders()
        strategy.client.create_order.side_effect = get_new_orders(strategy.buy.orders)
        hp_gui_data_buy = HPGuiDataBuy(
            data=HPBuyData(config=hp_config, state_info=strategy.buy.data.state_info),
            hp_update=HPUpdate(
                hp_id=hp_config.hp_id,
                coin=hp_config.coin,
                symbol_info=hp_config.symbol_info,
                state=State.NEW,
                buy_price=hp_config.price_high,
            ),
        )
        logger.debug("Going to send hpguidatabuy to ui queue: %s", hp_gui_data_buy)
        ui_queue.put_nowait(hp_gui_data_buy)

        return strategy

    return create_trading_system


@pytest.fixture
async def hp_gui(mock_AsyncClient) -> AsyncGenerator:
    with patch("kivy.base.EventLoop.ensure_window"):
        # Set up a mock HpManager instance
        mock_config_queue = MagicMock()
        symbols_info = {
            "BTCUSDT": SymbolInfo(symbol="BTCUSDT", precision=5, price_precision=2),
            "BTCUSDC": SymbolInfo(symbol="BTCUSDC", precision=5, price_precision=2),
        }

        # Create the StrategyExecutor instance
        price_resolver = UsdPriceResolver(
            client=mock_AsyncClient, symbols_info=symbols_info
        )
        price_resolver.latest_prices["BTCPLN"] = 320000.0
        price_resolver.latest_prices["BTCUSDC"] = 100000.0
        gui = HpFront(
            client=mock_AsyncClient,
            strategy_id="test_strategy",
            config_queue=mock_config_queue,
            db=MagicMock(),
            ui_queue=queue.Queue(),
            symbols_info=symbols_info,
            test_mode=True,
            price_resolver=price_resolver,
        )

        gui.initialize()

        yield gui

        for handler in logging.root.handlers[:]:
            handler.close()
            logging.root.removeHandler(handler)

        gui.stop_event.set()
        await wait_for_condition(condition_func=lambda: gui.ui_queue_closed)


@pytest.fixture
async def base(mock_AsyncClient):
    config = ConfigFutures(
        symbol="BTCUSDT",
        name="RE_BTCUSDT",
        number_of_orders=4,
        budget=400,
    )
    df_handler = DfHandlerFutures(client=mock_AsyncClient, config=config)

    df_handler.raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df_handler.df = df_handler.insert_to_pandas()

    strategy = BaseFuturesStrategy(
        client=mock_AsyncClient,
        balance=1000,
        df_handler=df_handler,
        config=config,
        gui_handler=GuiHandlerFutures(
            main_ui_queue=asyncio.Queue(), ui_queue=asyncio.Queue()
        ),
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
    df_handler = DfHandlerFutures(client=mock_AsyncClient, config=config)
    df_handler.raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df_handler.df = df_handler.insert_to_pandas()
    df_handler.df = df_handler.rsi_indicator_apply(df=df_handler.df)

    strategy = RsiBasic(
        client=mock_AsyncClient,
        balance=1000,
        df_handler=df_handler,
        gui_handler=GuiHandlerFutures(
            main_ui_queue=asyncio.Queue(), ui_queue=asyncio.Queue()
        ),
        config=config,
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
    df_handler = DfHandlerFutures(client=mock_AsyncClient, config=config)
    df_handler.raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df_handler.df = df_handler.insert_to_pandas()
    df_handler.df = df_handler.rsi_indicator_apply(df=df_handler.df)

    strategy = RsiExtended(
        client=mock_AsyncClient,
        balance=1000,
        df_handler=df_handler,
        gui_handler=GuiHandlerFutures(
            main_ui_queue=asyncio.Queue(), ui_queue=asyncio.Queue()
        ),
        config=config,
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
    df_handler = DfHandlerFutures(client=mock_AsyncClient, config=config)
    df_handler.raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df_handler.df = df_handler.insert_to_pandas()
    df_handler.df = df_handler.rsi_indicator_apply(df=df_handler.df)

    strategy = RsiSpecial(
        client=mock_AsyncClient,
        balance=1000,
        df_handler=df_handler,
        gui_handler=GuiHandlerFutures(
            main_ui_queue=asyncio.Queue(), ui_queue=asyncio.Queue()
        ),
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
