from datetime import datetime, timedelta
from unittest.mock import MagicMock
import logging

from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_FILLED,
)
from src.common.identifiers.spot import State
from src.strategies.spot.hp_manager import HpManager

logger = logging.getLogger("test_hp_manager")


async def test_default_lifecycle_long(spot_buy):
    # Set initial conditions
    strategy = spot_buy.strategy
    assert isinstance(strategy, HpManager)
    logger.info("Strategy at start: %s", strategy)
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
    logger.info("Strategy: %s", strategy)

    # Simulate order confirmation
    await strategy.process_order()

    # Simulate position closure
    for order in strategy.position_handler.position.orders:
        order.status = ORDER_STATUS_FILLED
    strategy.order_update = MagicMock(
        order_type=ORDER_TYPE_LIMIT, status=ORDER_STATUS_FILLED
    )

    # Simulate order confirmation
    await strategy.process_order()

    assert strategy.state == State.CLOSED

    # # Simulate ticker update handling
    # strategy.position_handler.next_monitor_position_time = datetime.now() - timedelta(
    #     hours=2
    # )
    # await strategy.process_ticker()
    # assert strategy.position_handler.stagnation_counter == 1

    # # Simulate order fill
    # strategy.order_update.status = ORDER_STATUS_FILLED
    # await strategy.process_order()
    # assert strategy.conditions_for_order_filled()
    # logger.info(
    #     "Order filled: %s, order status: %s",
    #     True,
    #     ORDER_STATUS_FILLED,
    # )


async def test_end_to_end_short(spot_sell):
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

    # Simulate process_signal triggering
    strategy.ticker_update = MagicMock(last_price=990)
    await strategy.process_ticker()
    assert strategy.state == State.OPEN

    # # Simulate order confirmation
    # await strategy.process_order()

    # # Simulate position closure
    # for order in strategy.position_handler.position.orders:
    #     order.status = ORDER_STATUS_FILLED
    # strategy.order_update = MagicMock(
    #     order_type=ORDER_TYPE_LIMIT, status=ORDER_STATUS_FILLED
    # )

    # # Simulate order confirmation
    # await strategy.process_order()

    # assert strategy.state == State.CLOSED

    # # Simulate ticker update handling
    # strategy.position_handler.next_monitor_position_time = datetime.now() - timedelta(
    #     hours=2
    # )
    # await strategy.process_ticker()
    # assert strategy.position_handler.stagnation_counter == 1

    # # Simulate order fill
    # strategy.order_update.status = ORDER_STATUS_FILLED
    # await strategy.process_order()
    # assert strategy.conditions_for_order_filled()
    # logger.info(
    #     "Order filled: %s, order status: %s",
    #     True,
    #     ORDER_STATUS_FILLED,
    # )
