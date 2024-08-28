import asyncio
import logging
import queue
from typing import Dict
from transitions.extensions.asyncio import AsyncMachine
from unittest.mock import AsyncMock, MagicMock
import pytest
from pytest_mock import MockerFixture
from decouple import Config, RepositoryEnv
from logging_config import StrategyLogger

from src.common.database import Database
from src.common.identifiers.futures import (
    Event,
    EventName,
    Signal,
    SignalUpdate,
)
from src.common.identifiers.common import Mode, PositionSide
from src.common.identifiers.spot import StrategyConfig as ConfigSpot
from src.common.identifiers.futures import StrategyConfig as ConfigFutures
from src.common.symbol_info import SymbolInfo
from src.df_handler.futures import DfHandler as DfHandlerFutures
from src.gui.gui_handler.futures import GuiHandler as GuiHandlerFutures
from src.strategies.futures.base import BaseFuturesStrategy
from src.strategies.futures.rsi_basic import RsiBasic
from src.strategies.futures.rsi_extended import RsiExtended
from src.strategies.futures.rsi_special import RsiSpecial
from src.strategies.spot.hp_manager import HpManager as StrategyHP

from tests.data.sample_dataframes import raw_data_generate

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
    db = Database(
        host=config("DB_HOST"),
        port=int(config("DB_PORT")),
        user=config("DB_USER"),
        password=config("DB_PASSWORD"),
        name=config("DB_TEST_NAME"),
    )
    try:
        await db.create_database_if_not_exists()
        await db.create_pool()

        # Drop tables if they exist
        async with db.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DROP TABLE IF EXISTS strategies")
                await cur.execute("DROP TABLE IF EXISTS price_levels")
                await cur.execute("DROP TABLE IF EXISTS orders")
                await conn.commit()

        await db.setup_tables()

        yield db
    except Exception as err:
        logger.error("Error setting up the database: %s", err)
        raise err
    await db.close_pool()


@pytest.fixture
def trading_system_factory(mock_AsyncClient, test_db):
    async def create_trading_system(config: ConfigSpot, balance: float = 10000):
        ui_queue: queue.Queue = queue.Queue()
        strategy = StrategyHP(
            client=mock_AsyncClient,
            balance=balance,
            config=config,
            ui_queue=ui_queue,
            logger=StrategyLogger(name="test"),
            db=test_db,
            core_queue=queue.Queue(),
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
async def spot_buy(mock_AsyncClient):
    ui_queue = MagicMock()
    db = AsyncMock()

    config = ConfigSpot(
        open_time="",
        system_id="1234",
        symbol_info=SymbolInfo(symbol="BTCUSDT", precision=2, price_precision=2),
        side=PositionSide.LONG,
        price_low=1000,
        price_high=1400,
        order_trigger=1,
        budget=1000,
        mode=Mode.DCA,
    )

    strategy = StrategyHP(
        client=mock_AsyncClient,
        balance=10000,
        config=config,
        ui_queue=ui_queue,
        logger=logger,
        db=db,
        core_queue=queue.Queue(),
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

    yield state_machine


@pytest.fixture
async def spot_sell(mock_AsyncClient):
    config = ConfigSpot(
        open_time="",
        system_id="1234",
        symbol_info=SymbolInfo(symbol="BTCUSDT", precision=2, price_precision=2),
        side=PositionSide.SHORT,
        price_low=1000,
        price_high=1400,
        order_trigger=1,
        budget=1000,
        mode=Mode.DCA,
    )

    ui_queue = MagicMock()
    db = AsyncMock()

    strategy = StrategyHP(
        client=mock_AsyncClient,
        balance=10000,
        config=config,
        ui_queue=ui_queue,
        logger=logger,
        db=db,
        core_queue=queue.Queue(),
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
    yield state_machine


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
