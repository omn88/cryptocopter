import asyncio
import logging
from unittest.mock import AsyncMock
import pytest
from pytest_mock import MockerFixture

from src.common.common import insert_to_pandas, rsi_indicator_apply
from src.common.identifiers import Event, EventName, Signal, SignalUpdate
from src.common.initialize_trading_environment import determine_start_position
from src.common.orders import order_quantity_list_prepare
from src.strategies.base import BaseStrategy
from src.workers.trading_state_machine import TradingStateMachine
from src.strategies.rsi_basic import RsiBasic
from src.strategies.rsi_extended import RsiExtended
from src.strategies.rsi_special import RsiSpecial
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
    raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df = insert_to_pandas(data=raw_data)

    number_of_orders = 4

    state_machine = TradingStateMachine(
        strategy=BaseStrategy(
            client=mock_AsyncClient,
            balance=1000,
            order_quantity_list=order_quantity_list_prepare(
                number_of_orders=number_of_orders
            ),
            df=df,
            raw_data=raw_data,
            symbol="BTCUSDT",
            strategy_name="RB_BTCUSDT",
            number_of_orders=number_of_orders,
            main_ui_queue=asyncio.Queue(),
            logger=logging.getLogger(name="RB_BTCUSDT")
        )
    )

    df["Signal"] = 0
    df["Position"] = state_machine.strategy.state

    await state_machine.strategy.queue.put(
        Event(name=EventName.SIGNAL, content=SignalUpdate(signal=Signal.NULL, price=0))
    )

    yield state_machine

    await state_machine.strategy.client.close_connection()


@pytest.fixture()
async def basic_rsi(mock_AsyncClient):
    raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df = insert_to_pandas(data=raw_data)
    df = rsi_indicator_apply(df=df)

    number_of_orders = 4

    state_machine = TradingStateMachine(
        strategy=RsiBasic(
            client=mock_AsyncClient,
            balance=1000,
            order_quantity_list=order_quantity_list_prepare(
                number_of_orders=number_of_orders
            ),
            df=df,
            raw_data=raw_data,
            symbol="BTCUSDT",
            strategy_name="RB_BTCUSDT",
            number_of_orders=number_of_orders,
            main_ui_queue=asyncio.Queue(),
            logger=logging.getLogger(name="RB_BTCUSDT")
        )
    )

    await determine_start_position(
        df=state_machine.strategy.df, queue=state_machine.strategy.queue
    )

    yield state_machine

    await state_machine.strategy.client.close_connection()


@pytest.fixture
async def extended_rsi(mock_AsyncClient):
    raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df = insert_to_pandas(data=raw_data)
    df = rsi_indicator_apply(df=df)
    number_of_orders = 4

    state_machine = TradingStateMachine(
        strategy=RsiExtended(
            client=mock_AsyncClient,
            balance=1000,
            order_quantity_list=order_quantity_list_prepare(
                number_of_orders=number_of_orders
            ),
            df=df,
            raw_data=raw_data,
            symbol="BTCUSDT",
            strategy_name="RE_BTCUSDT",
            number_of_orders=number_of_orders,
            main_ui_queue=asyncio.Queue(),
            logger=logging.getLogger(name="RB_BTCUSDT")
        )
    )

    await determine_start_position(
        df=state_machine.strategy.df, queue=state_machine.strategy.queue
    )
    yield state_machine

    await state_machine.strategy.client.close_connection()


@pytest.fixture
async def special_rsi(mock_AsyncClient):
    raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df = insert_to_pandas(data=raw_data)
    df = rsi_indicator_apply(df=df)
    number_of_orders = 4

    state_machine = TradingStateMachine(
        strategy=RsiSpecial(
            client=mock_AsyncClient,
            balance=1000,
            order_quantity_list=order_quantity_list_prepare(
                number_of_orders=number_of_orders
            ),
            df=df,
            raw_data=raw_data,
            symbol="BTCUSDT",
            strategy_name="RS_BTCUSDT",
            number_of_orders=number_of_orders,
            main_ui_queue=asyncio.Queue(),
            logger=logging.getLogger(name="RB_BTCUSDT")
        )
    )

    await determine_start_position(
        df=state_machine.strategy.df, queue=state_machine.strategy.queue
    )

    yield state_machine

    await state_machine.strategy.client.close_connection()
