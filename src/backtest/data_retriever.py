import os
import pandas as pd
from binance import Client
from binance.exceptions import BinanceRequestException
from decouple import config
import logging
import logging_config
from src.common.constants import SYMBOL, INTERVAL

logger = logging.getLogger("data_retriever")


class DataRetriever:
    def __init__(self, client: Client, symbol: str, interval: str):
        self.client = client
        self.symbol = symbol
        self.interval = interval

    def get_historical_data(self) -> pd.DataFrame:
        historical_data = []
        # Define the start and end date for the data
        start_date = "2019-09-02"
        end_date = "2023-06-09"

        # Convert the date strings to timestamps
        start_ts = int(pd.Timestamp(start_date, tz="utc").timestamp() * 1000)
        end_ts = int(pd.Timestamp(end_date, tz="utc").timestamp() * 1000)

        klines = self.client.futures_historical_klines(
            symbol=self.symbol,
            interval=self.interval,
            start_str=start_ts,
            end_str=end_ts,
        )
        historical_data.extend(klines)

        df = pd.DataFrame(
            historical_data,
            columns=[
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_asset_volume",
                "number_of_trades",
                "taker_buy_base_asset_volume",
                "taker_buy_quote_asset_volume",
                "ignore",
            ],
        )
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")

        # Reorder the DataFrame to fit backtrader's expected column order
        df = df[
            [
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "quote_asset_volume",
            ]
        ]
        df.rename(
            columns={"open_time": "datetime", "quote_asset_volume": "openinterest"},
            inplace=True,
        )

        return df

    def save_to_csv(self):
        df = self.get_historical_data()
        logger.info("got historical data")
        os.makedirs(f"data/{self.symbol}", exist_ok=True)
        df.to_csv(
            f"data/{self.symbol}/{self.interval}_historical_klines.csv", index=False
        )


def main():
    client = Client(
        api_key=config("FUTURES_API_KEY"), api_secret=config("FUTURES_API_SECRET")
    )
    data_retriever = DataRetriever(client=client, symbol=SYMBOL, interval=INTERVAL)
    data_retriever.save_to_csv()
    client.close_connection()


if __name__ == "__main__":
    main()
