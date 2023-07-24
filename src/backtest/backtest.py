import backtrader as bt
import pandas as pd
from backtrader.feeds import PandasData
import logging

from src.backtest.strategies.rsi_extended import StrategyRsiExtended

logger = logging.getLogger("backtrader")


class PandasDataWithSignals(PandasData):
    lines = ("rsi_signal",)
    params = (("rsi_signal", -1),)


class CommInfoFutures(bt.CommInfoBase):
    """Custom commission scheme for futures"""

    params = (
        # ("commission", 0.032),
        ("stocklike", False),
        ("commtype", bt.CommInfoBase.COMM_FIXED),
        ("percabs", True),
        # Add more parameters if necessary
    )


def run_strategy(start_timestamp, end_timestamp):
    cerebro = bt.Cerebro()

    comminfo = CommInfoFutures(mult=25)  # leverage of 25
    cerebro.broker.addcommissioninfo(comminfo)

    cerebro.broker.setcash(80000.0)  # cash set to reflect leverage

    # Set up the backwriter for logging
    cerebro.addwriter(bt.WriterFile, out="backtrader_log.csv", csv=True)

    # Load the CSV file into a pandas DataFrame
    df = pd.read_csv("data/BTCUSDT/15m_historical_klines_full.csv")

    # Convert the 'datetime' column to datetime format and adjust to your timezone
    df["datetime"] = pd.to_datetime(df["datetime"])
    # Add 2 hours to the datetime column to convert to UTC+2
    df["datetime"] = df["datetime"] + pd.Timedelta(hours=2)

    df.set_index("datetime", inplace=True)

    # Filter dataframe based on start and end timestamps
    start = pd.to_datetime(start_timestamp)
    end = pd.to_datetime(end_timestamp)
    df = df.loc[start:end]

    # Create a data feed
    data = PandasDataWithSignals(
        dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15
    )
    cerebro.adddata(data)
    cerebro.addstrategy(StrategyRsiExtended)
    cerebro.run()

    cerebro.plot(style="candle")


# Usage example
run_strategy("2023-06-24 00:00:00", "2023-07-24 00:00:00")
