from unittest.mock import MagicMock
import logging

from binance.enums import ORDER_TYPE_LIMIT, ORDER_STATUS_FILLED, ORDER_STATUS_NEW
from src.common.identifiers.spot import State
from src.strategies.spot.hp_manager import HpManager
from tests.common import get_orders_long, get_sell_orders

logger = logging.getLogger("test_hp_manager")


async def test_default_scenario_buy(spot_buy):
    spot_buy.strategy.client.create_order.side_effect = get_orders_long()

    # Set initial condition
    strategy = spot_buy.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.trigger_orders_price == 1414
    last_price = 1500
    logger.info(
        "Processing ticker with last price outside of threshold: %s", last_price
    )
    strategy.ticker_update = MagicMock(last_price=1500)  # Mocked TickerUpdate

    # Simulate no state change
    await strategy.process_ticker()
    assert strategy.state == State.NEW

    # Simulate no state change but on the price edge
    last_price = 1415
    logger.info(
        "Processing ticker with last price on the edge of threshold: %s", last_price
    )
    strategy.ticker_update = MagicMock(last_price=last_price)
    await strategy.process_ticker()
    assert strategy.state == State.NEW

    # Simulate process_signal triggering
    last_price = 1414
    logger.info(
        "Processing ticker with last price touching the threshold: %s", last_price
    )
    strategy.ticker_update = MagicMock(last_price=last_price)
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
    strategy.order_update = MagicMock(
        order_type=ORDER_TYPE_LIMIT, status=ORDER_STATUS_FILLED
    )

    # Simulate order confirmation
    await strategy.process_order()

    assert strategy.state == State.CLOSED


async def test_default_scenario_sell(spot_sell):
    spot_sell.strategy.client.create_order.side_effect = get_sell_orders()

    # Set initial conditions
    strategy = spot_sell.strategy
    strategy.ticker_update = MagicMock(last_price=900)  # Mocked TickerUpdate

    # Simulate no state change
    await strategy.process_ticker()
    assert strategy.state == State.NEW

    # Simulate no state change but on the price edge
    strategy.ticker_update = MagicMock(last_price=989)
    await strategy.process_ticker()
    assert strategy.state == State.NEW

    last_price = 990
    logger.info(
        "Processing ticker with last price touching the threshold: %s", last_price
    )
    strategy.ticker_update = MagicMock(last_price=last_price)
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
    strategy.order_update = MagicMock(
        order_type=ORDER_TYPE_LIMIT, status=ORDER_STATUS_FILLED
    )

    # Simulate order confirmation
    await strategy.process_order()

    assert strategy.state == State.CLOSED
