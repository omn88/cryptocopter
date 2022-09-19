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
    quantity: float = 200


class Backtest:
    def __init__(self, symbol):
        self.symbol = symbol
        self.saldo = 1000
        self.leverage = 25
        self.profit_long = []
        self.profit_short = []
        self.total_profit = 0
        self.depo_price = 0
        self.df = indicators.get_historical_data(
            symbol=self.symbol,
            interval="15m",
            lookback="88000",  # 44000 is approximately one month
        )
        if self.df.empty:
            print("No data pulled")
        else:
            self.calc_indicators()
            self.generate_signals()
            self.loop_it()
            # print(self.df[14:].to_string())

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
        print(
            f"{self.df.index[0]}: Start looping over rows, starting with {self.saldo} USDT, single order quantity: {Order.quantity}, leverage: {self.leverage}"
        )
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
        position = Order(price=0)

        def long_position_open(mode: str = "DCA"):
            buy_price = row["Open"]
            buyprices_long.append(buy_price)
            self.depo_price = depo_price_calculate("LONG", price=buy_price)
            if mode == "DCA":
                print(
                    f"{index}: Long opened at price {buy_price}, depo is {self.depo_price}"
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
                    f"{index}: Long opened at price {buy_price}, depo is {self.depo_price}, FULL mode"
                )
                position = Order(
                    price=sell_price,
                    status="OPEN",
                    quantity=(number_of_dca_orders + 1) * Order.quantity,
                )
                dca_orders = []

            return buy_price, dca_orders, position

        def short_position_open(mode: str = "DCA"):
            sell_price = row["Open"]
            sellprices_short.append(sell_price)
            self.depo_price = depo_price_calculate(side="SHORT", price=sell_price)
            if mode == "DCA":
                print(
                    f"{index}: Short opened. Price: {sell_price}, depo: {self.depo_price}"
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
                position = Order(
                    price=sell_price,
                    status="OPEN",
                    quantity=(number_of_dca_orders + 1) * Order.quantity,
                )
                dca_orders = []
                print(
                    f"{index}: Short opened in FULL mode. Price: {position.price}, depo: {self.depo_price}, quantity: {position.quantity}"
                )

            return sell_price, dca_orders, position

        def short_position_close():
            buy_price = row["Open"]
            buyprices_short.append(buy_price)
            net = round((sellprices_short[-1] - buy_price), 2)
            net_percent = round(
                100 * round((sellprices_short[-1] / buy_price - 1), 4), 2
            )
            print(
                f"{index}: Short closed. Price {buy_price}, it's {net} USDT and {net_percent}%"
            )

            real_earn = round((position.quantity * self.leverage / buy_price) * net, 2)
            self.saldo = round(self.saldo + real_earn, 2)

            print(
                f"{index}: Summary: quantity: {position.quantity}, leverage: {self.leverage}, earned: {real_earn}, new saldo is: {self.saldo}"
            )

        def long_position_close():
            sell_price = row["Open"]
            sellprices_long.append(sell_price)
            net = round((sell_price - buyprices_long[-1]), 2)
            net_percent = round(
                100 * round((sell_price / buyprices_long[-1] - 1), 4), 2
            )
            print(
                f"{index}: Long closed. Price: {sell_price}, it's: {net} USDT and {net_percent}%"
            )

            real_earn = round((position.quantity * self.leverage / sell_price) * net, 2)
            self.saldo = round(self.saldo + real_earn, 2)

            print(
                f"{index}: Summary: quantity: {position.quantity}, leverage: {self.leverage}, earned: {real_earn}, new saldo is: {self.saldo}"
            )

        def long_position_recalculate(position, order):
            new_quantity = position.quantity + order.quantity
            new_price = (
                position.price * position.quantity + order.price * order.quantity
            ) / new_quantity
            new_position = Order(
                price=new_price, status=position.status, quantity=new_quantity
            )
            self.depo_price = depo_price_calculate(side="LONG", price=new_price)
            print(
                f"{index}: Added to long. Price: {round(order.price, 2)}, new buy price: {round(new_position.price, 2)}, new quantity {new_position.quantity}, new depo {self.depo_price}"
            )
            buyprices_long[-1] = new_price
            return new_position

        def short_position_recalculate(position, order):
            new_quantity = position.quantity + order.quantity
            new_price = (
                position.price * position.quantity + order.price * order.quantity
            ) / new_quantity
            new_position = Order(
                price=new_price, status=position.status, quantity=new_quantity
            )
            self.depo_price = depo_price_calculate("SHORT", price=new_price)
            print(
                f"{index}: Added to short. Price: {round(order.price, 2)}, new sell price: {round(new_position.price, 2)}, new quantity {new_position.quantity}, new depo {self.depo_price}"
            )
            sellprices_short[-1] = new_price
            return new_position

        def long_profit_calculate():
            if len(self.buy_arr_long) > len(self.sell_arr_long):
                self.buy_arr_long = self.buy_arr_long[:-1]

            df_buy_long = pd.DataFrame(self.buy_arr_long, columns=["price"])
            df_sell_long = pd.DataFrame(self.sell_arr_long, columns=["price"])

            return (df_sell_long.values - df_buy_long.values) / df_buy_long.values

        def short_profit_calculate():
            if len(self.sell_arr_short) > len(self.buy_arr_short):
                self.sell_arr_short = self.sell_arr_short[:-1]

            df_buy_short = pd.DataFrame(self.buy_arr_short, columns=["price"])
            df_sell_short = pd.DataFrame(self.sell_arr_short, columns=["price"])

            return (df_sell_short.values - df_buy_short.values) / df_buy_short.values

        def calc_total_profit():

            total_profit_long = 0
            total_profit_short = 0

            for profit in self.profit_long:
                total_profit_long += profit

            for profit in self.profit_short:
                total_profit_short += profit

            print(f"Total profit long: {total_profit_long}")
            print(f"Total profit short: {total_profit_short}")

            return (total_profit_long + total_profit_short) / 2

        def depo_price_calculate(side: str, price):
            if side == "LONG":
                return round((1 - (100 / self.leverage / 100)) * price, 2)

            if side == "SHORT":
                return round((1 + (100 / self.leverage / 100)) * price, 2)

        def show_statistics():
            self.profit_long = long_profit_calculate()
            self.profit_short = short_profit_calculate()
            self.total_profit = calc_total_profit()

            print(f"Profit Long \n{self.profit_long}")
            print(f"Profit Short \n{self.profit_short}")
            print(f"Total profit \n{self.total_profit}")

        for index, row in self.df.iterrows():
            if not long_position and not short_position:
                if row["signal"] == "Buy":
                    buy_price, dca_orders, position = long_position_open()
                    long_position = True

                if row["signal"] == "Sell":
                    sell_price, dca_orders, position = short_position_open()
                    short_position = True

            if special_short:
                if 100 - row["RSI"] < 50:
                    short_position_close()
                    special_short = False
                    short_position = False

            if special_long:
                if 100 - row["RSI"] > 50:
                    long_position_close()
                    special_long = False
                    long_position = False

            if long_position and not special_short and not special_long:
                for order in dca_orders:
                    if order.status == "NEW" and row["Low"] < order.price:
                        position = long_position_recalculate(position, order)
                        order.status = "FILLED"

                if row["Low"] < self.depo_price:
                    long_position = False
                    net = round((self.depo_price - buy_price), 2)
                    self.saldo -= position.quantity
                    print(
                        f"{index}: your long has been stopped at price {self.depo_price}, difference of {net} USDT, but you've lost {position.quantity}, new saldo is: {self.saldo}"
                    )
                    sellprices_long.append(self.depo_price)

                if long_position and row["signal"] == "Sell":
                    long_position_close()
                    long_position = False
                    sell_price, dca_orders, position = short_position_open()
                    short_position = True

                if long_position and row["RSI"] < 18:
                    print(
                        f"{index}: Condition for Special Short triggered! Closing Long immediately and opening Special Short"
                    )
                    long_position_close()
                    long_position = False
                    sell_price, dca_orders, position = short_position_open("FULL")
                    special_short = True
                    short_position = True

            if short_position and not special_short and not special_long:
                for order in dca_orders:
                    if order.status == "NEW" and row["High"] > order.price:
                        position = short_position_recalculate(position, order)
                        order.status = "FILLED"

                if row["High"] > self.depo_price:
                    short_position = False
                    net = round((sell_price - self.depo_price), 2)
                    self.saldo -= position.quantity
                    print(
                        f"{index}: your short has been stopped at price {self.depo_price}, difference of {net} USDT, but you've lost {position.quantity}, new saldo is: {self.saldo}"
                    )
                    buyprices_short.append(self.depo_price)

                if short_position and row["signal"] == "Buy":
                    short_position_close()
                    short_position = False
                    buy_price, dca_orders, position = long_position_open()
                    long_position = True

                if short_position and row["RSI"] > 82:
                    print(
                        f"{index}: Condition for Special Long triggered! Closing Short immediately and opening Special Long"
                    )
                    short_position_close()
                    short_position = False
                    sell_price, dca_orders, position = long_position_open("FULL")
                    special_long = True
                    long_position = True

        self.buy_arr_long = buyprices_long
        self.sell_arr_long = sellprices_long

        self.buy_arr_short = buyprices_short
        self.sell_arr_short = sellprices_short

        print(f"Saldo to {round(self.saldo, 2)}")

        show_statistics()

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
# instance.plot_chart()
