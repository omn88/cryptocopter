import logging

from binance.enums import ORDER_STATUS_NEW, ORDER_STATUS_CANCELED


logger = logging.getLogger("common_spot")


def get_new_orders(price_low: float, price_high: float):
    number_of_orders = 11
    first_order_id = round(price_low * price_high / 3.14)
    order_list = []
    for item in range(number_of_orders):
        price = price_low + item * ((price_high - price_low) / (number_of_orders - 1))
        quantity = 333 / number_of_orders / price

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
