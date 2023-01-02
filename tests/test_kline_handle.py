from unittest.mock import patch

from src.features import Signals
from src.producers.producers import Event, EventName
from src.workers.worker import worker
from tests.data.sample_dataframes import (
    data_no_signal_then_null,
    data_no_signal_then_null_long_twenty_long_null_short_eighty,
    data_no_signal_then_null_long_twenty_long_null_short_eighty_short,
    data_no_signal_then_null_long_twenty,
    data_no_signal_then_null_long_twenty_long,
    data_no_signal_then_null_long_twenty_long_null,
    data_no_signal_then_null_long_twenty_long_null_short_eighty_short_null,
)


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
@patch("binance.AsyncClient.futures_historical_klines")
async def test_kline_handling(
    mock_get_historical_klines, mock_create_order, mock_cancel_order, base
):
    interval = "15m"
    mock_get_historical_klines.side_effect = [
        data_no_signal_then_null(),
        data_no_signal_then_null_long_twenty(),
        data_no_signal_then_null_long_twenty_long(),
        data_no_signal_then_null_long_twenty_long_null(),
        data_no_signal_then_null_long_twenty_long_null_short_eighty(),
        data_no_signal_then_null_long_twenty_long_null_short_eighty_short(),
        data_no_signal_then_null_long_twenty_long_null_short_eighty_short_null(),
    ]
    mock_create_order.return_value = {"orderId": 1, "price": 20000.8}
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    # NO SIGNAL THEN NULL
    await base.queue.put(Event(name=EventName.KLINE, content={}))
    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=base.position,
        queue=base.queue,
    )

    assert 0 == len(position.orders)
    assert 1000 == position.saldo

    # NO SIGNAL THEN NULL LONG20
    await base.queue.put(Event(name=EventName.KLINE, content={}))
    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=base.position,
        queue=base.queue,
    )

    assert 4 == len(position.orders)
    assert 1000 == position.saldo

    # NO SIGNAL THEN NULL LONG20 LONG

    await base.queue.put(Event(name=EventName.KLINE, content={}))
    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=base.position,
        queue=base.queue,
    )

    assert 4 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.LONG

    # NO SIGNAL THEN NULL LONG20 LONG NULL

    await base.queue.put(Event(name=EventName.KLINE, content={}))
    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=base.position,
        queue=base.queue,
    )

    assert 4 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.LONG

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80

    await base.queue.put(Event(name=EventName.KLINE, content={}))
    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=base.position,
        queue=base.queue,
    )

    assert 4 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.SHORT_80

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT

    await base.queue.put(Event(name=EventName.KLINE, content={}))
    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=base.position,
        queue=base.queue,
    )

    assert 4 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.SHORT

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT NULL

    await base.queue.put(Event(name=EventName.KLINE, content={}))
    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=base.position,
        queue=base.queue,
    )

    assert 4 == len(position.orders)
    assert 1000 == position.saldo
    assert position.status == Signals.SHORT
