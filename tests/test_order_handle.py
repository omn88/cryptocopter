from typing import Tuple
from unittest.mock import patch
from src.features.features import Signal
from src.common.orders import Order, Position
from src.producers.producers import OrderUpdate, SignalUpdate
import logging
import pandas
import binance

logger = logging.getLogger("TEST")


def mock_create_order_side_effect_long():
    return [
        {
            "orderId": "1",
            "price": "20000.8",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "2",
            "price": "19900.8",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "3",
            "price": "19800.8",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "4",
            "price": "19700.8",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "5",
            "price": "20800.0",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "6",
            "price": "20748.0",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "7",
            "price": "20696.0",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "8",
            "price": "20644.8",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
    ]


def mock_create_order_side_effect_short():
    return [
        {
            "orderId": "1",
            "price": "20000",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "2",
            "price": "20100",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "3",
            "price": "20200",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "4",
            "price": "20300",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "5",
            "price": "19200",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "6",
            "price": "20748.83",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "7",
            "price": "20696.83",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "8",
            "price": "20644.83",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
    ]


def mock_get_order_return_value():
    return {
        "orderId": 1,
        "price": 19567.72,
        "status": binance.AsyncClient.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }


async def first_order_filled(
    current_position: Position,
    entry_price: float,
    client: binance.AsyncClient,
    df: pandas.DataFrame,
    balance: float,
) -> Position:

    assert current_position.orders is not None
    quantity = current_position.orders[0].quantity

    order_update = OrderUpdate(
        price=entry_price,
        quantity=quantity,
        status=binance.AsyncClient.ORDER_STATUS_FILLED,
        order_id=1,
        last_filled_quantity=quantity,
        realized_quantity=quantity,
    )

    current_position, df, balance = await order_handle(
        client=client,
        current_position=current_position,
        order_update=order_update,
        df=df,
        balance=balance,
    )

    assert current_position.orders is not None

    assert current_position.orders[0].status == binance.AsyncClient.ORDER_STATUS_FILLED
    assert current_position.orders[1].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert current_position.orders[2].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert current_position.orders[3].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert current_position.entry_price == entry_price
    assert current_position.quantity == quantity
    assert current_position.take_profit_order is not None
    assert (
        current_position.take_profit_order.quantity
        == current_position.orders[0].quantity
    )
    assert current_position.orders[0].realized_quantity == quantity
    return current_position


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


async def start_long(base) -> Tuple[pandas.DataFrame, Position, float]:

    entry_signal = Signals.LONG
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)
    current_position, base.df = await signal_handle(
        signal_update=SignalUpdate(signal=entry_signal, price=entry_price),
        client=base.client,
        current_position=base.position.current_position,
        df=base.df,
        balance=base.position.balance,
        order_quantity_list=base.position.order_quantity_list,
        queue=base.queue,
    )

    assert current_position.orders is not None
    assert 4 == len(current_position.orders)
    assert 1000 == base.position.balance

    assert all(order.entry_price <= entry_price for order in current_position.orders)

    return base.df, current_position, entry_price


async def start_short(base) -> Tuple[pandas.DataFrame, Position, float]:

    entry_signal = Signals.SHORT
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)
    current_position, base.df = await signal_handle(
        signal_update=SignalUpdate(signal=entry_signal, price=entry_price),
        client=base.client,
        current_position=base.position.current_position,
        df=base.df,
        balance=base.position.balance,
        order_quantity_list=base.position.order_quantity_list,
        queue=base.queue,
    )

    assert current_position.orders is not None
    assert 4 == len(current_position.orders)
    assert 1000 == base.position.balance
    assert all(order.entry_price >= entry_price for order in current_position.orders)

    return base.df, current_position, entry_price


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_filled(
    mock_create_order, mock_position_information, mock_get_order, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.062"}],
    ]

    base.df, current_position, entry_price = await start_long(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )

    assert base.df.iloc[-1]["position"] == Signals.LONG


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_filled_partially(
    mock_create_order, mock_position_information, mock_get_order, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.062"}],
    ]

    base.df, base.position.current_position, entry_price = await start_long(base=base)

    realized_quantity = round(
        float(base.position.current_position.orders[0].quantity / 2), 3
    )

    price = entry_price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=base.position.current_position.orders[0].quantity,
        status=status,
        last_filled_quantity=realized_quantity,
        order_id=1,
        realized_quantity=realized_quantity,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=base.position.current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    for order in base.position.current_position.orders:
        logger.info("ORDER: %s", order)

    logger.info("tpo: %s", base.position.current_position.take_profit_order)

    assert (
        base.position.current_position.orders[0].status
        == base.client.ORDER_STATUS_PARTIALLY_FILLED
    )
    assert (
        base.position.current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    )
    assert (
        base.position.current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    )
    assert (
        base.position.current_position.orders[3].status == base.client.ORDER_STATUS_NEW
    )
    assert base.position.current_position.take_profit_order is not None
    assert (
        base.position.current_position.take_profit_order.quantity == realized_quantity
    )
    assert base.df.iloc[-1]["position"] == Signals.LONG


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_filled_partially_twice(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.046"}],
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, current_position, entry_price = await start_long(base=base)

    realized_quantity = round(float(current_position.orders[0].quantity / 2), 3)

    price = entry_price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=current_position.orders[0].quantity,
        status=status,
        realized_quantity=realized_quantity,
        last_filled_quantity=realized_quantity,
        order_id=1,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert (
        current_position.orders[0].status == base.client.ORDER_STATUS_PARTIALLY_FILLED
    )
    assert current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert current_position.take_profit_order is not None
    assert current_position.take_profit_order.quantity == realized_quantity

    another_realized_quantity = round(float(current_position.orders[0].quantity / 4), 3)

    price = entry_price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=current_position.orders[0].quantity,
        status=status,
        last_filled_quantity=another_realized_quantity,
        realized_quantity=(realized_quantity + another_realized_quantity),
        order_id=1,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert (
        current_position.orders[0].status == base.client.ORDER_STATUS_PARTIALLY_FILLED
    )
    assert current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert current_position.take_profit_order is not None
    assert current_position.take_profit_order.quantity == (
        realized_quantity + another_realized_quantity
    )
    assert base.df.iloc[-1]["position"] == Signals.LONG


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_two_orders_filled(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.125"}],
        [{"liquidationPrice": "19104", "entryPrice": "19900", "positionAmt": "0.188"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.251"}],
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, current_position, entry_price = await start_long(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )
    assert current_position.take_profit_order.price == 20800.0
    assert current_position.liquidation_price == 19200

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 20748.0
    assert current_position.liquidation_price == 19152
    assert base.df.iloc[-1]["position"] == Signals.LONG


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_new(
    mock_create_order, mock_position_information, mock_get_order, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.125"}],
        [{"liquidationPrice": "19104", "entryPrice": "19900", "positionAmt": "0.188"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.251"}],
    ]
    base.df, current_position, entry_price = await start_long(base=base)

    price = entry_price
    quantity = current_position.orders[0].quantity
    status = base.client.ORDER_STATUS_NEW

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders[0].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert base.df.iloc[-1]["position"] == Signals.LONG


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_expired(
    mock_create_order, mock_position_information, mock_get_order, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.125"}],
        [{"liquidationPrice": "19104", "entryPrice": "19900", "positionAmt": "0.188"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.251"}],
    ]
    base.df, current_position, entry_price = await start_long(base=base)

    price = entry_price
    quantity = current_position.orders[0].quantity
    status = base.client.ORDER_STATUS_EXPIRED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders[0].status == base.client.ORDER_STATUS_EXPIRED
    assert current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert base.df.iloc[-1]["position"] == Signals.LONG


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_canceled(
    mock_create_order, mock_position_information, mock_get_order, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.125"}],
        [{"liquidationPrice": "19104", "entryPrice": "19900", "positionAmt": "0.188"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.251"}],
    ]
    base.df, current_position, entry_price = await start_long(base=base)

    price = entry_price
    quantity = current_position.orders[0].quantity
    status = base.client.ORDER_STATUS_CANCELED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders[0].status == base.client.ORDER_STATUS_CANCELED
    assert current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert base.df.iloc[-1]["position"] == Signals.LONG


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_two_orders_filled_then_target_reached(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.125"}],
        [{"liquidationPrice": "19104", "entryPrice": "19900", "positionAmt": "0.188"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.251"}],
    ]

    base.df, current_position, entry_price = await start_long(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )
    assert current_position.take_profit_order.price == 20800.0
    assert current_position.liquidation_price == 19200

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 20748.0
    assert current_position.liquidation_price == 19152

    current_position, base.df, balance = await target_reached(
        base=base, current_position=current_position
    )

    assert balance == 1099.75
    assert base.df.iloc[-1]["position"] == Signals.FLAT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_all_orders_filled_then_target_reached(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.125"}],
        [{"liquidationPrice": "19104", "entryPrice": "19900", "positionAmt": "0.188"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.251"}],
    ]

    base.df, current_position, entry_price = await start_long(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )
    assert current_position.take_profit_order.price == 20800.0
    assert current_position.liquidation_price == 19200

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 20748.0
    assert current_position.liquidation_price == 19152

    current_position = await third_and_fourth_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 20644.0
    assert current_position.liquidation_price == 19056

    current_position, base.df, balance = await target_reached(
        base=base, current_position=current_position
    )

    assert current_position.orders == []
    assert current_position.take_profit_order is None
    assert balance == 1199.29
    assert base.df.iloc[-1]["position"] == Signals.FLAT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_all_orders_filled_then_target_reached_partially(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.125"}],
        [{"liquidationPrice": "19104", "entryPrice": "19900", "positionAmt": "0.188"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.251"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.063"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.126"}],
    ]

    base.df, current_position, entry_price = await start_long(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )
    assert current_position.take_profit_order.price == 20800.0
    assert current_position.liquidation_price == 19200

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 20748.0
    assert current_position.liquidation_price == 19152

    current_position = await third_and_fourth_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 20644.0
    assert current_position.liquidation_price == 19056

    partial_quantity = round(current_position.take_profit_order.quantity / 2, 3)

    remaining_quantity = current_position.take_profit_order.quantity - partial_quantity

    price = current_position.take_profit_order.price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=partial_quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=6,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert current_position.take_profit_order is not None
    assert current_position.take_profit_order.entry_price == 20644.0
    assert current_position.take_profit_order.quantity == remaining_quantity
    assert current_position.take_profit_order.realized_quantity == partial_quantity
    assert balance == 1100.04
    assert base.df.iloc[-1]["position"] == Signals.LONG


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_all_orders_filled_then_target_reached_partially_then_filled_completely(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.125"}],
        [{"liquidationPrice": "19104", "entryPrice": "19900", "positionAmt": "0.188"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.251"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.063"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0"}],
    ]

    base.df, current_position, entry_price = await start_long(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )
    assert current_position.take_profit_order.price == 20800.0
    assert current_position.liquidation_price == 19200

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 20748.0
    assert current_position.liquidation_price == 19152

    current_position = await third_and_fourth_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 20644.0
    assert current_position.liquidation_price == 19056

    partial_quantity = round(current_position.take_profit_order.quantity / 2, 3)

    remaining_quantity = current_position.take_profit_order.quantity - partial_quantity

    order_update = OrderUpdate(
        price=current_position.take_profit_order.price,
        quantity=partial_quantity,
        status=base.client.ORDER_STATUS_PARTIALLY_FILLED,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=6,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )
    try:

        assert current_position.orders[0].status == base.client.ORDER_STATUS_FILLED
        assert current_position.orders[1].status == base.client.ORDER_STATUS_FILLED
        assert current_position.orders[2].status == base.client.ORDER_STATUS_FILLED
        assert current_position.orders[3].status == base.client.ORDER_STATUS_FILLED
        assert current_position.take_profit_order is not None
        assert current_position.take_profit_order.entry_price == 20644.0
        assert current_position.take_profit_order.quantity == remaining_quantity
        assert current_position.take_profit_order.realized_quantity == partial_quantity
        assert balance == 1100.04
    except AssertionError as error:
        logger.info(error)
        raise error

    order_update = OrderUpdate(
        price=current_position.take_profit_order.entry_price,
        quantity=current_position.quantity,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=7,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=balance,
    )

    assert current_position.orders == []
    assert current_position.take_profit_order is None
    assert balance == 1200.08
    assert base.df.iloc[-1]["position"] == Signals.FLAT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_all_orders_filled_then_liquidation(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.125"}],
        [{"liquidationPrice": "19104", "entryPrice": "19900", "positionAmt": "0.188"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.251"}],
    ]

    base.df, current_position, entry_price = await start_long(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )
    assert current_position.take_profit_order.price == 20800.0
    assert current_position.liquidation_price == 19200

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 20748.0
    assert current_position.liquidation_price == 19152

    current_position = await third_and_fourth_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 20644.0
    assert current_position.liquidation_price == 19056

    price = current_position.liquidation_price
    quantity = current_position.take_profit_order.quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        order_id=6,
        order_type="LIQUIDATION",
        realized_quantity=quantity,
        last_filled_quantity=quantity,
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
    assert balance == 800.00
    assert base.df.iloc[-1]["position"] == Signals.FLAT


# ------------------------------ SHORT -------------------------------------#


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_filled(
    mock_create_order, mock_position_information, mock_get_order, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.093"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.124"}],
    ]

    base.df, current_position, entry_price = await start_short(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )

    assert base.df.iloc[-1]["position"] == Signals.SHORT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_filled_partially(
    mock_create_order, mock_position_information, mock_get_order, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.093"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.124"}],
    ]

    base.df, current_position, entry_price = await start_short(base=base)

    realized_quantity = round(float(current_position.orders[0].quantity / 2), 3)

    price = entry_price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=current_position.orders[0].quantity,
        status=status,
        realized_quantity=realized_quantity,
        last_filled_quantity=realized_quantity,
        order_id=1,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert (
        current_position.orders[0].status == base.client.ORDER_STATUS_PARTIALLY_FILLED
    )
    assert current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert current_position.take_profit_order is not None
    assert current_position.take_profit_order.quantity == realized_quantity

    assert base.df.iloc[-1]["position"] == Signals.SHORT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_filled_partially_twice(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.046"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.186"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.248"}],
    ]

    base.df, current_position, entry_price = await start_short(base=base)

    realized_quantity = round(float(current_position.orders[0].quantity / 2), 3)

    price = entry_price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=current_position.orders[0].quantity,
        status=status,
        realized_quantity=realized_quantity,
        last_filled_quantity=realized_quantity,
        order_id=1,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert (
        current_position.orders[0].status == base.client.ORDER_STATUS_PARTIALLY_FILLED
    )
    assert current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert current_position.take_profit_order is not None
    assert current_position.take_profit_order.quantity == realized_quantity

    another_realized_quantity = round(float(current_position.orders[0].quantity / 4), 3)

    price = entry_price

    order_update = OrderUpdate(
        price=price,
        quantity=current_position.orders[0].quantity,
        status=base.client.ORDER_STATUS_PARTIALLY_FILLED,
        realized_quantity=realized_quantity + another_realized_quantity,
        last_filled_quantity=another_realized_quantity,
        order_id=1,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert (
        current_position.orders[0].status == base.client.ORDER_STATUS_PARTIALLY_FILLED
    )
    assert current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert current_position.take_profit_order is not None
    assert (
        current_position.take_profit_order.quantity
        == realized_quantity + another_realized_quantity
    )

    assert base.df.iloc[-1]["position"] == Signals.SHORT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_two_orders_filled(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.124"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.186"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.248"}],
    ]

    base.df, current_position, entry_price = await start_short(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )

    assert base.df.iloc[-1]["position"] == Signals.SHORT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_new(mock_create_order, mock_get_order, base):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_get_order.return_value = mock_get_order_return_value()
    base.df, current_position, entry_price = await start_short(base=base)

    order_update = OrderUpdate(
        price=entry_price,
        quantity=0,
        status=base.client.ORDER_STATUS_NEW,
        last_filled_quantity=0,
        realized_quantity=0,
        order_id=1,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders[0].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[3].status == base.client.ORDER_STATUS_NEW

    assert base.df.iloc[-1]["position"] == Signals.SHORT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_expired(mock_create_order, mock_get_order, base):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_get_order.return_value = mock_get_order_return_value()
    base.df, current_position, entry_price = await start_short(base=base)

    order_update = OrderUpdate(
        price=entry_price,
        quantity=0,
        status=base.client.ORDER_STATUS_EXPIRED,
        last_filled_quantity=0,
        realized_quantity=0,
        order_id=1,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders[0].status == base.client.ORDER_STATUS_EXPIRED
    assert current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[3].status == base.client.ORDER_STATUS_NEW

    assert base.df.iloc[-1]["position"] == Signals.SHORT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_canceled(mock_create_order, mock_get_order, base):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_get_order.return_value = mock_get_order_return_value()
    base.df, current_position, entry_price = await start_short(base=base)

    order_update = OrderUpdate(
        price=entry_price,
        quantity=0,
        status=base.client.ORDER_STATUS_CANCELED,
        last_filled_quantity=0,
        realized_quantity=0,
        order_id=1,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders[0].status == base.client.ORDER_STATUS_CANCELED
    assert current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[3].status == base.client.ORDER_STATUS_NEW

    assert base.df.iloc[-1]["position"] == Signals.SHORT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_two_orders_filled_then_target_reached(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.124"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.186"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.248"}],
    ]

    base.df, current_position, entry_price = await start_short(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )
    assert current_position.take_profit_order.price == 19200.0
    assert current_position.liquidation_price == 20800.0

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19248.0
    assert current_position.liquidation_price == 20852.0

    current_position, base.df, balance = await target_reached(
        base=base, current_position=current_position
    )

    assert balance == 1099.45

    assert base.df.iloc[-1]["position"] == Signals.FLAT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_all_orders_filled_then_target_reached(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.124"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.186"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.248"}],
    ]

    base.df, current_position, entry_price = await start_short(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )
    assert current_position.take_profit_order.price == 19200.0
    assert current_position.liquidation_price == 20800.0

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19248.0
    assert current_position.liquidation_price == 20852.0

    current_position = await third_and_fourth_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19344.0
    assert current_position.liquidation_price == 20956.0

    price = current_position.take_profit_order.price
    quantity = current_position.take_profit_order.quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        last_filled_quantity=quantity,
        order_id=6,
        realized_quantity=quantity,
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
    assert round(balance, 2) == 1199.89
    assert base.df.iloc[-1]["position"] == Signals.FLAT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_all_orders_filled_then_target_reached_partially(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.124"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.186"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.248"}],
    ]

    base.df, current_position, entry_price = await start_short(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )
    assert current_position.take_profit_order.price == 19200.0
    assert current_position.liquidation_price == 20800.0

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19248.0
    assert current_position.liquidation_price == 20852.0

    current_position = await third_and_fourth_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19344.0
    assert current_position.liquidation_price == 20956.0

    whole_quantity = current_position.take_profit_order.quantity

    partial_quantity = round(current_position.take_profit_order.quantity / 2, 3)

    rest_of_order_quantity = whole_quantity - partial_quantity

    price = current_position.take_profit_order.price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=whole_quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=6,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert current_position.take_profit_order is not None
    assert current_position.take_profit_order.entry_price == 19344.0
    assert current_position.take_profit_order.quantity == rest_of_order_quantity
    assert current_position.take_profit_order.realized_quantity == partial_quantity
    assert balance == 1099.94
    assert base.df.iloc[-1]["position"] == Signals.SHORT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_all_orders_filled_then_target_reached_partially_then_filled_completely(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.124"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.186"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.248"}],
    ]

    base.df, current_position, entry_price = await start_short(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )
    assert current_position.take_profit_order.price == 19200.0
    assert current_position.liquidation_price == 20800.0

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19248.0
    assert current_position.liquidation_price == 20852.0

    current_position = await third_and_fourth_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19344.0
    assert current_position.liquidation_price == 20956.0

    whole_quantity = current_position.take_profit_order.quantity

    partial_quantity = round(current_position.take_profit_order.quantity / 2, 3)

    rest_of_order_quantity = whole_quantity - partial_quantity

    price = current_position.take_profit_order.price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=whole_quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=6,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert base.df.iloc[-1]["position"] == Signals.SHORT

    for order in current_position.orders:
        logger.info("Order status: %s", order.status)

    assert current_position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert current_position.take_profit_order is not None
    assert current_position.take_profit_order.entry_price == 19344.0
    assert current_position.take_profit_order.quantity == rest_of_order_quantity
    assert current_position.take_profit_order.realized_quantity == partial_quantity
    assert balance == 1099.94

    price = current_position.take_profit_order.entry_price
    quantity = rest_of_order_quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=whole_quantity,
        last_filled_quantity=quantity,
        order_id=7,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=balance,
    )

    assert current_position.orders == []
    assert current_position.take_profit_order is None
    assert balance == 1199.88
    assert base.df.iloc[-1]["position"] == Signals.FLAT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_all_orders_filled_then_liquidation(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_get_order.return_value = mock_get_order_return_value()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.124"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.186"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.248"}],
    ]

    base.df, current_position, entry_price = await start_short(base=base)

    for order in current_position.orders:
        logger.info("Orderdddd: %s", order)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )
    assert current_position.take_profit_order.price == 19200.0
    assert current_position.liquidation_price == 20800.0

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19248.0
    assert current_position.liquidation_price == 20852.0

    current_position = await third_and_fourth_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19344.0
    assert current_position.liquidation_price == 20956.0

    price = current_position.liquidation_price
    quantity = current_position.take_profit_order.quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=quantity,
        order_id=6,
        order_type="LIQUIDATION",
    )

    current_position, base.df, base.position.balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders == []
    assert current_position.take_profit_order is None
    assert base.position.balance == 800.00
    assert base.df.iloc[-1]["position"] == Signals.FLAT
