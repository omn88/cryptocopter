from unittest.mock import patch
import json
import binance
import pandas

from src.backtest.lib import get_futures_historical_data


@patch("binance.Client.get_historical_klines")
async def test_get_historical_data(mock_get_historical_klines):
    with open("tests/data/result_of_client.get_historical_klines.json") as file:
        mock_get_historical_klines.return_value = json.load(file)

    # one_year = '528000'
    frame_historical_data = await get_futures_historical_data(
        client=binance.AsyncClient(), symbol="BTCUSDT", interval="15m", lookback="4000"
    )
    assert mock_get_historical_klines.called
    assert len(frame_historical_data) == 15
    assert isinstance(frame_historical_data, pandas.DataFrame)
    assert frame_historical_data is not None
