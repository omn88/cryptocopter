from decimal import Decimal
import os

# Import kivy configuration first (must be before any Kivy imports)
import sys

from src.strategies.buy_dip.broker_adapter import BuyDipBrokerAdapter
from src.strategies.buy_dip.config import BuyDipConfig
from src.strategies.buy_dip.strategy import BuyDipStrategy
from tests.strategies.buy_dip.buy_dip_simulator import BuyDipSimulator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kivy_config

# Suppress aiosqlite debug logging in tests
import logging

logging.getLogger("aiosqlite").setLevel(logging.WARNING)

from src.gui.hp_manager.hpfront import HpFront
from src.broker import BrokerSpot
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.strategies.hp_manager.position_buy import HPPositionBuy
from src.strategies.hp_manager.position_sell import HPPositionSell
from src.strategy_executor import StrategyExecutor
from src.recovery import RecoveryService
from tests.strategies.hp.hp_simulator import wait_for_condition

import asyncio
import logging
import queue
import tempfile
import time
import pytest
from typing import AsyncGenerator, Dict
from unittest.mock import AsyncMock, MagicMock
from unittest.mock import patch
from pytest_mock import MockerFixture
from decouple import Config, RepositoryEnv
from src.common.helpers import generate_hp_id
from src.common.symbol import Symbol
from src.database.trading_database import Database
from src.common.identifiers import (
    HPBuyConfig,
    HPBuy,
    HPSellConfig,
    Order,
    PositionSide,
    SellPosition,
    State,
    StateInfo,
    InventoryItem,
)
from src.strategies.hp_manager.hp_manager import HpStrategy
from src.portfolio.portfolio_gui import PortfolioUI
from src.portfolio.portfolio_event_helper import PortfolioEventHelper

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
def strategy_executor_fixture(test_db: Database, mock_async_client, mock_inventory):
    """
    Fixture to create and run a StrategyExecutor instance.

    - Starts the executor loop in a separate thread.
    - Mocks necessary dependencies.
    - Provides an initialized instance for testing.
    """

    # Mock dependencies
    mock_broker = MagicMock(spec=BrokerSpot)
    ui_queue: queue.Queue = queue.Queue()
    symbols = {
        "BTCUSDC": Symbol(name="BTCUSDC", precision=5, price_precision=2),
        "BTCUSDT": Symbol(name="BTCUSDT", precision=5, price_precision=2),
        "ETHUSDT": Symbol(name="ETHUSDT", precision=5, price_precision=2),
        "AXLUSDT": Symbol(name="AXLUSDT", precision=5, price_precision=4),
        "AXLBTC": Symbol(name="AXLBTC", precision=5, price_precision=8),
        "BTCPLN": Symbol(name="BTCPLN", precision=5, price_precision=2),
        "DYMUSDT": Symbol(name="DYMUSDT", precision=5, price_precision=4),
    }
    # Create the StrategyExecutor instance
    price_resolver = UsdPriceResolver(client=mock_async_client, symbols=symbols)
    price_resolver.latest_prices["BTCPLN"] = 320000.0
    price_resolver.latest_prices["BTCUSDC"] = 100000.0

    executor = StrategyExecutor(
        db=test_db,
        broker=mock_broker,
        ui_queue=ui_queue,
        inventory=mock_inventory,
        test_mode=True,
        price_resolver=price_resolver,
        portfolio_ui_queue=queue.Queue(),
    )
    # Set the mock client directly on the executor for testing
    executor.client = mock_async_client

    yield executor  # Provide the instance for the test

    # Cleanup: Ensure proper shutdown after the test
    executor.stop()
    for handler in logging.root.handlers[:]:
        handler.close()
        logging.root.removeHandler(handler)


@pytest.fixture
async def test_db() -> AsyncGenerator[Database, None]:
    """Create a test SQLite database for testing."""  # Create a temporary SQLite database file for testing
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        test_db_path = tmp_file.name

    # Create the new Database instance
    db = Database(db_path=test_db_path)

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
        symbols = {
            "BTCUSDT": Symbol(name="BTCUSDT", precision=5, price_precision=2),
            "BTCUSDC": Symbol(name="BTCUSDC", precision=5, price_precision=2),
        }  # Create the StrategyExecutor instance
        price_resolver = UsdPriceResolver(client=mock_async_client, symbols=symbols)
        price_resolver.latest_prices["BTCPLN"] = 320000.0
        price_resolver.latest_prices["BTCUSDC"] = 100000.0

        gui = HpFront(
            client=mock_async_client,
            config_queue=mock_config_queue,
            db=AsyncMock(),
            ui_queue=queue.Queue(),
            test_mode=True,
            price_resolver=price_resolver,
            portfolio_queue=queue.Queue(),  # Use a mock queue for portfolio updates
        )

        gui.initialize()

        yield gui

        # Cancel tasks first, then wait for cleanup
        if (
            hasattr(gui, "refresh_task")
            and gui.refresh_task
            and not gui.refresh_task.done()
        ):
            gui.refresh_task.cancel()
        if hasattr(gui, "queue_task") and gui.queue_task and not gui.queue_task.done():
            gui.queue_task.cancel()

        gui.stop_event.set()

        # Wait for tasks to be cancelled
        tasks_to_wait = []
        if hasattr(gui, "refresh_task") and gui.refresh_task:
            tasks_to_wait.append(gui.refresh_task)
        if hasattr(gui, "queue_task") and gui.queue_task:
            tasks_to_wait.append(gui.queue_task)

        if tasks_to_wait:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks_to_wait, return_exceptions=True), timeout=2.0
                )
            except asyncio.TimeoutError:
                logger.warning("Some GUI tasks didn't complete within timeout")

        # Clean up logging handlers
        for handler in logging.root.handlers[:]:
            handler.close()
            logging.root.removeHandler(handler)


@pytest.fixture
def mock_broker():
    """Create a mock broker instance for WebSocket architecture testing"""
    with patch("src.common.identifiers.BinanceClient"):
        # Patch the thread.start() to prevent background thread from starting
        with patch("threading.Thread.start"):
            broker = BrokerSpot()
            # Manually set loop without starting the thread
            broker.loop = asyncio.new_event_loop()
            yield broker
            # Graceful teardown - cancel tasks if they were created
            try:
                if (
                    hasattr(broker, "_ticker_timeout_task")
                    and broker._ticker_timeout_task
                    and not broker._ticker_timeout_task.done()
                ):
                    broker._ticker_timeout_task.cancel()
                if (
                    hasattr(broker, "_connection_health_task")
                    and broker._connection_health_task
                    and not broker._connection_health_task.done()
                ):
                    broker._connection_health_task.cancel()
                if broker.loop and not broker.loop.is_closed():
                    broker.loop.close()
            except Exception:
                pass  # Ignore teardown errors


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
    hp_gui.price_resolver.symbols = strategy_executor_fixture.price_resolver.symbols

    # Debug: Verify queue objects are the same
    logger.info(
        f"[FIXTURE DEBUG] Backend UI queue id: {id(strategy_executor_fixture.ui_queue)}"
    )
    logger.info(f"[FIXTURE DEBUG] Frontend UI queue id: {id(hp_gui.ui_queue)}")
    logger.info(
        f"[FIXTURE DEBUG] Queue objects same: {strategy_executor_fixture.ui_queue is hp_gui.ui_queue}"
    )

    yield hp_gui, strategy_executor_fixture  # Provide both components

    for strategy in strategy_executor_fixture.strategies.values():
        strategy.stop_event.set()
        await wait_for_condition(condition_func=lambda: not strategy.worker_active)

    # Cleanup is handled in individual fixtures (strategy_executor_fixture, hp_gui)


@pytest.fixture
async def crash_recovery_factory(test_db: Database, mock_async_client, mock_inventory):
    """
    Factory fixture for crash recovery testing.

    Returns a factory function that can create frontend-backend pairs on demand.
    This allows tests to:
    1. Create original setup
    2. Run operations and save state
    3. Simulate crash
    4. Create recovery setup with same database
    5. Verify recovery
    """

    created_instances = []  # Track all created instances for cleanup

    def create_frontend_backend_pair(instance_name=""):
        """Create a new frontend-backend pair"""
        ui_queue = queue.Queue()
        config_queue = queue.Queue()

        symbols = {
            "BTCUSDC": Symbol(
                name="BTCUSDC",
                min_notional=10.0,
                lot_size=0.00001,
                min_qty=0.00001,
                max_qty=9000.0,
                price_filter=0.01,
                precision=5,
                price_precision=2,
            ),
            "BTCUSDT": Symbol(name="BTCUSDT", precision=5, price_precision=2),
            "ETHUSDT": Symbol(name="ETHUSDT", precision=5, price_precision=2),
            "AXLUSDT": Symbol(name="AXLUSDT", precision=5, price_precision=4),
            "AXLBTC": Symbol(name="AXLBTC", precision=5, price_precision=8),
            "BTCPLN": Symbol(name="BTCPLN", precision=5, price_precision=2),
            "DYMUSDT": Symbol(name="DYMUSDT", precision=5, price_precision=4),
        }

        price_resolver = UsdPriceResolver(client=mock_async_client, symbols=symbols)
        price_resolver.latest_prices["BTCPLN"] = 320000.0
        price_resolver.latest_prices["BTCUSDC"] = 100000.0

        # Create backend
        mock_broker = MagicMock(spec=BrokerSpot)
        logger.info("Creating StrategyExecutor in test mode")
        backend = StrategyExecutor(
            db=test_db,  # Always use the same database
            broker=mock_broker,
            ui_queue=ui_queue,
            inventory=mock_inventory,
            price_resolver=price_resolver,
            test_mode=True,
        )
        logger.info("StrategyExecutor created, assigning mock client")
        backend.client = mock_async_client
        logger.info("Mock client assigned to backend")

        # Create frontend with proper Kivy mocking
        with patch("kivy.base.EventLoop.ensure_window"):
            frontend = HpFront(
                client=mock_async_client,
                config_queue=config_queue,
                db=test_db,  # Always use the same database
                ui_queue=ui_queue,
                test_mode=True,
                price_resolver=price_resolver,
                portfolio_queue=queue.Queue(),  # Use a mock queue for portfolio updates
            )
            frontend.initialize()

        # Connect them
        frontend.config_queue = backend.config_queue
        backend.ui_queue = frontend.ui_queue
        frontend.db = backend.db

        # Track for cleanup
        created_instances.extend([frontend, backend])

        return frontend, backend

    async def simulate_crash(frontend, backend):
        """Simulate application crash by stopping all tasks without graceful shutdown"""
        # In a real crash, processes just terminate abruptly
        # We cannot set stop events as that would trigger graceful cleanup

        # Cancel strategy worker tasks directly without graceful shutdown
        for strategy in backend.strategies.values():
            # Forcefully mark as inactive without graceful stop
            if hasattr(strategy, "worker_active"):
                strategy.worker_active = False
            # Cancel the worker task abruptly
            if (
                hasattr(strategy, "worker_task")
                and strategy.worker_task
                and not strategy.worker_task.done()
            ):
                strategy.worker_task.cancel()

        # Cancel frontend tasks - these belong to the current event loop
        tasks_to_cancel = []
        if (
            hasattr(frontend, "queue_task")
            and frontend.queue_task
            and not frontend.queue_task.done()
        ):
            try:
                frontend.queue_task.cancel()
                tasks_to_cancel.append(frontend.queue_task)
            except Exception as e:
                logger.warning("Failed to cancel queue_task: %s", e)

        if (
            hasattr(frontend, "refresh_task")
            and frontend.refresh_task
            and not frontend.refresh_task.done()
        ):
            try:
                frontend.refresh_task.cancel()
                tasks_to_cancel.append(frontend.refresh_task)
            except Exception as e:
                logger.warning("Failed to cancel refresh_task: %s", e)

        # Wait for cancelled tasks to finish with short timeout
        if tasks_to_cancel:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks_to_cancel, return_exceptions=True),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Some tasks didn't complete within timeout during crash simulation"
                )
            except Exception as e:
                logger.warning("Error during task cancellation: %s", e)

        # For the backend thread, we need a different approach
        # In a real crash, the process would just die, but here we need to simulate that
        # The database state should remain intact (no graceful cleanup)
        logger.info(
            "Simulated crash completed - tasks cancelled, database state preserved"
        )

    # Return factory functions
    yield create_frontend_backend_pair, simulate_crash

    # Cleanup all created instances - need to properly cancel frontend tasks
    for i in range(0, len(created_instances), 2):
        if i + 1 < len(created_instances):
            frontend, backend = created_instances[i], created_instances[i + 1]

            # Cancel frontend tasks first
            if (
                hasattr(frontend, "refresh_task")
                and frontend.refresh_task
                and not frontend.refresh_task.done()
            ):
                frontend.refresh_task.cancel()
            if (
                hasattr(frontend, "queue_task")
                and frontend.queue_task
                and not frontend.queue_task.done()
            ):
                frontend.queue_task.cancel()

            # Set stop events
            frontend.stop_event.set()
            backend.stop_event.set()

            # Wait for frontend tasks to be cancelled
            frontend_tasks = []
            if hasattr(frontend, "refresh_task") and frontend.refresh_task:
                frontend_tasks.append(frontend.refresh_task)
            if hasattr(frontend, "queue_task") and frontend.queue_task:
                frontend_tasks.append(frontend.queue_task)

            if frontend_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*frontend_tasks, return_exceptions=True),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "Frontend tasks didn't complete within timeout during cleanup"
                    )

            # Cancel strategy worker tasks
            for strategy in backend.strategies.values():
                strategy.stop_event.set()
                if (
                    hasattr(strategy, "worker_task")
                    and strategy.worker_task
                    and not strategy.worker_task.done()
                ):
                    strategy.worker_task.cancel()

            # Stop backend thread
            if hasattr(backend, "thread") and backend.thread.is_alive():
                backend.thread.join(timeout=1.0)

    logger.info("Cleaned up all created frontend/backend instances.")


@pytest.fixture
def recovery_service(test_db, mock_async_client):
    """Create recovery service using the test database."""
    # Create mock symbols
    symbols = {
        "BTCUSDT": Symbol(name="BTCUSDT"),
        "ETHUSDT": Symbol(name="ETHUSDT"),
        "ADAUSDT": Symbol(name="ADAUSDT"),
        "DOTUSDT": Symbol(name="DOTUSDT"),
        "SOLUSDT": Symbol(name="SOLUSDT"),
        "AVAXUSDT": Symbol(name="AVAXUSDT"),
        "LINKUSDT": Symbol(name="LINKUSDT"),
        "UNIUSDT": Symbol(name="UNIUSDT"),
        "MATICUSDT": Symbol(name="MATICUSDT"),
        "ATOMUSDT": Symbol(name="ATOMUSDT"),
        "FTMUSDT": Symbol(name="FTMUSDT"),
        "NEARUSDT": Symbol(name="NEARUSDT"),
        "BTCETH": Symbol(name="BTCETH"),
        "ETHBNB": Symbol(name="ETHBNB"),
        "BNBUSDT": Symbol(name="BNBUSDT"),
        "SANDUSDT": Symbol(name="SANDUSDT"),
        "MANAUSDT": Symbol(name="MANAUSDT"),
        "APEUSDT": Symbol(name="APEUSDT"),
        "GMTUSDT": Symbol(name="GMTUSDT"),
    }

    return RecoveryService(test_db, mock_async_client, symbols)


@pytest.fixture
def trading_system_factory(mock_async_client, test_db, strategy_executor_fixture):
    """Factory fixture to create HpStrategy instances for testing."""

    created_strategies = []  # Track created strategies for cleanup

    def _create_strategy(hp_config: HPBuyConfig) -> HpStrategy:
        """Create an HpStrategy with the given config."""

        # Generate HP ID from existing strategies (empty list for tests)
        hp_id = generate_hp_id(hp_list=[])

        # Create buy data with the generated ID and config
        buy_data = HPBuy(
            config=HPBuyConfig(
                hp_id=hp_id,
                symbol=hp_config.symbol,
                coin=hp_config.coin,
                buy_price=hp_config.buy_price,
                order_trigger=hp_config.order_trigger,
                budget=hp_config.budget,
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
                    symbol=hp_config.symbol,
                    coin=hp_config.coin,
                ),
                state_info=StateInfo(side=PositionSide.SHORT),
                sell_order=Order(quantity=0.0),
            ),
            sell_strategy=None,
            db=test_db,
            price_resolver=strategy_executor_fixture.price_resolver,
            broker=strategy_executor_fixture.broker,
            worker_queue=worker_queue,
        )

        # Create temporary portfolio event helper (will be updated after strategy creation)
        portfolio_ui_queue: queue.Queue = queue.Queue()
        portfolio_event_helper = PortfolioEventHelper(None)

        # Create strategy with balance higher than budget to allow trading
        strategy = HpStrategy(
            client=mock_async_client,
            balance=10000.0,  # Set balance higher than budget (1000.0) to allow trading
            ui_queue=queue.Queue(),
            portfolio_ui_queue=portfolio_ui_queue,
            worker_queue=worker_queue,
            config_queue=queue.Queue(),
            db=test_db,
            buy_position=buy_position,
            sell_position=sell_position,
            portfolio_event_helper=portfolio_event_helper,
            initial_state=State.NEW,
        )

        # Update portfolio event helper with the strategy's callback
        portfolio_event_helper._callback = strategy.send_hp_event_to_portfolio

        # Prepare orders first (this is needed for proper hp_id resolution)
        strategy.buy.prepare_order()

        # Send initial UI message using the strategy's method
        strategy.send_buy_position_to_ui()

        # Track created strategy for cleanup
        created_strategies.append(strategy)

        return strategy

    yield _create_strategy

    # Cleanup: Stop all created strategies
    for strategy in created_strategies:
        if hasattr(strategy, "stop_event"):
            strategy.stop_event.set()
        if (
            hasattr(strategy, "worker_task")
            and strategy.worker_task
            and not strategy.worker_task.done()
        ):
            strategy.worker_task.cancel()


@pytest.fixture
def mock_inventory():
    """
    Mock inventory for testing with proper parent-child lot structure.

    Each coin has multiple lots (children) to properly test:
    - FIFO locking/unlocking behavior
    - Portfolio GUI parent-child display
    - Inventory management across lots
    - Crash recovery with multiple lots

    Structure: 15 total lots across 5 coins (3 lots per coin)
    """
    return [
        # BTC: 3 lots with different buy prices for FIFO testing
        InventoryItem(
            id="btc_lot1",
            coin="BTC",
            buy_price=45000.0,  # Lowest price - should be locked first
            quantity=0.3,
            available_quantity=0.3,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time() - 86400,  # 1 day ago
            notes="BTC Lot 1 - Early purchase",
        ),
        InventoryItem(
            id="btc_lot2",
            coin="BTC",
            buy_price=50000.0,  # Middle price
            quantity=0.4,
            available_quantity=0.4,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time() - 43200,  # 12 hours ago
            notes="BTC Lot 2 - Mid purchase",
        ),
        InventoryItem(
            id="btc_lot3",
            coin="BTC",
            buy_price=55000.0,  # Highest price - should be locked last
            quantity=0.3,
            available_quantity=0.3,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time(),  # Recent purchase
            notes="BTC Lot 3 - Recent purchase",
        ),
        # ETH: 3 lots with different buy prices
        InventoryItem(
            id="eth_lot1",
            coin="ETH",
            buy_price=2800.0,  # Lowest ETH price
            quantity=2.0,
            available_quantity=2.0,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time() - 86400,
            notes="ETH Lot 1 - Early purchase",
        ),
        InventoryItem(
            id="eth_lot2",
            coin="ETH",
            buy_price=3200.0,  # Middle ETH price
            quantity=2.5,
            available_quantity=2.5,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time() - 43200,
            notes="ETH Lot 2 - Mid purchase",
        ),
        InventoryItem(
            id="eth_lot3",
            coin="ETH",
            buy_price=3600.0,  # Highest ETH price
            quantity=0.5,
            available_quantity=0.5,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time(),
            notes="ETH Lot 3 - Recent purchase",
        ),
        # AXL: 3 lots for multihop testing
        InventoryItem(
            id="axl_lot1",
            coin="AXL",
            buy_price=0.6,  # Lowest AXL price
            quantity=500.0,
            available_quantity=500.0,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time() - 86400,
            notes="AXL Lot 1 - For multihop testing",
        ),
        InventoryItem(
            id="axl_lot2",
            coin="AXL",
            buy_price=0.8,  # Middle AXL price
            quantity=300.0,
            available_quantity=300.0,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time() - 43200,
            notes="AXL Lot 2 - For multihop testing",
        ),
        InventoryItem(
            id="axl_lot3",
            coin="AXL",
            buy_price=1.0,  # Highest AXL price
            quantity=200.0,
            available_quantity=200.0,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time(),
            notes="AXL Lot 3 - For multihop testing",
        ),
        # USDC: 3 lots (stable coin, same price)
        InventoryItem(
            id="usdc_lot1",
            coin="USDC",
            buy_price=1.0,
            quantity=400.0,
            available_quantity=400.0,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time() - 86400,
            notes="USDC Lot 1 - Stable coin",
        ),
        InventoryItem(
            id="usdc_lot2",
            coin="USDC",
            buy_price=1.0,
            quantity=400.0,
            available_quantity=400.0,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time() - 43200,
            notes="USDC Lot 2 - Stable coin",
        ),
        InventoryItem(
            id="usdc_lot3",
            coin="USDC",
            buy_price=1.0,
            quantity=200.0,
            available_quantity=200.0,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time(),
            notes="USDC Lot 3 - Stable coin",
        ),
        # DYM: 3 lots for convert testing
        InventoryItem(
            id="dym_lot1",
            coin="DYM",
            buy_price=1.0,  # Lowest DYM price
            quantity=100.0,
            available_quantity=100.0,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time() - 86400,
            notes="DYM Lot 1 - For convert testing",
        ),
        InventoryItem(
            id="dym_lot2",
            coin="DYM",
            buy_price=1.2,  # Middle DYM price
            quantity=75.0,
            available_quantity=75.0,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time() - 43200,
            notes="DYM Lot 2 - For convert testing",
        ),
        InventoryItem(
            id="dym_lot3",
            coin="DYM",
            buy_price=1.4,  # Highest DYM price
            quantity=25.0,
            available_quantity=25.0,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time(),
            notes="DYM Lot 3 - For convert testing",
        ),
    ]


@pytest.fixture
def portfolio_ui(test_db: Database, mock_async_client, mock_inventory):
    """Create portfolio UI for testing with test mode enabled."""
    ui_queue: queue.Queue = queue.Queue()

    # Use comprehensive symbols that includes USDC
    symbols = {
        "BTCUSDC": Symbol(name="BTCUSDC", precision=5, price_precision=2),
        "BTCUSDT": Symbol(name="BTCUSDT", precision=5, price_precision=2),
        "ETHUSDT": Symbol(name="ETHUSDT", precision=5, price_precision=2),
        "AXLUSDT": Symbol(name="AXLUSDT", precision=5, price_precision=4),
        "AXLBTC": Symbol(name="AXLBTC", precision=5, price_precision=8),
        "BTCPLN": Symbol(name="BTCPLN", precision=5, price_precision=2),
        "DYMUSDT": Symbol(name="DYMUSDT", precision=5, price_precision=4),
        "USDCUSDT": Symbol(
            name="USDCUSDT", precision=2, price_precision=4
        ),  # Add USDC symbol
    }

    price_resolver = UsdPriceResolver(client=mock_async_client, symbols=symbols)

    portfolio = PortfolioUI(
        ui_queue=ui_queue,
        strategy_config_queue=queue.Queue(),
        price_resolver=price_resolver,
        db=test_db,
        test_mode=True,  # Enable test mode to suppress UI refresh calls
    )

    # Set up the inventory directly from the mock_inventory fixture
    portfolio.set_inventory(mock_inventory)

    yield portfolio

    # Cleanup: Clear the queue and reset state
    while not ui_queue.empty():
        try:
            ui_queue.get_nowait()
        except queue.Empty:
            break


@pytest.fixture
async def portfolio_hp_backend_setup(
    hp_gui: HpFront,
    portfolio_ui: PortfolioUI,
    strategy_executor_fixture: StrategyExecutor,
):
    """
    Fixture for testing inventory-based sell flow that requires:
    1. Portfolio frontend (with inventory) - REAL PortfolioUI with inventory management
    2. HP manager frontend
    3. Strategy executor backend

    This enables testing the complete flow:
    inventory sell button → sell modal → HP creation → strategy execution → final state

    Note: Uses real PortfolioUI instead of mock for actual inventory locking/unlocking functionality
    """
    # Connect HP manager frontend to the strategy executor backend
    hp_gui.config_queue = strategy_executor_fixture.config_queue
    strategy_executor_fixture.ui_queue = hp_gui.ui_queue
    hp_gui.db = strategy_executor_fixture.db

    # Connect portfolio to strategy executor config queue (for sell button functionality)
    portfolio_ui.strategy_config_queue = strategy_executor_fixture.config_queue

    # CRITICAL: Connect strategy executor to real portfolio for HP event processing
    strategy_executor_fixture.portfolio_ui_queue = portfolio_ui.ui_queue

    # Note: hp_gui does NOT have a direct portfolio reference in real implementation
    # It only has portfolio_queue for communication

    yield portfolio_ui, hp_gui, strategy_executor_fixture

    if strategy_executor_fixture.strategies:
        strategy = strategy_executor_fixture.strategies["1000"]
        strategy.stop_event.set()
        await wait_for_condition(condition_func=lambda: not strategy.worker_active)


@pytest.fixture
async def portfolio_crash_recovery_factory(
    test_db: Database, mock_async_client, mock_inventory
):
    """
    Dedicated factory fixture for portfolio crash recovery testing.

    Based on portfolio_hp_backend_setup but designed specifically for crash recovery scenarios.
    Provides methods to create setups and simulate crashes for comprehensive testing.

    Usage Example:
        create_portfolio_hp_setup, simulate_crash = portfolio_crash_recovery_factory

        # Create original setup
        portfolio1, hp1, backend1 = create_portfolio_hp_setup("original")

        # Perform operations that modify database state
        await portfolio1.handle_hp_sell_created(sell_event)

        # Simulate crash
        await simulate_crash(portfolio1, hp1, backend1)  # All components
        # Or selective crash: await simulate_crash(portfolio1)  # Just portfolio

        # Create recovery setup (uses same database)
        portfolio2, hp2, backend2 = create_portfolio_hp_setup("recovered")

        # Verify state was preserved in database
        assert portfolio2.some_state == expected_value

    Returns:
        tuple: (create_portfolio_hp_setup, simulate_crash)
    """

    created_instances = []  # Track all created instances for cleanup

    def create_portfolio_hp_setup(instance_name=""):
        """
        Create a complete portfolio + HP + backend setup for crash recovery testing.

        Args:
            instance_name (str): Optional name suffix for the instance

        Returns:
            tuple: (portfolio_ui, hp_frontend, strategy_backend)

        This setup replicates portfolio_hp_backend_setup but allows multiple instances
        with the same database for crash recovery testing.
        """
        logger.info(f"Creating portfolio crash recovery setup: {instance_name}")

        # Create queues for communication
        ui_queue = queue.Queue()
        config_queue = queue.Queue()
        portfolio_ui_queue = queue.Queue()

        # Define symbols info
        symbols = {
            "BTCUSDC": Symbol(
                name="BTCUSDC",
                min_notional=10.0,
                lot_size=0.00001,
                min_qty=0.00001,
                max_qty=9000.0,
                price_filter=0.01,
                precision=5,
                price_precision=2,
            ),
            "BTCUSDT": Symbol(name="BTCUSDT", precision=5, price_precision=2),
            "ETHUSDT": Symbol(name="ETHUSDT", precision=5, price_precision=2),
            "AXLUSDT": Symbol(name="AXLUSDT", precision=5, price_precision=4),
            "AXLBTC": Symbol(name="AXLBTC", precision=5, price_precision=8),
            "BTCPLN": Symbol(name="BTCPLN", precision=5, price_precision=2),
            "DYMUSDT": Symbol(name="DYMUSDT", precision=5, price_precision=4),
            "USDCUSDT": Symbol(name="USDCUSDT", precision=2, price_precision=4),
        }

        # Create price resolver
        price_resolver = UsdPriceResolver(client=mock_async_client, symbols=symbols)
        price_resolver.latest_prices["BTCPLN"] = 320000.0
        price_resolver.latest_prices["BTCUSDC"] = 100000.0

        # Create Portfolio UI with real database persistence
        portfolio_ui = PortfolioUI(
            ui_queue=portfolio_ui_queue,
            strategy_config_queue=config_queue,
            price_resolver=price_resolver,
            db=test_db,  # Always use same database for persistence across crashes
            test_mode=True,
        )
        portfolio_ui.set_inventory(mock_inventory)
        logger.info(f"Created PortfolioUI for {instance_name}")

        # Create Strategy Executor backend
        mock_broker = MagicMock(spec=BrokerSpot)
        strategy_executor = StrategyExecutor(
            db=test_db,  # Always use same database
            broker=mock_broker,
            ui_queue=ui_queue,
            inventory=mock_inventory,
            price_resolver=price_resolver,
            test_mode=True,
        )
        strategy_executor.client = mock_async_client
        logger.info(f"Created StrategyExecutor for {instance_name}")

        # Create HP Frontend with proper Kivy mocking
        with patch("kivy.base.EventLoop.ensure_window"):
            hp_frontend = HpFront(
                client=mock_async_client,
                config_queue=config_queue,
                db=test_db,  # Always use same database
                ui_queue=ui_queue,
                test_mode=True,
                price_resolver=price_resolver,
                portfolio_queue=portfolio_ui_queue,
            )
            hp_frontend.initialize()
            logger.info(f"Created HpFront for {instance_name}")

        # Connect all components (same as portfolio_hp_backend_setup)
        # HP frontend <-> Strategy backend connection
        hp_frontend.config_queue = strategy_executor.config_queue
        strategy_executor.ui_queue = hp_frontend.ui_queue
        hp_frontend.db = strategy_executor.db

        # Portfolio <-> Strategy executor connection for sell operations
        portfolio_ui.strategy_config_queue = strategy_executor.config_queue
        portfolio_ui.symbols = strategy_executor.price_resolver.symbols

        # CRITICAL: Connect strategy executor to portfolio for HP event processing
        strategy_executor.portfolio_ui_queue = portfolio_ui.ui_queue

        logger.info(
            f"All components connected for crash recovery setup: {instance_name}"
        )

        # Track for cleanup
        created_instances.extend([portfolio_ui, hp_frontend, strategy_executor])

        return portfolio_ui, hp_frontend, strategy_executor

    async def simulate_crash(*components):
        """
        Simulate application crash for portfolio + HP + backend system.

        Args:
            *components: Components to crash. Expected order: (portfolio_ui, hp_frontend, strategy_backend)
        """
        logger.info(f"Simulating crash for {len(components)} components")

        for i, component in enumerate(components):
            component_type = "unknown"

            # Identify and crash each component type
            if hasattr(component, "strategies") and hasattr(component, "config_queue"):
                # This is a StrategyExecutor backend
                component_type = "StrategyExecutor"
                logger.info(f"Crashing {component_type}")

                # Cancel strategy worker tasks without graceful shutdown
                for strategy in component.strategies.values():
                    if hasattr(strategy, "worker_active"):
                        strategy.worker_active = False
                    if (
                        hasattr(strategy, "worker_task")
                        and strategy.worker_task
                        and not strategy.worker_task.done()
                    ):
                        strategy.worker_task.cancel()

            elif hasattr(component, "ui_queue") and (
                hasattr(component, "refresh_task") or hasattr(component, "strategy_id")
            ):
                # This is an HpFront frontend
                component_type = "HpFront"
                logger.info(f"Crashing {component_type}")

                # Cancel frontend tasks
                tasks_to_cancel = []
                if (
                    hasattr(component, "queue_task")
                    and component.queue_task
                    and not component.queue_task.done()
                ):
                    try:
                        component.queue_task.cancel()
                        tasks_to_cancel.append(component.queue_task)
                    except Exception as e:
                        logger.warning(f"Failed to cancel queue_task: {e}")

                if (
                    hasattr(component, "refresh_task")
                    and component.refresh_task
                    and not component.refresh_task.done()
                ):
                    try:
                        component.refresh_task.cancel()
                        tasks_to_cancel.append(component.refresh_task)
                    except Exception as e:
                        logger.warning(f"Failed to cancel refresh_task: {e}")

                # Wait for tasks to finish
                if tasks_to_cancel:
                    try:
                        await asyncio.wait_for(
                            asyncio.gather(*tasks_to_cancel, return_exceptions=True),
                            timeout=1.0,
                        )
                    except asyncio.TimeoutError:
                        logger.warning("Frontend tasks didn't complete within timeout")

            elif hasattr(component, "coin_list_data") and hasattr(component, "db"):
                # This is a PortfolioUI
                component_type = "PortfolioUI"
                logger.info(f"Crashing {component_type}")

                # Portfolio UI crash - just break any ongoing operations
                # The database state remains intact (this is key for recovery)
                if hasattr(component, "_current_operation"):
                    component._current_operation = None

            else:
                logger.warning(
                    f"Unknown component type at index {i}: {type(component)}"
                )

        logger.info(
            "Crash simulation completed - database state preserved for recovery"
        )

    # Return the factory methods
    yield create_portfolio_hp_setup, simulate_crash

    # Cleanup all created instances
    logger.info(
        f"Cleaning up {len(created_instances)} portfolio crash recovery instances"
    )

    # Group instances for proper cleanup
    portfolios = []
    hp_frontends = []
    strategy_executors = []

    for instance in created_instances:
        if hasattr(instance, "strategies") and hasattr(instance, "config_queue"):
            strategy_executors.append(instance)
        elif hasattr(instance, "ui_queue") and (
            hasattr(instance, "refresh_task") or hasattr(instance, "strategy_id")
        ):
            hp_frontends.append(instance)
        elif hasattr(instance, "coin_list_data") and hasattr(instance, "db"):
            portfolios.append(instance)

    # Cancel HP frontend tasks
    frontend_tasks = []
    for hp_frontend in hp_frontends:
        if (
            hasattr(hp_frontend, "refresh_task")
            and hp_frontend.refresh_task
            and not hp_frontend.refresh_task.done()
        ):
            hp_frontend.refresh_task.cancel()
            frontend_tasks.append(hp_frontend.refresh_task)
        if (
            hasattr(hp_frontend, "queue_task")
            and hp_frontend.queue_task
            and not hp_frontend.queue_task.done()
        ):
            hp_frontend.queue_task.cancel()
            frontend_tasks.append(hp_frontend.queue_task)
        if hasattr(hp_frontend, "stop_event"):
            hp_frontend.stop_event.set()

    # Wait for frontend tasks
    if frontend_tasks:
        try:
            await asyncio.wait_for(
                asyncio.gather(*frontend_tasks, return_exceptions=True), timeout=1.0
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Some frontend tasks didn't complete within timeout during cleanup"
            )

    # Stop strategy executors
    for executor in strategy_executors:
        if hasattr(executor, "stop_event"):
            executor.stop_event.set()
        for strategy in executor.strategies.values():
            if hasattr(strategy, "stop_event"):
                strategy.stop_event.set()
            if (
                hasattr(strategy, "worker_task")
                and strategy.worker_task
                and not strategy.worker_task.done()
            ):
                strategy.worker_task.cancel()
        if (
            hasattr(executor, "thread")
            and executor.thread
            and executor.thread.is_alive()
        ):
            executor.thread.join(timeout=1.0)

    # Portfolio UIs don't need special cleanup
    logger.info(
        f"Cleanup completed for {len(portfolios)} portfolios, "
        f"{len(hp_frontends)} frontends, {len(strategy_executors)} executors"
    )


# ============================================================================
# BUY DIP STRATEGY FIXTURES
# ============================================================================


@pytest.fixture
def sample_candle():
    """Create a sample candle for testing Buy Dip strategy components.

    Returns a factory function that creates candle dictionaries with
    customizable OHLCV data for unit tests.
    """

    def _create(
        open_price: float = 100.0,
        high: float = 105.0,
        low: float = 95.0,
        close: float = 102.0,
        timestamp: int = 1609459200000,
    ) -> Dict:
        return {
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "timestamp": timestamp,
            "volume": 1000.0,
        }

    return _create


@pytest.fixture
def sample_position():
    """Create a sample BuyDipPosition for testing.

    Returns a BuyDipPosition configured with:
    - Symbol: BTCUSDC
    - DCA distances: [φ=1.618%, e=2.718%, π=3.142%]
    - Order size: $200
    """
    from decimal import Decimal
    from src.strategies.buy_dip.position import BuyDipPosition

    return BuyDipPosition(
        position_id="test_pos_1",
        symbol="BTCUSDC",
        dca_distances_pct=[1.618, 2.718, 3.142],  # φ, e, π
        order_size=Decimal("200"),
    )


@pytest.fixture
def sample_buy_dip_config():
    """Create a sample BuyDipConfig for E2E testing."""
    from src.strategies.buy_dip.config import BuyDipConfig

    return BuyDipConfig(
        order_size_percentage=2.0,
        dca_distances_pct=[1.618, 2.718, 3.142],  # φ, e, π
        min_consecutive_rising=3,
        min_total_gain_pct=0.25,
    )


@pytest.fixture
def mock_binance_client_buy_dip():
    """Create a mock BinanceClient for Buy Dip E2E testing (simulates real integration)."""

    client = AsyncMock()

    # Track placed orders for E2E testing
    client.placed_orders = {}  # order_id -> {price, quantity, symbol, side}

    async def create_order_side_effect(*args, **kwargs):
        """Simulate BinanceClient.create_order() - returns order dict like Binance API"""
        symbol = kwargs.get("symbol", "BTCUSDC")
        side = kwargs.get("side", "BUY")
        price = kwargs.get("price", 0.0)
        quantity = kwargs.get("quantity", 0.0)

        # Generate unique order ID like get_new_order() pattern
        order_id = int(abs(hash((float(price) * float(quantity))))) % 1_000_000_000

        # Track order
        client.placed_orders[order_id] = {
            "symbol": symbol,
            "side": side,
            "price": float(price),
            "quantity": float(quantity),
            "status": "NEW",
        }

        # Return dict matching Binance API response
        return {
            "orderId": order_id,
            "symbol": symbol,
            "price": str(price),
            "origQty": str(quantity),
            "status": "NEW",
            "side": side,
            "type": "LIMIT",
            "timeInForce": "GTC",
        }

    client.create_order = AsyncMock(side_effect=create_order_side_effect)
    client.cancel_order = AsyncMock(return_value={"orderId": 0, "status": "CANCELED"})

    return client


@pytest.fixture
def broker_adapter_buy_dip(mock_binance_client_buy_dip):
    """Create BuyDipBrokerAdapter with mocked BinanceClient for E2E testing."""

    # Create Symbol with BTCUSDC precision rules
    symbol = Symbol(
        name="BTCUSDC",
        precision=8,  # Quantity precision (8 decimals for BTC)
        price_precision=2,  # Price precision (2 decimals for USDC)
        min_notional=10.0,  # Minimum order value
        lot_size=0.00000001,  # Step size for quantity
        price_filter=0.01,  # Step size for price
    )

    adapter = BuyDipBrokerAdapter(
        client=mock_binance_client_buy_dip,
        symbol=symbol,
    )
    return adapter


@pytest.fixture
def buy_dip_strategy(sample_buy_dip_config, broker_adapter_buy_dip):
    """Create a BuyDipStrategy instance for E2E testing with broker adapter integration."""

    strategy = BuyDipStrategy(
        config=sample_buy_dip_config,
        total_budget=Decimal("10000"),
        order_budget_pct=Decimal("2.0"),
        broker_adapter=broker_adapter_buy_dip,  # Real integration path!
    )

    # Add worker queue for execution reports (like HP Manager)
    strategy.worker_queue = queue.Queue()

    # Set the callback on broker adapter to route fills to strategy
    # Note: broker_adapter calls callback with (order_id, fill_price)
    # We need to determine if it's a buy order or sell order
    def on_order_filled(order_id: str, filled_price: float):
        """Callback invoked by broker adapter when order fills"""
        # Find the position for this order
        position_id = strategy._order_to_position.get(order_id)
        if not position_id:
            return  # Unknown order

        position = strategy._positions.get(position_id)
        if not position:
            return  # Position not found

        # Check if this is a sell order
        if position.sell_order and position.sell_order.order_id == order_id:
            # SELL order filled
            strategy.handle_sell_fill(order_id, filled_price)
        elif position.pending_order and position.pending_order.order_id == order_id:
            # BUY order filled
            fill_quantity = float(position.pending_order.quantity)
            strategy.handle_order_fill(order_id, filled_price, fill_quantity)

    def on_order_cancelled(order_id: str):
        """Callback invoked by broker adapter when order is cancelled"""
        # Invalidation handler already handles cancellation internally
        # No action needed here - just log it
        pass

    broker_adapter_buy_dip.set_order_filled_callback(on_order_filled)
    broker_adapter_buy_dip.set_order_cancelled_callback(on_order_cancelled)

    # Add BTCUSDC symbol for testing
    strategy.add_symbol("BTCUSDC")
    return strategy


@pytest.fixture
def sample_config():
    """Sample configuration for testing."""
    return BuyDipConfig(
        order_size_percentage=2.0,
        dca_distances_pct=[1.0, 2.0, 3.0],
        min_consecutive_rising=3,
        min_total_gain_pct=0.25,
    )


@pytest.fixture
async def buy_dip_simulator(buy_dip_strategy):
    """Create simulator with automatic cleanup of background worker task."""
    sim = BuyDipSimulator(buy_dip_strategy)
    yield sim
    # Cleanup: stop background worker task
    await sim.stop()
