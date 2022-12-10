import asyncio
from unittest.mock import patch
import json
import binance
import pandas
import pytest

from src.backtest.lib import get_futures_historical_data
from src.producers.producers import determine_start_position
from src.features import combined_signals_generate, Signals
from src.workers.workers import print_last_n_rows

# from sample_dataframes import dataframe_short


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


# @pytest.mark.asyncio
# @patch("src.features.combined_signals_generate")
# async def test_determine_start_position(mock_df):
#     client = binance.AsyncClient()
#     queue = asyncio.Queue()
#     assert queue.qsize() == 0
#
#     try:
#         mock_df.return_value = dataframe_short()
#         mock_df = combined_signals_generate(
#             df=mock_df, condition_lists=[], choice_lists=[]
#         )
#
#         mock_df["position"] = Signals.FLAT
#
#         mock_df = await determine_start_position(df=mock_df, queue=queue)
#
#         await print_last_n_rows(df=mock_df)
#
#         assert queue.qsize() == 1
#     finally:
#         await client.close_connection()
