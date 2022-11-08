import asyncio
import logging

import binance

import lib
import pandas
import features
import producers
import orders

logger = logging.getLogger("worker")


async def signal_handle(
    client: binance.AsyncClient,
    df: pandas.DataFrame,
    signal: features.Signals,
    saldo: float,
    symbol: str,
) -> pandas.DataFrame:

    current_position = df.at[df.index[-1], "position"]

    if current_position == features.Signals.FLAT:
        if signal == features.Signals.LONG:
            dca_orders, position = orders.futures_long_position_open(
                client=client, saldo=saldo, symbol=symbol
            )
            df.at[df.index[-1], "position"] = signal
            logger.info(
                "Position was %s, position is: %s, signal: %s. Long opened!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
        elif signal == features.Signals.LONG_20:
            dca_orders, position = orders.futures_long_position_open(
                client=client, saldo=saldo, symbol=symbol
            )
            df.at[df.index[-1], "position"] = signal
            logger.info(
                "Position was %s, position is: %s, signal: %s. Long opened!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
        elif signal == features.Signals.SHORT:
            dca_orders, position = orders.futures_short_position_open(
                client=client, saldo=saldo, symbol=symbol
            )
            df.at[df.index[-1], "position"] = signal
            logger.info(
                "Position was %s, position is: %s, signal: %s. Short opened!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
        elif signal == features.Signals.SHORT_80:
            dca_orders, position = orders.futures_short_position_open(
                client=client, saldo=saldo, symbol=symbol
            )
            df.at[df.index[-1], "position"] = signal
            logger.info(
                "Position was %s, position is: %s, signal: %s. Short opened!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )

    elif current_position == features.Signals.LONG:
        if signal == features.Signals.LONG:
            df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
            logger.info(
                "Position was %s, position is: %s, signal: %s. Du Nateng"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
        elif signal == features.Signals.LONG_20:
            df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
            logger.info(
                "Position was %s, position is: %s, signal: %s. Du Nateng"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
        elif signal == features.Signals.SHORT:
            await orders.futures_long_position_close(client=client, symbol=symbol)
            df.at[df.index[-1], "position"] = features.Signals.FLAT
            logger.info(
                "Position was %s, position is: %s, signal: %s. Long closed!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
        elif signal == features.Signals.SHORT_80:
            await orders.futures_long_position_close(client=client, symbol=symbol)
            df.at[df.index[-1], "position"] = features.Signals.FLAT
            logger.info(
                "Position was %s, position is: %s, signal: %s. Long closed!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )

    elif current_position == features.Signals.LONG_20:
        if signal == features.Signals.LONG:
            df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
            logger.info(
                "Position was %s, position is: %s, signal: %s. Du Nateng"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
        elif signal == features.Signals.LONG_20:
            df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
            logger.info(
                "Position was %s, position is: %s, signal: %s. Du Nateng"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
        elif signal == features.Signals.SHORT:
            await orders.futures_long_position_close(client=client, symbol=symbol)
            df.at[df.index[-1], "position"] = features.Signals.FLAT
            logger.info(
                "Position was %s, position is: %s, signal: %s. Long closed!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
        elif signal == features.Signals.SHORT_80:
            await orders.futures_long_position_close(client=client, symbol=symbol)
            df.at[df.index[-1], "position"] = features.Signals.FLAT
            logger.info(
                "Position was %s, position is: %s, signal: %s. Long closed!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )

    elif current_position == features.Signals.SHORT:
        if signal == features.Signals.LONG:
            await orders.futures_short_position_close(client=client, symbol=symbol)
            df.at[df.index[-1], "position"] = features.Signals.FLAT
            logger.info(
                "Position was %s, position is: %s, signal: %s. Short closed!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
        elif signal == features.Signals.LONG_20:
            await orders.futures_short_position_close(client=client, symbol=symbol)
            df.at[df.index[-1], "position"] = features.Signals.FLAT
            logger.info(
                "Position was %s, position is: %s, signal: %s. Short closed!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
        elif signal == features.Signals.SHORT:
            df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
            logger.info(
                "Position was %s, position is: %s, signal: %s. Du Nateng"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
        elif signal == features.Signals.SHORT_80:
            df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
            logger.info(
                "Position was %s, position is: %s, signal: %s. Du Nateng"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
    elif current_position == features.Signals.SHORT_80:
        if signal == features.Signals.LONG:
            await orders.futures_short_position_close(client=client, symbol=symbol)
            df.at[df.index[-1], "position"] = features.Signals.FLAT
            logger.info(
                "Position was %s, position is: %s, signal: %s. Short closed!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
        elif signal == features.Signals.LONG_20:
            await orders.futures_short_position_close(client=client, symbol=symbol)
            df.at[df.index[-1], "position"] = features.Signals.FLAT
            logger.info(
                "Position was %s, position is: %s, signal: %s. Short closed!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
        elif signal == features.Signals.SHORT:
            df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
            logger.info(
                "Position was %s, position is: %s, signal: %s. Du Nateng"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
        elif signal == features.Signals.SHORT_80:
            df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
            logger.info(
                "Position was %s, position is: %s, signal: %s. Du Nateng"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
    else:
        logger.info("You fucked up something big!")

    return df


async def user_socket_data_handle():
    pass


async def worker(
    df: pandas.DataFrame,
    queue: asyncio.Queue,
    client: binance.AsyncClient,
    symbol: str,
    interval: str,
    saldo: float,
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
                temp_df = await signal_handle(
                    client=client,
                    df=temp_df,
                    signal=temp_df.iloc[-1]["signal"],
                    saldo=saldo,
                    symbol=symbol,
                )
                df = df.append(temp_df.iloc[-1])

            elif producers.EventName.User == producers.Event.name:
                await user_socket_data_handle()
        elif isinstance(task, features.Signals):
            logger.info(task)
            df = await signal_handle(
                client=client, df=df, signal=task, saldo=saldo, symbol=symbol
            )

        queue.task_done()
