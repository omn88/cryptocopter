import backtrader as bt
import pandas as pd
import json
from datetime import datetime


class CrossOver(bt.Strategy):
    def __init__(self):
        self.sma = bt.ind.SMA(period=50)
        self.crossover = bt.ind.CrossOver(self.data.close, self.sma)

    def next(self):
        if not self.position:  # not in the market
            if self.crossover > 0:  # if fast crosses slow to the upside
                self.buy()  # enter long
        elif self.crossover < 0:  # in the market & cross to the downside
            self.close()  # close long position


# Create a backtest
cerebro = bt.Cerebro()
cerebro.addstrategy(CrossOver)

# Load the JSON data
with open("data/BTCUSDT/15m_historical_klines.json", "r") as f:
    data_dict = json.load(f)

# Convert the JSON data to a pandas DataFrame
data_df = pd.DataFrame(data_dict)
data_df["open_time"] = pd.to_datetime(data_df["open_time"])
data_df.set_index("open_time", inplace=True)

# Convert string data to float
for col in ["open", "high", "low", "close", "volume"]:
    data_df[col] = data_df[col].astype(float)


class CustomPandasData(bt.feeds.PandasData):
    # Define the 'lines' (fields) that your data feed will provide
    lines = (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "taker_buy_base_asset_volume",
        "taker_buy_quote_asset_volume",
    )

    # Define parameters for 'lines'
    params = (
        ("datetime", None),  # pandas datetime column (index)
        ("open", -1),
        ("high", -1),
        ("low", -1),
        ("close", -1),
        ("volume", -1),
        ("openinterest", None),
        ("taker_buy_base_asset_volume", -1),
        ("taker_buy_quote_asset_volume", -1),
    )


# Create a Data Feed
data = CustomPandasData(dataname=data_df)

# Add the Data Feed to Cerebro
cerebro.adddata(data)

# Run the backtest
cerebro.run()

# Plot the result
cerebro.plot(style="candlestick")
