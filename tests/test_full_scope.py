from unittest.mock import patch
from src.common.orders import PositionSide
from src.features.features import Signal
from src.workers.worker import worker
from src.producers.producers import Event, EventName, SignalUpdate, OrderUpdate
import logging

from tests.test_order_handle import mock_get_order_return_value

logger = logging.getLogger("TEST")


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_full_scope(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_get_order.return_value = mock_get_order_return_value()
    mock_create_order.side_effect = [
        {"orderId": 1, "price": 20000.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 2, "price": 19900.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 3, "price": 19800.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 4, "price": 19700.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20800, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20500, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 7, "price": 20500.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 8, "price": 20602.5, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 9, "price": 20705.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 10, "price": 20807.5, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 11, "price": 19680.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 12, "price": 19729.4, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 13, "price": 19814.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 14, "price": 19814.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 15, "price": 19714.9, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 16, "price": 19615.9, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 17, "price": 19516.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 18, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 19, "price": 20050.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 20, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 21, "price": 20050.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 22, "price": 20500.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 23, "price": 20602.5, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 24, "price": 20705.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 25, "price": 20807.5, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 26, "price": 19824.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 27, "price": 20500.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 28, "price": 20602.5, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 29, "price": 20705.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 27, "price": 20500.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 28, "price": 20602.5, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 29, "price": 20705.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 30, "price": 20807.5, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 34, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 35, "price": 21476.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 36, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 37, "price": 19814.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 38, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 39, "price": 20050.0, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 40, "price": 20150.2, "status": base.client.ORDER_STATUS_NEW},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "21320", "entryPrice": "20500", "positionAmt": "0.123"}],
        [
            {
                "liquidationPrice": "21373",
                "entryPrice": "20551.5",
                "positionAmt": "0.123",
            }
        ],
        [
            {
                "liquidationPrice": "19200",
                "entryPrice": "19814.0",
                "positionAmt": "0.032",
            }
        ],
        [
            {
                "liquidationPrice": "21320",
                "entryPrice": "19714.9",
                "positionAmt": "0.064",
            }
        ],
        [
            {
                "liquidationPrice": "21373",
                "entryPrice": "19615.9",
                "positionAmt": "0.096",
            }
        ],
        [
            {
                "liquidationPrice": "19056",
                "entryPrice": "19516.8",
                "positionAmt": "0.254",
            }
        ],
        [{"liquidationPrice": "21320", "entryPrice": "20500.0", "positionAmt": "0.03"}],
        [{"liquidationPrice": "21373", "entryPrice": "20551.0", "positionAmt": "0.06"}],
        [{"liquidationPrice": "21426", "entryPrice": "20602.5", "positionAmt": "0.09"}],
        [
            {
                "liquidationPrice": "21476",
                "entryPrice": "20650.0",
                "positionAmt": "0.242",
            }
        ],
        [
            {
                "liquidationPrice": "21320",
                "entryPrice": "20500.0",
                "positionAmt": "0.061",
            }
        ],
        [
            {
                "liquidationPrice": "21373",
                "entryPrice": "20551.0",
                "positionAmt": "0.0122",
            }
        ],
        [
            {
                "liquidationPrice": "21426",
                "entryPrice": "20602.5",
                "positionAmt": "0.182",
            }
        ],
        [
            {
                "liquidationPrice": "21476",
                "entryPrice": "20650.0",
                "positionAmt": "0.484",
            }
        ],
    ]

    logger.info("Base finished, start test")

    position = base.position

    logger.info("################ START LONG ####################")
    entry_signal = Signal.LONG
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    await base.queue.put(Event(name=EventName.SIGNAL, content=signal_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=signal_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert len(position.current_position.orders) == 4
    assert 1000 == position.balance
    assert position.current_position.status == entry_signal

    assert all(
        order.entry_price <= entry_price for order in position.current_position.orders
    )

    logger.info("################ REALIZE 1 ORDER ####################")

    quantity_first_order = position.current_position.orders[0].quantity

    order_update = OrderUpdate(
        price=entry_price,
        quantity=quantity_first_order,
        status=base.client.ORDER_STATUS_FILLED,
        last_filled_quantity=quantity_first_order,
        realized_quantity=quantity_first_order,
        order_id=1,
    )

    await base.queue.put(Event(name=EventName.ORDER, content=order_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=order_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert position.current_position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert (
        position.current_position.take_profit_order.quantity
        == position.current_position.orders[0].quantity
    )
    assert position.current_position.status == entry_signal
    assert position.current_position.take_profit_order.entry_price == 20800.0

    logger.info("################ SELL SIGNAL ####################")

    signal_update = SignalUpdate(signal=Signals.SHORT, price=20500)

    await base.queue.put(Event(name=EventName.SIGNAL, content=signal_update))
    await base.queue.put(Event(name=EventName.SIGNAL, content=signal_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=signal_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert position.current_position.status == signal_update.signal
    assert position.current_position.orders[0].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is None

    logger.info("################ REALIZE TWO ORDERS ####################")

    quantity_second_order = position.current_position.orders[0].quantity

    order_update_1 = OrderUpdate(
        price=position.current_position.orders[0].entry_price,
        quantity=quantity_first_order,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=quantity_first_order,
        last_filled_quantity=quantity_first_order,
        order_id=7,
    )
    order_update_2 = OrderUpdate(
        price=position.current_position.orders[1].entry_price,
        quantity=quantity_second_order,
        status=base.client.ORDER_STATUS_FILLED,
        last_filled_quantity=quantity_second_order,
        realized_quantity=quantity_second_order,
        order_id=8,
    )

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_1))

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_2))

    await base.queue.put(Event(name=EventName.SENTINEL, content=order_update_1))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert position.current_position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert (
        position.current_position.take_profit_order.quantity
        == position.current_position.orders[0].quantity
        + position.current_position.orders[1].quantity
    )
    assert position.current_position.take_profit_order.entry_price == 19729.4
    assert position.current_position.status == signal_update.signal

    logger.info("################ SIGNAL LONG ####################")

    signal_update = SignalUpdate(signal=Signals.LONG, price=19814)

    # ITS DONE TWICE AS THERE WAS A NEED WHEN CHAGNGING DIRECTLY FROM ONE POSITION TO OPPOSITE, TO GIVE SOME BREATH
    # AFTER CLOSING FIRST POSITION WITH MARKET, AS THERE GONNA BE ORDER TRADE UPDATE MSGS WITH MARKET TYPE FILLED
    # WHICH HAVE TO BE EXECUTED FIRST. SO FIRST SIGNAL UPDATE JUST CLOSES CURRENT POSITION, SECOND OPENS OPPOSITE ONE.
    await base.queue.put(Event(name=EventName.SIGNAL, content=signal_update))
    await base.queue.put(Event(name=EventName.SIGNAL, content=signal_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=signal_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert position.current_position.status == signal_update.signal
    assert position.current_position.orders[0].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is None

    logger.info("################ REALIZE ALL ORDERS ####################")

    order_update_1 = OrderUpdate(
        price=position.current_position.orders[0].entry_price,
        quantity=position.current_position.orders[0].quantity,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=position.current_position.orders[0].quantity,
        last_filled_quantity=position.current_position.orders[0].quantity,
        order_id=14,
    )
    order_update_2 = OrderUpdate(
        price=position.current_position.orders[1].entry_price,
        quantity=position.current_position.orders[1].quantity,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=position.current_position.orders[1].quantity,
        last_filled_quantity=position.current_position.orders[1].quantity,
        order_id=15,
    )
    order_update_3 = OrderUpdate(
        price=position.current_position.orders[2].entry_price,
        quantity=position.current_position.orders[2].quantity,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=position.current_position.orders[2].quantity,
        last_filled_quantity=position.current_position.orders[2].quantity,
        order_id=16,
    )
    order_update_4 = OrderUpdate(
        price=position.current_position.orders[3].entry_price,
        quantity=position.current_position.orders[3].quantity,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=position.current_position.orders[3].quantity,
        last_filled_quantity=position.current_position.orders[3].quantity,
        order_id=17,
    )

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_1))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_2))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_3))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_4))

    await base.queue.put(Event(name=EventName.SENTINEL, content=order_update_1))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert position.current_position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert (
        position.current_position.take_profit_order.quantity
        == position.current_position.orders[0].quantity
        + position.current_position.orders[1].quantity
        + position.current_position.orders[2].quantity
        + position.current_position.orders[3].quantity
    )
    assert position.current_position.take_profit_order.entry_price == 20297.5
    assert position.current_position.status == signal_update.signal

    logger.info("################ TARGET PRICE REACHED ####################")

    order_update = OrderUpdate(
        price=position.current_position.take_profit_order.entry_price,
        quantity=position.current_position.take_profit_order.quantity,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=position.current_position.take_profit_order.quantity,
        last_filled_quantity=position.current_position.take_profit_order.quantity,
        order_id=21,
    )

    await base.queue.put(Event(name=EventName.ORDER, content=order_update))

    await base.queue.put(Event(name=EventName.SENTINEL, content=order_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert len(position.current_position.orders) == 0
    assert position.current_position.take_profit_order is None
    assert position.current_position.side == PositionSide.FLAT
    assert position.current_position.status.value == PositionSide.FLAT

    logger.info("################ OPEN SHORT WITH SIGNAL ####################")

    signal_update = SignalUpdate(signal=Signals.SHORT, price=20500)
    await base.queue.put(Event(name=EventName.SIGNAL, content=signal_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=signal_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert position.current_position.status == signal_update.signal
    assert position.current_position.orders[0].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is None

    logger.info("################ REALIZE ALL SHORT ORDERS ####################")

    order_update_1 = OrderUpdate(
        price=position.current_position.orders[0].entry_price,
        quantity=position.current_position.orders[0].quantity,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=position.current_position.orders[0].quantity,
        last_filled_quantity=position.current_position.orders[0].quantity,
        order_id=22,
    )
    order_update_2 = OrderUpdate(
        price=position.current_position.orders[1].entry_price,
        quantity=position.current_position.orders[1].quantity,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=position.current_position.orders[1].quantity,
        last_filled_quantity=position.current_position.orders[1].quantity,
        order_id=23,
    )
    order_update_3 = OrderUpdate(
        price=position.current_position.orders[2].entry_price,
        quantity=position.current_position.orders[2].quantity,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=position.current_position.orders[2].quantity,
        last_filled_quantity=position.current_position.orders[2].quantity,
        order_id=24,
    )
    order_update_4 = OrderUpdate(
        price=position.current_position.orders[3].entry_price,
        quantity=position.current_position.orders[3].quantity,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=position.current_position.orders[3].quantity,
        last_filled_quantity=position.current_position.orders[3].quantity,
        order_id=25,
    )

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_1))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_2))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_3))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_4))

    await base.queue.put(Event(name=EventName.SENTINEL, content=order_update_1))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert position.current_position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert (
        position.current_position.take_profit_order.quantity
        == position.current_position.orders[0].quantity
        + position.current_position.orders[1].quantity
        + position.current_position.orders[2].quantity
        + position.current_position.orders[3].quantity
    )
    assert position.current_position.take_profit_order.entry_price == 19824.0
    assert position.current_position.status == signal_update.signal

    logger.info("################ TARGET PRICE REACHED ####################")

    order_update = OrderUpdate(
        price=position.current_position.take_profit_order.entry_price,
        quantity=position.current_position.take_profit_order.quantity,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=position.current_position.take_profit_order.quantity,
        last_filled_quantity=position.current_position.take_profit_order.quantity,
        order_id=26,
    )

    await base.queue.put(Event(name=EventName.ORDER, content=order_update))

    await base.queue.put(Event(name=EventName.SENTINEL, content=order_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert len(position.current_position.orders) == 0
    assert position.current_position.take_profit_order is None
    assert position.current_position.side == PositionSide.FLAT
    assert position.current_position.status.value == PositionSide.FLAT

    logger.info("################ OPEN SHORT WITH SIGNAL ####################")

    signal_update = SignalUpdate(signal=Signals.SHORT, price=20500)
    await base.queue.put(Event(name=EventName.SIGNAL, content=signal_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=signal_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert position.current_position.status == signal_update.signal
    assert position.current_position.orders[0].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is None

    logger.info("################ REALIZE ALL SHORT ORDERS ####################")

    order_update_1 = OrderUpdate(
        price=position.current_position.orders[0].entry_price,
        quantity=position.current_position.orders[0].quantity,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=position.current_position.orders[0].quantity,
        last_filled_quantity=position.current_position.orders[0].quantity,
        order_id=27,
    )
    order_update_2 = OrderUpdate(
        price=position.current_position.orders[1].entry_price,
        quantity=position.current_position.orders[1].quantity,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=position.current_position.orders[1].quantity,
        last_filled_quantity=position.current_position.orders[1].quantity,
        order_id=28,
    )
    order_update_3 = OrderUpdate(
        price=position.current_position.orders[2].entry_price,
        quantity=position.current_position.orders[2].quantity,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=position.current_position.orders[2].quantity,
        last_filled_quantity=position.current_position.orders[2].quantity,
        order_id=29,
    )
    order_update_4 = OrderUpdate(
        price=position.current_position.orders[3].entry_price,
        quantity=position.current_position.orders[3].quantity,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=position.current_position.orders[3].quantity,
        last_filled_quantity=position.current_position.orders[3].quantity,
        order_id=30,
    )

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_1))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_2))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_3))
    await base.queue.put(Event(name=EventName.ORDER, content=order_update_4))

    await base.queue.put(Event(name=EventName.SENTINEL, content=order_update_1))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert position.current_position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert (
        position.current_position.take_profit_order.quantity
        == position.current_position.orders[0].quantity
        + position.current_position.orders[1].quantity
        + position.current_position.orders[2].quantity
        + position.current_position.orders[3].quantity
    )
    assert position.current_position.take_profit_order.entry_price == 19824.0
    assert position.current_position.status == signal_update.signal

    logger.info("################ TARGET PRICE REACHED ####################")

    order_update = OrderUpdate(
        price=position.current_position.take_profit_order.entry_price,
        quantity=position.current_position.take_profit_order.quantity,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=position.current_position.take_profit_order.quantity,
        last_filled_quantity=position.current_position.take_profit_order.quantity,
        order_id=35,
    )

    await base.queue.put(Event(name=EventName.ORDER, content=order_update))

    await base.queue.put(Event(name=EventName.SENTINEL, content=order_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=[],
    )

    assert len(position.current_position.orders) == 0
    assert position.current_position.take_profit_order is None
    assert position.current_position.side == PositionSide.FLAT
    assert position.current_position.status.value == PositionSide.FLAT
    assert position.current_position.entry_price == 0
    assert position.current_position.quantity == 0
    assert position.current_position.target_price == 0
    assert position.current_position.liquidation_price == 0
