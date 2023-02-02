from typing import Tuple

import binance
import pandas

from src import features, orders

import logging

from src.features import Signals
from src.orders import PositionMode, CurrentPosition, PositionSide
from src.producers.producers import SignalUpdate

logger = logging.getLogger("handle_signal")


async def log_signal_change(df, signal):
    logger.info(
        "Position was %s, signal: %s, position now: %s",
        df.at[df.index[-2], "position"],
        signal,
        df.at[df.index[-1], "position"],
    )


async def signal_handle(
    client: binance.AsyncClient,
    df: pandas.DataFrame,
    signal_update: SignalUpdate,
    position: orders.Position,
) -> Tuple[pandas.DataFrame, orders.Position]:
    logger.info("Entering signal handle")
    logger.info(
        "Position status: %s, signal: %s", position.status, signal_update.signal
    )
    signal = signal_update.signal
    price = signal_update.price

    # OPEN LONG POSITION
    if position.status == features.Signals.FLAT and signal in [
        features.Signals.LONG,
        features.Signals.LONG_20,
    ]:
        logger.info("Opening Long")
        position = await orders.futures_position_open(
            client=client,
            position=position,
            entry_price=price,
            signal=signal,
            side=PositionSide.LONG,
        )
        df.at[df.index[-1], "position"] = signal
        await log_signal_change(df=df, signal=signal)

    # OPEN SHORT POSITION
    if position.status == features.Signals.FLAT and signal in [
        features.Signals.SHORT,
        features.Signals.SHORT_80,
    ]:
        logger.info("Opening short")
        position = await orders.futures_position_open(
            client=client,
            position=position,
            entry_price=price,
            signal=signal,
            side=PositionSide.SHORT,
        )
        df.at[df.index[-1], "position"] = signal

    # SKIP SIGNAL
    if (
        (
            position.status == features.Signals.LONG
            and signal in [features.Signals.LONG, features.Signals.LONG_20]
        )
        or (
            position.status == features.Signals.LONG_20
            and signal == features.Signals.LONG_20
        )
        or (
            position.status == features.Signals.SHORT
            and signal in [features.Signals.SHORT, features.Signals.SHORT_80]
        )
        or (
            position.status == features.Signals.SHORT_80
            and signal == features.Signals.SHORT_80
        )
    ):
        logger.info("Skipping signal: %s", signal)
        df.at[df.index[-1], "position"] = position.status

    # CHANGE STATUS (ONLY FOR LONG_20 and SHORT_80)
    if (
        position.status == features.Signals.LONG_20 and signal == features.Signals.LONG
    ) or (
        position.status == features.Signals.SHORT_80
        and signal == features.Signals.SHORT
    ):
        logger.info("Status change from %s to %s", position.status, signal)
        position.status = signal
        df.at[df.index[-1], "position"] = position.status

    # SWITCH FROM LONG TO SHORT
    if (
        position.status == features.Signals.LONG
        and signal in [features.Signals.SHORT, features.Signals.SHORT_80]
    ) or (
        position.status == features.Signals.LONG_20
        and signal in [features.Signals.SHORT, features.Signals.SHORT_80]
    ):
        logger.info("Switch from Long to Short")
        position = await orders.futures_position_close(client=client, position=position)

        df.at[df.index[-1], "position"] = signal
        logger.info("Long closed, opening DCA Short")
        position = await orders.futures_position_open(
            client=client,
            position=position,
            entry_price=price,
            signal=signal,
            side=PositionSide.SHORT,
        )

    # START SPECIAL SHORT
    if (
        position.status == features.Signals.LONG
        and signal == features.Signals.SHORT_SPECIAL
    ):
        logger.info("Start special short")
        position = await orders.futures_position_close(client=client, position=position)

        df.at[df.index[-1], "position"] = position.status
        logger.info("Long closed, opening FULL Short")
        position = await orders.futures_position_open(
            client=client,
            position=position,
            entry_price=price,
            signal=signal,
            mode=PositionMode.FULL,
            side=PositionSide.SHORT,
        )

        df.at[df.index[-1], "position"] = position.status

    # SWITCH FROM SHORT TO LONG
    if (
        position.status == features.Signals.SHORT
        and signal
        in [
            features.Signals.LONG,
            features.Signals.LONG_20,
        ]
    ) or (
        position.status == features.Signals.SHORT_80
        and signal in [features.Signals.LONG, features.Signals.LONG_20]
    ):
        logger.info("Switch from Short to Long")
        position = await orders.futures_position_close(client=client, position=position)
        df.at[df.index[-1], "position"] = signal
        await log_signal_change(df=df, signal=signal)

        position = await orders.futures_position_open(
            client=client,
            position=position,
            entry_price=price,
            signal=signal,
            side=PositionSide.LONG,
        )

    # OPEN SPECIAL LONG
    if (
        position.status == features.Signals.SHORT
        and signal == features.Signals.LONG_SPECIAL
    ):
        logger.info("Opening Special Long")
        position = await orders.futures_position_close(client=client, position=position)

        logger.info("Short closed, opening FULL Long")
        position = await orders.futures_position_open(
            client=client,
            position=position,
            entry_price=price,
            signal=signal,
            mode=PositionMode.FULL,
            side=PositionSide.LONG,
        )
        df.at[df.index[-1], "position"] = position.status

    # CLOSE SPECIAL LONG
    if position.status in [
        features.Signals.SHORT_SPECIAL,
        features.Signals.LONG_SPECIAL,
    ]:
        if signal in [
            features.Signals.LONG,
            features.Signals.LONG_20,
            features.Signals.SHORT,
            features.Signals.SHORT_80,
        ]:
            logger.info("Special %s, signal: %s, fock it", position.status, signal)

        if signal == features.Signals.CLOSE_SPECIAL:
            logger.info("Got signal: %s", signal)
            position = await orders.futures_position_close(
                client=client, position=position
            )

            position.current_position = CurrentPosition()
            position.orders = []
            position.status = Signals.FLAT

        df.at[df.index[-1], "position"] = position.status

    await log_signal_change(df=df, signal=signal)

    logger.info("Exiting signal handle")
    return df, position
