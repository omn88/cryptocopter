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


async def update_current_position(
    client: binance.AsyncClient,
    current_position: orders.CurrentPosition,
    order_price: float,
    order_quantity: float,
    leverage: int,
    symbol: str,
    saldo: float,
) -> Tuple[orders.CurrentPosition, float]:

    new_order_quantity = order_quantity + current_position.quantity
    weighted_avg_price = (
        current_position.price * current_position.quantity
        + order_price * order_quantity
    ) / new_order_quantity

    liquidation_price, target_price = orders.liquidation_target_price_calculate(
        side=current_position.side, price=weighted_avg_price, leverage=leverage
    )

    take_profit_order = await orders.update_take_profit_order(
        client=client,
        old_take_profit_order=current_position.take_profit_order,
        price=target_price,
        order_quantity=new_order_quantity,
        side=current_position.side,
        symbol=symbol,
    )

    current_position = orders.CurrentPosition(
        price=weighted_avg_price,
        quantity=new_order_quantity,
        liquidation_price=liquidation_price,
        target_price=target_price,
        side=current_position.side,
        take_profit_order=take_profit_order,
    )

    return current_position, saldo


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
                    (
                        position.current_position,
                        position.saldo,
                    ) = await update_current_position(
                        client=client,
                        current_position=position.current_position,
                        order_price=order_price,
                        order_quantity=order_quantity,
                        leverage=position.leverage,
                        symbol=position.symbol,
                        saldo=position.saldo,
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
    start_df: pandas.DataFrame,
    queue: asyncio.Queue,
    client: binance.AsyncClient,
    symbol: str,
    interval: str,
    saldo: float,
):
    df = start_df
    position = orders.Position(
        current_position=orders.CurrentPosition(
            price=0,
            quantity=0,
            target_price=0,
            liquidation_price=0,
            side=orders.PositionSide.FLAT,
            take_profit_order=orders.Order(price=0, quantity=0, order_id=0),
        ),
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

            elif producers.EventName.Order == producers.Event.name:
                logger.info("Order update: %s" % task.content)
                new_df, new_position = await order_handle(
                    client=client, position=position, order_update=task.content
                )
                df = new_df
                position = new_position
                logger.info("New DF: %s, new position: %s" % (new_df, new_position))
            elif producers.EventName.Account == producers.Event.name:
                logger.info("Account update: %s" % task.content)
                new_df, new_position = await account_handle(df=df, position=position)
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
