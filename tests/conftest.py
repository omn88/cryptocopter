import pytest
import logging

from binance import AsyncClient

from src.common.common import insert_to_pandas, rsi_indicator_apply
from src.common.identifiers import Position, Signal
from src.common.initialize_trading_environment import (
    create_async_client,
    create_async_queue,
)
from src.common.orders import order_quantity_list_prepare
from src.strategies.rsi_basic import BasicStrategy
from src.strategies.rsi_extended import ExtendedStrategy
from tests.data.sample_dataframes import raw_data_generate

logger = logging.getLogger("conftest")


@pytest.fixture()
async def basic_rsi():
    raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df = insert_to_pandas(data=raw_data)
    df = rsi_indicator_apply(df=df)
    client = await create_async_client()

    position = Position()
    queue = await create_async_queue()

    tsm = BasicStrategy(
        client=client,
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
async def extended_rsi():
    raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df = insert_to_pandas(data=raw_data)
    df = rsi_indicator_apply(df=df)
    client = await create_async_client()
    position = Position()
    queue = await create_async_queue()

    tsm = ExtendedStrategy(
        client=client,
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
