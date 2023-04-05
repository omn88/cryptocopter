import asyncio
from typing import Tuple, List
import binance
import pandas
from src import features, orders
import logging
from src.common.common import insert_to_pandas
from src.features.features import signals_from_features_generate, State, Signal
from src.orders import Position
from src.producers.producers import SignalUpdate
from src.workers.state_actions import signal_handle
from src.common.common import print_last_n_rows
from src.workers.trading_state_machine import TradingStateMachine

logger = logging.getLogger("handle_kline")


async def kline_handle(
    position: Position,
    historical_data: List,
    kline: List,
    state_machine: TradingStateMachine,
) -> Tuple[List, Position]:
    logger.info("Entering Kline handling")

    expected_index = int(historical_data[-1][0]) + 900000

    # I need historical data here, then add the kline, generate temp dataframe, then copy last
    assert expected_index == int(kline[0])
    len_hist_data = len(historical_data)
    historical_data.append(kline)
    assert len(historical_data) == len_hist_data + 1
    temp_df = insert_to_pandas(data=historical_data)
    temp_df = signals_from_features_generate(df=temp_df)

    df = state_machine.df.append(temp_df.iloc[-1])
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
        position, tsm = await signal_handle(
            signal_update=signal_update,
            position=position,
            state_machine=state_machine,
        )
    else:
        df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
        logger.info("Kline did not produce new signal")

    await print_last_n_rows(df=df)

    logger.info("Exiting Kline handling")
    return historical_data, position
