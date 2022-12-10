import asyncio
from unittest.mock import patch
import json
import binance
import pandas
import pytest

from src.backtest.lib import get_futures_historical_data
from src.producers.producers import determine_start_position, Event
from src.features import Signals
from src.workers.workers import print_last_n_rows

from tests.data.sample_dataframes import dataframe_gen


@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_historical_klines")
async def test_get_historical_data(mock_get_historical_klines):
    client = binance.AsyncClient()
    try:
        with open("tests/data/result_of_client.get_historical_klines.json") as file:
            mock_get_historical_klines.return_value = json.load(file)

        # one_year = '528000'
        frame_historical_data = await get_futures_historical_data(
            client=client, symbol="BTCUSDT", interval="15m", lookback="4000"
        )
        assert mock_get_historical_klines.called
        assert len(frame_historical_data) == 15
        assert isinstance(frame_historical_data, pandas.DataFrame)
        assert frame_historical_data is not None
    finally:
        await client.close_connection()


@pytest.mark.parametrize(
    "signal",
    [Signals.LONG, Signals.LONG_20, Signals.SHORT, Signals.SHORT_80, Signals.NULL],
)
@pytest.mark.asyncio
async def test_determine_start_position(signal):
    client = binance.AsyncClient()
    queue = asyncio.Queue()
    assert queue.qsize() == 0

    try:
        df = dataframe_gen(desired_signal=signal)
        df["position"] = Signals.FLAT

        await determine_start_position(df=df, queue=queue)

        assert queue.qsize() == 1
        event = await queue.get()
        assert isinstance(event, Event)
        assert event.content["last_signal"] == signal
        assert queue.qsize() == 0
    finally:
        await client.close_connection()
