from unittest.mock import patch
import json
import binance
import pandas
import pytest

from src.common.common import (
    insert_to_pandas,
    get_futures_historical_data,
    rsi_indicator_apply,
)
from src.common.identifiers import Signal, State, SignalUpdate, Position
from src.common.initialize_trading_environment import (
    create_async_queue,
    create_async_client,
)
from src.common.orders import order_quantity_list_prepare
from src.strategies.rsi_extended import ExtendedStrategy
from tests.data.sample_dataframes import raw_data_generate


@patch("binance.AsyncClient.futures_historical_klines")
async def test_get_historical_data(mock_get_historical_klines):
    client = binance.AsyncClient()
    try:
        with open("tests/data/result_of_client.get_historical_klines.json") as file:
            mock_get_historical_klines.return_value = json.load(file)

        # one_year = '528000'
        frame_historical_data = await get_futures_historical_data(
            client=client, interval="15m", lookback="4000"
        )
        assert mock_get_historical_klines.called
        frame_historical_data = insert_to_pandas(data=frame_historical_data)
        assert len(frame_historical_data) == 14
        assert isinstance(frame_historical_data, pandas.DataFrame)
        assert frame_historical_data is not None
    finally:
        await client.close_connection()


@pytest.mark.parametrize(
    "signal",
    [Signal.LONG, Signal.LONG_EXT, Signal.SHORT, Signal.SHORT_EXT],
)
async def test_determine_start_position(signal):

    raw_data = raw_data_generate(desired_signal=signal)
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
    tsm.signals_from_features_generate(df)
    tsm.signal_update = SignalUpdate(signal=signal, price=0)

    await tsm.determine_start_position()

    assert tsm.queue.qsize() == 1
    event = await tsm.queue.get()
    assert isinstance(event, SignalUpdate)
    assert event.signal == signal
    assert tsm.queue.qsize() == 0

    await tsm.client.close_connection()
