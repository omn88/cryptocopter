import indicators
from dataclasses import dataclass
import lib


@dataclass
class Order:
    price: float
    quantity: float
    status: str = "NEW"


class Backtest:
    def __init__(self, symbol):
        self.symbol = symbol
        self.saldo = 3200
        self.leverage = 25
        self.order_quantity = 0
        self.profit_long = []
        self.profit_short = []
        self.total_profit = 0
        self.depo_price = 0
        self.target_price = 0
        self.df = indicators.get_historical_data(
            symbol=self.symbol,
            interval="15m",
            lookback="528000",  # 44000 is approximately one month
        )
        if self.df.empty:
            print("No data pulled")
        else:
            lib.calc_indicators(df=self.df)
            lib.generate_signals(df=self.df)
            self.loop_it()
            # print(self.df[14:].to_string())

    def loop_it(self):
        print(
            f"{self.df.index[0]}: Start looping over rows, starting with {self.saldo} USDT, single order quantity: {self.order_quantity}, leverage: {self.leverage}"
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
        buy_price = 0
        sell_price = 0
        number_of_dca_orders = 3
        position = Order(price=0, quantity=self.order_quantity)

        ovc = lib.order_quantity_list_prepare()

        def long_position_open(mode: str = "DCA"):
            buy_price = row["Open"]
            buyprices_long.append(buy_price)
            self.order_quantity = lib.order_quantity_check(saldo=self.saldo, ovc=ovc)
            self.target_price, self.depo_price = lib.target_depo_price_calculate(
                "LONG", price=buy_price, leverage=self.leverage
            )
            if mode == "DCA":
                print(
                    f"{index}: Long opened at price {buy_price}, depo is {self.depo_price}"
                )
                position = Order(price=buy_price, quantity=self.order_quantity)
                dca_orders = [
                    Order(
                        price=round((buy_price - (0.005 * (order + 1) * buy_price)), 2),
                        quantity=self.order_quantity,
                    )
                    for order in range(number_of_dca_orders)
                ]
            else:
                position = Order(
                    price=sell_price,
                    quantity=(number_of_dca_orders + 1) * self.order_quantity,
                )
                dca_orders = []
                print(
                    f"{index}: Short opened in FULL mode. Price: {position.price}, depo: {self.depo_price}, quantity: {position.quantity}"
                )

            return buy_price, dca_orders, position

        def short_position_open(mode: str = "DCA"):
            sell_price = row["Open"]
            sellprices_short.append(sell_price)
            self.order_quantity = lib.order_quantity_check(saldo=self.saldo, ovc=ovc)
            self.target_price, self.depo_price = lib.target_depo_price_calculate(
                side="SHORT", price=sell_price, leverage=self.leverage
            )
            if mode == "DCA":
                print(
                    f"{index}: Short opened. Price: {sell_price}, depo: {self.depo_price}"
                )
                position = Order(price=sell_price, quantity=self.order_quantity)
                dca_orders = [
                    Order(
                        price=round(
                            (sell_price + (0.005 * (order + 1) * sell_price)), 2
                        ),
                        quantity=self.order_quantity,
                    )
                    for order in range(number_of_dca_orders)
                ]
            else:
                position = Order(
                    price=sell_price,
                    status="OPEN",
                    quantity=(number_of_dca_orders + 1) * self.order_quantity,
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

        def long_position_recalculate(position):
            new_quantity = position.quantity + self.order_quantity
            new_price = (
                position.price * position.quantity + order.price * self.order_quantity
            ) / new_quantity
            new_position = Order(
                price=new_price, status=position.status, quantity=new_quantity
            )
            self.target_price, self.depo_price = lib.target_depo_price_calculate(
                side="LONG", price=new_price, leverage=self.leverage
            )
            print(
                f"{index}: Added to long. Price: {round(order.price, 2)}, new buy price: {round(new_position.price, 2)}, new quantity {new_position.quantity}, new depo {self.depo_price}"
            )
            buyprices_long[-1] = new_price
            return new_position

        def short_position_recalculate(position):
            new_quantity = position.quantity + self.order_quantity
            new_price = (
                position.price * position.quantity + order.price * self.order_quantity
            ) / new_quantity
            new_position = Order(
                price=new_price, status=position.status, quantity=new_quantity
            )
            self.target_price, self.depo_price = lib.target_depo_price_calculate(
                "SHORT", price=new_price, leverage=self.leverage
            )
            print(
                f"{index}: Added to short. Price: {round(order.price, 2)}, new sell price: {round(new_position.price, 2)}, new quantity {new_position.quantity}, new depo {self.depo_price}"
            )
            sellprices_short[-1] = new_price
            return new_position

        for index, row in self.df.iterrows():

            self.df.at[index, "Saldo"] = self.saldo
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
                        position = long_position_recalculate(position)
                        order.status = "FILLED"

                if row["Low"] < self.depo_price:
                    long_position = False
                    net = round((self.depo_price - buy_price), 2)
                    self.saldo -= position.quantity
                    print(
                        f"{index}: your long has been stopped at price {self.depo_price}, difference of {net} USDT, you've lost {position.quantity}, new saldo is: {self.saldo}"
                    )
                    sellprices_long.append(self.depo_price)

                if row["High"] > self.target_price:
                    long_position = False
                    net = round((self.target_price - buy_price), 2)
                    self.saldo += position.quantity
                    print(
                        f"{index}: target of {100 / self.leverage}% reached at price {self.target_price}, difference of {net} USDT, you've earned {position.quantity}, new saldo is: {self.saldo}"
                    )
                    sellprices_long.append(self.target_price)

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
                        position = short_position_recalculate(position)
                        order.status = "FILLED"

                if row["High"] > self.depo_price:
                    short_position = False
                    net = round((sell_price - self.depo_price), 2)
                    self.saldo -= position.quantity
                    print(
                        f"{index}: your short has been stopped at price {self.depo_price}, difference of {net} USDT, but you've lost {position.quantity}, new saldo is: {self.saldo}"
                    )
                    buyprices_short.append(self.depo_price)

                if row["Low"] < self.target_price:
                    short_position = False
                    net = round((sell_price - self.target_price), 2)
                    self.saldo += position.quantity
                    print(
                        f"{index}: target of {100 / self.leverage}% reached at price {self.target_price}, difference of {net} USDT, you've earned {position.quantity}, new saldo is: {self.saldo}"
                    )
                    buyprices_short.append(self.target_price)

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

            if not long_position and not short_position:
                if row["signal"] == "Buy":
                    buy_price, dca_orders, position = long_position_open()
                    long_position = True

                if row["signal"] == "Sell":
                    sell_price, dca_orders, position = short_position_open()
                    short_position = True

        print(f"Saldo to {round(self.saldo, 2)}")

        lib.show_statistics(
            df=self.df,
            buy_arr_long=buyprices_long,
            sell_arr_long=sellprices_long,
            buy_arr_short=buyprices_short,
            sell_arr_short=sellprices_short,
        )

    # def plot_chart(self):
    #     plt.figure(figsize=(10, 5))
    #     plt.plot(self.saldo_for_plot)
    #     plt.show()
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
