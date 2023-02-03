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


async def futures_long_position_open(
    position: orders.Position,
    client: binance.AsyncClient,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
) -> Tuple[orders.Position, pandas.DataFrame]:
    logger.info("Opening Long")
    position.current_position = await orders.futures_position_open(
        client=client,
        entry_price=signal_update.price,
        signal=signal_update.signal,
        side=PositionSide.LONG,
        balance=position.balance,
        leverage=position.leverage,
        number_of_dca_orders=position.number_of_dca_orders,
        order_quantity_list=position.order_quantity_list,
        symbol=position.symbol,
    )
    df.at[df.index[-1], "position"] = signal_update.signal

    return position, df


async def futures_short_position_open(
    position: orders.Position,
    signal_update: SignalUpdate,
    client: binance.AsyncClient,
    df: pandas.DataFrame,
) -> Tuple[orders.Position, pandas.DataFrame]:
    logger.info("Opening short")
    position.current_position = await orders.futures_position_open(
        client=client,
        entry_price=signal_update.price,
        signal=signal_update.signal,
        side=PositionSide.SHORT,
        balance=position.balance,
        leverage=position.leverage,
        number_of_dca_orders=position.number_of_dca_orders,
        order_quantity_list=position.order_quantity_list,
        symbol=position.symbol,
    )
    df.at[df.index[-1], "position"] = signal_update.signal

    return position, df


def futures_skip_signal(
    df: pandas.DataFrame, signal: features.Signals, status: features.Signals
) -> pandas.DataFrame:
    logger.info("Skipping signal: %s", signal)
    df.at[df.index[-1], "position"] = status

    return df


def futures_change_status_long20_short80(
    position: orders.Position, signal: features.Signals, df: pandas.DataFrame
) -> Tuple[orders.Position, pandas.DataFrame]:

    logger.info("Status change from %s to %s", position.current_position.status, signal)
    position.current_position.status = signal
    df.at[df.index[-1], "position"] = position.current_position.status

    return position, df


async def futures_switch_from_long_to_short(
    position: orders.Position,
    client: binance.AsyncClient,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
):
    logger.info("Switch from Long to Short")
    position.current_position = await orders.futures_position_close(
        client=client,
        current_position=position.current_position,
        symbol=position.symbol,
    )

    logger.info("Long closed, opening DCA Short")
    position.current_position = await orders.futures_position_open(
        client=client,
        entry_price=signal_update.price,
        signal=signal_update.signal,
        side=PositionSide.SHORT,
        balance=position.balance,
        leverage=position.leverage,
        number_of_dca_orders=position.number_of_dca_orders,
        order_quantity_list=position.order_quantity_list,
        symbol=position.symbol,
    )
    df.at[df.index[-1], "position"] = signal_update.signal

    return position, df


async def futures_start_special_short(
    position: orders.Position,
    client: binance.AsyncClient,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
) -> Tuple[orders.Position, pandas.DataFrame]:
    logger.info("Start special short")
    position.current_position = await orders.futures_position_close(
        client=client,
        current_position=position.current_position,
        symbol=position.symbol,
    )

    df.at[df.index[-1], "position"] = position.current_position.status
    logger.info("Long closed, opening FULL Short")
    position.current_position = await orders.futures_position_open(
        client=client,
        entry_price=signal_update.price,
        signal=signal_update.signal,
        side=PositionSide.SHORT,
        balance=position.balance,
        leverage=position.leverage,
        number_of_dca_orders=position.number_of_dca_orders,
        order_quantity_list=position.order_quantity_list,
        symbol=position.symbol,
        mode=PositionMode.FULL,
    )

    df.at[df.index[-1], "position"] = position.current_position.status

    return position, df


async def futures_switch_from_short_to_long(
    position: orders.Position,
    client: binance.AsyncClient,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
) -> Tuple[orders.Position, pandas.DataFrame]:
    logger.info("Switch from Short to Long")
    position.current_position = await orders.futures_position_close(
        client=client,
        current_position=position.current_position,
        symbol=position.symbol,
    )
    df.at[df.index[-1], "position"] = signal_update.signal
    await log_signal_change(df=df, signal=signal_update.signal)

    position.current_position = await orders.futures_position_open(
        client=client,
        entry_price=signal_update.price,
        signal=signal_update.signal,
        side=PositionSide.LONG,
        balance=position.balance,
        leverage=position.leverage,
        number_of_dca_orders=position.number_of_dca_orders,
        order_quantity_list=position.order_quantity_list,
        symbol=position.symbol,
    )

    return position, df


async def futures_start_special_long(
    position: orders.Position,
    client: binance.AsyncClient,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
) -> Tuple[orders.Position, pandas.DataFrame]:
    logger.info("Opening Special Long")
    position.current_position = await orders.futures_position_close(
        client=client,
        current_position=position.current_position,
        symbol=position.symbol,
    )

    logger.info("Short closed, opening FULL Long")
    position.current_position = await orders.futures_position_open(
        client=client,
        entry_price=signal_update.price,
        signal=signal_update.signal,
        side=PositionSide.LONG,
        balance=position.balance,
        leverage=position.leverage,
        number_of_dca_orders=position.number_of_dca_orders,
        order_quantity_list=position.order_quantity_list,
        symbol=position.symbol,
        mode=PositionMode.FULL,
    )
    df.at[df.index[-1], "position"] = position.current_position.status

    return position, df


async def futures_close_special_position(
    position: orders.Position,
    client: binance.AsyncClient,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
) -> Tuple[orders.Position, pandas.DataFrame]:
    logger.info("Got signal: %s", signal_update.signal)
    position.current_position = await orders.futures_position_close(
        client=client,
        current_position=position.current_position,
        symbol=position.symbol,
    )

    position.current_position = CurrentPosition()

    df.at[df.index[-1], "position"] = position.current_position.status

    return position, df


async def signal_handle(
    client: binance.AsyncClient,
    df: pandas.DataFrame,
    signal_update: SignalUpdate,
    position: orders.Position,
) -> Tuple[orders.Position, pandas.DataFrame]:

    current_position = position.current_position

    logger.info(
        "Entering signal handle, current status: %s, signal: %s",
        current_position.status,
        signal_update.signal,
    )

    signal = signal_update.signal
    price = signal_update.price

    if conditions_for_opening_long(status=current_position.status, signal=signal):
        position, df = await futures_long_position_open(
            client=client, position=position, df=df, signal_update=signal_update
        )

    if conditions_for_opening_short(
        status=position.current_position.status, signal=signal
    ):
        position, df = await futures_short_position_open(
            client=client, df=df, position=position, signal_update=signal_update
        )

    if conditions_for_skipping_signal(
        status=position.current_position.status, signal=signal
    ):
        df = futures_skip_signal(
            df=df, signal=signal, status=position.current_position.status
        )

    # CHANGE STATUS (ONLY FOR LONG_20 and SHORT_80)
    if conditions_for_changing_status(
        status=position.current_position.status, signal=signal
    ):
        position, df = futures_change_status_long20_short80(
            df=df, position=position, signal=signal
        )

    if conditions_for_switch_from_long_to_short(
        status=position.current_position.status, signal=signal
    ):
        position, df = await futures_switch_from_long_to_short(
            client=client, signal_update=signal_update, df=df, position=position
        )

    # START SPECIAL SHORT
    if conditions_for_special_short(
        status=position.current_position.status, signal=signal
    ):
        position, df = await futures_start_special_short(
            client=client, signal_update=signal_update, df=df, position=position
        )

    # SWITCH FROM SHORT TO LONG
    if conditions_for_switch_from_short_to_long(
        status=position.current_position.status, signal=signal
    ):
        position, df = await futures_switch_from_short_to_long(
            client=client, signal_update=signal_update, df=df, position=position
        )

    # OPEN SPECIAL LONG
    if conditions_for_special_long(
        status=position.current_position.status, signal=signal
    ):
        position, df = await futures_start_special_long(
            client=client, signal_update=signal_update, df=df, position=position
        )

    if condition_to_close_special_position(
        status=position.current_position.status, signal=signal
    ):
        position, df = await futures_close_special_position(
            client=client, signal_update=signal_update, df=df, position=position
        )

    await log_signal_change(df=df, signal=signal)

    logger.info("Exiting signal handle")
    return position, df
