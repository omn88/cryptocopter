from pprint import pformat
from unittest.mock import patch

from src.features import Signals
from src.orders import PositionSide
from src.producers.producers import Event, EventName, KlineUpdate
from src.workers.worker import worker
from tests.data.sample_dataframes import data_no_signal
import logging

logger = logging.getLogger("test")


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_kline_handling(mock_create_order, mock_cancel_order, base):
    mock_create_order.side_effect = [
        {"orderId": "1", "price": "18500.7", "status": base.client.ORDER_STATUS_NEW},
        {"orderId": "2", "price": "18408.2", "status": base.client.ORDER_STATUS_NEW},
        {"orderId": "3", "price": "18315.7", "status": base.client.ORDER_STATUS_NEW},
        {"orderId": "4", "price": "18223.2", "status": base.client.ORDER_STATUS_NEW},
        {"orderId": "5", "price": "20800", "status": base.client.ORDER_STATUS_NEW},
        {"orderId": "6", "price": "20500", "status": base.client.ORDER_STATUS_NEW},
        {"orderId": "7", "price": "20500.0", "status": base.client.ORDER_STATUS_NEW},
        {"orderId": "8", "price": "20602.5", "status": base.client.ORDER_STATUS_NEW},
        {"orderId": "9", "price": "20602.5", "status": base.client.ORDER_STATUS_NEW},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    # NO SIGNAL THEN NULL
    kline_update = KlineUpdate(
        kline=["1672306200000", "19573.19", "19605.9", "17160.1", "16700.72", "0", "0"]
    )
    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=base.position,
        queue=base.queue,
        historical_data=data_no_signal(),
    )

    assert 0 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.FLAT

    # NO SIGNAL THEN NULL LONG20
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672307100000, 19573.19, 19605.9, 18360.1, 18500.72, 0, 0]
        ]
    )

    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    logger.info("base.df: %s", base.df.to_string())

    assert 4 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.LONG_20

    # NO SIGNAL THEN NULL LONG20 LONG
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672308000000, 19573.19, 19605.9, 18360.1, 27000.72, 0, 0]
        ]
    )

    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    assert 4 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.LONG

    # NO SIGNAL THEN NULL LONG20 LONG NULL
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672308900000, 19573.19, 19605.9, 18360.1, 29700.72, 0, 0]
        ]
    )

    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    assert 4 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.LONG

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672309800000, 19573.19, 19605.9, 18360.1, 26200.72, 0, 0]
        ]
    )

    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    logger.info("DF: %s", base.df.to_string())

    assert 4 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.SHORT_80

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672310700000, 19573.19, 19605.9, 18360.1, 22200.72, 0, 0]
        ]
    )

    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    assert 4 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.SHORT

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT NULL
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672311600000, 19573.19, 19605.9, 18360.1, 28200.72, 0, 0]
        ]
    )
    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    logger.info("base: %s", base.df.to_string())

    assert 4 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.SHORT

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT NULL SPECIAL_LONG
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672312500000, 19573.19, 19605.9, 18360.1, 56400.72, 0, 0]
        ]
    )
    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    logger.info("base: %s", base.df)

    assert 1 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.LONG_SPECIAL

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT NULL SPECIAL_LONG SHORT_80
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672313400000, 19573.19, 19605.9, 18360.1, 36400.72, 0, 0]
        ]
    )
    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    logger.info("base: %s", base.df)

    assert 1 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.LONG_SPECIAL

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT NULL SPECIAL_LONG SHORT_80 SHORT
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672314300000, 19573.19, 19605.9, 18360.1, 32400.72, 0, 0]
        ]
    )
    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    logger.info("base: %s", base.df)

    assert 1 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.LONG_SPECIAL

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT NULL SPECIAL_LONG SHORT_80 SHORT NULL
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672315200000, 19573.19, 19605.9, 18360.1, 32400.72, 0, 0]
        ]
    )
    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    logger.info("base: %s", base.df)

    assert 1 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.LONG_SPECIAL

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT NULL SPECIAL_LONG SHORT_80 SHORT NULL NULL
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672316100000, 19573.19, 19605.9, 18360.1, 20400.72, 0, 0]
        ]
    )
    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    logger.info("base: %s", base.df.to_string())

    logger.info(position.orders)

    assert 0 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.FLAT


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_kline_handling_for_special_short(
    mock_create_order, mock_cancel_order, base
):
    mock_create_order.side_effect = [
        {"orderId": "1", "price": "18500.7", "status": base.client.ORDER_STATUS_NEW},
        {"orderId": "2", "price": "18408.2", "status": base.client.ORDER_STATUS_NEW},
        {"orderId": "3", "price": "18315.7", "status": base.client.ORDER_STATUS_NEW},
        {"orderId": "4", "price": "18223.2", "status": base.client.ORDER_STATUS_NEW},
        {"orderId": "5", "price": "20800", "status": base.client.ORDER_STATUS_NEW},
        {"orderId": "6", "price": "20500", "status": base.client.ORDER_STATUS_NEW},
        {"orderId": "7", "price": "20500.0", "status": base.client.ORDER_STATUS_NEW},
        {"orderId": "8", "price": "20602.5", "status": base.client.ORDER_STATUS_NEW},
        {"orderId": "9", "price": "20602.5", "status": base.client.ORDER_STATUS_NEW},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    # NO SIGNAL THEN NULL
    kline_update = KlineUpdate(
        kline=["1672306200000", "19573.19", "19605.9", "17160.1", "17700.72", "0", "0"]
    )
    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=base.position,
        queue=base.queue,
        historical_data=data_no_signal(),
    )

    assert 0 == len(position.orders)
    assert 1000 == position.saldo

    # NO SIGNAL THEN NULL NULL
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672307100000, 19573.19, 19605.9, 18360.1, 18200.72, 0, 0]
        ]
    )

    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    logger.info("base.df: %s", base.df.to_string())

    assert 0 == len(position.orders)
    assert 1000 == position.saldo

    # NO SIGNAL THEN NULL NULL LONG
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672308000000, 19573.19, 19605.9, 18360.1, 17700.72, 0, 0]
        ]
    )

    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    assert 4 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.LONG

    # NO SIGNAL THEN NULL NULL LONG SPECIAL_SHORT
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672308900000, 19573.19, 19605.9, 18360.1, 14700.72, 0, 0]
        ]
    )

    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    assert 1 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.SHORT_SPECIAL

    # NO SIGNAL THEN NULL NULL LONG SPECIAL_SHORT LONG_20
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672309800000, 19573.19, 19605.9, 18360.1, 17700.72, 0, 0]
        ]
    )

    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    assert 1 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.SHORT_SPECIAL

    # NO SIGNAL THEN NULL NULL LONG SPECIAL_SHORT LONG_20 LONG
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672310700000, 19573.19, 19605.9, 18360.1, 17700.72, 0, 0]
        ]
    )

    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    assert 1 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.SHORT_SPECIAL

    # NO SIGNAL THEN NULL NULL LONG SPECIAL_SHORT LONG_20 LONG NULL
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672311600000, 19573.19, 19605.9, 18360.1, 17800.72, 0, 0]
        ]
    )

    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    assert 1 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.SHORT_SPECIAL

    # NO SIGNAL THEN NULL NULL LONG SPECIAL_SHORT LONG_20 LONG NULL CLOSE
    kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672312500000, 19573.19, 19605.9, 18360.1, 19700.72, 0, 0]
        ]
    )

    await base.queue.put(Event(name=EventName.KLINE, content=kline_update))
    await base.queue.put(Event(name=EventName.SENTINEL, content=kline_update))

    historical_data, base.df, position = await worker(
        client=base.client,
        df=base.df,
        position=position,
        queue=base.queue,
        historical_data=historical_data,
    )

    assert 0 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.FLAT
