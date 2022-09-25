from typing import Optional, List, Tuple

import btalib as ta
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


def calc_indicators(df):
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


def generate_signals(df):
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


def order_quantity_check(ovc: pd.DataFrame, saldo: float) -> float:
    index_list = []

    [index_list.append(thrshld) for thrshld in ovc.threshold if saldo > thrshld]

    selected_order_value = ovc.order_value[len(index_list) - 1]
    # print(f"{index}: Selected new order value: {selected_order_value}")
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
