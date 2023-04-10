from typing import Tuple
import binance
import pandas
import logging
from src.features.features import Signal
from src.common.orders import PositionMode, Position, PositionSide
from src.producers.producers import SignalUpdate
from src.workers import handle_order
from src.workers.trading_state_machine import TradingStateMachine

logger = logging.getLogger("state_actions")


def futures_change_status_long20_short80(
    current_position: Position, signal: Signal, df: pandas.DataFrame
) -> Tuple[Position, pandas.DataFrame]:

    logger.info("Status change from %s to %s", current_position.status, signal)
    current_position.status = signal
    df.at[df.index[-1], "position"] = current_position.status

    return current_position, df


async def futures_open_special_long(
    client: binance.AsyncClient,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
    balance: float,
    order_quantity_list: pandas.DataFrame,
) -> Tuple[Position, pandas.DataFrame]:
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
) -> Tuple[Position, pandas.DataFrame]:
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
    signal_update, position, tsm: TradingStateMachine
) -> Tuple[Position, TradingStateMachine]:

    logger.info(
        "Entering signal handle, current status: %s, signal: %s",
        position.status,
        signal_update.signal,
    )

    logger.info("Exiting signal handle")
    return position, tsm
