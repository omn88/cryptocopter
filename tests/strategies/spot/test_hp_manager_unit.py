from datetime import datetime
from unittest.mock import MagicMock
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_EXPIRED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_PARTIALLY_FILLED,
)
from src.common.identifiers.spot import ExecutionReport, State
from src.common.identifiers.common import PositionSide


async def test_initialize_strategy(spot_sell):
    strategy = spot_sell.strategy
    await strategy.initialize()
    assert strategy.state == State.NEW


async def test_configuration_settings(spot_buy):
    strategy = spot_buy.strategy
    assert strategy.config.price_low == 1000
    assert strategy.config.price_high == 1400
    assert strategy.config.order_trigger == 1
    assert strategy.config.budget == 1000


async def test_conditions_for_new_order_confirmation(spot_sell):
    strategy = spot_sell.strategy
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT, current_order_status=ORDER_STATUS_NEW
    )
    assert strategy.conditions_for_new_order_confirmation()


async def test_conditions_for_order_cancellation(spot_sell):
    strategy = spot_sell.strategy
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT, current_order_status=ORDER_STATUS_CANCELED
    )
    assert strategy.conditions_for_order_cancellation()


async def test_conditions_for_order_expiration(spot_sell):
    strategy = spot_sell.strategy
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT, current_order_status=ORDER_STATUS_EXPIRED
    )
    assert strategy.conditions_for_order_expiration()


async def test_conditions_for_order_filled(spot_sell):
    strategy = spot_sell.strategy
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT, current_order_status=ORDER_STATUS_FILLED
    )
    assert strategy.conditions_for_order_filled()


async def test_conditions_for_order_partially_filled(spot_sell):
    strategy = spot_sell.strategy
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT, current_order_status=ORDER_STATUS_PARTIALLY_FILLED
    )
    assert strategy.conditions_for_order_partially_filled()


async def test_conditions_for_sending_buy_orders(spot_buy):
    strategy = spot_buy.strategy
    strategy.state = State.NEW
    strategy.config.side = PositionSide.LONG
    strategy.ticker_update = MagicMock(last_price=1300)
    assert strategy.conditions_for_sending_buy_orders()


async def test_conditions_for_sending_sell_orders(spot_sell):
    strategy = spot_sell.strategy
    strategy.state = State.NEW
    strategy.config.side = PositionSide.SHORT
    strategy.ticker_update = MagicMock(last_price=1500)
    assert strategy.conditions_for_sending_sell_orders()


async def test_conditions_for_cancelling_buy_orders(spot_buy):
    strategy = spot_buy.strategy
    strategy.state = State.OPEN
    strategy.position_handler.config.side = PositionSide.LONG
    strategy.position_handler.stagnation_counter = 8

    # Condition met
    strategy.ticker_update = MagicMock(last_price=1415)
    assert strategy.conditions_for_cancelling_buy_orders() is True

    # Condition not met
    strategy.ticker_update = MagicMock(last_price=1414)
    assert strategy.conditions_for_cancelling_buy_orders() is False


async def test_conditions_for_cancelling_sell_orders(spot_sell):
    strategy = spot_sell.strategy
    strategy.state = State.OPEN
    strategy.config.side = PositionSide.SHORT
    strategy.position_handler.config.side = PositionSide.SHORT
    strategy.position_handler.stagnation_counter = 8

    print("order trigger ", strategy.trigger_orders_price)

    # Condition met
    strategy.ticker_update = MagicMock(
        last_price=989
    )  # price_low * (1 - order_trigger / 100) - 1
    assert strategy.conditions_for_cancelling_sell_orders() is True

    # Condition not met
    strategy.ticker_update = MagicMock(
        last_price=991
    )  # price_low * (1 - order_trigger / 100)
    assert strategy.conditions_for_cancelling_sell_orders() is False


async def test_handle_ticker(spot_buy):
    strategy = spot_buy.strategy
    strategy.state = State.OPEN
    strategy.position_handler.next_monitor_position_time = datetime.now()
    await strategy.increase_stagnation_counter()
    assert strategy.position_handler.stagnation_counter == 1


async def test_process_ticker_updates_state(spot_buy):
    # Set initial conditions
    strategy = spot_buy.strategy
    strategy.state = State.OPEN
    strategy.position_handler.next_monitor_position_time = datetime.now()
    strategy.ticker_update = MagicMock(last_price=1200)  # Mocked TickerUpdate
    initial_stagnation_counter = strategy.position_handler.stagnation_counter

    # Execute the process_ticker method
    await strategy.process_ticker()

    # Assertions
    assert (
        strategy.position_handler.stagnation_counter == initial_stagnation_counter + 1
    )
    assert strategy.position_handler.next_monitor_position_time > datetime.now()

    strategy.logger.info(
        "Stagnation counter increase due to crossing stagnation timer: %s, time now: %s, stagnation counter: %s",
        strategy.position_handler.next_monitor_position_time,
        datetime.now(),
        initial_stagnation_counter + 1,
    )
