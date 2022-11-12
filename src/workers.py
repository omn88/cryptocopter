import asyncio
import logging
from typing import Tuple

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
    position: orders.Position,
) -> Tuple[pandas.DataFrame, orders.Position]:

    logger.info("Entering signal handle")
    current_position = position.status

    if current_position == features.Signals.FLAT:
        if signal == features.Signals.LONG:
            position = await orders.futures_long_position_open(
                client=client, position=position, signal=signal
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
            position = await orders.futures_long_position_open(
                client=client, position=position, signal=signal
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
            position = await orders.futures_short_position_open(
                client=client, position=position, signal=signal
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
            position = await orders.futures_short_position_open(
                client=client, position=position, signal=signal
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
        elif signal == features.Signals.NULL:
            df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
        elif signal == features.Signals.FLAT:
            df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]

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
            position = await orders.futures_long_position_close(
                client=client, position=position
            )

            df.at[df.index[-1], "position"] = position.status
            logger.info(
                "Position was %s, position is: %s, signal: %s. Long closed!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
            logger.info("Opening DCA Short")
            position = await orders.futures_short_position_open(
                client=client, position=position, signal=signal
            )

        elif signal == features.Signals.SHORT_80:
            position = await orders.futures_long_position_close(
                client=client, position=position
            )
            df.at[df.index[-1], "position"] = position.status
            logger.info(
                "Position was %s, position is: %s, signal: %s. Long closed!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
            logger.info("Opening DCA Short")
            position = await orders.futures_short_position_open(
                client=client, position=position, signal=signal
            )

        elif signal == features.Signals.NULL:
            df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]

    elif current_position == features.Signals.LONG_20:
        if signal == features.Signals.LONG:
            df.at[df.index[-1], "position"] = signal
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
            position = await orders.futures_long_position_close(
                client=client, position=position
            )

            df.at[df.index[-1], "position"] = position.status
            logger.info(
                "Position was %s, position is: %s, signal: %s. Long closed!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
            logger.info("Opening DCA Short")
            position = await orders.futures_short_position_open(
                client=client, position=position, signal=signal
            )

        elif signal == features.Signals.SHORT_80:
            position = await orders.futures_long_position_close(
                client=client, position=position
            )
            df.at[df.index[-1], "position"] = position.status
            logger.info(
                "Position was %s, position is: %s, signal: %s. Long closed!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )
            logger.info("Opening DCA Short")
            position = await orders.futures_short_position_open(
                client=client, position=position, signal=signal
            )
        elif signal == features.Signals.NULL:
            df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]

    elif current_position == features.Signals.SHORT:
        if signal == features.Signals.LONG:
            position = await orders.futures_short_position_close(
                client=client, position=position
            )
            df.at[df.index[-1], "position"] = position.status
            logger.info(
                "Position was %s, position is: %s, signal: %s. Short closed!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )

            position = await orders.futures_long_position_open(
                client=client, position=position, signal=signal
            )

        elif signal == features.Signals.LONG_20:
            position = await orders.futures_short_position_close(
                client=client, position=position
            )
            df.at[df.index[-1], "position"] = position.status
            logger.info(
                "Position was %s, position is: %s, signal: %s. Short closed!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )

            position = await orders.futures_long_position_open(
                client=client, position=position, signal=signal
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
        elif signal == features.Signals.NULL:
            df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]

    elif current_position == features.Signals.SHORT_80:
        if signal == features.Signals.LONG:
            position = await orders.futures_short_position_close(
                client=client, position=position
            )
            df.at[df.index[-1], "position"] = position.status
            logger.info(
                "Position was %s, position is: %s, signal: %s. Short closed!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )

            position = await orders.futures_long_position_open(
                client=client, position=position, signal=signal
            )
        elif signal == features.Signals.LONG_20:
            position = await orders.futures_short_position_close(
                client=client, position=position
            )
            df.at[df.index[-1], "position"] = position.status
            logger.info(
                "Position was %s, position is: %s, signal: %s. Short closed!"
                % (
                    df.at[df.index[-2], "position"],
                    df.at[df.index[-1], "position"],
                    signal,
                )
            )

            position = await orders.futures_long_position_open(
                client=client, position=position, signal=signal
            )
        elif signal == features.Signals.SHORT:
            df.at[df.index[-1], "position"] = signal
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
        elif signal == features.Signals.NULL:
            df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
    else:
        logger.info("You fucked up something big!")

    return df, position


async def user_socket_data_handle(
    df: pandas.DataFrame, position: orders.Position
) -> Tuple[pandas.DataFrame, orders.Position]:
    return df, position


async def worker(
    start_df: pandas.DataFrame,
    queue: asyncio.Queue,
    client: binance.AsyncClient,
    symbol: str,
    interval: str,
    saldo: float,
):
    df = start_df
    position = orders.Position(
        current_position=orders.Order(price=0, quantity=0, order_id=0),
        orders=[],
        status=features.Signals.FLAT,
        saldo=saldo,
        symbol=symbol,
    )

    while True:
        task = await queue.get()

        if isinstance(task, producers.Event):
            logger.info("New event came: %s" % task.name)
            if producers.EventName.Kline == task.name:
                temp_df = await lib.get_futures_historical_data(
                    client=client,
                    symbol=symbol,
                    interval=interval,
                    lookback="3360",  # 44000 is approximately one month
                )
                temp_df = features.signals_from_features_generate(df=temp_df)
                temp_df["position"] = df.at[df.index[-1], "position"]
                temp_df, position = await signal_handle(
                    client=client,
                    df=temp_df,
                    signal=temp_df.iloc[-1]["signal"],
                    position=position,
                )
                last_rows = 5
                logger.info(
                    "Last %d rows from main df: %s"
                    % (last_rows, "\n%s" % df.tail(last_rows).to_string())
                )
                df = df.append(temp_df.iloc[-1])

                last_rows = 5
                logger.info(
                    "Last %d rows from main df after new row append: %s"
                    % (last_rows, "\n%s" % df.tail(last_rows).to_string())
                )

            elif producers.EventName.User == producers.Event.name:
                logger.info("Some data from user socket came: %s" % task.content)
                new_df, new_position = await user_socket_data_handle(
                    df=df, position=position
                )
                df = new_df
                position = new_position
                logger.info("New DF: %s, new position: %s" % (new_df, new_position))
        elif isinstance(task, features.Signals):
            logger.info("New signal came: %s" % task)

            last_rows = 5
            logger.info(
                "Last %d rows from main df: %s"
                % (last_rows, "\n%s" % df.tail(last_rows).to_string())
            )

            new_df, new_position = await signal_handle(
                client=client,
                df=df,
                signal=task,
                position=position,
            )
            df = new_df
            position = new_position

            last_rows = 5
            logger.info(
                "Last %d rows from main df after signal handle: %s"
                % (last_rows, "\n%s" % df.tail(last_rows).to_string())
            )

            # logger.info("New DF: %s, new position: %s" % (new_df, new_position))
        queue.task_done()
