import logging
from typing import List

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
    target_depo_price_calculate,
    long_position_open,
    long_position_close,
    short_position_close,
    short_position_open,
    Order,
)

from src.features import (
    rsi_indicator_apply,
    rsi_signal_extended_generate,
    rsi_signal_basic_generate,
    Signals,
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


@pytest.mark.parametrize(
    "side, price, leverage, target_price, depo_price",
    [
        ("LONG", 100, 25, 104, 96),
        ("SHORT", 100, 25, 96, 104),
        ("LONG", 100, 10, 110, 90),
        ("SHORT", 100, 10, 90, 110),
        ("LONG", 100, 5, 120, 80),
        ("SHORT", 100, 5, 80, 120),
        ("LONG", 100, 50, 102, 98),
        ("SHORT", 100, 50, 98, 102),
    ],
)
def test_target_depo_price_calculations(
    side: str, price: float, leverage: int, target_price: float, depo_price: float
):

    target, depo = target_depo_price_calculate(
        side=side, price=price, leverage=leverage
    )

    assert (target, depo) == (target_price, depo_price)


@pytest.mark.parametrize(
    "buy_price, number_of_dca_orders, index, order_quantity, depo_price, mode, dca_orders, position",
    [
        (
            10000,
            3,
            "2021-09-29 07:00:00",
            100,
            9600,
            "DCA",
            [
                Order(price=9950, quantity=100),
                Order(price=9900, quantity=100),
                Order(price=9850, quantity=100),
            ],
            Order(price=10000, quantity=100),
        ),
        (
            10000,
            3,
            "2021-09-29 07:00:00",
            100,
            9600,
            "FULL",
            [],
            Order(price=10000, quantity=400),
        ),
    ],
)
def test_opening_position_long(
    buy_price,
    number_of_dca_orders,
    index,
    order_quantity,
    depo_price,
    mode,
    dca_orders,
    position,
):

    do, p = long_position_open(
        buy_price=buy_price,
        number_of_dca_orders=number_of_dca_orders,
        index=index,
        order_quantity=order_quantity,
        depo_price=depo_price,
        mode=mode,
    )

    assert do == dca_orders
    assert p == position


@pytest.mark.parametrize(
    "sell_price, number_of_dca_orders, index, order_quantity, depo_price, mode, dca_orders, position",
    [
        (
            10000,
            3,
            "2021-09-29 07:00:00",
            100,
            10400,
            "DCA",
            [
                Order(price=10050, quantity=100),
                Order(price=10100, quantity=100),
                Order(price=10150, quantity=100),
            ],
            Order(price=10000, quantity=100),
        ),
        (
            10000,
            3,
            "2021-09-29 07:00:00",
            100,
            10400,
            "FULL",
            [],
            Order(price=10000, quantity=400),
        ),
    ],
)
def test_opening_position_short(
    sell_price,
    number_of_dca_orders,
    index,
    order_quantity,
    depo_price,
    mode,
    dca_orders,
    position,
):

    test_dca_orders, test_position = short_position_open(
        sell_price=sell_price,
        number_of_dca_orders=number_of_dca_orders,
        index=index,
        order_quantity=order_quantity,
        depo_price=depo_price,
        mode=mode,
    )

    assert test_dca_orders == dca_orders
    assert test_position == position


@pytest.mark.parametrize(
    "sell_price, buyprices_long, index, position, leverage, saldo, new_saldo",
    [
        (
            11000,
            [10000],
            "2021-09-29 07:00:00",
            Order(price=10000, quantity=100),
            25,
            3200,
            3450,
        ),
        (
            11000,
            [10000],
            "2021-09-29 07:00:00",
            Order(price=10000, quantity=200),
            50,
            3200,
            4200,
        ),
        (
            9800,
            [10000],
            "2021-09-29 07:00:00",
            Order(price=10000, quantity=100),
            25,
            3200,
            3150,
        ),
    ],
)
def test_closing_position_long(
    sell_price: float,
    buyprices_long: List[float],
    index: str,
    position: Order,
    leverage: int,
    saldo: float,
    new_saldo: float,
):

    assert new_saldo == long_position_close(
        sell_price=sell_price,
        buyprices_long=buyprices_long,
        index=index,
        position=position,
        leverage=leverage,
        saldo=saldo,
    )


@pytest.mark.parametrize(
    "buy_price, sellprices_short, index, position, leverage, saldo, new_saldo",
    [
        (
            10000,
            [11000],
            "2021-09-29 07:00:00",
            Order(price=11000, quantity=100),
            25,
            3200,
            3450,
        ),
        (
            10000,
            [11000],
            "2021-09-29 07:00:00",
            Order(price=11000, quantity=200),
            50,
            3200,
            4200,
        ),
        (
            10200,
            [10000],
            "2021-09-29 07:00:00",
            Order(price=10000, quantity=100),
            25,
            3200,
            3151,
        ),
    ],
)
def test_closing_position_short(
    buy_price: float,
    sellprices_short: List[float],
    index: str,
    position: Order,
    leverage: int,
    saldo: float,
    new_saldo: float,
):

    assert new_saldo == short_position_close(
        buy_price=buy_price,
        sellprices_short=sellprices_short,
        index=index,
        position=position,
        leverage=leverage,
        saldo=saldo,
    )


def test_basic_rsi_signal_generate():
    test_data = pandas.read_csv("tests/data/sample_data_for_rsi_calculactions.csv")
    test_data = test_data.set_index("Date")

    expected_data = [
        [
            "2022-10-18 10:30:00",
            19620.36,
            19628.75,
            19546.55,
            19567.72,
            3150.76158,
            1666082699999.0,
            49.75987867554145,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 10:45:00",
            19568.43,
            19588.75,
            19524.15,
            19300.45,
            3158.19164,
            1666083599999.0,
            30.978669835358417,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 11:00:00",
            19535.29,
            19549.2,
            19493.92,
            19000.24,
            4731.03937,
            1666084499999.0,
            21.26828679970889,
            1,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 11:15:00",
            19529.61,
            19560.74,
            19524.49,
            18900.69,
            2188.40715,
            1666085399999.0,
            19.127237625857305,
            1,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 11:30:00",
            19553.03,
            19565.59,
            19470.0,
            19000.4,
            4361.07817,
            1666086299999.0,
            27.04876484044469,
            1,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 11:45:00",
            19505.1,
            19535.0,
            19495.97,
            19100.61,
            2083.69754,
            1666087199999.0,
            34.04131599751409,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 12:00:00",
            19528.61,
            19541.37,
            19502.98,
            19534.84,
            1943.77302,
            1666088099999.0,
            54.42631176949443,
            0,
            0,
            1,
            0,
            Signals.LONG,
        ],
        [
            "2022-10-18 12:15:00",
            19534.79,
            19566.94,
            19518.07,
            20000.81,
            2098.2689,
            1666088999999.0,
            66.41978421867684,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 12:30:00",
            19548.88,
            19583.35,
            19540.61,
            20500.14,
            2226.78542,
            1666089899999.0,
            74.24237990499101,
            0,
            1,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 12:45:00",
            19556.59,
            19565.0,
            19524.0,
            21500.16,
            1752.03307,
            1666090799999.0,
            82.85599414068994,
            0,
            1,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 13:00:00",
            19532.17,
            19558.85,
            19528.83,
            21000.84,
            1966.05651,
            1666091699999.0,
            70.2277394324218,
            0,
            1,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 13:15:00",
            19532.61,
            19566.87,
            19528.93,
            20600.04,
            1688.81098,
            1666092599999.0,
            62.052306440017624,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 13:30:00",
            19561.08,
            19595.12,
            19559.42,
            21500.4,
            2179.03486,
            1666093499999.0,
            70.39101442782444,
            0,
            1,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 13:45:00",
            19573.19,
            19605.9,
            19560.1,
            20400.59,
            2160.13734,
            1666094399999.0,
            54.60614330831202,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 14:00:00",
            19563.59,
            19613.33,
            19562.55,
            19800.71,
            2311.59211,
            1666095299999.0,
            48.250532060154285,
            0,
            0,
            0,
            1,
            Signals.SHORT,
        ],
        [
            "2022-10-18 14:15:00",
            19597.74,
            19608.68,
            19573.0,
            20400.66,
            2138.86181,
            1666096199999.0,
            54.01509602582641,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 14:30:00",
            19600.83,
            19620.61,
            19590.6,
            20200.15,
            2457.19063,
            1666097099999.0,
            51.93295901166873,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 14:45:00",
            19602.15,
            19650.31,
            19580.0,
            19626.76,
            2873.77001,
            1666097999999.0,
            46.42211819856351,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 15:00:00",
            19626.02,
            19640.87,
            19595.1,
            19598.62,
            2116.34421,
            1666098899999.0,
            46.16321968848757,
            0,
            0,
            0,
            0,
            0,
        ],
    ]

    expected = pandas.DataFrame(data=expected_data)
    expected = expected.iloc[:, :13]
    expected.columns = [
        "Date",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "OpenInterest",
        "RSI",
        "RSIbelowThirty",
        "RSIaboveSeventy",
        "RSIBuy",
        "RSISell",
        "signal",
    ]
    expected = expected.set_index("Date")

    test_data = rsi_indicator_apply(df=test_data)
    assert "RSI" in test_data.columns

    test_data = rsi_signal_basic_generate(df=test_data)
    assert "RSIbelowThirty" in test_data.columns
    assert "RSIaboveSeventy" in test_data.columns
    assert "RSIBuy" in test_data.columns
    assert "RSISell" in test_data.columns
    assert "signal" in test_data.columns

    pandas.testing.assert_frame_equal(left=test_data, right=expected)
    assert test_data.equals(expected)


def test_rsi_signal_extended_generate():
    test_data = pandas.read_csv("tests/data/sample_data_for_rsi_calculactions.csv")
    test_data = test_data.set_index("Date")

    expected_data = [
        [
            "2022-10-18 10:30:00",
            19620.36,
            19628.75,
            19546.55,
            19567.72,
            3150.76158,
            1666082699999.0,
            49.75987867554145,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 10:45:00",
            19568.43,
            19588.75,
            19524.15,
            19300.45,
            3158.19164,
            1666083599999.0,
            30.978669835358417,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 11:00:00",
            19535.29,
            19549.2,
            19493.92,
            19000.24,
            4731.03937,
            1666084499999.0,
            21.26828679970889,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 11:15:00",
            19529.61,
            19560.74,
            19524.49,
            18900.69,
            2188.40715,
            1666085399999.0,
            19.127237625857305,
            1,
            0,
            0,
            0,
            1,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 11:30:00",
            19553.03,
            19565.59,
            19470.0,
            19000.4,
            4361.07817,
            1666086299999.0,
            27.04876484044469,
            1,
            0,
            0,
            0,
            0,
            0,
            1,
            0,
            Signals.LONG_20,
        ],
        [
            "2022-10-18 11:45:00",
            19505.1,
            19535.0,
            19495.97,
            19100.61,
            2083.69754,
            1666087199999.0,
            34.04131599751409,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 12:00:00",
            19528.61,
            19541.37,
            19502.98,
            19534.84,
            1943.77302,
            1666088099999.0,
            54.42631176949443,
            0,
            0,
            1,
            0,
            0,
            0,
            0,
            0,
            Signals.LONG,
        ],
        [
            "2022-10-18 12:15:00",
            19534.79,
            19566.94,
            19518.07,
            20000.81,
            2098.2689,
            1666088999999.0,
            66.41978421867684,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 12:30:00",
            19548.88,
            19583.35,
            19540.61,
            20500.14,
            2226.78542,
            1666089899999.0,
            74.24237990499101,
            0,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 12:45:00",
            19556.59,
            19565.0,
            19524.0,
            21500.16,
            1752.03307,
            1666090799999.0,
            82.85599414068994,
            0,
            1,
            0,
            0,
            0,
            1,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 13:00:00",
            19532.17,
            19558.85,
            19528.83,
            21000.84,
            1966.05651,
            1666091699999.0,
            70.2277394324218,
            0,
            1,
            0,
            0,
            0,
            0,
            0,
            1,
            Signals.SHORT_80,
        ],
        [
            "2022-10-18 13:15:00",
            19532.61,
            19566.87,
            19528.93,
            20600.04,
            1688.81098,
            1666092599999.0,
            62.052306440017624,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 13:30:00",
            19561.08,
            19595.12,
            19559.42,
            21500.4,
            2179.03486,
            1666093499999.0,
            70.39101442782444,
            0,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 13:45:00",
            19573.19,
            19605.9,
            19560.1,
            20400.59,
            2160.13734,
            1666094399999.0,
            54.60614330831202,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 14:00:00",
            19563.59,
            19613.33,
            19562.55,
            19800.71,
            2311.59211,
            1666095299999.0,
            48.250532060154285,
            0,
            0,
            0,
            1,
            0,
            0,
            0,
            0,
            Signals.SHORT,
        ],
        [
            "2022-10-18 14:15:00",
            19597.74,
            19608.68,
            19573.0,
            20400.66,
            2138.86181,
            1666096199999.0,
            54.01509602582641,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 14:30:00",
            19600.83,
            19620.61,
            19590.6,
            20200.15,
            2457.19063,
            1666097099999.0,
            51.93295901166873,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 14:45:00",
            19602.15,
            19650.31,
            19580.0,
            19626.76,
            2873.77001,
            1666097999999.0,
            46.42211819856351,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            "2022-10-18 15:00:00",
            19626.02,
            19640.87,
            19595.1,
            19598.62,
            2116.34421,
            1666098899999.0,
            46.16321968848757,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
    ]

    expected = pandas.DataFrame(data=expected_data)
    expected = expected.iloc[:, :17]
    expected.columns = [
        "Date",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "OpenInterest",
        "RSI",
        "RSIbelowThirty",
        "RSIaboveSeventy",
        "RSIBuy",
        "RSISell",
        "RSIbelowTwenty",
        "RSIaboveEighty",
        "RSIBuyTwenty",
        "RSISellEighty",
        "signal",
    ]
    expected = expected.set_index("Date")

    test_data = rsi_indicator_apply(df=test_data)
    assert "RSI" in test_data.columns

    test_data = rsi_signal_extended_generate(df=test_data)
    assert "RSIbelowTwenty" in test_data.columns
    assert "RSIaboveEighty" in test_data.columns
    assert "RSIBuyTwenty" in test_data.columns
    assert "RSISellEighty" in test_data.columns
    assert "RSIbelowThirty" in test_data.columns
    assert "RSIaboveSeventy" in test_data.columns
    assert "RSIBuy" in test_data.columns
    assert "RSISell" in test_data.columns
    assert "signal" in test_data.columns

    pandas.testing.assert_frame_equal(left=test_data, right=expected)
    assert test_data.equals(expected)
