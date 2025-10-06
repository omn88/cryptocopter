import logging
from typing import List, Optional
from binance.enums import ORDER_STATUS_NEW, ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED

from src.common.identifiers import Order

logger = logging.getLogger("common_spot")


def get_new_orders(orders: List[Order], used_ids: Optional[set] = None):
    """
    Generate new orders with unique order IDs. Optionally accepts a set of used_ids to ensure uniqueness across multiple calls.
    """
    if not orders:
        return []

    order_list = []
    if used_ids is None:
        used_ids = set()
    for item, order in enumerate(orders):
        if order.status != ORDER_STATUS_FILLED:
            quantity = order.quantity - order.realized_quantity
            # Start with a hash-based candidate, but increment until unused
            base_id = int(abs(hash((order.price * quantity + item)))) % 1_000_000_000
            candidate_id = base_id
            while candidate_id in used_ids:
                candidate_id += 1
            used_ids.add(candidate_id)
            order_list.append(
                {
                    "orderId": candidate_id,
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
