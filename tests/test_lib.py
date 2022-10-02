from src.lib import get_historical_data
import binance
import json
import pandas
from unittest.mock import patch

@patch("binance.Client.get_historical_klines", return_value=None)
def test_get_historical_data(mock_get_historical_klines):
    with open("tests/data/historical_short.json") as file:
        mock_get_historical_klines.return_value = json.load(file)

    # one_year='528000'
    historical_data = get_historical_data(symbol='BTCUSDT', interval='15m', lookback='4000')
    assert mock_get_historical_klines.called
    assert len(historical_data) == 15
    assert isinstance(historical_data, pandas.DataFrame)
    assert historical_data is not None
