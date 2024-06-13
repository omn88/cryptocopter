from datetime import timedelta
import logging

from binance.enums import (
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_NEW,
    ORDER_STATUS_PARTIALLY_FILLED,
)
from src.common.identifiers.spot import ExecutionReport, State, TickerUpdate
from src.strategies.spot.hp_manager import STAGNATION_LIMIT, HpManager
from tests.spot import get_buy_orders, get_cancel_order, get_sell_orders

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
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT, current_order_status=ORDER_STATUS_FILLED
    )

    # Simulate order confirmation
    await strategy.process_order()

    assert strategy.queue.qsize() == 1

    strategy.signal_update = await strategy.queue.get()
    await strategy.process_signal()

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
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT, current_order_status=ORDER_STATUS_FILLED
    )

    # Simulate order confirmation
    await strategy.process_order()

    assert strategy.queue.qsize() == 1

    strategy.signal_update = await strategy.queue.get()
    await strategy.process_signal()

    assert strategy.state == State.CLOSED


async def test_partial_order_fill_buy(spot_buy):
    spot_buy.strategy.client.create_order.side_effect = get_buy_orders()
    strategy = spot_buy.strategy
    assert isinstance(strategy, HpManager)
    last_price = 1000
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    # Simulate order creation
    await strategy.process_ticker()
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    # Simulate partial fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=1,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate full fill order 1
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=1,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate full fill order 2
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=2,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate full fill order 3
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=3,
    )
    await strategy.process_order()
    assert all(
        order.status == ORDER_STATUS_FILLED
        for order in strategy.position_handler.orders
    )
    assert strategy.queue.qsize() == 1
    strategy.signal_update = await strategy.queue.get()
    await strategy.process_signal()
    assert strategy.state == State.CLOSED


async def test_partial_order_fill_sell(spot_sell):
    spot_sell.strategy.client.create_order.side_effect = get_sell_orders()
    strategy = spot_sell.strategy
    assert isinstance(strategy, HpManager)
    last_price = 1000
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    # Simulate order creation
    await strategy.process_ticker()
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    # Simulate partial fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=1,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate full fill order 1
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=1,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate full fill order 2
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=2,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate full fill order 3
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=3,
    )
    await strategy.process_order()
    assert all(
        order.status == ORDER_STATUS_FILLED
        for order in strategy.position_handler.orders
    )
    assert strategy.queue.qsize() == 1
    strategy.signal_update = await strategy.queue.get()
    await strategy.process_signal()
    assert strategy.state == State.CLOSED


async def test_order_cancellation_sell(spot_sell):
    spot_sell.strategy.client.create_order.side_effect = get_sell_orders()
    spot_sell.strategy.client.cancel_order.side_effect = get_cancel_order()
    strategy = spot_sell.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.trigger_orders_price == 990
    last_price = 1000
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    # Simulate order creation
    await strategy.process_ticker()
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    # Simulate stagnation counter increase
    assert strategy.position_handler.stagnation_counter == 0

    strategy.position_handler.next_monitor_position_time -= timedelta(hours=8)
    strategy.ticker_update = TickerUpdate(last_price=1014)

    # Simulate reaching the stagnation limit
    for _ in range(STAGNATION_LIMIT):
        await strategy.process_ticker()

    assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

    # Simulate price being outside the threshold
    strategy.ticker_update = TickerUpdate(last_price=989)
    await strategy.process_ticker()

    assert strategy.state == State.STAGNATED

    last_price = 900
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    # Simulate nothing happening
    await strategy.process_ticker()

    logger.info("Ticker outside, nothing should happen: %s", last_price)

    last_price = 1000
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    # Simulate nothing happening
    await strategy.process_ticker()

    logger.info("Ticker inside, reopen orders: %s", last_price)

    assert strategy.state == State.OPEN

    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )


async def test_order_cancellation_buy(spot_buy):
    spot_buy.strategy.client.create_order.side_effect = get_buy_orders()
    spot_buy.strategy.client.cancel_order.side_effect = get_cancel_order()
    strategy = spot_buy.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.trigger_orders_price == 1414
    last_price = 1400
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    # Simulate order creation
    await strategy.process_ticker()
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    # Simulate stagnation counter increase
    assert strategy.position_handler.stagnation_counter == 0

    strategy.position_handler.next_monitor_position_time -= timedelta(hours=8)

    # Simulate reaching the stagnation limit
    for _ in range(STAGNATION_LIMIT):
        await strategy.process_ticker()

    assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

    # Simulate price being outside the threshold
    strategy.ticker_update = TickerUpdate(last_price=1415)
    await strategy.process_ticker()

    assert strategy.state == State.STAGNATED

    last_price = 1500
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    # Simulate nothing happening
    await strategy.process_ticker()

    logger.info("Ticker outside, nothing should happen: %s", last_price)

    last_price = 1400
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    # Simulate nothing happening
    await strategy.process_ticker()

    logger.info("Ticker inside, reopen orders: %s", last_price)

    assert strategy.state == State.OPEN

    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )


async def test_order_reopen_with_filled_orders_sell(spot_sell):
    spot_sell.strategy.client.create_order.side_effect = get_sell_orders()
    spot_sell.strategy.client.cancel_order.side_effect = get_cancel_order()
    strategy = spot_sell.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.trigger_orders_price == 990
    last_price = 1000
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    # Simulate order creation
    await strategy.process_ticker()
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    # Simulate full fill order 1
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=1,
        cumulative_filled_quantity=strategy.position_handler.orders[0].quantity,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate partial fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=2,
        cumulative_filled_quantity=(strategy.position_handler.orders[1].quantity / 2),
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate stagnation counter increase
    assert strategy.position_handler.stagnation_counter == 0

    strategy.position_handler.next_monitor_position_time -= timedelta(hours=8)
    strategy.ticker_update = TickerUpdate(last_price=1014)

    # Simulate reaching the stagnation limit
    for _ in range(STAGNATION_LIMIT):
        await strategy.process_ticker()

    assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

    # Simulate price being outside the threshold
    strategy.ticker_update = TickerUpdate(last_price=989)
    await strategy.process_ticker()

    assert strategy.state == State.STAGNATED

    last_price = 900
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    # Simulate nothing happening
    await strategy.process_ticker()

    logger.info("Ticker outside, nothing should happen: %s", last_price)

    last_price = 1000
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    # Simulate nothing happening
    await strategy.process_ticker()

    logger.info("Ticker inside, reopen orders: %s", last_price)

    assert strategy.state == State.OPEN

    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    assert len(strategy.position_handler.orders) == 2

    logger.info("All valid orders reopened.")


async def test_order_reopen_with_filled_orders_buy(spot_buy):
    spot_buy.strategy.client.create_order.side_effect = get_buy_orders()
    spot_buy.strategy.client.cancel_order.side_effect = get_cancel_order()
    strategy = spot_buy.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.trigger_orders_price == 1414
    last_price = 1400
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    # Simulate order creation
    await strategy.process_ticker()
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    # Simulate full fill order 1
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=1,
        cumulative_filled_quantity=strategy.position_handler.orders[0].quantity,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate partial fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=2,
        cumulative_filled_quantity=(strategy.position_handler.orders[1].quantity / 2),
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate stagnation counter increase
    assert strategy.position_handler.stagnation_counter == 0

    strategy.position_handler.next_monitor_position_time -= timedelta(hours=8)

    # Simulate reaching the stagnation limit
    for _ in range(STAGNATION_LIMIT):
        await strategy.process_ticker()

    assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

    # Simulate price being outside the threshold
    strategy.ticker_update = TickerUpdate(last_price=1415)
    await strategy.process_ticker()
    assert strategy.state == State.STAGNATED

    logger.info("Ticker outside, nothing should happen: %s", last_price)
    last_price = 1500
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    # Simulate nothing happening
    await strategy.process_ticker()

    logger.info("Ticker inside, reopen orders: %s", last_price)
    last_price = 1400
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()

    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    assert len(strategy.position_handler.orders) == 2
    logger.info("All valid orders reopened.")
