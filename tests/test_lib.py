from src.lib import get_historical_data, calc_indicators
import json
import pandas
import numpy

from unittest.mock import patch


@patch("binance.Client.get_historical_klines")
def test_get_historical_data(mock_get_historical_klines):
    with open("tests/data/historical_data_form_socet_short_version.json") as file:
        mock_get_historical_klines.return_value = json.load(file)

    # one_year = '528000'
    frame_historical_data = get_historical_data(
        symbol="BTCUSDT", interval="15m", lookback="4000"
    )
    assert mock_get_historical_klines.called
    assert len(frame_historical_data) == 15
    assert isinstance(frame_historical_data, pandas.DataFrame)
    assert frame_historical_data is not None


def test_calc_indicators():
    frame_historical_data = None
    Date = []
    Open = []
    High = []
    Low = []
    Close = []
    Volume = []
    OpenInterest = []

    with open(
        "tests/data/historical_data_after_get_historical_data_short_version.json"
    ) as file:
        frames_historical_data = json.load(file)

    for date, open_, high, low, close, volume, open_interest in frames_historical_data:
        Date.append(pandas.to_datetime(date))
        Open.append(open_)
        High.append(high)
        Low.append(low)
        Close.append(close)
        Volume.append(volume)
        OpenInterest.append(open_interest)

    data = {
        "Open": Open,
        "High": High,
        "Low": Low,
        "Close": Close,
        "Volume": Volume,
        "OpenInterest": OpenInterest,
    }
    historical_data = pandas.DataFrame(data=data, index=Date)
    historical_data.index.name = "Data"

    expected_data = {
        "Open": 42245.79,
        "High": 42299.21,
        "Low": 42091.61,
        "Close": 42140.98,
        "Volume": 251.21745,
        "OpenInterest": 1.632892e12,
        "RSI":  numpy.float64(numpy.array([71.88830689226394], dtype=numpy.float64)),
        "RSIbTwenty": 0,
        "RSIbThirty": 0,
        "RSIaSeventy": 1,
        "RSIaEighty": 0,
        "RSIBuyTw": 0,
        "RSIBuy": 0,
        "RSISell": 0,
        "RSISellEi": 0,
        "Saldo": 0,
    }
    expected = pandas.DataFrame(
        data=expected_data, index=[pandas.to_datetime("2021-09-29 07:00:00")]
    )
    expected.index.name = "Data"

    calc_indicators(historical_data)

    assert expected.equals(historical_data) is True
