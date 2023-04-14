import asyncio
from typing import Tuple, List
import logging

import pandas

from src.common.common import insert_to_pandas
from src.common.identifiers import (
    Position,
    State,
    Signal,
    SignalUpdate,
    Event,
    EventName,
)
from src.common.common import print_last_n_rows

logger = logging.getLogger("handle_kline")


async def kline_handle(
    kline: List,
    raw_data: List,
    df: pandas.DataFrame,
    position: Position,
    queue: asyncio.Queue,
) -> Tuple[Position, List, pandas.DataFrame]:
    logger.info("Entering Kline handling")

    expected_index = int(raw_data[-1][0]) + 900000

    # I need historical data here, then add the kline, generate temp dataframe, then copy last
    assert expected_index == int(kline[0])
    len_hist_data = len(raw_data)
    raw_data.append(kline)
    assert len(raw_data) == len_hist_data + 1
    temp_df = insert_to_pandas(data=raw_data)
    temp_df = signals_from_features_generate(df=temp_df)

    df = df.append(temp_df.iloc[-1])
    kline_signal = df.iloc[-1]["signal"]

    if position.status == State.LONG_SPECIAL and df.iloc[-1]["RSI"] < 50:
        logger.info("Closing special long")
        kline_signal = Signal.CLOSE_SPECIAL
        df.at[df.index[-1], "signal"] = kline_signal

    if position.status == State.SHORT_SPECIAL and df.iloc[-1]["RSI"] > 50:
        logger.info("Closing special short")
        kline_signal = Signal.CLOSE_SPECIAL
        df.at[df.index[-1], "signal"] = kline_signal

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
        await queue.put(Event(name=EventName.SIGNAL, content=signal_update))
        logger.info(
            "Added signal to queue: signal: %s, price: %s",
            signal_update.signal,
            signal_update.price,
        )
    else:
        df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
        logger.info("Kline did not produce new signal")

    await print_last_n_rows(df=df)

    logger.info("Exiting Kline handling")
    return position, raw_data, df
