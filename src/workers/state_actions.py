import asyncio
from typing import Tuple
import binance
import pandas
from src import features
import logging

from src.common.common import log_signal_change
from src.features import Signals
from src.orders import PositionMode, CurrentPosition, PositionSide
from src.producers.producers import SignalUpdate, Event, EventName
from src.workers import handle_order
from src.workers.trading_state_machine import TradingStateMachine

logger = logging.getLogger("state_actions")


async def futures_signal_position_open(
    client: binance.AsyncClient,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
    balance: float,
    order_quantity_list,
) -> Tuple[CurrentPosition, pandas.DataFrame]:
    logger.info("Opening %s", signal_update.signal)
    current_position = await handle_order.futures_position_open(
        client=client,
        entry_price=signal_update.price,
        signal=signal_update.signal,
        side=PositionSide.LONG
        if signal_update.signal in [Signals.LONG, Signals.LONG_20, Signals.LONG_SPECIAL]
        else PositionSide.SHORT,
        balance=balance,
        order_quantity_list=order_quantity_list,
        df=df,
    )
    df.at[df.index[-1], "position"] = signal_update.signal

    return current_position, df


def futures_skip_signal(
    df: pandas.DataFrame, signal: features.Signals, status: features.Signals
) -> pandas.DataFrame:
    logger.info("Skipping signal: %s", signal)
    df.at[df.index[-1], "position"] = status

    return df


def futures_change_status_long20_short80(
    current_position: CurrentPosition, signal: features.Signals, df: pandas.DataFrame
) -> Tuple[CurrentPosition, pandas.DataFrame]:

    logger.info("Status change from %s to %s", current_position.status, signal)
    current_position.status = signal
    df.at[df.index[-1], "position"] = current_position.status

    return current_position, df


async def market_close_and_send_signal(
    current_position: CurrentPosition,
    client: binance.AsyncClient,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
    balance: float,
    queue: asyncio.Queue,
) -> Tuple[CurrentPosition, pandas.DataFrame]:

    # Close current position
    current_position = await handle_order.futures_position_close(
        client=client, current_position=current_position, balance=balance
    )
    df.at[df.index[-1], "position"] = features.Signals.FLAT
    await log_signal_change(df=df, signal=signal_update.signal)

    logger.info(
        "Market order send, remaining orders cancelled, adding %s to queue",
        signal_update,
    )
    # Add new signal to queue
    await queue.put(Event(name=EventName.SIGNAL, content=signal_update))

    return current_position, df


async def futures_open_special_long(
    client: binance.AsyncClient,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
    balance: float,
    order_quantity_list: pandas.DataFrame,
) -> Tuple[CurrentPosition, pandas.DataFrame]:
    logger.info("Opening Special Long")

    current_position = await handle_order.futures_position_open(
        client=client,
        df=df,
        signal=signal_update.signal,
        balance=balance,
        entry_price=signal_update.price,
        side=PositionSide.LONG,
        order_quantity_list=order_quantity_list,
        mode=PositionMode.FULL,
    )

    df.at[df.index[-1], "position"] = signal_update.signal

    return current_position, df


async def futures_open_special_short(
    client: binance.AsyncClient,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
    balance: float,
    order_quantity_list: pandas.DataFrame,
) -> Tuple[CurrentPosition, pandas.DataFrame]:
    logger.info("Opening Special Short")

    current_position = await handle_order.futures_position_open(
        client=client,
        df=df,
        signal=signal_update.signal,
        balance=balance,
        entry_price=signal_update.price,
        side=PositionSide.SHORT,
        order_quantity_list=order_quantity_list,
        mode=PositionMode.FULL,
    )

    df.at[df.index[-1], "position"] = signal_update.signal

    return current_position, df


async def futures_close_special_position(
    current_position: CurrentPosition,
    client: binance.AsyncClient,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
    balance: float,
) -> Tuple[CurrentPosition, pandas.DataFrame]:
    logger.info("Got signal: %s", signal_update.signal)
    current_position = await handle_order.futures_position_close(
        client=client, current_position=current_position, balance=balance
    )

    df.at[df.index[-1], "position"] = features.Signals.FLAT

    return current_position, df


# async def signal_handle(
#     client: binance.AsyncClient,
#     df: pandas.DataFrame,
#     signal_update: SignalUpdate,
#     current_position: CurrentPosition,
#     balance: float,
#     order_quantity_list: pandas.DataFrame,
#     queue: asyncio.Queue,
# ) -> Tuple[CurrentPosition, pandas.DataFrame]:
#
#     logger.info(
#         "Entering signal handle, current status: %s, signal: %s",
#         current_position.status,
#         signal_update.signal,
#     )
#
#     # ToDo: This is place where being careful is needed as the order of these funcs matters.
#     # So last example is need for moving conditions for opening special long/short higher
#     # as it was being performed too early.
#
#     # SKIP SIGNAL
#     if conditions_for_skipping_signal(
#         status=current_position.status, signal=signal_update.signal
#     ):
#         df = futures_skip_signal(
#             df=df, signal=signal_update.signal, status=current_position.status
#         )
#
#     # OPEN SPECIAL LONG
#     if conditions_for_special_long(
#         status=current_position.status, signal=signal_update.signal
#     ):
#         current_position, df = await futures_open_special_long(
#             client=client,
#             signal_update=signal_update,
#             df=df,
#             balance=balance,
#             order_quantity_list=order_quantity_list,
#         )
#
#     # OPEN SPECIAL SHORT
#     if conditions_for_special_short(
#         status=current_position.status, signal=signal_update.signal
#     ):
#         current_position, df = await futures_open_special_short(
#             client=client,
#             signal_update=signal_update,
#             df=df,
#             balance=balance,
#             order_quantity_list=order_quantity_list,
#         )
#
#     # OPEN LONG OR SHORT
#     if conditions_for_opening_long(
#         status=current_position.status, signal=signal_update.signal
#     ) or conditions_for_opening_short(
#         status=current_position.status, signal=signal_update.signal
#     ):
#         current_position, df = await futures_signal_position_open(
#             client=client,
#             df=df,
#             signal_update=signal_update,
#             balance=balance,
#             order_quantity_list=order_quantity_list,
#         )
#
#     # CHANGE STATUS (ONLY FOR LONG_20 and SHORT_80)
#     if conditions_for_changing_status(
#         status=current_position.status, signal=signal_update.signal
#     ):
#         current_position, df = futures_change_status_long20_short80(
#             df=df, current_position=current_position, signal=signal_update.signal
#         )
#
#     # CLOSE CURRENT POSITION AND SEND SIGNAL TO OPEN NEW
#     if (
#         conditions_for_switch_from_long_to_short(
#             status=current_position.status, signal=signal_update.signal
#         )
#         or conditions_for_special_long_close_short(
#             status=current_position.status, signal=signal_update.signal
#         )
#         or conditions_for_special_short_close_long(
#             status=current_position.status, signal=signal_update.signal
#         )
#         or conditions_for_switch_from_short_to_long(
#             status=current_position.status, signal=signal_update.signal
#         )
#     ):
#         current_position, df = await market_close_and_send_signal(
#             client=client,
#             signal_update=signal_update,
#             df=df,
#             current_position=current_position,
#             balance=balance,
#             queue=queue,
#         )
#
#     # CLOSE SPECIAL POSITION
#     if condition_to_close_special_position(
#         status=current_position.status, signal=signal_update.signal
#     ):
#         current_position, df = await futures_close_special_position(
#             client=client,
#             signal_update=signal_update,
#             df=df,
#             current_position=current_position,
#             balance=balance,
#         )
#
#     await log_signal_change(df=df, signal=signal_update.signal)
#
#     logger.info("Exiting signal handle")
#     return current_position, df


async def signal_handle(
    client,
    df,
    signal_update,
    current_position,
    balance,
    order_quantity_list,
    queue,
) -> Tuple[CurrentPosition, pandas.DataFrame]:

    logger.info(
        "Entering signal handle, current status: %s, signal: %s",
        current_position.status,
        signal_update.signal,
    )

    state_machine = TradingStateMachine(
        client=client,
        balance=balance,
        order_quantity_list=order_quantity_list,
        queue=queue,
    )

    await state_machine.process_signal(
        signal_update=signal_update,
        df=df,
        current_position=current_position,
    )

    current_position.status = state_machine.machine.state

    logger.info("Exiting signal handle")
    return current_position, df
