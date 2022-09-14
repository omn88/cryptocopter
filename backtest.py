import numpy as np
import btalib as ta
import matplotlib.pyplot as plt
import indicators
from dataclasses import dataclass
import pandas as pd


@dataclass
class Order:
    price: float
    status: str = "NEW"
    quantity: float = 100


class Backtest:
    def __init__(self, symbol):
        self.symbol = symbol
        self.df = indicators.get_historical_data(
            symbol=self.symbol, interval="15m", lookback="360000"
        )
        if self.df.empty:
            print("No data pulled")
        else:
            self.calc_indicators()
            self.generate_signals()
            self.loop_it()
            # print(self.df[14:].to_string())
            self.profit_long = self.calc_profit_long()
            self.profit_short = self.calc_profit_short()
            print(f"Profit Long \n{25 * self.profit_long}")
            print(f"Profit Short \n{25 * self.profit_short}")
            self.total_profit = self.calc_total_profit()

    def calc_indicators(self):
        rsi = ta.rsi(self.df, period=14)
        self.df["RSI"] = rsi.df
        self.df["RSIbTwenty"] = np.where(self.df["RSI"] < 20, 1, 0)
        self.df["RSIbThirty"] = np.where(self.df["RSI"] < 30, 1, 0)
        self.df["RSIaSeventy"] = np.where(self.df["RSI"] > 70, 1, 0)
        self.df["RSIaEighty"] = np.where(self.df["RSI"] > 80, 1, 0)
        self.df["RSIBuyTw"] = np.where(self.df.RSIbTwenty.diff() == -1, 1, 0)
        self.df["RSIBuy"] = np.where(self.df.RSIbThirty.diff() == 0, 1, 0) & np.where(
            self.df.RSIbThirty.diff(periods=2) == -1, 1, 0
        )
        self.df["RSISell"] = np.where(self.df.RSIaSeventy.diff() == 0, 1, 0) & np.where(
            self.df.RSIaSeventy.diff(periods=2) == -1, 1, 0
        )
        self.df["RSISellEi"] = np.where(self.df.RSIaEighty.diff() == -1, 1, 0)
        self.df.dropna(inplace=True)

    def generate_signals(self):
        conditions = [
            (self.df.RSIbTwenty.diff() == -1)
            | (self.df.RSIbThirty.diff() == 0)
            & (self.df.RSIbThirty.diff(periods=2) == -1),
            (self.df.RSIaEighty.diff() == -1)
            | (self.df.RSIaSeventy.diff() == 0)
            & (self.df.RSIaSeventy.diff(periods=2) == -1),
        ]

        choices = ["Buy", "Sell"]
        self.df["signal"] = np.select(conditions, choices)
        self.df.signal = self.df.signal.shift()
        self.df.dropna(inplace=True)

    def loop_it(self):
        long_position = False
        short_position = False
        special_long = False
        special_short = False
        (
            buyprices_long,
            sellprices_long,
            buyprices_short,
            sellprices_short,
            dca_orders,
        ) = (
            [],
            [],
            [],
            [],
            [],
        )
        number_of_dca_orders = 3
        buy_price = 0
        sell_price = 0
        depo_price = 0
        saldo = 0
        position = Order(price=0)

        def long_position_open(mode: str = "DCA"):
            buy_price = row["Open"]
            buyprices_long.append(buy_price)
            depo_price = round(0.96 * buy_price, 2)
            if mode == "DCA":
                print(
                    f"{index}: Long opened at price {buy_price}, depo is {depo_price}"
                )
                position = Order(price=buy_price, status="OPEN")
                dca_orders = [
                    Order(
                        price=round((buy_price - (0.005 * (order + 1) * buy_price)), 2),
                        status="NEW",
                    )
                    for order in range(number_of_dca_orders)
                ]
            else:
                print(
                    f"{index}: Long opened at price {buy_price}, depo is {depo_price}, FULL mode"
                )
                position = Order(price=sell_price, status="OPEN", quantity=400)
                dca_orders = []

            return buy_price, depo_price, dca_orders, position

        def short_position_open(mode: str = "DCA"):
            sell_price = row["Open"]
            sellprices_short.append(sell_price)
            depo_price = round(1.04 * sell_price)
            if mode == "DCA":
                print(
                    f"{index}: Short opened at price {sell_price}, depo is {depo_price}"
                )
                position = Order(price=sell_price, status="OPEN")
                dca_orders = [
                    Order(
                        price=round(
                            (sell_price + (0.005 * (order + 1) * sell_price)), 2
                        ),
                        status="NEW",
                    )
                    for order in range(number_of_dca_orders)
                ]
            else:
                print(
                    f"{index}: Short opened at price {sell_price}, depo is {depo_price}, FULL mode"
                )
                position = Order(price=sell_price, status="OPEN", quantity=400)
                dca_orders = []

            return sell_price, depo_price, dca_orders, position

        def short_position_close():
            buyprices_short.append(row["Open"])
            net = round((sellprices_short[-1] - row["Open"]), 2)
            print(
                f"{index}: Youve closed short as planned at price {row['Open']}, youve earned {net}"
            )

            return net

        def long_position_close():
            sellprices_long.append(row["Open"])
            net = round((row["Open"] - buyprices_long[-1]), 2)
            print(
                f"{index}: Youve closed long as planned at price {row['Open']}!, youve earned: {net}"
            )

            return net

        def long_position_recalculate(position, order):
            new_quantity = position.quantity + order.quantity
            new_price = (
                position.price * position.quantity + order.price * order.quantity
            ) / new_quantity
            new_position = Order(
                price=new_price, status=position.status, quantity=new_quantity
            )
            depo_price = round(0.96 * new_position.price, 2)
            print(
                f"{index}: You added to long at price {round(order.price, 2)}, new price: {round(new_position.price, 2)}, new quantity {new_position.quantity}, new depo {depo_price}"
            )
            buyprices_long[-1] = new_price
            return new_position, depo_price

        def short_position_recalculate(position, order):
            new_quantity = position.quantity + order.quantity
            new_price = (
                position.price * position.quantity + order.price * order.quantity
            ) / new_quantity
            new_position = Order(
                price=new_price, status=position.status, quantity=new_quantity
            )
            depo_price = round(1.04 * new_position.price, 2)
            print(
                f"{index}: You added to short at price {round(order.price, 2)}, new price: {round(new_position.price, 2)}, new quantity {new_position.quantity}, new depo {depo_price}"
            )
            sellprices_short[-1] = new_price
            return new_position, depo_price

        for index, row in self.df.iterrows():
            if not long_position and not short_position:
                if row["signal"] == "Buy":
                    buy_price, depo_price, dca_orders, position = long_position_open()
                    long_position = True

                if row["signal"] == "Sell":
                    sell_price, depo_price, dca_orders, position = short_position_open()
                    short_position = True

            if special_short:
                if 100 - row["RSI"] < 50:
                    net = short_position_close()
                    print("Youve just closed special short, GRATZ!")
                    saldo += net
                    short_position = False
                    special_short = False

            if special_long:
                if 100 - row["RSI"] > 50:
                    net = long_position_close()
                    print("Youve just closed special long, GRATZ!")
                    saldo += net
                    long_position = False
                    special_long = False

            if long_position and not special_short and not special_long:
                for order in dca_orders:
                    if order.status == "NEW" and row["Low"] < order.price:
                        position, depo_price = long_position_recalculate(
                            position, order
                        )
                        order.status = "FILLED"

                if row["Low"] < depo_price:
                    long_position = False
                    net = round((depo_price - buy_price), 2)
                    saldo += net
                    print(
                        f"{index}: your long has been stopped at price {depo_price}, you lost: {net}"
                    )
                    sellprices_long.append(depo_price)

                if row["signal"] == "Sell":
                    net = long_position_close()
                    long_position = False
                    saldo += net
                    sell_price, depo_price, dca_orders, position = short_position_open()
                    short_position = True

                if row["RSI"] < 18:
                    net = long_position_close()
                    long_position = False
                    saldo += net
                    sell_price, depo_price, dca_orders, position = short_position_open(
                        "FULL"
                    )
                    short_position = True
                    special_short = True
                    print("Youve just opened special short, Lets see what happens!")

            if short_position and not special_short and not special_long:
                for order in dca_orders:
                    if order.status == "NEW" and row["High"] > order.price:
                        position, depo_price = short_position_recalculate(
                            position, order
                        )
                        order.status = "FILLED"

                if row["High"] > depo_price:
                    short_position = False
                    net = round((sell_price - depo_price), 2)
                    saldo += net
                    print(
                        f"{index}: your short has been stopped at price {depo_price}, youve lost {net}"
                    )
                    buyprices_short.append(depo_price)

                if row["signal"] == "Buy":
                    net = short_position_close()
                    saldo += net
                    short_position = False
                    buy_price, depo_price, dca_orders, position = long_position_open()
                    long_position = True

                if row["RSI"] > 82:
                    net = short_position_close()
                    short_position = False
                    saldo += net
                    sell_price, depo_price, dca_orders, position = long_position_open(
                        "FULL"
                    )
                    long_position = True
                    special_long = True
                    print("Youve just opened special long, Lets see what happens!")

        self.buy_arr_long = buyprices_long
        self.sell_arr_long = sellprices_long

        self.buy_arr_short = buyprices_short
        self.sell_arr_short = sellprices_short

        # print("Buy Long")
        # for item in self.buy_arr_long:
        #     print(item)
        #
        # print("Sell Long")
        # for item in self.sell_arr_long:
        #     print(item)
        #
        # print("Buy Short")
        # for item in self.buy_arr_short:
        #     print(item)
        #
        # print("Sell Short")
        # for item in self.sell_arr_short:
        #     print(item)

        print(f"Saldo to {round(saldo, 2)}")

    def calc_profit_long(self):
        if len(self.buy_arr_long) > len(self.sell_arr_long):
            self.buy_arr_long = self.buy_arr_long[:-1]

        df_buy_long = pd.DataFrame(self.buy_arr_long, columns=["price"])
        df_sell_long = pd.DataFrame(self.sell_arr_long, columns=["price"])

        # df_buy_long['price'].astype('int')
        # df_sell_long['price'].astype('int')

        # print(df_buy_long.values)
        # print(df_sell_long.values)

        return (df_sell_long.values - df_buy_long.values) / df_buy_long.values

    def calc_profit_short(self):
        if len(self.sell_arr_short) > len(self.buy_arr_short):
            self.sell_arr_short = self.sell_arr_short[:-1]

        df_buy_short = pd.DataFrame(self.buy_arr_short, columns=["price"])
        df_sell_short = pd.DataFrame(self.sell_arr_short, columns=["price"])

        # df_buy_short['price'].astype('int')
        # df_sell_short['price'].astype('int')

        return (df_sell_short.values - df_buy_short.values) / df_buy_short.values

    def calc_total_profit(self):

        total_profit_long = 0
        total_profit_short = 0

        for profit in self.profit_long:
            total_profit_long += profit

        for profit in self.profit_short:
            total_profit_short += profit

        print(f"Total profit long: {total_profit_long}")
        print(f"Total profit short: {total_profit_short}")

        total_profit = total_profit_long + total_profit_short

        print(f"Total profit {total_profit}")

        return total_profit

    # def plot_chart(self):
    #     plt.figure(figsize=(10, 5))
    #     plt.plot(self.df.Close)
    #     plt.scatter(
    #         self.sell_arr_long.index, self.sell_arr_long.values, marker="v", c="r"
    #     )
    #     plt.scatter(
    #         self.buy_arr_long.index, self.buy_arr_long.values, marker="^", c="g"
    #     )
    #
    #     plt.scatter(
    #         self.sell_arr_short.index, self.sell_arr_short.values, marker="v", c="r"
    #     )
    #     plt.scatter(
    #         self.buy_arr_short.index, self.buy_arr_short.values, marker="^", c="g"
    #     )
    #     plt.show()


instance = Backtest(symbol="BTCUSDT")

# print(instance.buy_arr)
# print(instance.sell_arr)
# print(instance.profit)
#
#
# instance.plot_chart()
