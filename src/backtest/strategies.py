import backtrader as bt
from backtrader import Order

from src.backtest.signals import BasicRSISignal


class StrategyRsiBasic(bt.Strategy):
    params = (
        ("dca_orders", 4),
        ("dca_span", 0.005),
        ("value", 4),
        ("period", 14),
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
                size=0.01,
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
                size=0.01,
            )
            self.log("Sell order send at price %s" % round(price, 2))
            self.orders.append(order)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        # Check if an order has been completed
        # Broker could reject order if not enough cash
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(
                    "BUY EXECUTED, Price: %.2f, Cost: %.2f, Comm %.2f, Position size %.2f"
                    % (
                        order.executed.price,
                        order.executed.value,
                        order.executed.comm,
                        self.position.size,
                    )
                )

            else:  # Sell
                self.log(
                    "SELL EXECUTED, Price: %.2f, Cost: %.2f, Comm %.2f, Position size %.2f"
                    % (
                        order.executed.price,
                        order.executed.value,
                        order.executed.comm,
                        self.position.size,
                    )
                )

            self.orders.remove(order)

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log("Order Canceled/Margin/Rejected")

            self.orders.remove(order)

    def next(self):
        self.log("Close, %.2f, RSI: %.2f" % (self.data.close[0], self.rsi[0]))

        order_price = self.data.close[0]

        # self.log("Position size: %s" % self.position.size)

        if self.position.size == 0:  # check if there is an open position
            if self.rsi_signal.buy_signal[0] == 1:
                self.send_buy_dca_orders(order_price=order_price)

            elif self.rsi_signal.sell_signal[0] == 1:
                self.send_sell_dca_orders(order_price=order_price)

        else:
            if self.position.size > 0:
                if self.rsi_signal.buy_signal[0] == 1:
                    self.log("Another buy signal when already long")
                else:
                    if self.rsi_signal.sell_signal[0] == 1:
                        order = self.sell(
                            price=order_price,
                            exectype=Order.Market,
                            size=abs(self.position.size),
                        )
                        self.orders.append(order)
                        self.send_sell_dca_orders(order_price=order_price)

            if self.position.size < 0:
                if self.rsi_signal.sell_signal[0] == 1:
                    self.log("Another sell signal when already short")
                else:
                    if self.rsi_signal.buy_signal[0] == 1:
                        order = self.buy(
                            price=order_price,
                            exectype=Order.Market,
                            size=abs(self.position.size),
                        )
                        self.orders.append(order)
                        self.send_buy_dca_orders(order_price=order_price)
