import backtrader as bt
import pandas as pd
from backtrader.feeds import PandasData
import logging
import logging_config
from src.backtest.strategies import StrategyRsiBasic

logger = logging.getLogger("backtrader")


class PandasDataWithSignals(PandasData):
    lines = ("rsi_signal",)
    params = (("rsi_signal", -1),)


def run_strategy(start_timestamp, end_timestamp):
    cerebro = bt.Cerebro()

    # Set up the backwriter for logging
    cerebro.addwriter(bt.WriterFile, out="backtrader_log.csv", csv=True)

    # Load the CSV file into a pandas DataFrame
    df = pd.read_csv("data/BTCUSDT/15m_historical_klines.csv")

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
    cerebro.addstrategy(StrategyRsiBasic)
    cerebro.run()

    cerebro.plot(style="candle")


# Usage example
run_strategy("2023-05-01 00:00:00", "2023-05-10 00:00:00")
