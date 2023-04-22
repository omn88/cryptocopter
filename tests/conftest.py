import pandas
import pytest
import logging
from dataclasses import dataclass

from constants import SYMBOL
from src.common.common import insert_to_pandas, rsi_indicator_apply
from src.common.identifiers import Position, Signal
from src.common.initialize_trading_environment import create_async_client
from src.common.orders import order_quantity_list_prepare
from src.strategies.rsi_basic import BasicStrategy
from src.strategies.rsi_extended import ExtendedStrategy
from src.workers.trading_state_machine import TradingStateMachine
from tests.data.sample_dataframes import raw_data_generate

logger = logging.getLogger("conftest")


@pytest.fixture()
def mock_create_orders_long():
    mock_create_orders_long.side_effect = [
        {
            "orderId": 1,
            "price": 20000.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 2,
            "price": 19900.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 3,
            "price": 19800.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 4,
            "price": 19700.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
    ]
    return mock_create_orders_long


@pytest.fixture()
def mock_create_orders_long_then_short():
    mock_create_orders_long_then_short.side_effect = [
        {
            "orderId": 1,
            "price": 20000.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 2,
            "price": 19900.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 3,
            "price": 19800.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 4,
            "price": 19700.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 5,
            "price": 20000.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 6,
            "price": 20100.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 7,
            "price": 20200.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 8,
            "price": 20300.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
    ]
    return mock_create_orders_long_then_short


@pytest.fixture()
def mock_create_orders_short_then_long():
    mock_create_orders_short_then_long.side_effect = [
        {
            "orderId": 1,
            "price": 20000.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 2,
            "price": 20100.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 3,
            "price": 20200.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 4,
            "price": 20300.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 5,
            "price": 20000.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 6,
            "price": 19900.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 7,
            "price": 19800.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 8,
            "price": 19700.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
    ]
    return mock_create_orders_short_then_long


@pytest.fixture()
def mock_create_orders_short():
    mock_create_orders_short.side_effect = [
        {
            "orderId": 1,
            "price": 20000.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 2,
            "price": 20100.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 3,
            "price": 20200.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 4,
            "price": 20300.00,
            "status": basic_rsi.client.ORDER_STATUS_NEW,
        },
    ]
    return mock_create_orders_short


@pytest.fixture()
def mock_cancel_order():

    mock_cancel_order.return_value = {"status": "CANCELED"}

    return mock_cancel_order


@pytest.fixture
async def basic_rsi():
    raw_data = raw_data_generate(desired_signal=Signal.NULL)
    df = insert_to_pandas(data=raw_data)
    df = rsi_indicator_apply(df=df)
    client = await create_async_client()
    position = Position()

    tsm = BasicStrategy(
        client=client,
        balance=1000,
        order_quantity_list=order_quantity_list_prepare(),
        df=df,
        position=position,
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

    tsm = ExtendedStrategy(
        client=client,
        balance=1000,
        order_quantity_list=order_quantity_list_prepare(),
        df=df,
        position=position,
        raw_data=raw_data,
    )

    yield tsm

    await tsm.client.close_connection()
