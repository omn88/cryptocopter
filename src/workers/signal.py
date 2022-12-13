from typing import Tuple

import binance
import pandas

from src import features, orders

import logging

logger = logging.getLogger("signal_handle")


async def log_signal_change(df, signal):
    logger.info(
        "Position was %s, position is: %s, signal: %s."
        % (
            df.at[df.index[-2], "position"],
            df.at[df.index[-1], "position"],
            signal,
        )
    )


async def when_flat(
    signal: features.Signals,
    client: binance.AsyncClient,
    position: orders.Position,
    df: pandas.DataFrame,
    entry_price: float,
) -> Tuple[pandas.DataFrame, orders.Position]:
    if signal == features.Signals.LONG:
        position = await orders.futures_long_position_open(
            client=client, position=position, entry_price=entry_price, signal=signal
        )
        df.at[df.index[-1], "position"] = signal
        await log_signal_change(df=df, signal=signal)

    elif signal == features.Signals.LONG_20:
        position = await orders.futures_long_position_open(
            client=client, position=position, entry_price=entry_price, signal=signal
        )
        df.at[df.index[-1], "position"] = signal
        await log_signal_change(df=df, signal=signal)

    elif signal == features.Signals.SHORT:
        position = await orders.futures_short_position_open(
            client=client, position=position, entry_price=entry_price, signal=signal
        )
        df.at[df.index[-1], "position"] = signal
        await log_signal_change(df=df, signal=signal)
    elif signal == features.Signals.SHORT_80:
        position = await orders.futures_short_position_open(
            client=client, position=position, entry_price=entry_price, signal=signal
        )
        df.at[df.index[-1], "position"] = signal
        await log_signal_change(df=df, signal=signal)
    elif signal == features.Signals.NULL:
        df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
        await log_signal_change(df=df, signal=signal)
    else:
        logger.info("Unexpected signal came: %s" % signal)

    return df, position


async def when_long(
    signal: features.Signals,
    client: binance.AsyncClient,
    position: orders.Position,
    df: pandas.DataFrame,
    entry_price: float,
) -> Tuple[pandas.DataFrame, orders.Position]:
    if signal == features.Signals.LONG:
        df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
        await log_signal_change(df=df, signal=signal)
    elif signal == features.Signals.LONG_20:
        df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
        await log_signal_change(df=df, signal=signal)
    elif signal == features.Signals.SHORT:
        position = await orders.futures_long_position_close(
            client=client, position=position
        )

        df.at[df.index[-1], "position"] = position.status
        await log_signal_change(df=df, signal=signal)
        logger.info("Opening DCA Short")
        position = await orders.futures_short_position_open(
            client=client, position=position, entry_price=entry_price, signal=signal
        )

    elif signal == features.Signals.SHORT_80:
        position = await orders.futures_long_position_close(
            client=client, position=position
        )
        df.at[df.index[-1], "position"] = position.status
        await log_signal_change(df=df, signal=signal)
        logger.info("Opening DCA Short")
        position = await orders.futures_short_position_open(
            client=client, position=position, entry_price=entry_price, signal=signal
        )

    elif signal == features.Signals.NULL:
        df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]

    return df, position


async def when_long_twenty(
    signal: features.Signals,
    client: binance.AsyncClient,
    position: orders.Position,
    df: pandas.DataFrame,
    entry_price: float,
) -> Tuple[pandas.DataFrame, orders.Position]:
    if signal == features.Signals.LONG:
        df.at[df.index[-1], "position"] = signal
        await log_signal_change(df=df, signal=signal)
    elif signal == features.Signals.LONG_20:
        df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
        await log_signal_change(df=df, signal=signal)
    elif signal == features.Signals.SHORT:
        position = await orders.futures_long_position_close(
            client=client, position=position
        )

        df.at[df.index[-1], "position"] = position.status
        await log_signal_change(df=df, signal=signal)
        logger.info("Opening DCA Short")
        position = await orders.futures_short_position_open(
            client=client, position=position, entry_price=entry_price, signal=signal
        )

    elif signal == features.Signals.SHORT_80:
        position = await orders.futures_long_position_close(
            client=client, position=position
        )
        df.at[df.index[-1], "position"] = position.status
        await log_signal_change(df=df, signal=signal)
        logger.info("Opening DCA Short")
        position = await orders.futures_short_position_open(
            client=client, position=position, entry_price=entry_price, signal=signal
        )
    elif signal == features.Signals.NULL:
        df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]

    return df, position


async def when_short(
    signal: features.Signals,
    client: binance.AsyncClient,
    position: orders.Position,
    df: pandas.DataFrame,
    entry_price: float,
) -> Tuple[pandas.DataFrame, orders.Position]:
    if signal == features.Signals.LONG:
        position = await orders.futures_short_position_close(
            client=client, position=position
        )
        df.at[df.index[-1], "position"] = position.status
        await log_signal_change(df=df, signal=signal)

        position = await orders.futures_long_position_open(
            client=client, position=position, entry_price=entry_price, signal=signal
        )

    elif signal == features.Signals.LONG_20:
        position = await orders.futures_short_position_close(
            client=client, position=position
        )
        df.at[df.index[-1], "position"] = position.status
        await log_signal_change(df=df, signal=signal)

        position = await orders.futures_long_position_open(
            client=client, position=position, entry_price=entry_price, signal=signal
        )

    elif signal == features.Signals.SHORT:
        df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
        await log_signal_change(df=df, signal=signal)
    elif signal == features.Signals.SHORT_80:
        df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
        await log_signal_change(df=df, signal=signal)
    elif signal == features.Signals.NULL:
        df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]

    return df, position


async def when_short_eighty(
    signal: features.Signals,
    client: binance.AsyncClient,
    position: orders.Position,
    df: pandas.DataFrame,
    entry_price: float,
) -> Tuple[pandas.DataFrame, orders.Position]:
    if signal == features.Signals.LONG:
        position = await orders.futures_short_position_close(
            client=client, position=position
        )
        df.at[df.index[-1], "position"] = position.status
        await log_signal_change(df=df, signal=signal)

        position = await orders.futures_long_position_open(
            client=client, position=position, entry_price=entry_price, signal=signal
        )
    elif signal == features.Signals.LONG_20:
        position = await orders.futures_short_position_close(
            client=client, position=position
        )
        df.at[df.index[-1], "position"] = position.status
        await log_signal_change(df=df, signal=signal)

        position = await orders.futures_long_position_open(
            client=client, position=position, entry_price=entry_price, signal=signal
        )
    elif signal == features.Signals.SHORT:
        df.at[df.index[-1], "position"] = signal
        await log_signal_change(df=df, signal=signal)
    elif signal == features.Signals.SHORT_80:
        df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
        await log_signal_change(df=df, signal=signal)
    elif signal == features.Signals.NULL:
        df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]

    return df, position


async def signal_handle(
    client: binance.AsyncClient,
    df: pandas.DataFrame,
    signal: features.Signals,
    position: orders.Position,
    entry_price: float,
) -> Tuple[pandas.DataFrame, orders.Position]:
    logger.info("Entering signal handle")
    logger.info("Position status: %s" % position.status)

    if position.status == features.Signals.FLAT:
        df, position = await when_flat(
            client=client,
            position=position,
            signal=signal,
            df=df,
            entry_price=entry_price,
        )

    elif position.status == features.Signals.LONG:
        df, position = await when_long(
            client=client,
            position=position,
            signal=signal,
            df=df,
            entry_price=entry_price,
        )

    elif position.status == features.Signals.LONG_20:
        df, position = await when_long_twenty(
            client=client,
            position=position,
            signal=signal,
            df=df,
            entry_price=entry_price,
        )

    elif position.status == features.Signals.SHORT:
        df, position = await when_short(
            client=client,
            position=position,
            signal=signal,
            df=df,
            entry_price=entry_price,
        )

    elif position.status == features.Signals.SHORT_80:
        df, position = await when_short_eighty(
            client=client,
            position=position,
            signal=signal,
            df=df,
            entry_price=entry_price,
        )

    else:
        logger.info("You fucked up something big!")

    return df, position
