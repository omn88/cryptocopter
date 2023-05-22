import logging

from src.common.common import insert_to_pandas, rsi_indicator_apply
from src.common.identifiers import Position, Signal
from src.common.initialize_trading_environment import (
    create_async_queue,
    create_async_client,
)
from src.common.orders import order_quantity_list_prepare
from src.strategies.rsi_basic import BasicStrategy
from src.strategies.rsi_extended import ExtendedStrategy
from tests.data.sample_dataframes import raw_data_generate

logger = logging.getLogger("conftest")

import pytest
from pytest_mock import MockerFixture
from unittest.mock import AsyncMock

# Define the module where the real AsyncClient is.
# For example, if the real AsyncClient is in a file named 'bot.py', then:
TESTED_MODULE = "binance"


@pytest.fixture
def mock_AsyncClient(mocker: MockerFixture) -> AsyncMock:
    # Mock the AsyncClient.
    mocked_AsyncClient = mocker.patch(f"{TESTED_MODULE}.AsyncClient")
    # Create an async mock for the instance methods.
    mocked_async_client = AsyncMock()
    # Assign the instance to the mocked AsyncClient when used in a context manager.
    mocked_AsyncClient.return_value.__aenter__.return_value = mocked_async_client
    return mocked_async_client


@pytest.fixture()
async def basic_rsi(mock_AsyncClient):
    raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df = insert_to_pandas(data=raw_data)
    df = rsi_indicator_apply(df=df)
    position = Position()
    queue = create_async_queue()

    tsm = BasicStrategy(
        client=mock_AsyncClient,
        balance=1000,
        order_quantity_list=order_quantity_list_prepare(),
        df=df,
        position=position,
        queue=queue,
        raw_data=raw_data,
    )

    await tsm.determine_start_position()

    yield tsm

    await tsm.client.close_connection()


@pytest.fixture
async def extended_rsi(mock_AsyncClient):
    raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df = insert_to_pandas(data=raw_data)
    df = rsi_indicator_apply(df=df)
    position = Position()
    queue = create_async_queue()

    tsm = ExtendedStrategy(
        client=mock_AsyncClient,
        balance=1000,
        order_quantity_list=order_quantity_list_prepare(),
        df=df,
        position=position,
        raw_data=raw_data,
        queue=queue,
    )

    await tsm.determine_start_position()

    yield tsm

    await tsm.client.close_connection()
