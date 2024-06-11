import logging

from binance.enums import (
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_NEW,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_CANCELED
)
from src.common.identifiers.common import OrderUpdate, TickerUpdate
from src.common.identifiers.spot import State
from src.strategies.spot.hp_manager import HpManager
from tests.common import get_buy_orders, get_sell_orders

logger = logging.getLogger("test_hp_manager")


async def test_default_scenario_buy(spot_buy):
    spot_buy.strategy.client.create_order.side_effect = get_buy_orders()

    # Set initial condition
    strategy = spot_buy.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.trigger_orders_price == 1414
    last_price = 1500
    logger.info(
        "Processing ticker with last price outside of threshold: %s", last_price
    )
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    # Simulate no state change
    await strategy.process_ticker()
    assert strategy.state == State.NEW

    # Simulate no state change but on the price edge
    last_price = 1415
    logger.info(
        "Processing ticker with last price on the edge of threshold: %s", last_price
    )
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()
    assert strategy.state == State.NEW

    # Simulate process_signal triggering
    last_price = 1414
    logger.info(
        "Processing ticker with last price touching the threshold: %s", last_price
    )
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()
    assert strategy.state == State.OPEN

    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    # Simulate order confirmation
    await strategy.process_order()

    # Simulate position closure
    for order in strategy.position_handler.orders:
        order.status = ORDER_STATUS_FILLED
    strategy.order_update = OrderUpdate(
        order_type=ORDER_TYPE_LIMIT, status=ORDER_STATUS_FILLED
    )

    # Simulate order confirmation
    await strategy.process_order()

    assert strategy.state == State.CLOSED


async def test_default_scenario_sell(spot_sell):
    spot_sell.strategy.client.create_order.side_effect = get_sell_orders()

    # Set initial conditions
    strategy = spot_sell.strategy
    last_price = 900
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    # Simulate no state change
    await strategy.process_ticker()
    assert strategy.state == State.NEW

    # Simulate no state change but on the price edge
    last_price = 989
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()
    assert strategy.state == State.NEW

    last_price = 990
    logger.info(
        "Processing ticker with last price touching the threshold: %s", last_price
    )
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()
    assert strategy.state == State.OPEN

    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    # Simulate order confirmation
    await strategy.process_order()

    # Simulate position closure
    for order in strategy.position_handler.orders:
        order.status = ORDER_STATUS_FILLED
    strategy.order_update = OrderUpdate(
        order_type=ORDER_TYPE_LIMIT, status=ORDER_STATUS_FILLED
    )

    # Simulate order confirmation
    await strategy.process_order()

    assert strategy.state == State.CLOSED


async def test_partial_order_fill(spot_buy):
    spot_buy.strategy.client.create_order.side_effect = get_buy_orders()
    strategy = spot_buy.strategy
    last_price = 1000
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    # Simulate order creation
    await strategy.process_ticker()
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    # Simulate partial fill
    strategy.order_update = OrderUpdate(
        order_type=ORDER_TYPE_LIMIT, status=ORDER_STATUS_PARTIALLY_FILLED, order_id=1
    )
    # Process the partial fill
    await strategy.process_order()
    assert strategy.state == State.OPEN  # Should remain open until fully filled

    # Simulate full fill order 1
    strategy.order_update = OrderUpdate(
        order_type=ORDER_TYPE_LIMIT, status=ORDER_STATUS_FILLED, order_id=1
    )
    # Process the partial fill
    await strategy.process_order()
    assert strategy.state == State.OPEN


    strategy.order_update = OrderUpdate(
        order_type=ORDER_TYPE_LIMIT, status=ORDER_STATUS_FILLED, order_id=2
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    strategy.order_update = OrderUpdate(
        order_type=ORDER_TYPE_LIMIT, status=ORDER_STATUS_FILLED, order_id=3
    )
    await strategy.process_order()
    assert all(
        order.status == ORDER_STATUS_FILLED for order in strategy.position_handler.orders
    )

    assert strategy.state == State.CLOSED

    logger.info("orders: %s", list(strategy.position_handler.orders))

    # # Simulate full order fill
    # for order in strategy.position_handler.orders:
    #     order.status = ORDER_STATUS_FILLED
    # strategy.order_update = MagicMock(
    #     order_type=ORDER_TYPE_LIMIT, status=ORDER_STATUS_FILLED
    # )

    # # Process the full fill
    # await strategy.process_order()
    # assert strategy.state == State.CLOSED  # Should transition to closed


async def test_order_cancellation(spot_sell):
    spot_sell.strategy.client.create_order.side_effect = get_sell_orders()
    strategy = spot_sell.strategy
    last_price = 1000
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    # Simulate order creation
    await strategy.process_ticker()
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    # Simulate order cancellation
    for order in strategy.position_handler.orders:
        order.status = ORDER_STATUS_CANCELED
    strategy.order_update = OrderUpdate(
        order_type=ORDER_TYPE_LIMIT, status=ORDER_STATUS_CANCELED
    )

    # Process the cancellation
    await strategy.process_order()
    assert strategy.state == State.CLOSED  # Should transition to closed
