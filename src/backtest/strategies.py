import backtrader as bt
from backtrader import Order

from src.backtest.signals import BasicRSISignal


class StrategyRsiBasic(bt.Strategy):
    params = (
        ("dca_orders", 4),
        ("dca_span", 0.005),
        ("value", 4),
        ("period", 14),
        ("leverage", 25),
    )

    def log(self, txt, dt=None):
        """Logging function fot this strategy"""
        dt = dt or self.datas[0].datetime.datetime(0)
        print("%s, %s" % (dt.strftime("%Y-%m-%d %H:%M"), txt))

    def __init__(self):
        self.rsi = bt.ind.RSI(
            self.data.close,
            period=self.params.period,
            plothlines=[30, 70],
        )
        self.rsi_signal = BasicRSISignal(self.data)
        self.orders = []

    def send_buy_dca_orders(self, order_price):
        for i in range(self.p.dca_orders):
            price = order_price - self.p.dca_span * i * order_price
            order = self.buy(
                price=price,
                size=0.25,
                exectype=Order.Limit,
            )
            self.log("Buy order send at price %s" % round(price, 2))
            self.orders.append(order)

    def send_sell_dca_orders(self, order_price):
        for i in range(self.p.dca_orders):
            price = order_price + self.p.dca_span * i * order_price
            order = self.sell(
                price=price,
                exectype=Order.Limit,
                size=0.25,
            )
            self.log("Sell order send at price %s" % round(price, 2))
            self.orders.append(order)

    def notify_cashvalue(self, cash, value):
        self.log("cash: %.2f value: %.2f update" % (cash, value))

    def notify_trade(self, trade):
        if not trade.isclosed:
            return

        self.log("OPERATION PROFIT, GROSS %.2f, NET %.2f" % (trade.pnl, trade.pnlcomm))

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            # self.log("Order Status: %s" % order.status)
            return

        # Check if an order has been completed
        # Broker could reject order if not enough cash
        if order.status is order.Completed:
            if order.isbuy():
                self.log(
                    "BUY EXECUTED, Price: %.2f, Cost: %.2f, Comm %.2f, Position: %s"
                    % (
                        order.executed.price,
                        order.executed.value,
                        order.executed.comm,
                        self.position,
                    )
                )

            else:  # Sell
                self.log(
                    "SELL EXECUTED, Price: %.2f, Cost: %.2f, Comm %.2f, Position: %s"
                    % (
                        order.executed.price,
                        order.executed.value,
                        order.executed.comm,
                        self.position,
                    )
                )

            self.orders.remove(order)

        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log("Order Canceled/Margin/Rejected")

            self.orders.remove(order)

    def next(self):
        order_price = self.data.close[0]

        buy_signal = self.rsi_signal.buy_signal[0]
        sell_signal = self.rsi_signal.sell_signal[0]

        liquidation_long = (
            self.data.low[0] < (1 - (1 / self.p.leverage)) * self.position.price
        )
        liquidation_short = (
            self.data.high[0] > (1 + (1 / self.p.leverage)) * self.position.price
        )

        flat = self.position.size == 0
        long = self.position.size > 0
        short = self.position.size < 0

        self.log("Close, %.2f, RSI: %.2f" % (order_price, self.rsi[0]))

        def cancel_remaining_limit_orders():
            for order in self.orders:
                if order.status in [Order.Accepted, Order.Partial]:
                    self.log("Cancelling order: %s" % order)
                    self.cancel(order)

        if flat:  # check if there is an open position
            if buy_signal:
                self.send_buy_dca_orders(order_price=order_price)
            if sell_signal:
                self.send_sell_dca_orders(order_price=order_price)

        if long:
            if liquidation_long:
                self.log("Liquidating LONG")
                order = self.close()
                self.orders.append(order)
            if buy_signal:
                self.log("Another buy signal when already long")

            if sell_signal:
                self.log("Closing Long, position: %s" % self.position)
                cancel_remaining_limit_orders()

                order = self.sell(
                    exectype=Order.Market,
                    size=abs(self.position.size),
                )
                self.orders.append(order)
                self.send_sell_dca_orders(order_price=order_price)

        if short:
            if liquidation_short:
                self.log("Liquidating SHORT")
                order = self.close()
                self.orders.append(order)
            if sell_signal:
                self.log("Another sell signal when already short")

            if buy_signal:
                self.log("Closing Short, position: %s" % self.position)
                cancel_remaining_limit_orders()

                order = self.buy(
                    price=order_price,
                    exectype=Order.Market,
                    size=abs(self.position.size),
                )
                self.orders.append(order)
                self.send_buy_dca_orders(order_price=order_price)
