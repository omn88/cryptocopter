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


def conditions_for_opening_long(
    status: features.Signals, signal: features.Signals
) -> bool:
    return status == features.Signals.FLAT and signal in [
        features.Signals.LONG,
        features.Signals.LONG_20,
    ]


def conditions_for_opening_short(
    status: features.Signals, signal: features.Signals
) -> bool:
    return status == features.Signals.FLAT and signal in [
        features.Signals.SHORT,
        features.Signals.SHORT_80,
    ]


def conditions_for_skipping_signal(
    status: features.Signals, signal: features.Signals
) -> bool:
    return (
        (
            status == features.Signals.LONG
            and signal in [features.Signals.LONG, features.Signals.LONG_20]
        )
        or (status == features.Signals.LONG_20 and signal == features.Signals.LONG_20)
        or (
            status == features.Signals.SHORT
            and signal in [features.Signals.SHORT, features.Signals.SHORT_80]
        )
        or (status == features.Signals.SHORT_80 and signal == features.Signals.SHORT_80)
        or (
            status == features.Signals.SHORT_SPECIAL
            and signal
            in [
                features.Signals.LONG,
                features.Signals.LONG_20,
                features.Signals.SHORT,
                features.Signals.SHORT_80,
            ]
        )
        or (
            status == features.Signals.LONG_SPECIAL
            and signal
            in [
                features.Signals.LONG,
                features.Signals.LONG_20,
                features.Signals.SHORT,
                features.Signals.SHORT_80,
            ]
        )
    )


def conditions_for_changing_status(
    status: features.Signals, signal: features.Signals
) -> bool:
    return (status == features.Signals.LONG_20 and signal == features.Signals.LONG) or (
        status == features.Signals.SHORT_80 and signal == features.Signals.SHORT
    )


def conditions_for_switch_from_long_to_short(
    status: features.Signals, signal: features.Signals
) -> bool:
    return (
        status == features.Signals.LONG
        and signal in [features.Signals.SHORT, features.Signals.SHORT_80]
    ) or (
        status == features.Signals.LONG_20
        and signal in [features.Signals.SHORT, features.Signals.SHORT_80]
    )


def conditions_for_switch_from_short_to_long(
    status: features.Signals, signal: features.Signals
) -> bool:
    return (
        status == features.Signals.SHORT
        and signal
        in [
            features.Signals.LONG,
            features.Signals.LONG_20,
        ]
    ) or (
        status == features.Signals.SHORT_80
        and signal in [features.Signals.LONG, features.Signals.LONG_20]
    )


def conditions_for_special_long(
    status: features.Signals, signal: features.Signals
) -> bool:
    return status == features.Signals.SHORT and signal == features.Signals.LONG_SPECIAL


def conditions_for_special_short(
    status: features.Signals, signal: features.Signals
) -> bool:
    return status == features.Signals.LONG and signal == features.Signals.SHORT_SPECIAL


def condition_to_close_special_position(
    status: features.Signals, signal: features.Signals
) -> bool:
    return (
        status
        in [
            features.Signals.SHORT_SPECIAL,
            features.Signals.LONG_SPECIAL,
        ]
        and signal == features.Signals.CLOSE_SPECIAL
    )


async def signal_handle(
    client: binance.AsyncClient,
    df: pandas.DataFrame,
    signal_update: SignalUpdate,
    rbf: orders.RsiBasedFutures,
) -> Tuple[pandas.DataFrame, orders.RsiBasedFutures]:
    logger.info("Entering signal handle")
    logger.info("Position status: %s, signal: %s", rbf.status, signal_update.signal)
    signal = signal_update.signal
    price = signal_update.price

    if conditions_for_opening_long(status=rbf.status, signal=signal):
        logger.info("Opening Long")
        rbf = await orders.futures_position_open(
            client=client,
            position=rbf,
            entry_price=price,
            signal=signal,
            side=PositionSide.LONG,
        )
        df.at[df.index[-1], "position"] = signal

    if conditions_for_opening_short(status=rbf.status, signal=signal):
        logger.info("Opening short")
        rbf = await orders.futures_position_open(
            client=client,
            position=rbf,
            entry_price=price,
            signal=signal,
            side=PositionSide.SHORT,
        )
        df.at[df.index[-1], "position"] = signal

    if conditions_for_skipping_signal(status=rbf.status, signal=signal):
        logger.info("Skipping signal: %s", signal)
        df.at[df.index[-1], "position"] = rbf.status

    # CHANGE STATUS (ONLY FOR LONG_20 and SHORT_80)
    if conditions_for_changing_status(status=rbf.status, signal=signal):
        logger.info("Status change from %s to %s", rbf.status, signal)
        rbf.status = signal
        df.at[df.index[-1], "position"] = rbf.status

    if conditions_for_switch_from_long_to_short(status=rbf.status, signal=signal):
        logger.info("Switch from Long to Short")
        rbf = await orders.futures_position_close(client=client, position=rbf)

        logger.info("Long closed, opening DCA Short")
        rbf = await orders.futures_position_open(
            client=client,
            position=rbf,
            entry_price=price,
            signal=signal,
            side=PositionSide.SHORT,
        )
        df.at[df.index[-1], "position"] = signal

    # START SPECIAL SHORT
    if conditions_for_special_short(status=rbf.status, signal=signal):
        logger.info("Start special short")
        rbf = await orders.futures_position_close(client=client, position=rbf)

        df.at[df.index[-1], "position"] = rbf.status
        logger.info("Long closed, opening FULL Short")
        rbf = await orders.futures_position_open(
            client=client,
            position=rbf,
            entry_price=price,
            signal=signal,
            mode=PositionMode.FULL,
            side=PositionSide.SHORT,
        )

        df.at[df.index[-1], "position"] = rbf.status

    # SWITCH FROM SHORT TO LONG
    if conditions_for_switch_from_short_to_long(status=rbf.status, signal=signal):
        logger.info("Switch from Short to Long")
        rbf = await orders.futures_position_close(client=client, position=rbf)
        df.at[df.index[-1], "position"] = signal
        await log_signal_change(df=df, signal=signal)

        rbf = await orders.futures_position_open(
            client=client,
            position=rbf,
            entry_price=price,
            signal=signal,
            side=PositionSide.LONG,
        )

    # OPEN SPECIAL LONG
    if conditions_for_special_long(status=rbf.status, signal=signal):
        logger.info("Opening Special Long")
        rbf = await orders.futures_position_close(client=client, position=rbf)

        logger.info("Short closed, opening FULL Long")
        rbf = await orders.futures_position_open(
            client=client,
            position=rbf,
            entry_price=price,
            signal=signal,
            mode=PositionMode.FULL,
            side=PositionSide.LONG,
        )
        df.at[df.index[-1], "position"] = rbf.status

    if condition_to_close_special_position(status=rbf.status, signal=signal):

        logger.info("Got signal: %s", signal)
        rbf = await orders.futures_position_close(client=client, position=rbf)

        rbf.current_position = CurrentPosition()
        rbf.orders = []
        rbf.status = Signals.FLAT

        df.at[df.index[-1], "position"] = rbf.status

    await log_signal_change(df=df, signal=signal)

    logger.info("Exiting signal handle")
    return df, rbf
