import logging
import queue

from binance.enums import ORDER_STATUS_NEW, ORDER_STATUS_CANCELED

from src.common.symbol_info import SymbolInfo
from src.identifiers.common import Mode
from src.identifiers.spot import (
    Event,
    EventName,
    HPBuyConfig,
    HPBuyData,
    StateInfo,
    TickerUpdate,
)


logger = logging.getLogger("common_spot")


def get_new_orders(price_low: float, price_high: float, number_of_orders: int = 11):
    assert (
        number_of_orders >= 3 and number_of_orders % 2 == 1
    ), "Number of orders must be an odd number starting from 3"
    first_order_id = round(price_low * price_high / 3.14)
    order_list = []
    for item in range(number_of_orders):
        price = price_low + item * ((price_high - price_low) / (number_of_orders - 1))
        quantity = 0.1

        order_list.append(
            {
                "orderId": first_order_id + item,
                "price": price,
                "quantity": quantity,
                "status": ORDER_STATUS_NEW,
                "updateTime": 1566818724722,
            }
        )
    return order_list


def get_sell_order(sell_price: float):
    order_list = []
    order_list.append(
        {
            "orderId": round(sell_price * sell_price / 3.14),
            "price": sell_price,
            "quantity": 0.1,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        }
    )
    return order_list


def get_cancel_order():
    return [
        {
            "orderId": 1,
            "price": 1000.00,
            "status": ORDER_STATUS_CANCELED,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 2,
            "price": 1040.00,
            "status": ORDER_STATUS_CANCELED,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 3,
            "price": 1080.00,
            "status": ORDER_STATUS_CANCELED,
            "updateTime": 1566818724722,
        },
    ]


def simulate_new_price(worker_queue: queue.Queue, price: float):
    ticker_event = Event(name=EventName.TICKER, content=TickerUpdate(last_price=price))
    worker_queue.put_nowait(ticker_event)
    logger.info("Put event to the worker: %s", ticker_event)


def simulate_buy_position(
    config_queue: queue.Queue,
    symbol: str,
    mode: Mode = Mode.DCA,
    budget: float = 1000,
    price_low: float = 1000,
    price_high: float = 1400,
    order_trigger: float = 1.0,
):
    hp = HPBuyData(
        HPBuyConfig(
            hp_id="0",
            symbol_info=SymbolInfo(symbol=symbol, precision=2, price_precision=2),
            price_low=price_low,
            price_high=price_high,
            order_trigger=order_trigger,
            budget=budget,
            mode=mode,
        ),
        state_info=StateInfo(),
    )

    config_queue.put_nowait(hp)
    logger.info("HP Buy Data added to the queue: %s", hp)
