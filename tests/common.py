from typing import Tuple

import binance
import pandas

from src.common.identifiers import (
    Signal,
    SignalUpdate,
    Position,
    State,
    OrderUpdate,
    Order,
)


def generate_signal(signal: Signal, df: pandas.DataFrame) -> SignalUpdate:
    entry_price = round(float(df.at[df.index[-1], "Close"]), 1)
    return SignalUpdate(signal=signal, price=entry_price)


def assert_dca_long_opened(
    position: Position,
    balance: float,
    state: State,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
):
    assert 4 == len(position.orders)
    assert 1000 == balance
    assert state == State(signal_update.signal.value)
    assert state == position.status
    assert all(order.price <= signal_update.price for order in position.orders)
    assert df.at[df.index[-1], "Position"] == State(signal_update.signal.value)


def assert_dca_short_opened(
    position: Position,
    balance: float,
    state: State,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
):
    assert 4 == len(position.orders)
    assert 1000 == balance
    assert state == State(signal_update.signal.value)
    assert (
        state == position.status
    ), f"State: {state}, position.status: {position.status}"
    assert all(order.price >= signal_update.price for order in position.orders)
    assert df.at[df.index[-1], "Position"] == State(signal_update.signal.value)


async def first_order_filled(
    base,
):

    assert base.position.orders is not None
    price = base.position.orders[0].price
    quantity = base.position.orders[0].quantity

    base.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=binance.AsyncClient.ORDER_STATUS_FILLED,
        order_id=1,
        last_filled_quantity=quantity,
        realized_quantity=quantity,
    )

    await base.process_order()

    assert base.position.orders is not None

    assert base.position.orders[0].status == binance.AsyncClient.ORDER_STATUS_FILLED
    assert base.position.orders[1].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert base.position.orders[2].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert base.position.orders[3].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert base.position.entry_price == price
    assert base.position.quantity == quantity
    assert base.position.take_profit_order is not None
    assert base.position.take_profit_order.quantity == base.position.orders[0].quantity
    assert base.position.orders[0].realized_quantity == quantity


async def second_order_filled(
    base: pandas.DataFrame, current_position: Position
) -> Position:
    assert current_position.orders is not None
    price = current_position.orders[1].price
    quantity = current_position.orders[1].quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=quantity,
        order_id=2,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders is not None

    assert current_position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert current_position.entry_price == round(
        (current_position.orders[0].price + current_position.orders[1].price) / 2,
        1,
    )
    assert current_position.quantity == round(
        (
            current_position.orders[0].realized_quantity
            + current_position.orders[1].realized_quantity
        ),
        3,
    )
    assert current_position.take_profit_order is not None
    assert current_position.take_profit_order.quantity == (
        current_position.orders[0].quantity + current_position.orders[1].quantity
    )

    return current_position


async def third_and_fourth_order_filled(base, current_position: Position) -> Position:
    assert current_position.orders is not None
    price = current_position.orders[2].price
    quantity = current_position.orders[2].quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=quantity,
        order_id=3,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders is not None

    assert current_position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert current_position.take_profit_order is not None

    assert current_position.take_profit_order.quantity == (
        current_position.orders[0].quantity
        + current_position.orders[1].quantity
        + current_position.orders[2].quantity
    )

    price = current_position.orders[3].price
    quantity = current_position.orders[3].quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=quantity,
        order_id=4,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders is not None

    assert current_position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert current_position.entry_price == round(
        (
            current_position.orders[0].price
            + current_position.orders[1].price
            + current_position.orders[2].price
            + current_position.orders[3].price
        )
        / 4,
        1,
    )
    assert current_position.take_profit_order is not None
    assert current_position.take_profit_order.quantity == (
        current_position.orders[0].quantity
        + current_position.orders[1].quantity
        + current_position.orders[2].quantity
        + current_position.orders[3].quantity
    )

    return current_position


async def target_reached(
    base, current_position: Position
) -> Tuple[Position, pandas.DataFrame, float]:

    assert isinstance(current_position.take_profit_order, Order)

    price = current_position.take_profit_order.price
    quantity = current_position.take_profit_order.quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=quantity,
        order_id=5,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders == []
    assert current_position.take_profit_order is None

    return current_position, base.df, balance


async def start_long(base) -> None:

    base.signal_update = generate_signal(signal=Signal.LONG, df=base.df)

    await base.process_signal()

    assert_dca_long_opened(
        position=base.position,
        balance=base.balance,
        state=base.state,
        signal_update=base.signal_update,
        df=base.df,
    )


async def start_short(base) -> None:

    base.signal_update = generate_signal(signal=Signal.SHORT, df=base.df)

    await base.process_signal()

    assert_dca_short_opened(
        position=base.position,
        balance=base.balance,
        state=base.state,
        signal_update=base.signal_update,
        df=base.df,
    )
