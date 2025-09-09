import os

# Import kivy configuration first (must be before any Kivy imports)
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kivy_config

# Suppress aiosqlite debug logging in tests
import logging
from collections import defaultdict

logging.getLogger("aiosqlite").setLevel(logging.WARNING)

from src.gui.hp_manager.hpfront import HpFront
from src.broker import BrokerSpot
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.position_buy import HPPositionBuy
from src.position_sell import HPPositionSell
from src.strategy_executor import StrategyExecutor
from src.database.recovery_service import RecoveryService
from tests.strategies.hp_manager_helpers import (
    wait_for_condition,
    get_hp_positions_by_type,
    get_parent_hp_positions,
    get_child_hp_positions,
    get_buy_positions,
    has_active_buy_positions,
    has_idle_buy_positions,
    has_active_sell_positions,
    has_idle_sell_positions,
    wait_for_active_buy_positions,
    wait_for_no_idle_buy_positions,
    wait_for_idle_buy_positions,
    wait_for_no_active_buy_positions,
    wait_for_active_sell_positions,
    wait_for_no_idle_sell_positions,
    wait_for_idle_sell_positions,
    wait_for_no_active_sell_positions,
)

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
from src.common.common import generate_hp_id
from src.common.symbol_info import SymbolInfo
from src.database.trading_database import TradingDatabase
from src.identifiers import (
    HPBuyConfig,
    HPBuyData,
    HPSellConfig,
    Order,
    PositionSide,
    SellPosition,
    State,
    StateInfo,
    InventoryItem,
    Event,
    EventName,
    HPSellPositionCreated,
    HPSellPositionCompleted,
    HPBuyPositionFilled,
    HPPositionCancelled,
)
from src.strategies.hp_manager import HpStrategy
from src.portfolio.portfolio_gui import PortfolioUI

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
def strategy_executor_fixture(
    test_db: TradingDatabase, mock_async_client, mock_inventory
):
    """
    Fixture to create and run a StrategyExecutor instance.

    - Starts the executor loop in a separate thread.
    - Mocks necessary dependencies.
    - Provides an initialized instance for testing.
    """

    # Mock dependencies
    mock_broker = MagicMock(spec=BrokerSpot)
    ui_queue: queue.Queue = queue.Queue()
    symbols_info = {
        "BTCUSDC": SymbolInfo(symbol="BTCUSDC", precision=5, price_precision=2),
        "BTCUSDT": SymbolInfo(symbol="BTCUSDT", precision=5, price_precision=2),
        "ETHUSDT": SymbolInfo(symbol="ETHUSDT", precision=5, price_precision=2),
        "AXLUSDT": SymbolInfo(symbol="AXLUSDT", precision=5, price_precision=4),
        "AXLBTC": SymbolInfo(symbol="AXLBTC", precision=5, price_precision=8),
        "BTCPLN": SymbolInfo(symbol="BTCPLN", precision=5, price_precision=2),
        "DYMUSDT": SymbolInfo(symbol="DYMUSDT", precision=5, price_precision=4),
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
        inventory=mock_inventory,
        test_mode=True,
        price_resolver=price_resolver,
        portfolio_ui_queue=queue.Queue(),
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
async def crash_recovery_factory(
    test_db: TradingDatabase, mock_async_client, mock_inventory
):
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

        symbols_info = {
            "BTCUSDC": SymbolInfo(
                symbol="BTCUSDC",
                min_notional=10.0,
                lot_size=0.00001,
                min_qty=0.00001,
                max_qty=9000.0,
                price_filter=0.01,
                precision=5,
                price_precision=2,
            ),
            "BTCUSDT": SymbolInfo(symbol="BTCUSDT", precision=5, price_precision=2),
            "ETHUSDT": SymbolInfo(symbol="ETHUSDT", precision=5, price_precision=2),
            "AXLUSDT": SymbolInfo(symbol="AXLUSDT", precision=5, price_precision=4),
            "AXLBTC": SymbolInfo(symbol="AXLBTC", precision=5, price_precision=8),
            "BTCPLN": SymbolInfo(symbol="BTCPLN", precision=5, price_precision=2),
            "DYMUSDT": SymbolInfo(symbol="DYMUSDT", precision=5, price_precision=4),
        }

        price_resolver = UsdPriceResolver(
            client=mock_async_client, symbols_info=symbols_info
        )
        price_resolver.latest_prices["BTCPLN"] = 320000.0
        price_resolver.latest_prices["BTCUSDC"] = 100000.0

        # Create backend
        mock_broker = MagicMock(spec=BrokerSpot)
        logger.info("Creating StrategyExecutor in test mode")
        backend = StrategyExecutor(
            db=test_db,  # Always use the same database
            broker=mock_broker,
            ui_queue=ui_queue,
            symbols_info=symbols_info,
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
                strategy_id=f"test_strategy{instance_name}",
                config_queue=config_queue,
                db=test_db,  # Always use the same database
                ui_queue=ui_queue,
                symbols_info=symbols_info,
                test_mode=True,
                price_resolver=price_resolver,
                portfolio_queue=queue.Queue(),  # Use a mock queue for portfolio updates
            )
            frontend.initialize()

        # Connect them
        frontend.config_queue = backend.config_queue
        backend.ui_queue = frontend.ui_queue
        frontend.db = backend.db
        frontend.symbols_info = backend.symbols_info

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

    created_strategies = []  # Track created strategies for cleanup

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
    """Mock inventory for testing - replaces mock_balances."""
    return [
        InventoryItem(
            id="btc_lot",
            coin="BTC",
            buy_price=50000.0,
            quantity=1.0,
            available_quantity=1.0,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time(),
            notes="Initial BTC position",
        ),
        InventoryItem(
            id="eth_lot",
            coin="ETH",
            buy_price=3000.0,
            quantity=5.0,
            available_quantity=5.0,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time(),
            notes="Initial ETH position",
        ),
        InventoryItem(
            id="axl_lot",
            coin="AXL",
            buy_price=0.8,
            quantity=1000.0,
            available_quantity=1000.0,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time(),
            notes="Initial AXL position for multihop testing",
        ),
        InventoryItem(
            id="usdc_lot",
            coin="USDC",
            buy_price=1.0,
            quantity=1000.0,
            available_quantity=1000.0,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time(),
            notes="Initial USDC position",
        ),
        InventoryItem(
            id="dym_lot",
            coin="DYM",
            buy_price=1.2,
            quantity=200.0,
            available_quantity=200.0,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time(),
            notes="Initial DYM position for convert testing",
        ),
    ]


# TO BE REPLACED WITH mock_inventory ABOVE - kept for reference
@pytest.fixture
def test_inventory():
    """Test inventory with multiple BTC lots for FIFO testing."""
    return [
        InventoryItem(
            id="btc_lot_1",
            coin="BTC",
            buy_price=46000.0,  # Lowest price - should be locked first in FIFO
            quantity=0.5,
            available_quantity=0.5,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time() - 1000,  # Oldest
            notes="First BTC lot",
        ),
        InventoryItem(
            id="btc_lot_2",
            coin="BTC",
            buy_price=47000.0,  # Middle price
            quantity=0.3,
            available_quantity=0.3,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time() - 500,  # Middle
            notes="Second BTC lot",
        ),
        InventoryItem(
            id="btc_lot_3",
            coin="BTC",
            buy_price=48000.0,  # Highest price - should be locked last
            quantity=0.2,
            available_quantity=0.2,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time(),  # Newest
            notes="Third BTC lot",
        ),
        InventoryItem(
            id="usdc_lot",
            coin="USDC",
            buy_price=1.0,
            quantity=1000.0,
            available_quantity=1000.0,
            locked_quantity=0.0,
            source="EXCHANGE",
            timestamp=time.time(),
            notes="USDC position",
        ),
    ]


@pytest.fixture
def portfolio_ui(test_db, mock_inventory):
    """Create portfolio UI for testing with test mode enabled."""
    ui_queue = queue.Queue()

    # Use comprehensive symbols_info that includes USDC
    symbols_info = {
        "BTCUSDC": SymbolInfo(symbol="BTCUSDC", precision=5, price_precision=2),
        "BTCUSDT": SymbolInfo(symbol="BTCUSDT", precision=5, price_precision=2),
        "ETHUSDT": SymbolInfo(symbol="ETHUSDT", precision=5, price_precision=2),
        "AXLUSDT": SymbolInfo(symbol="AXLUSDT", precision=5, price_precision=4),
        "AXLBTC": SymbolInfo(symbol="AXLBTC", precision=5, price_precision=8),
        "BTCPLN": SymbolInfo(symbol="BTCPLN", precision=5, price_precision=2),
        "DYMUSDT": SymbolInfo(symbol="DYMUSDT", precision=5, price_precision=4),
        "USDCUSDT": SymbolInfo(
            symbol="USDCUSDT", precision=2, price_precision=4
        ),  # Add USDC symbol
    }

    portfolio = PortfolioUI(
        ui_queue=ui_queue,
        symbols_info=symbols_info,
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
def portfolio_strategy_executor(test_db, mock_async_client, mock_inventory):
    """Create strategy executor with portfolio UI queue for testing HP-Portfolio communication."""
    ui_queue = queue.Queue()
    portfolio_ui_queue = queue.Queue()

    # Create mock portfolio UI that doesn't touch Kivy widgets
    portfolio = MagicMock(spec=PortfolioUI)
    portfolio.ui_queue = portfolio_ui_queue
    portfolio.handle_hp_sell_created = AsyncMock()
    portfolio.handle_hp_sell_completed = AsyncMock()
    portfolio.handle_hp_buy_filled = AsyncMock()
    portfolio.handle_hp_position_cancelled = AsyncMock()
    # Add inventory to portfolio so tests can access it
    portfolio.inventory = mock_inventory

    # Compute balances from inventory for compatibility with StrategyExecutor
    inventory_by_coin = defaultdict(float)
    for item in mock_inventory:
        inventory_by_coin[item.coin] += item.available_quantity

    # Create strategy executor with portfolio queue
    symbols_info = {
        "BTCUSDC": SymbolInfo(symbol="BTCUSDC", precision=5, price_precision=2),
        "BTCUSDT": SymbolInfo(symbol="BTCUSDT", precision=5, price_precision=2),
        "ETHUSDT": SymbolInfo(symbol="ETHUSDT", precision=5, price_precision=2),
        "AXLUSDT": SymbolInfo(symbol="AXLUSDT", precision=5, price_precision=4),
        "AXLBTC": SymbolInfo(symbol="AXLBTC", precision=5, price_precision=8),
        "BTCPLN": SymbolInfo(symbol="BTCPLN", precision=5, price_precision=2),
        "DYMUSDT": SymbolInfo(symbol="DYMUSDT", precision=5, price_precision=4),
        "USDCUSDT": SymbolInfo(
            symbol="USDCUSDT", precision=2, price_precision=4
        ),  # Add USDC symbol
    }

    mock_broker = MagicMock(spec=BrokerSpot)
    price_resolver = UsdPriceResolver(
        client=mock_async_client, symbols_info=symbols_info
    )
    # Set the required prices for multihop tests
    price_resolver.latest_prices["BTCPLN"] = 320000.0
    price_resolver.latest_prices["BTCUSDC"] = 100000.0

    executor = StrategyExecutor(
        db=test_db,
        broker=mock_broker,
        ui_queue=ui_queue,
        symbols_info=symbols_info,
        inventory=mock_inventory,
        test_mode=True,
        price_resolver=price_resolver,
        portfolio_ui_queue=portfolio_ui_queue,
    )
    executor.client = mock_async_client

    yield executor, portfolio

    # Cleanup: Stop the executor properly
    executor.stop()

    # Clear any remaining items in queues
    while not ui_queue.empty():
        try:
            ui_queue.get_nowait()
        except queue.Empty:
            break

    while not portfolio_ui_queue.empty():
        try:
            portfolio_ui_queue.get_nowait()
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
    hp_gui.symbols_info = strategy_executor_fixture.symbols_info

    # Connect portfolio to HP manager (for sell button functionality)
    portfolio_ui.hp_manager = hp_gui

    # CRITICAL: Connect strategy executor to real portfolio for HP event processing
    strategy_executor_fixture.portfolio_ui_queue = portfolio_ui.ui_queue

    # Note: hp_gui does NOT have a direct portfolio reference in real implementation
    # It only has portfolio_queue for communication

    yield portfolio_ui, hp_gui, strategy_executor_fixture

    # Cleanup strategies
    for strategy in strategy_executor_fixture.strategies.values():
        strategy.stop_event.set()
        await wait_for_condition(condition_func=lambda: not strategy.worker_active)

    # Cleanup is handled in individual fixtures
