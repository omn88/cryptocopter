import asyncio
from unittest.mock import patch
import json
import binance
import pandas
import pytest

from src.common.common import insert_to_pandas, get_futures_historical_data


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
    [Signal.LONG, Signal.LONG_20, Signal.SHORT, Signal.SHORT_80],
)
async def test_determine_start_position(signal):
    client = binance.AsyncClient()
    queue = asyncio.Queue()
    assert queue.qsize() == 0

    try:
        df = dataframe_gen(desired_signal=signal)
        df["position"] = State.FLAT

        await determine_start_position(df=df, queue=queue)

        assert queue.qsize() == 1
        event = await queue.get()
        assert isinstance(event.content, SignalUpdate)
        assert event.content.signal == signal
        assert queue.qsize() == 0
    finally:
        await client.close_connection()
