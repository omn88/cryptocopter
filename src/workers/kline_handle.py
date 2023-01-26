from typing import Tuple, List
import binance
import pandas
from src import features, orders
import logging
from src.common import insert_to_pandas
from src.producers.producers import SignalUpdate
from src.workers.handle_signal import signal_handle
from src.common import print_last_n_rows

logger = logging.getLogger("handle_kline")


async def kline_handle(
    client: binance.AsyncClient,
    df: pandas.DataFrame,
    position: orders.Position,
    historical_data: List,
    kline: List,
) -> Tuple[List, pandas.DataFrame, orders.Position]:
    logger.info("Entering Kline handling")

    expected_index = int(historical_data[-1][0]) + 900000

    # I need historical data here, then add the kline, generate temp dataframe, then copy last
    assert expected_index == kline[0]
    len_hist_data = len(historical_data)
    historical_data.append(kline)
    assert len(historical_data) == len_hist_data + 1
    temp_df = insert_to_pandas(data=historical_data)
    temp_df = features.signals_from_features_generate(df=temp_df)

    df = df.append(temp_df.iloc[-1])
    kline_signal = df.iloc[-1]["signal"]

    # If kline signal is NULL, fock it, else s

    if position.status == features.Signals.LONG and df.iloc[-1]["RSI"] < 18:
        kline_signal = features.Signals.SHORT_SPECIAL

    if position.status == features.Signals.SHORT and df.iloc[-1]["RSI"] > 82:
        kline_signal = features.Signals.SHORT_SPECIAL

    signal_update = SignalUpdate(
        signal=kline_signal,
        price=round(float(df.iloc[-1]["Close"]), 2),
    )

    if kline_signal != 0:
        logger.info(
            "Kline produced new signal: %s, price: %s",
            signal_update.signal,
            signal_update.price,
        )
        df, position = await signal_handle(
            client=client,
            df=df,
            signal_update=signal_update,
            position=position,
        )
    else:
        logger.info("Kline did not produce new signal")

    await print_last_n_rows(df=df)

    logger.info("Exiting Kline handling")
    return historical_data, df, position
