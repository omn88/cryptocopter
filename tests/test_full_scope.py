from unittest.mock import patch
from src.features import Signals
from src.orders import PositionSide
from src.workers.worker import worker
from src.producers.producers import Event, EventName
import logging

logger = logging.getLogger("TEST")


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_full_scope(mock_create_order, mock_cancel_order, base):
    mock_create_order.side_effect = [
        {"orderId": 1, "price": 20000.8},
        {"orderId": 2, "price": 19900.8},
        {"orderId": 3, "price": 19800.8},
        {"orderId": 4, "price": 19700.8},
        {"orderId": 5, "price": 20500},
        {"orderId": 6, "price": 20500},
        {"orderId": 7, "price": 20500.0},
        {"orderId": 8, "price": 20602.5},
        {"orderId": 9, "price": 20705.0},
        {"orderId": 10, "price": 20807.5},
        {"orderId": 11, "price": 20050.0},
        {"orderId": 12, "price": 20150.2},
        {"orderId": 13, "price": 19814.0},
        {"orderId": 14, "price": 20150.2},
        {"orderId": 15, "price": 20050.0},
        {"orderId": 16, "price": 20150.2},
        {"orderId": 17, "price": 19814.0},
        {"orderId": 18, "price": 20150.2},
        {"orderId": 19, "price": 20050.0},
        {"orderId": 20, "price": 20150.2},
        {"orderId": 21, "price": 20050.0},
        {"orderId": 22, "price": 20150.2},
        {"orderId": 23, "price": 19814.0},
        {"orderId": 24, "price": 20150.2},
        {"orderId": 25, "price": 20050.0},
        {"orderId": 26, "price": 20150.2},
        {"orderId": 27, "price": 19814.0},
        {"orderId": 28, "price": 20150.2},
        {"orderId": 29, "price": 20050.0},
        {"orderId": 30, "price": 20150.2},
        {"orderId": 31, "price": 20050.0},
        {"orderId": 32, "price": 20150.2},
        {"orderId": 33, "price": 19814.0},
        {"orderId": 34, "price": 20150.2},
        {"orderId": 35, "price": 20050.0},
        {"orderId": 36, "price": 20150.2},
        {"orderId": 37, "price": 19814.0},
        {"orderId": 38, "price": 20150.2},
        {"orderId": 39, "price": 20050.0},
        {"orderId": 40, "price": 20150.2},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    logger.info("Base finished, start test")

    interval = "15m"
    position = base.position

    logger.info("################ START LONG ####################")
    entry_signal = Signals.LONG
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)
    signal = {"price": entry_price, "signal": entry_signal}

    await base.queue.put(Event(name=EventName.SIGNAL, content=signal))
    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=position,
        queue=base.queue,
    )

    assert 4 == len(position.orders)
    assert 1000 == position.saldo

    assert all(order.price <= entry_price for order in position.orders)

    logger.info("################ REALIZE 1 ORDER ####################")

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": entry_price,
            "q": position.orders[0].quantity,
        }
    }

    await base.queue.put(Event(name=EventName.ORDER, content=order_update))

    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=position,
        queue=base.queue,
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
    assert position.current_position.take_profit_order.price == 20350.41

    logger.info("################ SELL SIGNAL ####################")

    msg = {"signal": Signals.SHORT, "price": 20500}

    await base.queue.put(Event(name=EventName.SIGNAL, content=msg))
    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=position,
        queue=base.queue,
    )

    logger.info("################ REALIZE TWO ORDERS ####################")

    order_update_0 = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[0].price,
            "q": position.orders[0].quantity,
        }
    }

    order_update_1 = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[1].price,
            "q": position.orders[1].quantity,
        }
    }

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_0))

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_1))

    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=position,
        queue=base.queue,
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

    msg = {"signal": Signals.LONG, "price": 19814}

    await base.queue.put(Event(name=EventName.SIGNAL, content=msg))
    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=position,
        queue=base.queue,
    )

    logger.info("################ REALIZE ALL ORDERS ####################")

    order_update_0 = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[0].price,
            "q": position.orders[0].quantity,
        }
    }

    order_update_1 = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[1].price,
            "q": position.orders[1].quantity,
        }
    }

    order_update_2 = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[2].price,
            "q": position.orders[2].quantity,
        }
    }

    order_update_3 = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[3].price,
            "q": position.orders[3].quantity,
        }
    }

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_0))

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_1))

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_2))

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_3))

    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=position,
        queue=base.queue,
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
    assert position.current_position.take_profit_order.price == 20452.02

    logger.info("################ TARGET PRICE REACHED ####################")

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.current_position.take_profit_order.price,
            "q": position.current_position.take_profit_order.quantity,
        }
    }

    await base.queue.put(Event(name=EventName.ORDER, content=order_update))

    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=position,
        queue=base.queue,
    )

    assert len(position.orders) == 0
    assert position.current_position.take_profit_order is None
    assert position.current_position.side == PositionSide.FLAT

    logger.info("################ OPEN SHORT WITH SIGNAL ####################")

    msg = {"signal": Signals.SHORT, "price": 20500}

    await base.queue.put(Event(name=EventName.SIGNAL, content=msg))
    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=position,
        queue=base.queue,
    )

    logger.info("################ REALIZE ALL SHORT ORDERS ####################")

    order_update_0 = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[0].price,
            "q": position.orders[0].quantity,
        }
    }

    order_update_1 = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[1].price,
            "q": position.orders[1].quantity,
        }
    }

    order_update_2 = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[2].price,
            "q": position.orders[2].quantity,
        }
    }

    order_update_3 = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[3].price,
            "q": position.orders[3].quantity,
        }
    }

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_0))

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_1))

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_2))

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_3))

    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=position,
        queue=base.queue,
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

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.current_position.take_profit_order.price,
            "q": position.current_position.take_profit_order.quantity,
        }
    }

    await base.queue.put(Event(name=EventName.ORDER, content=order_update))

    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=position,
        queue=base.queue,
    )

    assert len(position.orders) == 0
    assert position.current_position.take_profit_order is None
    assert position.current_position.side == PositionSide.FLAT

    logger.info("################ OPEN SHORT WITH SIGNAL ####################")

    msg = {"signal": Signals.SHORT, "price": 20500}

    await base.queue.put(Event(name=EventName.SIGNAL, content=msg))
    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=position,
        queue=base.queue,
    )

    logger.info("################ REALIZE ALL SHORT ORDERS ####################")

    order_update_0 = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[0].price,
            "q": position.orders[0].quantity,
        }
    }

    order_update_1 = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[1].price,
            "q": position.orders[1].quantity,
        }
    }

    order_update_2 = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[2].price,
            "q": position.orders[2].quantity,
        }
    }

    order_update_3 = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[3].price,
            "q": position.orders[3].quantity,
        }
    }

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_0))

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_1))

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_2))

    await base.queue.put(Event(name=EventName.ORDER, content=order_update_3))

    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=position,
        queue=base.queue,
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
    assert position.current_position.take_profit_order.price == 19826.78

    logger.info("################ TARGET PRICE REACHED ####################")

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.current_position.liquidation_price,
            "q": position.current_position.take_profit_order.quantity,
        }
    }

    await base.queue.put(Event(name=EventName.ORDER, content=order_update))

    await base.queue.put(Event(name=EventName.SENTINEL, content={}))

    base.df, position = await worker(
        client=base.client,
        symbol=base.symbol,
        interval=interval,
        df=base.df,
        position=position,
        queue=base.queue,
    )

    assert len(position.orders) == 0
    assert position.current_position.take_profit_order is None
    assert position.current_position.side == PositionSide.FLAT
