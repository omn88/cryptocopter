from datetime import datetime, timedelta
from unittest.mock import MagicMock
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_FILLED,
)
from src.common.identifiers.spot import State

import logging

logger = logging.getLogger("test_base_spot")


async def test_end_to_end_process(spot_long):
    # Set initial conditions
    strategy = spot_long.strategy
    strategy.ticker_update = MagicMock(last_price=1500)  # Mocked TickerUpdate

    # Simulate no state change
    await strategy.process_ticker()
    assert strategy.state == State.NEW

    strategy.ticker_update = MagicMock(last_price=1402)  # Mocked TickerUpdate
    # Simulate process_signal triggering
    await strategy.process_ticker()
    assert strategy.state == State.OPEN
    
    strategy.position_handler.position = MagicMock()
    strategy.position_handler.position.orders = [MagicMock(status=ORDER_STATUS_NEW)]

    # Simulate process_signal triggering
    await strategy.process_ticker()
    assert strategy.state == State.OPEN

    # Simulate order confirmation
    await strategy.process_order()
    logger.info(
        "New order confirmation: %s, order type: %s order status: %s",
        True,
        ORDER_TYPE_LIMIT,
        ORDER_STATUS_NEW,
    )

    # Simulate ticker update handling
    strategy.position_handler.next_monitor_position_time = datetime.now() - timedelta(
        hours=2
    )
    await strategy.process_ticker()
    assert strategy.position_handler.stagnation_counter == 1

    # Simulate order fill
    strategy.order_update.status = ORDER_STATUS_FILLED
    await strategy.process_order()
    assert strategy.conditions_for_order_filled()
    logger.info(
        "Order filled: %s, order status: %s",
        True,
        ORDER_STATUS_FILLED,
    )

    # Simulate position closure
    strategy.position_handler.position.orders = [MagicMock(status=ORDER_STATUS_FILLED)]
    await strategy.process_order()
    assert strategy.state == State.CLOSED