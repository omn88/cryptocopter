import pytest
import json
import pandas
import numpy

from unittest.mock import patch

from src.lib import (
    get_historical_data,
    calc_indicators,
    order_quantity_list_prepare,
    order_quantity_check,
    generate_signals,
)


@patch("binance.Client.get_historical_klines")
def test_get_historical_data(mock_get_historical_klines):
    with open("tests/data/result_of_client.get_historical_klines.json") as file:
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
    Date = []
    Open = []
    High = []
    Low = []
    Close = []
    Volume = []
    OpenInterest = []

    with open("tests/data/result_of_lib.get_historical_data.json") as file:
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
        "RSI": numpy.float64(numpy.array([71.88830689226394], dtype=numpy.float64)),
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

    pandas.testing.assert_frame_equal(historical_data, expected)


def test_order_quantity_list_prepare():
    expected_data = {
        "order_value": [1.0],
        "sum_of_all_losses": 16.0,
        "threshold": 16.0,
    }
    expected_ovc = pandas.DataFrame(data=expected_data)

    ovc = order_quantity_list_prepare(
        number_of_dca_orders=3, order_values=[1.0], losses_per_level=4
    )

    pandas.testing.assert_frame_equal(
        left=ovc,
        right=expected_ovc,
    )


def test_order_quantity_list_prepare_default_values():
    data_expected_boundaries = {
        "order_value": [12.5, 3000.0, 50000.0],
        "sum_of_all_losses": [200.0, 48000.0, 800000.0],
        "threshold": [200.0, 88000.0, 1520000.0],
    }
    expected_ovc = pandas.DataFrame(data=data_expected_boundaries)
    ovc = order_quantity_list_prepare()
    min_ = (0, 0)
    average = (18, 1)
    max_ = (36, 2)
    for index_ovc, index_expected_ovc in (min_, average, max_):
        assert ovc.iloc[index_ovc].equals(expected_ovc.iloc[index_expected_ovc])


def test_rsi_calculations():
    test_data = pandas.read_csv("tests/data/sample_data_for_rsi_calculactions.csv")
    test_data = test_data.set_index("Date")

    expected_data = pandas.read_csv("tests/data/sample_data_for_rsi_calculated.csv")
    expected_data = expected_data.set_index("Date")

    calc_indicators(test_data)

    pandas.testing.assert_frame_equal(test_data, expected_data)


def test_rsi_signals_generation():
    test_data = pandas.read_csv("tests/data/sample_data_for_rsi_calculated.csv")
    test_data = test_data.set_index("Date")

    expected_data = pandas.read_csv(
        "tests/data/sample_data_for_rsi_signals_generated.csv"
    )
    expected_data = expected_data.set_index("Date")

    generate_signals(test_data)

    pandas.testing.assert_frame_equal(test_data, expected_data)


@pytest.mark.parametrize(
    "saldo, order_quantity",
    [
        (199.9, 12.5),
        (200.1, 12.5),
        (599.9, 12.5),
        (600.1, 25),
        (1359999.9, 40000),
        (1360000.1, 45000),
        (1519999.9, 45000),
        (1520000.1, 50000),
    ],
)
def test_order_quantity_check(saldo, order_quantity):
    ovc = order_quantity_list_prepare()
    assert order_quantity == order_quantity_check(
        ovc=ovc, saldo=saldo, index="2021-09-29 07:00:00"
    )
