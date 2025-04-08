import logging
from typing import List
from binance.enums import ORDER_STATUS_NEW, ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED

from src.identifiers.spot import Order

logger = logging.getLogger("common_spot")


def get_new_orders(orders: List[Order]):
    price_low = min(order.price for order in orders)
    price_high = max(order.price for order in orders)

    first_order_id = round(price_low * price_high / 3.14)
    order_list = []
    for item, order in enumerate(orders):
        if order.status != ORDER_STATUS_FILLED:
            quantity = order.quantity - order.realized_quantity

            order_list.append(
                {
                    "orderId": first_order_id + item,
                    "price": order.price,
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
