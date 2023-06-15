import backtrader as bt
import pandas as pd
from backtrader.feeds import PandasData
import logging
import logging_config

logger = logging.getLogger("backtrader")


class CustomRSISignal(bt.Indicator):
    lines = (
        "buy_signal",
        "sell_signal",
    )
    params = (
        ("rsi_low", 30),
        ("rsi_high", 70),
        ("dca_orders", 4),
        ("dca_span", 0.005),
    )

    def __init__(self):
        self.rsi = bt.ind.RSI(self.data.close)
        super(CustomRSISignal, self).__init__()

    def next(self):
        # Buy signals
        if (
            self.rsi[-2] < self.p.rsi_low
            and self.rsi[-1] > self.p.rsi_low
            and self.rsi[0] > self.p.rsi_low
        ):
            self.lines.buy_signal[0] = True
        else:
            self.lines.buy_signal[0] = False

        # Sell signals
        if (
            self.rsi[-2] > self.p.rsi_high
            and self.rsi[-1] < self.p.rsi_high
            and self.rsi[0] < self.p.rsi_high
        ):
            self.lines.sell_signal[0] = True
        else:
            self.lines.sell_signal[0] = False


class StrategyRsiBasic(bt.Strategy):
    def log(self, txt, dt=None):
        """Logging function fot this strategy"""
        dt = dt or self.datas[0].datetime.datetime(0)
        print("%s, %s" % (dt.strftime("%Y-%m-%d %H:%M"), txt))

    params = (
        ("dca_orders", 4),
        ("dca_span", 0.005),
        ("value", 4),
        ("period", 14),
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI_SMA(self.data.close, period=self.params.period, plothlines=[20, 30, 70, 80],)
        self.rsi_signal = CustomRSISignal(self.data)


    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            # Order submitted/accepted to/by broker - Nothing to do
            return

        # Check if an order has been completed
        # Broker could reject order if not enough cash
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(
                    "BUY EXECUTED, Price: %.2f, Cost: %.2f, Comm %.2f"
                    % (order.executed.price, order.executed.value, order.executed.comm)
                )

            else:  # Sell
                self.log(
                    "SELL EXECUTED, Price: %.2f, Cost: %.2f, Comm %.2f"
                    % (order.executed.price, order.executed.value, order.executed.comm)
                )

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log("Order Canceled/Margin/Rejected")

        # Write down: no pending order
        self.order = None

    def next(self):
        self.log("Close, %.2f, RSI: %.2f" % (self.data.close[0], self.rsi[0]))

        if self.position.size == 0:  # check if there is an open position
            if self.rsi_signal.buy_signal[0] == 1:
                order_price = self.data.close[0]
                self.log("Buy signal at price: %s" % order_price)

                self.buy()

                # for i in range(self.p.dca_orders):
                #     self.buy(
                #         price=order_price - self.p.dca_span * i,
                #         exectype="Limit",
                #     )
            elif self.rsi_signal.sell_signal[0] == 1:
                order_price = self.data.close[0]
                self.log("Sell signal at price: %s" % order_price)

                # for i in range(self.p.dca_orders):
                #     self.sell(
                #         price=order_price + self.p.dca_span * i,
                #         exectype="Limit",
                #     )

                self.sell()


class PandasDataWithSignals(PandasData):
    lines = ("rsi_signal",)
    params = (("rsi_signal", -1),)


cerebro = bt.Cerebro()


# Set up the backwriter for logging
cerebro.addwriter(bt.WriterFile, out="backtrader_log.csv", csv=True)

# Load the CSV file into a pandas DataFrame
df = pd.read_csv("data/BTCUSDT/recent.csv")

# Convert the 'datetime' column to datetime format and adjust to your timezone
df['datetime'] = pd.to_datetime(df['datetime'])
# Add 2 hours to the datetime column to convert to UTC+2
df['datetime'] = df['datetime'] + pd.Timedelta(hours=2)

df.set_index("datetime", inplace=True)


# Create a data feed
data = PandasDataWithSignals(
    dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15
)
cerebro.adddata(data)
cerebro.addstrategy(StrategyRsiBasic)
cerebro.run()

# cerebro.plot(style="candle")
logger.info("DONE")
