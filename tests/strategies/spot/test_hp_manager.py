import datetime
import logging

from binance.enums import (
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_NEW,
    ORDER_STATUS_PARTIALLY_FILLED,
)
from src.common.identifiers.spot import ExecutionReport, State, TickerUpdate
from src.strategies.spot.hp_manager import STAGNATION_LIMIT, HpManager
from tests.spot import get_cancel_order, get_new_orders

logger = logging.getLogger("test_hp_manager")


async def test_default_scenario_buy(spot_buy):
    spot_buy.strategy.client.create_order.side_effect = get_new_orders(
        price_low=spot_buy.strategy.config.price_low,
        price_high=spot_buy.strategy.config.price_high,
    )

    # Set initial condition
    strategy = spot_buy.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price() == 1414
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
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.position_handler.orders[0].order_id,
    )

    # Simulate order confirmation
    await strategy.process_order()

    assert strategy.queue.qsize() == 1

    event = await strategy.queue.get()
    strategy.signal_update = event.content
    await strategy.process_signal()

    assert strategy.state == State.CLOSED


async def test_default_scenario_sell(spot_sell):
    spot_sell.strategy.client.create_order.side_effect = get_new_orders(
        price_low=spot_sell.strategy.config.price_low,
        price_high=spot_sell.strategy.config.price_high,
    )

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
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.position_handler.orders[0].order_id,
    )

    # Simulate order confirmation
    await strategy.process_order()

    assert strategy.queue.qsize() == 1

    event = await strategy.queue.get()
    strategy.signal_update = event.content
    await strategy.process_signal()

    assert strategy.state == State.CLOSED


async def test_partial_order_fill_buy(spot_buy):
    spot_buy.strategy.client.create_order.side_effect = get_new_orders(
        price_low=spot_buy.strategy.config.price_low,
        price_high=spot_buy.strategy.config.price_high,
    )
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
        order_id=445862,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate full fill order 1
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445862,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate full fill order 2
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445861,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate full fill order 3
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445860,
    )
    await strategy.process_order()
    assert all(
        order.status == ORDER_STATUS_FILLED
        for order in strategy.position_handler.orders
    )
    assert strategy.queue.qsize() == 1
    event = await strategy.queue.get()
    strategy.signal_update = event.content
    await strategy.process_signal()
    assert strategy.state == State.CLOSED


async def test_partial_order_fill_sell(spot_sell):
    spot_sell.strategy.client.create_order.side_effect = get_new_orders(
        price_low=spot_sell.strategy.config.price_low,
        price_high=spot_sell.strategy.config.price_high,
    )
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
        order_id=445860,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate full fill order 1
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445860,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate full fill order 2
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445861,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate full fill order 3
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445862,
    )
    await strategy.process_order()
    assert all(
        order.status == ORDER_STATUS_FILLED
        for order in strategy.position_handler.orders
    )
    assert strategy.queue.qsize() == 1
    event = await strategy.queue.get()
    strategy.signal_update = event.content
    await strategy.process_signal()
    assert strategy.state == State.CLOSED


async def test_order_cancellation_sell(spot_sell):
    spot_sell.strategy.client.create_order.side_effect = get_new_orders(
        price_low=spot_sell.strategy.config.price_low,
        price_high=spot_sell.strategy.config.price_high,
    )
    spot_sell.strategy.client.cancel_order.side_effect = get_cancel_order()
    strategy = spot_sell.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_cancel_orders_price() == 980
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

    time_date = datetime.datetime.strptime(
        strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
    )

    time_date -= datetime.timedelta(hours=8)
    strategy.position_handler.next_monitor_position_time = time_date.strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    strategy.ticker_update = TickerUpdate(last_price=1014)

    # Simulate reaching the stagnation limit
    for _ in range(STAGNATION_LIMIT):
        await strategy.process_ticker()

    assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

    # Simulate price being outside the threshold
    strategy.ticker_update = TickerUpdate(last_price=979)
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
    spot_buy.strategy.client.create_order.side_effect = get_new_orders(
        price_low=spot_buy.strategy.config.price_low,
        price_high=spot_buy.strategy.config.price_high,
    )
    spot_buy.strategy.client.cancel_order.side_effect = get_cancel_order()
    strategy = spot_buy.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_cancel_orders_price() == 1428
    last_price = 1400
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    # Simulate order creation
    await strategy.process_ticker()
    assert strategy.state == State.OPEN
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    time_date = datetime.datetime.strptime(
        strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
    )

    time_date -= datetime.timedelta(hours=8)
    strategy.position_handler.next_monitor_position_time = time_date.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # Simulate reaching the stagnation limit
    for _ in range(STAGNATION_LIMIT):
        await strategy.process_ticker()

    assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

    # Simulate price being outside the threshold
    strategy.ticker_update = TickerUpdate(last_price=1429)
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
    spot_sell.strategy.client.create_order.side_effect = get_new_orders(
        price_low=spot_sell.strategy.config.price_low,
        price_high=spot_sell.strategy.config.price_high,
    )
    spot_sell.strategy.client.cancel_order.side_effect = get_cancel_order()
    strategy = spot_sell.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_cancel_orders_price() == 980
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
        order_id=445860,
        cumulative_filled_quantity=strategy.position_handler.orders[0].quantity,
        quantity=strategy.position_handler.orders[0].quantity,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate partial fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=445861,
        cumulative_filled_quantity=(strategy.position_handler.orders[1].quantity / 2),
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate stagnation counter increase
    assert strategy.position_handler.stagnation_counter == 0

    time_date = datetime.datetime.strptime(
        strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
    )

    time_date -= datetime.timedelta(hours=8)
    strategy.position_handler.next_monitor_position_time = time_date.strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    strategy.ticker_update = TickerUpdate(last_price=1014)

    # Simulate reaching the stagnation limit
    for _ in range(STAGNATION_LIMIT):
        await strategy.process_ticker()

    assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

    # Simulate price being outside the threshold
    strategy.ticker_update = TickerUpdate(last_price=979)
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
    spot_buy.strategy.client.create_order.side_effect = get_new_orders(
        price_low=spot_buy.strategy.config.price_low,
        price_high=spot_buy.strategy.config.price_high,
    )
    spot_buy.strategy.client.cancel_order.side_effect = get_cancel_order()
    strategy = spot_buy.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_cancel_orders_price() == 1428
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
        order_id=445860,
        cumulative_filled_quantity=strategy.position_handler.orders[0].quantity,
        quantity=strategy.position_handler.orders[0].quantity,
        symbol=strategy.config.symbol_info.symbol,
        price=strategy.position_handler.orders[0].price,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate partial fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=445861,
        cumulative_filled_quantity=(strategy.position_handler.orders[1].quantity / 2),
        symbol=strategy.config.symbol_info.symbol,
        price=strategy.position_handler.orders[1].price,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate stagnation counter increase
    assert strategy.position_handler.stagnation_counter == 0

    time_date = datetime.datetime.strptime(
        strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
    )

    time_date -= datetime.timedelta(hours=8)
    strategy.position_handler.next_monitor_position_time = time_date.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # Simulate reaching the stagnation limit
    for _ in range(STAGNATION_LIMIT):
        await strategy.process_ticker()

    assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

    # Simulate price being outside the threshold
    last_price = 1429
    strategy.ticker_update = TickerUpdate(last_price=last_price)
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






async def test_default_scenario_buy_with_low_budget(spot_buy):
    spot_buy.strategy.client.create_order.side_effect = get_new_orders(
        price_low=spot_buy.strategy.config.price_low,
        price_high=spot_buy.strategy.config.price_high,
    )

    # Set initial condition
    strategy = spot_buy.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price() == 1414
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

    # Price is within the range but the balance is too little so position is not opened
    strategy.balance = 100
    last_price = 1414
    logger.info(
        "Processing ticker with last price touching the threshold: %s, but balance: %s is too low for this position budget: %s",
        last_price,
        strategy.balance,
        strategy.config.budget,
    )
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()
    assert strategy.state == State.NEW


    strategy.balance = 10000
    logger.info(
        "After balance is enough for sending orders: %s, budget: %s",
        strategy.balance,
        strategy.config.budget,
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
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.position_handler.orders[0].order_id,
    )

    # Simulate order confirmation
    await strategy.process_order()

    assert strategy.queue.qsize() == 1

    event = await strategy.queue.get()
    strategy.signal_update = event.content
    await strategy.process_signal()

    assert strategy.state == State.CLOSED


async def test_default_scenario_sell_with_low_budget(spot_sell):
    spot_sell.strategy.client.create_order.side_effect = get_new_orders(
        price_low=spot_sell.strategy.config.price_low,
        price_high=spot_sell.strategy.config.price_high,
    )

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
    strategy.balance = 100
    logger.info(
        "Processing ticker with last price touching the threshold: %s, but balance: %s is too low for this position budget: %s",
        last_price,
        strategy.balance,
        strategy.config.budget,
    )
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()
    assert strategy.state == State.NEW

    strategy.balance = 10000
    logger.info(
        "After balance is enough for sending orders: %s, budget: %s",
        strategy.balance,
        strategy.config.budget,
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
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.position_handler.orders[0].order_id,
    )

    # Simulate order confirmation
    await strategy.process_order()

    assert strategy.queue.qsize() == 1

    event = await strategy.queue.get()
    strategy.signal_update = event.content
    await strategy.process_signal()

    assert strategy.state == State.CLOSED

async def test_order_reopen_with_filled_orders_low_budget_sell(spot_sell):
    spot_sell.strategy.client.create_order.side_effect = get_new_orders(
        price_low=spot_sell.strategy.config.price_low,
        price_high=spot_sell.strategy.config.price_high,
    )
    spot_sell.strategy.client.cancel_order.side_effect = get_cancel_order()
    strategy = spot_sell.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_cancel_orders_price() == 980
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
        order_id=445860,
        cumulative_filled_quantity=strategy.position_handler.orders[0].quantity,
        quantity=strategy.position_handler.orders[0].quantity,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate partial fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=445861,
        cumulative_filled_quantity=(strategy.position_handler.orders[1].quantity / 2),
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate stagnation counter increase
    assert strategy.position_handler.stagnation_counter == 0

    time_date = datetime.datetime.strptime(
        strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
    )

    time_date -= datetime.timedelta(hours=8)
    strategy.position_handler.next_monitor_position_time = time_date.strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    strategy.ticker_update = TickerUpdate(last_price=1014)

    # Simulate reaching the stagnation limit
    for _ in range(STAGNATION_LIMIT):
        await strategy.process_ticker()

    assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

    # Simulate price being outside the threshold
    strategy.ticker_update = TickerUpdate(last_price=979)
    await strategy.process_ticker()

    assert strategy.state == State.STAGNATED

    last_price = 900
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    # Simulate nothing happening
    await strategy.process_ticker()

    logger.info("Ticker outside, nothing should happen: %s", last_price)

    last_price = 1000
    strategy.balance = 30
    logger.info("Ticker inside: %s, but do not reopen orders due to low balance: %s", last_price, strategy.balance)

    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()

    assert strategy.state == State.STAGNATED

    strategy.balance = 30000
    await strategy.process_ticker()
    logger.info("Ticker inside: %s, reopen orders due to sufficient balance: %s", last_price, strategy.balance)
    assert strategy.state == State.OPEN

    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )

    assert len(strategy.position_handler.orders) == 2

    logger.info("All valid orders reopened.")


async def test_order_reopen_with_filled_orders_low_budget_buy(spot_buy):
    spot_buy.strategy.client.create_order.side_effect = get_new_orders(
        price_low=spot_buy.strategy.config.price_low,
        price_high=spot_buy.strategy.config.price_high,
    )
    spot_buy.strategy.client.cancel_order.side_effect = get_cancel_order()
    strategy = spot_buy.strategy
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_cancel_orders_price() == 1428
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
        order_id=445860,
        cumulative_filled_quantity=strategy.position_handler.orders[0].quantity,
        quantity=strategy.position_handler.orders[0].quantity,
        symbol=strategy.config.symbol_info.symbol,
        price=strategy.position_handler.orders[0].price,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate partial fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=445861,
        cumulative_filled_quantity=(strategy.position_handler.orders[1].quantity / 2),
        symbol=strategy.config.symbol_info.symbol,
        price=strategy.position_handler.orders[1].price,
    )
    await strategy.process_order()
    assert strategy.state == State.OPEN

    # Simulate stagnation counter increase
    assert strategy.position_handler.stagnation_counter == 0

    time_date = datetime.datetime.strptime(
        strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
    )

    time_date -= datetime.timedelta(hours=8)
    strategy.position_handler.next_monitor_position_time = time_date.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # Simulate reaching the stagnation limit
    for _ in range(STAGNATION_LIMIT):
        await strategy.process_ticker()

    assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

    # Simulate price being outside the threshold
    last_price = 1429
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()
    assert strategy.state == State.STAGNATED

    logger.info("Ticker outside, nothing should happen: %s", last_price)
    last_price = 1500
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    # Simulate nothing happening
    await strategy.process_ticker()

    strategy.balance = 30
    last_price = 1400
    logger.info("Ticker inside: %s, but do not reopen orders due to low balance: %s", last_price, strategy.balance)

    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()

    assert strategy.state == State.STAGNATED

    strategy.balance = 30000
    last_price = 1400
    logger.info("Ticker inside: %s, reopen orders due to sufficient balance: %s", last_price, strategy.balance)

    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()

    assert strategy.state == State.OPEN

    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
    )
    assert len(strategy.position_handler.orders) == 2
    logger.info("All valid orders reopened.")