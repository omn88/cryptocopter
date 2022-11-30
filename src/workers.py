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


async def when_flat(
    signal: features.Signals,
    client: binance.AsyncClient,
    position: orders.Position,
    df: pandas.DataFrame,
) -> Tuple[pandas.DataFrame, orders.Position]:
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
        logger.info(
            "Position was %s, position is: %s, signal: %s. Staying FLAT!"
            % (
                df.at[df.index[-2], "position"],
                df.at[df.index[-1], "position"],
                signal,
            )
        )
    elif signal == features.Signals.FLAT:
        df.at[df.index[-1], "position"] = df.at[df.index[-2], "position"]
        logger.info(
            "Position was %s, position is: %s, signal: %s. Staying FLAT!"
            % (
                df.at[df.index[-2], "position"],
                df.at[df.index[-1], "position"],
                signal,
            )
        )

    return df, position


async def when_long(
    signal: features.Signals,
    client: binance.AsyncClient,
    position: orders.Position,
    df: pandas.DataFrame,
) -> Tuple[pandas.DataFrame, orders.Position]:
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

    return df, position


async def when_long_twenty(
    signal: features.Signals,
    client: binance.AsyncClient,
    position: orders.Position,
    df: pandas.DataFrame,
) -> Tuple[pandas.DataFrame, orders.Position]:
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

    return df, position


async def when_short(
    signal: features.Signals,
    client: binance.AsyncClient,
    position: orders.Position,
    df: pandas.DataFrame,
) -> Tuple[pandas.DataFrame, orders.Position]:
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

    return df, position


async def when_short_eighty(
    signal: features.Signals,
    client: binance.AsyncClient,
    position: orders.Position,
    df: pandas.DataFrame,
) -> Tuple[pandas.DataFrame, orders.Position]:
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

    return df, position


async def signal_handle(
    client: binance.AsyncClient,
    df: pandas.DataFrame,
    signal: features.Signals,
    position: orders.Position,
) -> Tuple[pandas.DataFrame, orders.Position]:
    logger.info("Entering signal handle")

    if position.status == features.Signals.FLAT:
        df, position = await when_flat(
            client=client, position=position, signal=signal, df=df
        )

    elif position.status == features.Signals.LONG:
        df, position = await when_long(
            client=client, position=position, signal=signal, df=df
        )

    elif position.status == features.Signals.LONG_20:
        df, position = await when_long_twenty(
            client=client, position=position, signal=signal, df=df
        )

    elif position.status == features.Signals.SHORT:
        df, position = await when_short(
            client=client, position=position, signal=signal, df=df
        )

    elif position.status == features.Signals.SHORT_80:
        df, position = await when_short_eighty(
            client=client, position=position, signal=signal, df=df
        )

    else:
        logger.info("You fucked up something big!")

    return df, position


async def order_handle(
    client: binance.AsyncClient, position: orders.Position, order_update: dict
) -> Tuple[pandas.DataFrame, orders.Position]:

    updated_order = order_update["o"]
    order_status = updated_order["X"]
    order_type = updated_order["o"]
    order_side = updated_order["S"]
    order_price = updated_order["p"]
    order_quantity = updated_order["q"]

    # HANDLE WHEN LIQUIDATION OR TAKE PROFIT

    for order in position.orders:
        if order.status in [
            client.ORDER_STATUS_NEW,
            client.ORDER_STATUS_PARTIALLY_FILLED,
        ]:
            if order.price == round(order_price, 2):
                if order_status == client.ORDER_STATUS_PARTIALLY_FILLED:
                    order.realized_quantity = order.realized_quantity + order_quantity
                    order.status = order_status
                    logger.info(
                        "Order partially filled, price: %s, quantity: %s"
                        % (order_price, order_quantity)
                    )
                elif order_status == client.ORDER_STATUS_FILLED:
                    order.realized_quantity = order.quantity
                    order.status = order_status

                    logger.info(
                        "Order filled, price: %s, quantity: %s"
                        % (order_price, order_quantity)
                    )
                    position.current_position.take_profit_order = await orders.update_take_profit_order(
                        client=client,
                        take_profit_order=position.current_position.take_profit_order,
                        price=order_price,
                        order_quantity=order_quantity,
                        symbol=position.symbol,
                        side=position.current_position.side,
                    )

                elif order_status == client.ORDER_STATUS_NEW:
                    logger.info("New order created")
                elif order_status == client.ORDER_STATUS_CANCELED:
                    logger.info("Order cancelled")
                elif order_status == client.ORDER_STATUS_EXPIRED:
                    logger.info("Order expired")

    return position


async def account_handle(
    df: pandas.DataFrame, position: orders.Position
) -> Tuple[pandas.DataFrame, orders.Position]:

    return df, position


async def worker(
    df: pandas.DataFrame,
    queue: asyncio.Queue,
    client: binance.AsyncClient,
    symbol: str,
    interval: str,
    position: orders.Position,
):
    while True:
        logger.info("Entering worker")
        logger.info("queue size: %s" % queue.qsize())
        event = await queue.get()
        logger.info(
            "New event arrived, name: %s, \ncontent: %s" % (event.name, event.content)
        )
        assert isinstance(event, producers.Event)

        if producers.EventName.KLINE == event.name:
            logger.info("Entering Kline handling")
            temp_df = await lib.get_futures_historical_data(
                client=client,
                symbol=symbol,
                interval=interval,
                lookback="3360",  # 44000 is approximately one month
            )
            temp_df = features.signals_from_features_generate(df=temp_df)
            temp_df["position"] = df.at[df.index[-1], "position"]
            kline_signal = temp_df.iloc[-1]["signal"]
            if kline_signal == 0:
                kline_signal = features.Signals.NULL

            logger.info("Kline produced new signal: %s" % kline_signal.value)

            temp_df, position = await signal_handle(
                client=client,
                df=temp_df,
                signal=kline_signal,
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
        elif producers.EventName.ORDER == event.name:
            logger.info("Order update: %s" % event.content)
            new_df, new_position = await order_handle(
                client=client, position=position, order_update=event.content
            )
            df = new_df
            position = new_position
            logger.info("New DF: %s, new position: %s" % (new_df, new_position))
        elif producers.EventName.ACCOUNT == producers.Event.name:
            logger.info("Account update: %s" % event.content)
            new_df, new_position = await account_handle(df=df, position=position)
            df = new_df
            position = new_position
            logger.info("New DF: %s, new position: %s" % (new_df, new_position))
        elif producers.EventName.SIGNAL == producers.Event.name:
            logger.info("Event signal update: %s" % event.content)
            new_df, new_position = await signal_handle(
                client=client,
                df=df,
                signal=event.content["last_signal"],
                position=position,
            )
            df = new_df
            position = new_position
            logger.info("New DF: %s, new position: %s" % (new_df, new_position))

            last_rows = 5
            logger.info(
                "Last %d rows from main df after signal handle: %s"
                % (last_rows, "\n%s" % df.tail(last_rows).to_string())
            )

        # logger.info("New DF: %s, new position: %s" % (df, position))
        logger.info("Task Done, Awaiting new signal")
        queue.task_done()
