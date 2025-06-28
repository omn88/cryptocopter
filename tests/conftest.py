import os

os.environ["KIVY_NO_CONSOLELOG"] = "1"

# Suppress aiosqlite debug logging in tests
import logging

logging.getLogger("aiosqlite").setLevel(logging.WARNING)

from src.gui.hpfront import HpFront
from src.broker import BrokerSpot
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.position_buy import HPPositionBuy
from src.position_sell import HPPositionSell
from src.strategy_executor import StrategyExecutor
from src.database.recovery_service import RecoveryService
from tests.strategies.spot.hp_manager_helpers import wait_for_condition

# Use dummy window for Kivy in headless testing
os.environ["KIVY_WINDOW"] = "dummy"
import asyncio
import logging
import queue
import tempfile
import warnings
import pytest
from typing import AsyncGenerator, Dict
from unittest.mock import AsyncMock, MagicMock
from unittest.mock import patch
from pytest_mock import MockerFixture
from decouple import Config, RepositoryEnv
from src.common.common import generate_hp_id
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import HPGuiDataBuy, HPUpdate
from src.database.trading_database import TradingDatabase
from src.identifiers import (
    HPBuyConfig,
    HPBuyData,
    HPSellConfig,
    HPSellData,
    Order,
    PositionSide,
    SellPosition,
    State,
    StateInfo,
)
from src.strategies.hp_manager import HpStrategy
from tests.spot import get_new_orders

logger = logging.getLogger("conftest")

DB_CONFIG_FILE = "config/.db_config"
config = Config(RepositoryEnv(DB_CONFIG_FILE))

logger.info("DB CONFIG: %s", config)


@pytest.fixture
def mock_async_client(mocker: MockerFixture) -> AsyncMock:
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
def strategy_executor_fixture(test_db: TradingDatabase, mock_async_client):
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
        "BTCUSDT": SymbolInfo(symbol="BTCUSDT", precision=5, price_precision=2),
        "ETHUSDT": SymbolInfo(symbol="ETHUSDT", precision=5, price_precision=2),
        "AXLUSDT": SymbolInfo(symbol="AXLUSDT", precision=5, price_precision=4),
        "AXLBTC": SymbolInfo(symbol="AXLBTC", precision=5, price_precision=8),
        "BTCPLN": SymbolInfo(symbol="BTCPLN", precision=5, price_precision=2),
    }
    # Create the StrategyExecutor instance
    price_resolver = UsdPriceResolver(
        client=mock_async_client, symbols_info=symbols_info
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
    executor.client = mock_async_client

    yield executor  # Provide the instance for the test

    # Cleanup: Ensure proper shutdown after the test
    executor.stop()
    for handler in logging.root.handlers[:]:
        handler.close()
        logging.root.removeHandler(handler)


@pytest.fixture
async def test_db() -> AsyncGenerator[TradingDatabase, None]:
    """Create a test SQLite database for testing."""  # Create a temporary SQLite database file for testing
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        test_db_path = tmp_file.name

    # Create the new TradingDatabase instance
    db = TradingDatabase(db_path=test_db_path)

    logger.info("Created test database: %s", test_db_path)

    yield db  # Provide the database instance for the test

    # Cleanup: close database and remove file
    await db.close()
    try:
        os.unlink(test_db_path)
    except OSError:
        pass  # File might already be deleted


@pytest.fixture
async def hp_gui(mock_async_client) -> AsyncGenerator:
    with patch("kivy.base.EventLoop.ensure_window"):
        # Set up a mock HpManager instance
        mock_config_queue = MagicMock()
        symbols_info = {
            "BTCUSDT": SymbolInfo(symbol="BTCUSDT", precision=5, price_precision=2),
            "BTCUSDC": SymbolInfo(symbol="BTCUSDC", precision=5, price_precision=2),
        }  # Create the StrategyExecutor instance
        price_resolver = UsdPriceResolver(
            client=mock_async_client, symbols_info=symbols_info
        )
        price_resolver.latest_prices["BTCPLN"] = 320000.0
        price_resolver.latest_prices["BTCUSDC"] = 100000.0
        gui = HpFront(
            client=mock_async_client,
            strategy_id="test_strategy",
            config_queue=mock_config_queue,
            db=AsyncMock(),
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
    hp_gui.db = strategy_executor_fixture.db
    hp_gui.symbols_info = strategy_executor_fixture.symbols_info
    yield hp_gui, strategy_executor_fixture  # Provide both components

    for strategy in strategy_executor_fixture.strategies.values():
        strategy.stop_event.set()
        await wait_for_condition(condition_func=lambda: not strategy.worker_active)

    # Cleanup is handled in individual fixtures (strategy_executor_fixture, hp_gui)


@pytest.fixture
def recovery_service(test_db, mock_async_client):
    """Create recovery service using the test database."""
    # Create mock symbols_info
    symbols_info = {
        "BTCUSDT": SymbolInfo(symbol="BTCUSDT"),
        "ETHUSDT": SymbolInfo(symbol="ETHUSDT"),
        "ADAUSDT": SymbolInfo(symbol="ADAUSDT"),
        "DOTUSDT": SymbolInfo(symbol="DOTUSDT"),
        "SOLUSDT": SymbolInfo(symbol="SOLUSDT"),
        "AVAXUSDT": SymbolInfo(symbol="AVAXUSDT"),
        "LINKUSDT": SymbolInfo(symbol="LINKUSDT"),
        "UNIUSDT": SymbolInfo(symbol="UNIUSDT"),
        "MATICUSDT": SymbolInfo(symbol="MATICUSDT"),
        "ATOMUSDT": SymbolInfo(symbol="ATOMUSDT"),
        "FTMUSDT": SymbolInfo(symbol="FTMUSDT"),
        "NEARUSDT": SymbolInfo(symbol="NEARUSDT"),
        "BTCETH": SymbolInfo(symbol="BTCETH"),
        "ETHBNB": SymbolInfo(symbol="ETHBNB"),
        "BNBUSDT": SymbolInfo(symbol="BNBUSDT"),
        "SANDUSDT": SymbolInfo(symbol="SANDUSDT"),
        "MANAUSDT": SymbolInfo(symbol="MANAUSDT"),
        "APEUSDT": SymbolInfo(symbol="APEUSDT"),
        "GMTUSDT": SymbolInfo(symbol="GMTUSDT"),
    }

    return RecoveryService(test_db, mock_async_client, symbols_info)


@pytest.fixture
def trading_system_factory(mock_async_client, test_db, strategy_executor_fixture):
    """Factory fixture to create HpStrategy instances for testing."""

    def _create_strategy(hp_config: HPBuyConfig) -> HpStrategy:
        """Create an HpStrategy with the given config."""
        from src.strategies.hp_manager import HpStrategy

        # Generate HP ID from existing strategies (empty list for tests)
        hp_id = generate_hp_id(hp_list=[])

        # Create buy data with the generated ID and config
        buy_data = HPBuyData(
            config=HPBuyConfig(
                hp_id=hp_id,
                symbol_info=hp_config.symbol_info,
                coin=hp_config.coin,
                price_low=hp_config.price_low,
                price_high=hp_config.price_high,
                order_trigger=hp_config.order_trigger,
                budget=hp_config.budget,
                mode=hp_config.mode,
            ),
            state_info=StateInfo(side=PositionSide.LONG),
        )

        # Create worker queue
        worker_queue: queue.Queue = queue.Queue()

        # Create buy position
        buy_position = HPPositionBuy(
            client=mock_async_client,
            data=buy_data,
            db=test_db,
        )

        # Create sell position
        sell_position = HPPositionSell(
            client=mock_async_client,
            original_position=SellPosition(
                config=HPSellConfig(
                    hp_id=hp_id,
                    symbol_info=hp_config.symbol_info,
                    coin=hp_config.coin,
                ),
                state_info=StateInfo(side=PositionSide.SHORT),
                sell_order=Order(quantity=0.0),
            ),
            sell_strategy=[],
            db=test_db,
            price_resolver=strategy_executor_fixture.price_resolver,
            broker=strategy_executor_fixture.broker,
            worker_queue=worker_queue,
        )  # Create strategy with balance higher than budget to allow trading
        strategy = HpStrategy(
            client=mock_async_client,
            balance=10000.0,  # Set balance higher than budget (1000.0) to allow trading
            ui_queue=queue.Queue(),
            worker_queue=worker_queue,
            config_queue=queue.Queue(),
            db=test_db,
            buy_position=buy_position,
            sell_position=sell_position,
            initial_state=State.NEW,
        )

        # Prepare orders first (this is needed for proper hp_id resolution)
        strategy.buy.prepare_orders()

        # Send initial UI message using the strategy's method
        strategy.send_buy_position_to_ui()

        return strategy

    return _create_strategy
