import logging
from typing import List, Tuple, Optional
import btalib
import numpy
import pandas
from matplotlib import pyplot
import binance

from constants import SYMBOL
from src.orders import Order, PositionSide

logger = logging.getLogger("lib")


def target_depo_price_calculate(
    side: str, price: float, leverage: int
) -> Tuple[float, float]:
    if side == "LONG":
        depo_price = round((1 - (100 / leverage / 100)) * price, 2)
        target_price = round((1 + (100 / leverage / 100)) * price, 2)
        return target_price, depo_price

    if side == "SHORT":
        target_price = round((1 - (100 / leverage / 100)) * price, 2)
        depo_price = round((1 + (100 / leverage / 100)) * price, 2)
        return target_price, depo_price


async def get_futures_historical_data(
    client: binance.AsyncClient, interval: str, lookback: str
) -> List:

    historical_data = await client.futures_historical_klines(
        SYMBOL, interval, lookback + "min ago UTC"
    )
    return historical_data[:-1]


def get_futures_historical_data_sync(
    client: binance.Client,
    symbol: str,
    interval: str,
    lookback: str,
    look_end: Optional[str] = None,
) -> pandas.DataFrame:

    # ToDo: Below Timedelta must react to time change (winter/summer)
    pandas.Timedelta(hours=1)
    historical_data = client.futures_historical_klines(
        symbol=symbol,
        interval=interval,
        start_str=lookback + "min ago UTC",
        end_str=look_end + "min ago UTC" if look_end is not None else None,
    )
    frame = pandas.DataFrame(historical_data)
    frame = frame.iloc[:, :7]
    frame.columns = ["Date", "Open", "High", "Low", "Close", "Volume", "OpenInterest"]
    frame = frame.set_index("Date")
    frame.index = pandas.to_datetime(frame.index, unit="ms") + numpy.timedelta64(1, "h")
    frame = frame.astype(float)
    return frame


def calc_indicators(df: pandas.DataFrame) -> None:
    rsi = btalib.rsi(df, period=14)
    df["RSI"] = rsi.df
    df["RSIbTwenty"] = numpy.where(df["RSI"] < 20, 1, 0)
    df["RSIbThirty"] = numpy.where(df["RSI"] < 30, 1, 0)
    df["RSIaSeventy"] = numpy.where(df["RSI"] > 70, 1, 0)
    df["RSIaEighty"] = numpy.where(df["RSI"] > 80, 1, 0)
    df["RSIBuyTw"] = numpy.where(df.RSIbTwenty.diff() == -1, 1, 0)
    df["RSIBuy"] = numpy.where(df.RSIbThirty.diff() == 0, 1, 0) & numpy.where(
        df.RSIbThirty.diff(periods=2) == -1, 1, 0
    )
    df["RSISell"] = numpy.where(df.RSIaSeventy.diff() == 0, 1, 0) & numpy.where(
        df.RSIaSeventy.diff(periods=2) == -1, 1, 0
    )
    df["RSISellEi"] = numpy.where(df.RSIaEighty.diff() == -1, 1, 0)
    df["Saldo"] = 0
    df.dropna(inplace=True)


def generate_signals(df: pandas.DataFrame) -> None:
    conditions = [
        (df.RSIbTwenty.diff() == -1)
        | (df.RSIbThirty.diff() == 0) & (df.RSIbThirty.diff(periods=2) == -1),
        (df.RSIaEighty.diff() == -1)
        | (df.RSIaSeventy.diff() == 0) & (df.RSIaSeventy.diff(periods=2) == -1),
    ]

    choices = ["Buy", "Sell"]
    df["signal"] = numpy.select(conditions, choices)
    df.dropna(inplace=True)


def plot_saldo(df: pandas.DataFrame):
    pyplot.figure(figsize=(10, 5))
    pyplot.plot(df.Saldo)
    pyplot.show()


def plot_saldo_log(df: pandas.DataFrame):
    pyplot.figure(figsize=(10, 5))
    pyplot.plot(df.Saldo)
    pyplot.yscale("log")
    pyplot.show()


# def plot_price_and_rsi(df: pd.DataFrame):
#     pyplot.figure(num=1, figsize=(10, 5))
#     pyplot.plot(df.Saldo)
#     pyplot.figure(num=2, figsize=(10, 5))
#     pyplot.plot(df.RSI)
#     pyplot.show()


def long_profit_calculate(buy_arr_long, sell_arr_long):
    if len(buy_arr_long) > len(sell_arr_long):
        buy_arr_long = buy_arr_long[:-1]

    df_buy_long = pandas.DataFrame(buy_arr_long, columns=["price"])
    df_sell_long = pandas.DataFrame(sell_arr_long, columns=["price"])

    return (df_sell_long.values - df_buy_long.values) / df_buy_long.values


def short_profit_calculate(sell_arr_short, buy_arr_short):
    if len(sell_arr_short) > len(buy_arr_short):
        sell_arr_short = sell_arr_short[:-1]

    df_buy_short = pandas.DataFrame(buy_arr_short, columns=["price"])
    df_sell_short = pandas.DataFrame(sell_arr_short, columns=["price"])

    return (df_sell_short.values - df_buy_short.values) / df_buy_short.values


def show_statistics(
    df: pandas.DataFrame, buy_arr_long, sell_arr_long, sell_arr_short, buy_arr_short
) -> None:
    profit_long = long_profit_calculate(
        buy_arr_long=buy_arr_long, sell_arr_long=sell_arr_long
    )
    profit_short = short_profit_calculate(
        sell_arr_short=sell_arr_short, buy_arr_short=buy_arr_short
    )

    avg_profit_long_all = sum(profit_long) / len(profit_long)
    avg_profit_short_all = sum(profit_short) / len(profit_short)

    success_longs = []
    unsuccess_longs = []
    [success_longs.append(long) for long in profit_long if long > 0]
    [unsuccess_longs.append(long) for long in profit_long if long < 0]

    avg_profit_long_success = (
        sum(success_longs) / len(success_longs) if len(success_longs) > 0 else 0
    )
    avg_loss_long = (
        (sum(unsuccess_longs) / len(unsuccess_longs)) if len(unsuccess_longs) > 0 else 0
    )

    print(f"Longs! \nTotal: {len(profit_long)}\nSuccessful longs: {len(success_longs)}")
    print(f"Unsuccessful longs: {len(unsuccess_longs)}")
    print(
        f"Average Profit Long From Successful Positions: {round(100 * round(float(avg_profit_long_success), 5), 2)}%"
    )
    print(f"Average Loss: {round(100 * round(float(avg_loss_long), 4), 2)}%")
    print(
        f"Average Profit Long From All Positions: {round(100 * round(float(avg_profit_long_all), 5), 2)}%"
    )

    success_shorts = []
    unsuccess_shorts = []
    [success_shorts.append(short) for short in profit_short if short > 0]
    [unsuccess_shorts.append(short) for short in profit_short if short < 0]
    avg_profit_short_success = (
        (sum(success_shorts) / len(success_shorts)) if len(success_shorts) > 0 else 0
    )
    avg_loss_short = (
        (sum(unsuccess_shorts) / len(unsuccess_shorts))
        if len(unsuccess_shorts) > 0
        else 0
    )
    print(
        f"Shorts! \nTotal: {len(profit_short)}\nSuccessful shorts: {len(success_shorts)}"
    )
    print(f"Unsuccessful shorts: {len(unsuccess_shorts)}")
    print(
        f"Average Profit Short From Successful Positions: {round(100 * round(float(avg_profit_short_success), 5), 2)}%"
    )
    print(f"Average Loss: {round(100 * round(float(avg_loss_short), 4), 2)}%")
    print(
        f"Average Profit Short From All Positions: {round(100 * round(float(avg_profit_short_all), 5), 2)}%"
    )

    plot_saldo(df=df)
    plot_saldo_log(df=df)
    # plot_price_and_rsi(df=df)


def long_position_open(
    buy_price: float,
    number_of_dca_orders: int,
    index: str,
    order_quantity,
    depo_price: float,
    mode: str = "DCA",
) -> Tuple[List[Order], Order]:
    if mode == "DCA":
        print(f"{index}: Long opened at price {buy_price}, depo is {depo_price}")
        position = Order(price=buy_price, quantity=order_quantity)
        dca_orders = [
            Order(
                price=round((buy_price - (0.005 * (order + 1) * buy_price)), 2),
                quantity=order_quantity,
            )
            for order in range(number_of_dca_orders)
        ]
    else:
        position = Order(
            price=buy_price,
            quantity=number_of_dca_orders * order_quantity,
        )
        dca_orders = []
        print(
            f"{index}: Long opened in FULL mode. Price: {position.price}, depo: {depo_price}, quantity: {position.quantity}"
        )

    return dca_orders, position


def short_position_open(
    sell_price: float,
    depo_price: float,
    index: str,
    number_of_dca_orders: int,
    order_quantity: float,
    mode: str = "DCA",
) -> Tuple[List[Order], Order]:
    if mode == "DCA":
        print(f"{index}: Short opened. Price: {sell_price}, depo: {depo_price}")
        position = Order(price=sell_price, quantity=order_quantity)
        dca_orders = [
            Order(
                price=round((sell_price + (0.005 * (order + 1) * sell_price)), 2),
                quantity=order_quantity,
            )
            for order in range(number_of_dca_orders)
        ]
    else:
        position = Order(
            price=sell_price,
            quantity=number_of_dca_orders * order_quantity,
        )
        dca_orders = []
        print(
            f"{index}: Short opened in FULL mode. Price: {position.price}, depo: {depo_price}, quantity: {position.quantity}"
        )

    return dca_orders, position


def short_position_close(
    buy_price: float,
    sellprices_short: List[float],
    index: str,
    position: Order,
    leverage: int,
    saldo: float,
) -> float:
    net = round((sellprices_short[-1] - buy_price), 2)
    net_percent = round((sellprices_short[-1] / buy_price - 1), 4)
    print(
        f"{index}: Short closed. Price {buy_price}, it's {net} USDT and {100 * net_percent}%"
    )

    real_earn = round((position.quantity * leverage * net_percent), 2)
    saldo = round(saldo + real_earn, 2)

    print(
        f"{index}: Summary: quantity: {position.quantity}, leverage: {leverage}, earned: {real_earn}, new saldo is: {saldo}"
    )

    return saldo


def long_position_close(
    sell_price: float,
    buyprices_long: List[float],
    index: str,
    position: Order,
    leverage: int,
    saldo: float,
) -> float:
    net = round((sell_price - buyprices_long[-1]), 2)
    net_percent = round((sell_price / buyprices_long[-1] - 1), 4)
    print(
        f"{index}: Long closed. Price: {sell_price}, it's: {net} USDT and {100 * net_percent}%"
    )

    real_earn = round((position.quantity * leverage * net_percent), 2)
    saldo = round(saldo + real_earn, 2)

    print(
        f"{index}: Summary: quantity: {position.quantity}, leverage: {leverage}, earned: {real_earn}, new saldo is: {saldo}"
    )

    return saldo


def long_position_recalculate(
    position: Order,
    order_quantity: float,
    order: Order,
    leverage: int,
    index: str,
) -> Tuple[Order, float, float]:
    new_quantity = position.quantity + order_quantity
    new_price = (
        position.price * position.quantity + order.price * order_quantity
    ) / new_quantity
    new_position = Order(price=new_price, quantity=new_quantity)
    target_price, depo_price = target_depo_price_calculate(
        side="LONG", price=new_price, leverage=leverage
    )
    print(
        f"{index}: Added to long. Price: {round(order.price, 2)}, new buy price: {round(new_position.price, 2)}, new quantity {new_position.quantity}, new depo {depo_price}"
    )
    return new_position, target_price, depo_price


def short_position_recalculate(
    position: Order,
    order_quantity: float,
    order: Order,
    leverage: int,
    index: str,
) -> Tuple[Order, float, float]:
    new_quantity = position.quantity + order_quantity
    new_price = (
        position.price * position.quantity + order.price * order_quantity
    ) / new_quantity
    new_position = Order(price=new_price, quantity=new_quantity)
    target_price, depo_price = target_depo_price_calculate(
        "SHORT", price=new_price, leverage=leverage
    )
    print(
        f"{index}: Added to short. Price: {round(order.price, 2)}, new sell price: {round(new_position.price, 2)}, new quantity {new_position.quantity}, new depo {depo_price}"
    )
    return new_position, target_price, depo_price


def target_price_calculate(side: str, price: float, leverage: int) -> float:
    logger.info("Entering target price calculate")
    if side == PositionSide.LONG:
        target_price = round((1 + (100 / leverage / 100)) * price, 1)
    elif side == PositionSide.SHORT:
        target_price = round((1 - (100 / leverage / 100)) * price, 1)
    else:
        raise AssertionError("Wrong position side: %s", side)

    logger.info("position side: %s, target: %s" % (side, target_price))
    return target_price
