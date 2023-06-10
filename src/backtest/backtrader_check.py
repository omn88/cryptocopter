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
        ("rsi_low1", 30),
        ("rsi_low2", 20),
        ("rsi_high1", 70),
        ("rsi_high2", 80),
        ("dca_orders", 4),
        ("dca_span", 0.005),
        ("value", 4),
    )

    def __init__(self):
        self.rsi = bt.ind.RSI(self.data.close)
        super(CustomRSISignal, self).__init__()

    def next(self):
        # Buy signals
        if (
            self.rsi[-3] < self.p.rsi_low1
            and self.rsi[-2] > self.p.rsi_low1
            and self.rsi[-1] > self.p.rsi_low1
        ):
            self.lines.buy_signal[0] = True
        elif self.rsi[-2] < self.p.rsi_low2 and self.rsi[-1] > self.p.rsi_low2:
            self.lines.buy_signal[0] = True
        else:
            self.lines.buy_signal[0] = False

        # Sell signals
        if (
            self.rsi[-3] > self.p.rsi_high1
            and self.rsi[-2] < self.p.rsi_high1
            and self.rsi[-1] < self.p.rsi_high1
        ):
            self.lines.sell_signal[0] = True
        elif self.rsi[-2] > self.p.rsi_high2 and self.rsi[-1] < self.p.rsi_high2:
            self.lines.sell_signal[0] = True
        else:
            self.lines.sell_signal[0] = False


class StrategyRsiExtended(bt.Strategy):
    params = (
        ("dca_orders", 4),
        ("dca_span", 0.005),
        ("value", 4),
    )

    def __init__(self):
        self.rsi_signal = CustomRSISignal(self.data)

    def next(self):
        if self.position.size == 0:  # check if there is an open position
            if self.rsi_signal.buy_signal[0] == 1:
                order_price = self.data.close[0]
                for i in range(self.p.dca_orders):
                    self.buy(
                        price=order_price - self.p.dca_span * i,
                        size=self.p.value,
                        exectype="Order.Limit",
                    )
            elif self.rsi_signal.sell_signal[0] == 1:
                order_price = self.data.close[0]
                for i in range(self.p.dca_orders):
                    self.sell(
                        price=order_price + self.p.dca_span * i,
                        size=self.p.value,
                        exectype="Order.Limit",
                    )


class PandasDataWithSignals(PandasData):
    lines = ("rsi_signal",)
    params = (("rsi_signal", -1),)


cerebro = bt.Cerebro()

# Load the CSV file into a pandas DataFrame
df = pd.read_csv("data/BTCUSDT/test.csv")
df["datetime"] = pd.to_datetime(df["datetime"])
df.set_index("datetime", inplace=True)


# Create a data feed
data = PandasDataWithSignals(dataname=df)
cerebro.adddata(data)
cerebro.addstrategy(StrategyRsiExtended)
cerebro.run()

cerebro.plot(style="candlestick")
logger.info("DONE")
