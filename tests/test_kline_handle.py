from unittest.mock import patch

from src.common.identifiers import State
from src.producers.producers import Event, EventName, KlineUpdate
from src.workers.worker import worker
from tests.common import get_orders_long, get_cancel_order
import logging

logger = logging.getLogger("test")


async def test_rsi_basic_handle_kline_null(basic_rsi):
    basic_rsi.client.futures_create_order.side_effect = get_orders_long()
    basic_rsi.client.futures_cancel_order.return_value = get_cancel_order()

    # NO SIGNAL THEN NULL
    kline_update = KlineUpdate(
        kline=["1672306200000", "19573.19", "19605.9", "17160.1", "16700.72", "0", "0"]
    )
    await basic_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await basic_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=basic_rsi,
        queue=basic_rsi.queue,
    )

    assert len(basic_rsi.position.orders) == 0
    assert 1000 == basic_rsi.balance
    assert basic_rsi.position.status == State.FLAT


async def test_rsi_basic_handle_kline_long_twenty(extended_rsi):
    extended_rsi.client.futures_create_order.side_effect = get_orders_long()
    extended_rsi.client.futures_cancel_order.return_value = get_cancel_order()

    # NO SIGNAL THEN NULL
    kline_update = KlineUpdate(
        kline=["1672306200000", "19573.19", "19605.9", "17160.1", "16700.72", "0", "0"]
    )
    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert len(extended_rsi.position.orders) == 0
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.FLAT

    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672307100000, 19573.19, 19605.9, 18360.1, 18500.72, 0, 0]
        ]
    )

    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert len(extended_rsi.position.orders) == 4
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.LONG_EXT


async def test_rsi_basic_handle_kline_long_twenty_long(extended_rsi):
    extended_rsi.client.futures_create_order.side_effect = get_orders_long()
    extended_rsi.client.futures_cancel_order.return_value = get_cancel_order()

    # NO SIGNAL THEN NULL
    kline_update = KlineUpdate(
        kline=["1672306200000", "19573.19", "19605.9", "17160.1", "16700.72", "0", "0"]
    )
    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert len(extended_rsi.position.orders) == 0
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.FLAT

    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672307100000, 19573.19, 19605.9, 18360.1, 18500.72, 0, 0]
        ]
    )

    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert len(extended_rsi.position.orders) == 4
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.LONG_EXT

    # LONG
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672308000000, 19573.19, 19605.9, 18360.1, 27000.72, 0, 0]
        ]
    )

    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert 4 == len(extended_rsi.position.orders)
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.LONG


async def test_rsi_basic_handle_kline_long_twenty_long_null(extended_rsi):
    extended_rsi.client.futures_create_order.side_effect = get_orders_long()
    extended_rsi.client.futures_cancel_order.return_value = get_cancel_order()

    # NO SIGNAL THEN NULL
    kline_update = KlineUpdate(
        kline=["1672306200000", "19573.19", "19605.9", "17160.1", "16700.72", "0", "0"]
    )
    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert len(extended_rsi.position.orders) == 0
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.FLAT

    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672307100000, 19573.19, 19605.9, 18360.1, 18500.72, 0, 0]
        ]
    )

    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert len(extended_rsi.position.orders) == 4
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.LONG_EXT

    # LONG
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672308000000, 19573.19, 19605.9, 18360.1, 27000.72, 0, 0]
        ]
    )

    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert 4 == len(extended_rsi.position.orders)
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.LONG

    # NO SIGNAL THEN NULL LONG20 LONG NULL
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672308900000, 19573.19, 19605.9, 18360.1, 29700.72, 0, 0]
        ]
    )

    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert 4 == len(extended_rsi.position.orders)
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.LONG


@patch("src.workers.handle_order.save_to_file")
async def test_rsi_basic_handle_kline_long_twenty_long_null_short_eighty(
    mock_save_to_file, extended_rsi
):
    extended_rsi.client.futures_create_order.side_effect = get_orders_long()
    extended_rsi.client.futures_cancel_order.return_value = get_cancel_order()
    mock_save_to_file.return_value = True

    # NO SIGNAL THEN NULL
    kline_update = KlineUpdate(
        kline=["1672306200000", "19573.19", "19605.9", "17160.1", "16700.72", "0", "0"]
    )
    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert len(extended_rsi.position.orders) == 0
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.FLAT

    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672307100000, 19573.19, 19605.9, 18360.1, 18500.72, 0, 0]
        ]
    )

    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert len(extended_rsi.position.orders) == 4
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.LONG_EXT

    # LONG
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672308000000, 19573.19, 19605.9, 18360.1, 27000.72, 0, 0]
        ]
    )

    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert 4 == len(extended_rsi.position.orders)
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.LONG

    # NO SIGNAL THEN NULL LONG20 LONG NULL
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672308900000, 19573.19, 19605.9, 18360.1, 29700.72, 0, 0]
        ]
    )

    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert 4 == len(extended_rsi.position.orders)
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.LONG

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672309800000, 19573.19, 19605.9, 18360.1, 26200.72, 0, 0]
        ]
    )

    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert 4 == len(extended_rsi.position.orders)
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.SHORT_EXT


@patch("src.workers.handle_order.save_to_file")
async def test_rsi_basic_handle_kline_long_twenty_long_null_short_eighty_short(
    mock_save_to_file,
    extended_rsi,
):
    extended_rsi.client.futures_create_order.side_effect = get_orders_long()
    extended_rsi.client.futures_cancel_order.return_value = get_cancel_order()
    mock_save_to_file.return_value = True

    # NO SIGNAL THEN NULL
    kline_update = KlineUpdate(
        kline=["1672306200000", "19573.19", "19605.9", "17160.1", "16700.72", "0", "0"]
    )
    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert len(extended_rsi.position.orders) == 0
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.FLAT

    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672307100000, 19573.19, 19605.9, 18360.1, 18500.72, 0, 0]
        ]
    )

    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert len(extended_rsi.position.orders) == 4
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.LONG_EXT

    # LONG
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672308000000, 19573.19, 19605.9, 18360.1, 27000.72, 0, 0]
        ]
    )

    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert 4 == len(extended_rsi.position.orders)
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.LONG

    # NO SIGNAL THEN NULL LONG20 LONG NULL
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672308900000, 19573.19, 19605.9, 18360.1, 29700.72, 0, 0]
        ]
    )

    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert 4 == len(extended_rsi.position.orders)
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.LONG

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672309800000, 19573.19, 19605.9, 18360.1, 26200.72, 0, 0]
        ]
    )

    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert 4 == len(extended_rsi.position.orders)
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.SHORT_EXT

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672310700000, 19573.19, 19605.9, 18360.1, 22200.72, 0, 0]
        ]
    )

    await extended_rsi.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    await extended_rsi.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
    await worker(
        tsm=extended_rsi,
        queue=extended_rsi.queue,
    )

    assert 4 == len(extended_rsi.position.orders)
    assert 1000 == extended_rsi.balance
    assert extended_rsi.position.status == State.SHORT

    # ToDO: CONTINUE WHEN THE SPECIAL FEATURE IS IMPLEMENTED


#     # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT NULL
#     kline_update = KlineUpdate(
#         kline=[
#             str(x) for x in [1672311600000, 19573.19, 19605.9, 18360.1, 28200.72, 0, 0]
#         ]
#     )
#     await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
#     await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
#
#     historical_data, base.df, position = await worker(
#         client=base.client,
#         df=base.df,
#         position=position,
#         queue=base.queue,
#         historical_data=historical_data,
#     )
#
#     logger.info("base: %s", base.df.to_string())
#
#     assert 4 == len(position.current_position.orders)
#     assert 1000 == position.balance
#     assert position.current_position.status == Signals.SHORT
#
#     # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT NULL SPECIAL_LONG
#     kline_update = KlineUpdate(
#         kline=[
#             str(x) for x in [1672312500000, 19573.19, 19605.9, 18360.1, 56400.72, 0, 0]
#         ]
#     )
#     await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
#     await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
#
#     historical_data, base.df, position = await worker(
#         client=base.client,
#         df=base.df,
#         position=position,
#         queue=base.queue,
#         historical_data=historical_data,
#     )
#
#     logger.info("base: %s", base.df)
#
#     event = await base.queue.get()
#
#     signal_update = event.content
#
#     position.current_position, base.df = await signal_handle(
#         signal_update=signal_update,
#         client=base.client,
#         current_position=position.current_position,
#         df=base.df,
#         balance=base.position.balance,
#         order_quantity_list=base.position.order_quantity_list,
#         queue=base.queue,
#     )
#
#     logger.info("ORDERS: %s", position.current_position.orders)
#
#     assert 1 == len(position.current_position.orders)
#     assert 1000 == position.balance
#     assert position.current_position.status == Signals.LONG_SPECIAL
#
#     # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT NULL SPECIAL_LONG SHORT_EXT
#     kline_update = KlineUpdate(
#         kline=[
#             str(x) for x in [1672313400000, 19573.19, 19605.9, 18360.1, 36400.72, 0, 0]
#         ]
#     )
#     await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
#     await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
#
#     historical_data, base.df, position = await worker(
#         client=base.client,
#         df=base.df,
#         position=position,
#         queue=base.queue,
#         historical_data=historical_data,
#     )
#
#     logger.info("base: %s", base.df)
#
#     assert 1 == len(position.current_position.orders)
#     assert 1000 == position.balance
#     assert position.current_position.status == Signals.LONG_SPECIAL
#
#     # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT NULL SPECIAL_LONG SHORT_EXT SHORT
#     kline_update = KlineUpdate(
#         kline=[
#             str(x) for x in [1672314300000, 19573.19, 19605.9, 18360.1, 32400.72, 0, 0]
#         ]
#     )
#     await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
#     await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
#
#     historical_data, base.df, position = await worker(
#         client=base.client,
#         df=base.df,
#         position=position,
#         queue=base.queue,
#         historical_data=historical_data,
#     )
#
#     logger.info("base: %s", base.df)
#
#     assert 1 == len(position.current_position.orders)
#     assert 1000 == position.balance
#     assert position.current_position.status == Signals.LONG_SPECIAL
#
#     # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT NULL SPECIAL_LONG SHORT_EXT SHORT NULL
#     kline_update = KlineUpdate(
#         kline=[
#             str(x) for x in [1672315200000, 19573.19, 19605.9, 18360.1, 32400.72, 0, 0]
#         ]
#     )
#     await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
#     await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
#
#     historical_data, base.df, position = await worker(
#         client=base.client,
#         df=base.df,
#         position=position,
#         queue=base.queue,
#         historical_data=historical_data,
#     )
#
#     logger.info("base: %s", base.df)
#
#     assert 1 == len(position.current_position.orders)
#     assert 1000 == position.balance
#     assert position.current_position.status == Signals.LONG_SPECIAL
#
#     # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT NULL SPECIAL_LONG SHORT_EXT SHORT NULL NULL
#     kline_update = KlineUpdate(
#         kline=[
#             str(x) for x in [1672316100000, 19573.19, 19605.9, 18360.1, 20400.72, 0, 0]
#         ]
#     )
#     await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
#     await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
#
#     historical_data, base.df, position = await worker(
#         client=base.client,
#         df=base.df,
#         position=position,
#         queue=base.queue,
#         historical_data=historical_data,
#     )
#
#     logger.info("base: %s", base.df.to_string())
#
#     logger.info(position.current_position.orders)
#
#     assert 0 == len(position.current_position.orders)
#     assert 1000 == position.balance
#     assert position.current_position.status == Signals.FLAT
#
#
# @patch("binance.AsyncClient.futures_get_order")
# @patch("binance.AsyncClient.futures_cancel_order")
# @patch("binance.AsyncClient.futures_create_order")
# async def test_kline_handling_for_special_short(
#     mock_create_order, mock_cancel_order, mock_get_order, base
# ):
#     mock_create_order.side_effect = [
#         {"orderId": "1", "price": "18500.7", "status": base.client.ORDER_STATUS_NEW},
#         {"orderId": "2", "price": "18408.2", "status": base.client.ORDER_STATUS_NEW},
#         {"orderId": "3", "price": "18315.7", "status": base.client.ORDER_STATUS_NEW},
#         {"orderId": "4", "price": "18223.2", "status": base.client.ORDER_STATUS_NEW},
#         {"orderId": "5", "price": "20800", "status": base.client.ORDER_STATUS_NEW},
#         {"orderId": "6", "price": "20500", "status": base.client.ORDER_STATUS_NEW},
#         {"orderId": "7", "price": "20500.0", "status": base.client.ORDER_STATUS_NEW},
#         {"orderId": "8", "price": "20602.5", "status": base.client.ORDER_STATUS_NEW},
#         {"orderId": "9", "price": "20602.5", "status": base.client.ORDER_STATUS_NEW},
#     ]
#     mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
#     mock_get_order.return_value = mock_get_order_return_value()
#     # NO SIGNAL THEN NULL
#     kline_update = KlineUpdate(
#         kline=["1672306200000", "19573.19", "19605.9", "17160.1", "17700.72", "0", "0"]
#     )
#     await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
#     await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
#
#     historical_data, base.df, position = await worker(
#         client=base.client,
#         df=base.df,
#         position=base.position,
#         queue=base.queue,
#         historical_data=data_no_signal(),
#     )
#
#     assert len(position.current_position.orders) == 0
#     assert 1000 == position.balance
#
#     # NO SIGNAL THEN NULL NULL
#     kline_update = KlineUpdate(
#         kline=[
#             str(x) for x in [1672307100000, 19573.19, 19605.9, 18360.1, 18200.72, 0, 0]
#         ]
#     )
#
#     await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
#     await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
#
#     historical_data, base.df, position = await worker(
#         client=base.client,
#         df=base.df,
#         position=position,
#         queue=base.queue,
#         historical_data=historical_data,
#     )
#
#     logger.info("base.df: %s", base.df.to_string())
#
#     assert len(position.current_position.orders) == 0
#     assert 1000 == position.balance
#
#     # NO SIGNAL THEN NULL NULL LONG
#     kline_update = KlineUpdate(
#         kline=[
#             str(x) for x in [1672308000000, 19573.19, 19605.9, 18360.1, 17700.72, 0, 0]
#         ]
#     )
#
#     await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
#     await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
#
#     historical_data, base.df, position = await worker(
#         client=base.client,
#         df=base.df,
#         position=position,
#         queue=base.queue,
#         historical_data=historical_data,
#     )
#
#     assert 4 == len(position.current_position.orders)
#     assert 1000 == position.balance
#     assert position.current_position.status == Signals.LONG
#
#     # NO SIGNAL THEN NULL NULL LONG SPECIAL_SHORT
#     kline_update = KlineUpdate(
#         kline=[
#             str(x) for x in [1672308900000, 19573.19, 19605.9, 18360.1, 14700.72, 0, 0]
#         ]
#     )
#
#     await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
#     await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
#
#     historical_data, base.df, position = await worker(
#         client=base.client,
#         df=base.df,
#         position=position,
#         queue=base.queue,
#         historical_data=historical_data,
#     )
#
#     event = await base.queue.get()
#
#     signal_update = event.content
#
#     position.current_position, base.df = await signal_handle(
#         signal_update=signal_update,
#         client=base.client,
#         current_position=position.current_position,
#         df=base.df,
#         balance=base.position.balance,
#         order_quantity_list=base.position.order_quantity_list,
#         queue=base.queue,
#     )
#
#     assert 1 == len(position.current_position.orders)
#     assert 1000 == position.balance
#     assert position.current_position.status == Signals.SHORT_SPECIAL
#
#     # NO SIGNAL THEN NULL NULL LONG SPECIAL_SHORT LONG_EXT
#     kline_update = KlineUpdate(
#         kline=[
#             str(x) for x in [1672309800000, 19573.19, 19605.9, 18360.1, 17700.72, 0, 0]
#         ]
#     )
#
#     await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
#     await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
#
#     historical_data, base.df, position = await worker(
#         client=base.client,
#         df=base.df,
#         position=position,
#         queue=base.queue,
#         historical_data=historical_data,
#     )
#
#     assert 1 == len(position.current_position.orders)
#     assert 1000 == position.balance
#     assert position.current_position.status == Signals.SHORT_SPECIAL
#
#     # NO SIGNAL THEN NULL NULL LONG SPECIAL_SHORT LONG_EXT LONG
#     kline_update = KlineUpdate(
#         kline=[
#             str(x) for x in [1672310700000, 19573.19, 19605.9, 18360.1, 17700.72, 0, 0]
#         ]
#     )
#
#     await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
#     await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
#
#     historical_data, base.df, position = await worker(
#         client=base.client,
#         df=base.df,
#         position=position,
#         queue=base.queue,
#         historical_data=historical_data,
#     )
#
#     assert 1 == len(position.current_position.orders)
#     assert 1000 == position.balance
#     assert position.current_position.status == Signals.SHORT_SPECIAL
#
#     # NO SIGNAL THEN NULL NULL LONG SPECIAL_SHORT LONG_EXT LONG NULL
#     kline_update = KlineUpdate(
#         kline=[
#             str(x) for x in [1672311600000, 19573.19, 19605.9, 18360.1, 17800.72, 0, 0]
#         ]
#     )
#
#     await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
#     await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
#
#     historical_data, base.df, position = await worker(
#         client=base.client,
#         df=base.df,
#         position=position,
#         queue=base.queue,
#         historical_data=historical_data,
#     )
#
#     assert 1 == len(position.current_position.orders)
#     assert 1000 == position.balance
#     assert position.current_position.status == Signals.SHORT_SPECIAL
#
#     # NO SIGNAL THEN NULL NULL LONG SPECIAL_SHORT LONG_EXT LONG NULL CLOSE
#     kline_update = KlineUpdate(
#         kline=[
#             str(x) for x in [1672312500000, 19573.19, 19605.9, 18360.1, 19700.72, 0, 0]
#         ]
#     )
#
#     await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
#     await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))
#
#     historical_data, base.df, position = await worker(
#         client=base.client,
#         df=base.df,
#         position=position,
#         queue=base.queue,
#         historical_data=historical_data,
#     )
#
#     assert len(position.current_position.orders) == 0
#     assert 1000 == position.balance
#     assert position.current_position.status == Signals.FLAT
