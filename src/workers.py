import asyncio
import json
import logging

import binance

import lib
import pandas
import features
import producers

logger = logging.getLogger("worker")


async def signal_handle(
    df: pandas.DataFrame, signal: features.Signals
) -> pandas.DataFrame:

    if signal == features.Signals.FLAT:
        if df.position == features.Signals.FLAT:
            logger.info(
                "Current position is: %s and signal: %s. Duuu Nateng"
                % (df.position, signal)
            )
        if df.position == features.Signals.LONG:
            df.at[df.index, "position"] = signal
            logger.info(
                "Current position is: %s and signal: %s. Change to FLAT"
                % (df.position, signal)
            )
        if df.position == features.Signals.LONG_20:
            df.at[df.index, "position"] = signal
            logger.info(
                "Current position is: %s and signal: %s. Change to FLAT"
                % (df.position, signal)
            )
        if df.position == features.Signals.SHORT:
            df.at[df.index, "position"] = signal
            logger.info(
                "Current position is: %s and signal: %s. Change to FLAT"
                % (df.position, signal)
            )
        if df.position == features.Signals.SHORT_80:
            df.at[df.index, "position"] = signal
            logger.info(
                "Current position is: %s and signal: %s. Change to FLAT"
                % (df.position, signal)
            )

    elif signal == features.Signals.LONG:
        if df.position == features.Signals.FLAT:
            logger.info(
                "Current position is: %s and signal: %s. Open Long!"
                % (df.position, signal)
            )

        if df.position == features.Signals.LONG:
            df.at[df.index, "position"] = signal
            logger.info(
                "Current position is: %s and signal: %s. Change to FLAT"
                % (df.position, signal)
            )
        if df.position == features.Signals.LONG_20:
            df.at[df.index, "position"] = signal
            logger.info(
                "Current position is: %s and signal: %s. Change to FLAT"
                % (df.position, signal)
            )
        if df.position == features.Signals.SHORT:
            df.at[df.index, "position"] = signal
            logger.info(
                "Current position is: %s and signal: %s. Change to FLAT"
                % (df.position, signal)
            )
        if df.position == features.Signals.SHORT_80:
            df.at[df.index, "position"] = signal
            logger.info(
                "Current position is: %s and signal: %s. Change to FLAT"
                % (df.position, signal)
            )

    return df


async def user_socket_data_handle():
    pass


async def worker(
    df: pandas.DataFrame,
    queue: asyncio.Queue,
    client: binance.AsyncClient,
    symbol: str,
    interval: str,
):
    while True:
        task = await queue.get()

        if isinstance(task, producers.Event):
            logger.info(task)
            if producers.EventName.Kline == task.name:
                temp_df = await lib.get_futures_historical_data(
                    client=client,
                    symbol=symbol,
                    interval=interval,
                    lookback="3360",  # 44000 is approximately one month
                )
                temp_df = features.signals_from_features_generate(df=temp_df)
                temp_df["position"] = df.at[df.index[-1], "position"]
                if temp_df.iloc[-1, "signal"] != 0:
                    temp_df = await signal_handle(
                        df=temp_df, signal=temp_df.iloc[-1]["signal"]
                    )
                df = df.append(temp_df.iloc[-1])

            elif producers.EventName.User == producers.Event.name:
                await user_socket_data_handle()
        elif isinstance(task, features.Signals):
            logger.info(task)
            df = await signal_handle(df=df, signal=task)

        queue.task_done()
