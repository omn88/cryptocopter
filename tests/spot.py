import logging
from binance.enums import ORDER_STATUS_NEW, ORDER_STATUS_CANCELED

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
