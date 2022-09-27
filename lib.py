from typing import Optional, List, Tuple
from dataclasses import dataclass
import btalib as ta
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


@dataclass
class Order:
    price: float
    quantity: float
    status: str = "NEW"


def calc_indicators(df: pd.DataFrame) -> None:
    rsi = ta.rsi(df, period=14)
    df["RSI"] = rsi.df
    df["RSIbTwenty"] = np.where(df["RSI"] < 20, 1, 0)
    df["RSIbThirty"] = np.where(df["RSI"] < 30, 1, 0)
    df["RSIaSeventy"] = np.where(df["RSI"] > 70, 1, 0)
    df["RSIaEighty"] = np.where(df["RSI"] > 80, 1, 0)
    df["RSIBuyTw"] = np.where(df.RSIbTwenty.diff() == -1, 1, 0)
    df["RSIBuy"] = np.where(df.RSIbThirty.diff() == 0, 1, 0) & np.where(
        df.RSIbThirty.diff(periods=2) == -1, 1, 0
    )
    df["RSISell"] = np.where(df.RSIaSeventy.diff() == 0, 1, 0) & np.where(
        df.RSIaSeventy.diff(periods=2) == -1, 1, 0
    )
    df["RSISellEi"] = np.where(df.RSIaEighty.diff() == -1, 1, 0)
    df["Saldo"] = 0
    df.dropna(inplace=True)


def generate_signals(df: pd.DataFrame):
    conditions = [
        (df.RSIbTwenty.diff() == -1)
        | (df.RSIbThirty.diff() == 0) & (df.RSIbThirty.diff(periods=2) == -1),
        (df.RSIaEighty.diff() == -1)
        | (df.RSIaSeventy.diff() == 0) & (df.RSIaSeventy.diff(periods=2) == -1),
    ]

    choices = ["Buy", "Sell"]
    df["signal"] = np.select(conditions, choices)
    df.signal = df.signal.shift()
    df.dropna(inplace=True)


def order_quantity_list_prepare(
    number_of_dca_orders: int = 3,
    order_values: Optional[List[float]] = None,
    losses_per_level: int = 4,
) -> pd.DataFrame:
    order_values = (
        [
            12.5,
            25,
            50,
            100,
            200,
            300,
            400,
            500,
            600,
            700,
            800,
            900,
            1000,
            1250,
            1500,
            1750,
            2000,
            2500,
            3000,
            3500,
            4000,
            5000,
            6000,
            7000,
            8000,
            9000,
            10000,
            12500,
            15000,
            17500,
            20000,
            25000,
            30000,
            35000,
            40000,
            45000,
            50000,
        ]
        if order_values is None
        else order_values
    )

    # OVC stands for order value calculator
    ovc = pd.DataFrame(order_values, columns=["order_value"])
    ovc.set_index(pd.Index([i for i in range(len(order_values))]))
    ovc["sum_of_all_losses"] = (
        ovc.order_value * (number_of_dca_orders + 1) * losses_per_level
    )
    ovc["threshold"] = ovc.sum_of_all_losses + ovc.sum_of_all_losses.shift(1)
    ovc.threshold.iloc[0] = ovc.sum_of_all_losses.iloc[0]

    return ovc


def order_quantity_check(ovc: pd.DataFrame, saldo: float, index: str) -> float:
    index_list = []

    [index_list.append(thrshld) for thrshld in ovc.threshold if saldo > thrshld]

    selected_order_value = ovc.order_value[len(index_list) - 1]
    print(f"{index}: Selected new order value: {selected_order_value}")
    order_quantity = selected_order_value

    return order_quantity


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


def plot_saldo(df: pd.DataFrame):
    plt.figure(figsize=(10, 5))
    plt.plot(df.Saldo)
    plt.show()


def plot_saldo_log(df: pd.DataFrame):
    plt.figure(figsize=(10, 5))
    plt.plot(df.Saldo)
    plt.yscale("log")
    plt.show()


# def plot_price_and_rsi(df: pd.DataFrame):
#     plt.figure(num=1, figsize=(10, 5))
#     plt.plot(df.Saldo)
#     plt.figure(num=2, figsize=(10, 5))
#     plt.plot(df.RSI)
#     plt.show()


def long_profit_calculate(buy_arr_long, sell_arr_long):
    if len(buy_arr_long) > len(sell_arr_long):
        buy_arr_long = buy_arr_long[:-1]

    df_buy_long = pd.DataFrame(buy_arr_long, columns=["price"])
    df_sell_long = pd.DataFrame(sell_arr_long, columns=["price"])

    return (df_sell_long.values - df_buy_long.values) / df_buy_long.values


def short_profit_calculate(sell_arr_short, buy_arr_short):
    if len(sell_arr_short) > len(buy_arr_short):
        sell_arr_short = sell_arr_short[:-1]

    df_buy_short = pd.DataFrame(buy_arr_short, columns=["price"])
    df_sell_short = pd.DataFrame(sell_arr_short, columns=["price"])

    return (df_sell_short.values - df_buy_short.values) / df_buy_short.values


def show_statistics(
    df: pd.DataFrame, buy_arr_long, sell_arr_long, sell_arr_short, buy_arr_short
):
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
    buyprices_long: List[float],
    saldo: float,
    ovc: pd.DataFrame,
    leverage: int,
    number_of_dca_orders: int,
    index: str,
    mode: str = "DCA",
) -> Tuple[List[Order], Order, float, float, float]:
    buyprices_long.append(buy_price)
    order_quantity = order_quantity_check(saldo=saldo, ovc=ovc, index=index)
    target_price, depo_price = target_depo_price_calculate(
        "LONG", price=buy_price, leverage=leverage
    )
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
            quantity=(number_of_dca_orders + 1) * order_quantity,
        )
        dca_orders = []
        print(
            f"{index}: Long opened in FULL mode. Price: {position.price}, depo: {depo_price}, quantity: {position.quantity}"
        )

    return dca_orders, position, target_price, depo_price, order_quantity


def short_position_open(
    sell_price: float,
    sellprices_short: List[float],
    saldo: float,
    ovc: pd.DataFrame,
    leverage: int,
    index: str,
    number_of_dca_orders: int,
    mode: str = "DCA",
) -> Tuple[List[Order], Order, float, float, float]:
    sellprices_short.append(sell_price)
    order_quantity = order_quantity_check(saldo=saldo, ovc=ovc, index=index)
    target_price, depo_price = target_depo_price_calculate(
        side="SHORT", price=sell_price, leverage=leverage
    )
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
            status="OPEN",
            quantity=(number_of_dca_orders + 1) * order_quantity,
        )
        dca_orders = []
        print(
            f"{index}: Short opened in FULL mode. Price: {position.price}, depo: {depo_price}, quantity: {position.quantity}"
        )

    return dca_orders, position, target_price, depo_price, order_quantity


def short_position_close(
    buy_price: float,
    buyprices_short: List[float],
    sellprices_short: List[float],
    index: str,
    position: Order,
    leverage: int,
    saldo: float,
):
    buyprices_short.append(buy_price)
    net = round((sellprices_short[-1] - buy_price), 2)
    net_percent = round(100 * round((sellprices_short[-1] / buy_price - 1), 4), 2)
    print(
        f"{index}: Short closed. Price {buy_price}, it's {net} USDT and {net_percent}%"
    )

    real_earn = round((position.quantity * leverage / buy_price) * net, 2)
    saldo = round(saldo + real_earn, 2)

    print(
        f"{index}: Summary: quantity: {position.quantity}, leverage: {leverage}, earned: {real_earn}, new saldo is: {saldo}"
    )

    return saldo, buyprices_short


def long_position_close(
    sell_price: float,
    sellprices_long: List[float],
    buyprices_long: List[float],
    index: str,
    position: Order,
    leverage: int,
    saldo: float,
):
    sellprices_long.append(sell_price)
    net = round((sell_price - buyprices_long[-1]), 2)
    net_percent = round(100 * round((sell_price / buyprices_long[-1] - 1), 4), 2)
    print(
        f"{index}: Long closed. Price: {sell_price}, it's: {net} USDT and {net_percent}%"
    )

    real_earn = round((position.quantity * leverage / sell_price) * net, 2)
    saldo = round(saldo + real_earn, 2)

    print(
        f"{index}: Summary: quantity: {position.quantity}, leverage: {leverage}, earned: {real_earn}, new saldo is: {saldo}"
    )

    return saldo, sellprices_long


def long_position_recalculate(
    position: Order,
    order_quantity: float,
    order: Order,
    leverage: int,
    index: str,
    buyprices_long: List[float],
):
    new_quantity = position.quantity + order_quantity
    new_price = (
        position.price * position.quantity + order.price * order_quantity
    ) / new_quantity
    new_position = Order(price=new_price, status=position.status, quantity=new_quantity)
    target_price, depo_price = target_depo_price_calculate(
        side="LONG", price=new_price, leverage=leverage
    )
    print(
        f"{index}: Added to long. Price: {round(order.price, 2)}, new buy price: {round(new_position.price, 2)}, new quantity {new_position.quantity}, new depo {depo_price}"
    )
    buyprices_long[-1] = new_price
    return new_position, target_price, depo_price, buyprices_long


def short_position_recalculate(
    position: Order,
    order_quantity: float,
    order: Order,
    leverage: int,
    index: str,
    sellprices_short: List[float],
):
    new_quantity = position.quantity + order_quantity
    new_price = (
        position.price * position.quantity + order.price * order_quantity
    ) / new_quantity
    new_position = Order(price=new_price, status=position.status, quantity=new_quantity)
    target_price, depo_price = target_depo_price_calculate(
        "SHORT", price=new_price, leverage=leverage
    )
    print(
        f"{index}: Added to short. Price: {round(order.price, 2)}, new sell price: {round(new_position.price, 2)}, new quantity {new_position.quantity}, new depo {depo_price}"
    )
    sellprices_short[-1] = new_price
    return new_position, target_price, depo_price, sellprices_short
