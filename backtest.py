import indicators
import lib


class Backtest:
    def __init__(self, symbol):
        self.symbol = symbol
        self.saldo = 1000
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
        position = lib.Order(price=0, quantity=self.order_quantity)

        ovc = lib.order_quantity_list_prepare()

        for index, row in self.df.iterrows():

            self.df.at[index, "Saldo"] = self.saldo

            if special_short:
                if 100 - row["RSI"] < 50:
                    buy_price = row["Open"]
                    self.saldo, buyprices_short = lib.short_position_close(
                        buy_price=buy_price,
                        buyprices_short=buyprices_short,
                        sellprices_short=sellprices_short,
                        index=index,
                        position=position,
                        leverage=self.leverage,
                        saldo=self.saldo,
                    )
                    special_short = False
                    short_position = False

            if special_long:
                if 100 - row["RSI"] > 50:
                    sell_price = row["Open"]
                    self.saldo, sellprices_long = lib.long_position_close(
                        sell_price=sell_price,
                        saldo=self.saldo,
                        buyprices_long=buyprices_long,
                        sellprices_long=sellprices_long,
                        leverage=self.leverage,
                        position=position,
                        index=index,
                    )
                    special_long = False
                    long_position = False

            if long_position and not special_short and not special_long:
                for order in dca_orders:
                    if order.status == "NEW" and row["Low"] < order.price:
                        (
                            position,
                            self.target_price,
                            self.depo_price,
                            buyprices_long,
                        ) = lib.long_position_recalculate(
                            position=position,
                            order_quantity=self.order_quantity,
                            order=order,
                            leverage=self.leverage,
                            index=index,
                            buyprices_long=buyprices_long,
                        )
                        order.status = "FILLED"

                if row["Low"] < self.depo_price:
                    long_position = False
                    net = round((self.depo_price - buy_price), 2)
                    self.saldo = round(self.saldo - position.quantity, 2)
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
                    sell_price = row["Open"]
                    self.saldo, sellprices_long = lib.long_position_close(
                        sell_price=sell_price,
                        saldo=self.saldo,
                        buyprices_long=buyprices_long,
                        sellprices_long=sellprices_long,
                        leverage=self.leverage,
                        position=position,
                        index=index,
                    )
                    long_position = False
                    (
                        dca_orders,
                        position,
                        self.target_price,
                        self.depo_price,
                        self.order_quantity,
                    ) = lib.short_position_open(
                        sell_price=sell_price,
                        sellprices_short=sellprices_short,
                        ovc=ovc,
                        leverage=self.leverage,
                        number_of_dca_orders=number_of_dca_orders,
                        index=index,
                        saldo=self.saldo,
                    )
                    short_position = True

                if long_position and row["RSI"] < 18:
                    print(
                        f"{index}: Condition for Special Short triggered! Closing Long immediately and opening Special Short"
                    )
                    sell_price = row["Open"]
                    self.saldo, sellprices_long = lib.long_position_close(
                        sell_price=sell_price,
                        saldo=self.saldo,
                        buyprices_long=buyprices_long,
                        sellprices_long=sellprices_long,
                        leverage=self.leverage,
                        position=position,
                        index=index,
                    )
                    long_position = False
                    (
                        dca_orders,
                        position,
                        self.target_price,
                        self.depo_price,
                        self.order_quantity,
                    ) = lib.short_position_open(
                        sell_price=sell_price,
                        sellprices_short=sellprices_short,
                        ovc=ovc,
                        leverage=self.leverage,
                        number_of_dca_orders=number_of_dca_orders,
                        index=index,
                        saldo=self.saldo,
                        mode="FULL",
                    )
                    special_short = True
                    short_position = True

            if short_position and not special_short and not special_long:
                for order in dca_orders:
                    if order.status == "NEW" and row["High"] > order.price:
                        (
                            position,
                            self.target_price,
                            self.depo_price,
                            sellprices_short,
                        ) = lib.short_position_recalculate(
                            position=position,
                            order_quantity=self.order_quantity,
                            order=order,
                            leverage=self.leverage,
                            index=index,
                            sellprices_short=sellprices_short,
                        )
                        order.status = "FILLED"

                if row["High"] > self.depo_price:
                    short_position = False
                    net = round((sell_price - self.depo_price), 2)
                    self.saldo = round(self.saldo - position.quantity, 2)
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
                    buy_price = row["Open"]
                    self.saldo, buyprices_short = lib.short_position_close(
                        buy_price=buy_price,
                        buyprices_short=buyprices_short,
                        sellprices_short=sellprices_short,
                        index=index,
                        position=position,
                        leverage=self.leverage,
                        saldo=self.saldo,
                    )
                    short_position = False
                    (
                        dca_orders,
                        position,
                        self.target_price,
                        self.depo_price,
                        self.order_quantity,
                    ) = lib.long_position_open(
                        buy_price=buy_price,
                        buyprices_long=buyprices_long,
                        saldo=self.saldo,
                        ovc=ovc,
                        leverage=self.leverage,
                        number_of_dca_orders=number_of_dca_orders,
                        index=index,
                    )
                    long_position = True

                if short_position and row["RSI"] > 82:
                    print(
                        f"{index}: Condition for Special Long triggered! Closing Short immediately and opening Special Long"
                    )
                    buy_price = row["Open"]
                    self.saldo, buyprices_short = lib.short_position_close(
                        buy_price=buy_price,
                        buyprices_short=buyprices_short,
                        sellprices_short=sellprices_short,
                        index=index,
                        position=position,
                        leverage=self.leverage,
                        saldo=self.saldo,
                    )
                    short_position = False
                    (
                        dca_orders,
                        position,
                        self.target_price,
                        self.depo_price,
                        self.order_quantity,
                    ) = lib.long_position_open(
                        buy_price=buy_price,
                        buyprices_long=buyprices_long,
                        saldo=self.saldo,
                        ovc=ovc,
                        leverage=self.leverage,
                        number_of_dca_orders=number_of_dca_orders,
                        index=index,
                        mode="FULL",
                    )
                    special_long = True
                    long_position = True

            if not long_position and not short_position:
                if row["signal"] == "Buy":
                    buy_price = row["Open"]
                    (
                        dca_orders,
                        position,
                        self.target_price,
                        self.depo_price,
                        self.order_quantity,
                    ) = lib.long_position_open(
                        buy_price=buy_price,
                        buyprices_long=buyprices_long,
                        saldo=self.saldo,
                        ovc=ovc,
                        leverage=self.leverage,
                        number_of_dca_orders=number_of_dca_orders,
                        index=index,
                    )
                    long_position = True

                if row["signal"] == "Sell":
                    sell_price = row["Open"]
                    (
                        dca_orders,
                        position,
                        self.target_price,
                        self.depo_price,
                        self.order_quantity,
                    ) = lib.short_position_open(
                        sell_price=sell_price,
                        sellprices_short=sellprices_short,
                        ovc=ovc,
                        leverage=self.leverage,
                        number_of_dca_orders=number_of_dca_orders,
                        index=index,
                        saldo=self.saldo,
                    )
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
