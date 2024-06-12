import logging

from binance.enums import ORDER_STATUS_NEW, ORDER_STATUS_CANCELED


logger = logging.getLogger("common_spot")


def get_buy_orders():
    return [
        {
            "orderId": 1,
            "price": 1000.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 2,
            "price": 1040.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 3,
            "price": 1080.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 4,
            "price": 1120.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 5,
            "price": 1160.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 6,
            "price": 1200.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 7,
            "price": 1240.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 8,
            "price": 1280.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 9,
            "price": 1320.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 10,
            "price": 1360.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 11,
            "price": 1400.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
    ]


def get_sell_orders():
    return [
        {
            "orderId": 1,
            "price": 1000.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 2,
            "price": 1040.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 3,
            "price": 1080.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 4,
            "price": 1120.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 5,
            "price": 1160.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 6,
            "price": 1200.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 7,
            "price": 1240.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 8,
            "price": 1280.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 9,
            "price": 1320.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 10,
            "price": 1360.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 11,
            "price": 1400.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
    ]


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
