from typing import Tuple

import binance
import pandas

from src import features, orders
from src.backtest import lib

import logging

logger = logging.getLogger("handle_signal")


async def log_signal_change(df, signal):
    logger.info(
        "Position was %s, signal: %s, position now: %s"
        % (
            df.at[df.index[-2], "position"],
            signal,
            df.at[df.index[-1], "position"],
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
        logger.info("Long closed, opening DCA Short")
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
        position.status = signal
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
        position.status = signal
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


async def kline_handle(
    client: binance.AsyncClient,
    symbol: str,
    interval: str,
    df: pandas.DataFrame,
    position: orders.Position,
) -> Tuple[pandas.DataFrame, orders.Position]:
    logger.info("Entering Kline handling")
    # await print_last_n_rows(df=df)

    temp_df = await lib.get_futures_historical_data(
        client=client,
        symbol=symbol,
        interval=interval,
        lookback="3360",  # 44000 is approximately one month
    )
    logger.info("DF: \n%s", df.to_string())
    logger.info("TEMP DF: \n%s", temp_df.to_string())
    temp_df = features.signals_from_features_generate(df=temp_df)
    logger.info("LAST POSITION %s", df.at[df.index[-1], "position"])
    temp_df["position"] = df.at[df.index[-1], "position"]
    kline_signal = temp_df.iloc[-1]["signal"]
    if kline_signal == 0:
        kline_signal = features.Signals.NULL

    logger.info("Kline produced new signal: %s" % kline_signal.value)

    df = df.append(temp_df.iloc[-1])

    logger.info("NEW DF: \n%s", df.to_string())

    df, position = await signal_handle(
        client=client,
        df=df,
        signal=kline_signal,
        position=position,
        entry_price=df.at[df.index[-1], "Close"],
    )
    logger.info("Exiting Kline handling")
    return df, position
