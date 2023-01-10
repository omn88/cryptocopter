from unittest.mock import patch
from src.features import Signals
from src.orders import PositionSide
from src.workers.worker import worker
from src.producers.producers import Event, EventName, SignalUpdate, OrderUpdate
import logging

logger = logging.getLogger("TEST")


@patch("src.workers.worker.validate_current_position")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_full_scope(
    mock_create_order, mock_cancel_order, mock_validate_current_position, base
):
    mock_create_order.side_effect = [
        {"orderId": 1, "price": 20000.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 2, "price": 19900.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 3, "price": 19800.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 4, "price": 19700.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20500, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20500, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 7, "price": 20500.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 8, "price": 20602.5, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 9, "price": 20705.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 10, "price": 20807.5, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 11, "price": 20050.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 12, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 13, "price": 19814.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 14, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 15, "price": 20050.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 16, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 17, "price": 19814.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 18, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 19, "price": 20050.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 20, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 21, "price": 20050.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 22, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 23, "price": 19814.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 24, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 25, "price": 20050.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 26, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 27, "price": 19814.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 28, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 29, "price": 20050.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 30, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 31, "price": 20050.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 32, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 33, "price": 19814.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 34, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 35, "price": 20050.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 36, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 37, "price": 19814.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 38, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 39, "price": 20050.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 40, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_validate_current_position.return_value = True

    logger.info("Base finished, start test")

    interval = "15m"
    position = base.position

    logger.info("################ START LONG ####################")
    entry_signal = Signals.LONG
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    await base.queue.put(Event(name=EventName.SIGNAL, content=signal_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=signal_update))

    base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert 4 == len(position.orders)
    assert 1000 == position.saldo

    assert all(order.price <= entry_price for order in position.orders)

    logger.info("################ REALIZE 1 ORDER ####################")

    order_update = OrderUpdate(
        price=entry_price,
        quantity=position.orders[0].quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )

    await base.queue.put(Event(name=EventName.ORDER, content=order_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=order_update))

    base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert (
        position.current_position.take_profit_order.quantity
        == position.orders[0].quantity
    )
    assert position.current_position.take_profit_order.price == 20350.4

    logger.info("################ SELL SIGNAL ####################")

    signal_update = SignalUpdate(signal=Signals.SHORT, price=20500)

    await base.queue.put(Event(name=EventName.SIGNAL, content=signal_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=signal_update))

    base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    logger.info("################ REALIZE TWO ORDERS ####################")

    order_update_1 = OrderUpdate(
        price=position.orders[0].price,
        quantity=position.orders[0].quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )
    order_update_2 = OrderUpdate(
        price=position.orders[1].price,
        quantity=position.orders[1].quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_1))

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_2))

    await base.queue.put(Event(name=EventName.SENTINEL, content=order_update_1))

    base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert (
        position.current_position.take_profit_order.quantity
        == position.orders[0].quantity + position.orders[1].quantity
    )
    assert position.current_position.take_profit_order.price == 19729.2

    logger.info("################ SIGNAL LONG ####################")

    signal_update = SignalUpdate(signal=Signals.LONG, price=19814)

    await base.queue.put(Event(name=EventName.SIGNAL, content=signal_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=signal_update))

    base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    logger.info("################ REALIZE ALL ORDERS ####################")

    order_update_1 = OrderUpdate(
        price=position.orders[0].price,
        quantity=position.orders[0].quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )
    order_update_2 = OrderUpdate(
        price=position.orders[1].price,
        quantity=position.orders[1].quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )
    order_update_3 = OrderUpdate(
        price=position.orders[2].price,
        quantity=position.orders[2].quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )
    order_update_4 = OrderUpdate(
        price=position.orders[3].price,
        quantity=position.orders[3].quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_1))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_2))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_3))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_4))

    await base.queue.put(Event(name=EventName.SENTINEL, content=order_update_1))

    base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert (
        position.current_position.take_profit_order.quantity
        == position.orders[0].quantity
        + position.orders[1].quantity
        + position.orders[2].quantity
        + position.orders[3].quantity
    )
    assert position.current_position.take_profit_order.price == 20452.0

    logger.info("################ TARGET PRICE REACHED ####################")

    order_update = OrderUpdate(
        price=position.current_position.take_profit_order.price,
        quantity=position.current_position.take_profit_order.quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )

    await base.queue.put(Event(name=EventName.ORDER, content=order_update))

    await base.queue.put(Event(name=EventName.SENTINEL, content=order_update))

    base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert len(position.orders) == 0
    assert position.current_position.take_profit_order is None
    assert position.current_position.side == PositionSide.FLAT

    logger.info("################ OPEN SHORT WITH SIGNAL ####################")

    signal_update = SignalUpdate(signal=Signals.SHORT, price=20500)
    await base.queue.put(Event(name=EventName.SIGNAL, content=signal_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=signal_update))

    base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    logger.info("################ REALIZE ALL SHORT ORDERS ####################")

    order_update_1 = OrderUpdate(
        price=position.orders[0].price,
        quantity=position.orders[0].quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )
    order_update_2 = OrderUpdate(
        price=position.orders[1].price,
        quantity=position.orders[1].quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )
    order_update_3 = OrderUpdate(
        price=position.orders[2].price,
        quantity=position.orders[2].quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )
    order_update_4 = OrderUpdate(
        price=position.orders[3].price,
        quantity=position.orders[3].quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_1))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_2))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_3))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_4))

    await base.queue.put(Event(name=EventName.SENTINEL, content=order_update_1))

    base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert (
        position.current_position.take_profit_order.quantity
        == position.orders[0].quantity
        + position.orders[1].quantity
        + position.orders[2].quantity
        + position.orders[3].quantity
    )
    assert position.current_position.take_profit_order.price == 19827.6

    logger.info("################ TARGET PRICE REACHED ####################")

    order_update = OrderUpdate(
        price=position.current_position.take_profit_order.price,
        quantity=position.current_position.take_profit_order.quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )

    await base.queue.put(Event(name=EventName.ORDER, content=order_update))

    await base.queue.put(Event(name=EventName.SENTINEL, content=order_update))

    base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert len(position.orders) == 0
    assert position.current_position.take_profit_order is None
    assert position.current_position.side == PositionSide.FLAT

    logger.info("################ OPEN SHORT WITH SIGNAL ####################")

    signal_update = SignalUpdate(signal=Signals.SHORT, price=20500)
    await base.queue.put(Event(name=EventName.SIGNAL, content=signal_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=signal_update))

    base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    logger.info("################ REALIZE ALL SHORT ORDERS ####################")

    order_update_1 = OrderUpdate(
        price=position.orders[0].price,
        quantity=position.orders[0].quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )
    order_update_2 = OrderUpdate(
        price=position.orders[1].price,
        quantity=position.orders[1].quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )
    order_update_3 = OrderUpdate(
        price=position.orders[2].price,
        quantity=position.orders[2].quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )
    order_update_4 = OrderUpdate(
        price=position.orders[3].price,
        quantity=position.orders[3].quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_1))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_2))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_3))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_4))

    await base.queue.put(Event(name=EventName.SENTINEL, content=order_update_1))

    base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert (
        position.current_position.take_profit_order.quantity
        == position.orders[0].quantity
        + position.orders[1].quantity
        + position.orders[2].quantity
        + position.orders[3].quantity
    )
    assert position.current_position.take_profit_order.price == 19826.8

    logger.info("################ TARGET PRICE REACHED ####################")

    order_update = OrderUpdate(
        price=position.current_position.liquidation_price,
        quantity=position.current_position.take_profit_order.quantity,
        status=base.client.ORDER_STATUS_FILLED,
    )

    await base.queue.put(Event(name=EventName.ORDER, content=order_update))

    await base.queue.put(Event(name=EventName.SENTINEL, content=order_update))

    base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert len(position.orders) == 0
    assert position.current_position.take_profit_order is None
    assert position.current_position.side == PositionSide.FLAT
