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
import pytest
from src.common.identifiers.spot import ExecutionReport, State
from src.common.identifiers.common import Mode, PositionSide
from src.strategies.spot.hp_manager import HpManager
from tests.spot import get_new_orders
from tests.strategies.spot.hp_manager import get_default_strategy_config


async def test_initialize_strategy(trading_system_factory) -> None:
    trading_system = await trading_system_factory(get_default_strategy_config())
    trading_system.model.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.model.buy_position.config.price_low,
        price_high=trading_system.model.buy_position.config.price_high,
    )

    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price_buy() == 1414
    assert strategy.state == State.NEW


async def test_configuration_settings(trading_system_factory) -> None:
    trading_system = await trading_system_factory(get_default_strategy_config())
    buy_position = trading_system.model.buy_position
    assert buy_position.config.price_low == 1000
    assert buy_position.config.price_high == 1400
    assert buy_position.config.order_trigger == 1
    assert buy_position.config.budget == 1000
    assert buy_position.config.mode == Mode.DCA
    assert buy_position.config.symbol_info.symbol == "BTCUSDT"
    assert buy_position.config.hp_id == 1000


async def test_conditions_for_new_order_confirmation(trading_system_factory) -> None:
    trading_system = await trading_system_factory(get_default_strategy_config())
    trading_system.model.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.model.buy_position.config.price_low,
        price_high=trading_system.model.buy_position.config.price_high,
    )
    strategy: HpManager = trading_system.model
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_NEW,
        symbol=strategy.buy_position.config.symbol_info.symbol,
    )
    assert strategy.conditions_for_new_order_confirmation()


async def test_conditions_for_order_cancellation(trading_system_factory) -> None:
    trading_system = await trading_system_factory(get_default_strategy_config())
    trading_system.model.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.model.buy_position.config.price_low,
        price_high=trading_system.model.buy_position.config.price_high,
    )
    strategy: HpManager = trading_system.model
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_CANCELED,
        symbol=strategy.buy_position.config.symbol_info.symbol,
    )
    assert strategy.conditions_for_order_cancellation()


async def test_conditions_for_order_expiration(trading_system_factory) -> None:
    trading_system = await trading_system_factory(get_default_strategy_config())
    trading_system.model.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.model.buy_position.config.price_low,
        price_high=trading_system.model.buy_position.config.price_high,
    )
    strategy: HpManager = trading_system.model
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT, current_order_status=ORDER_STATUS_EXPIRED
    )
    assert strategy.conditions_for_order_expiration()


async def test_conditions_for_order_filled_buy(trading_system_factory) -> None:
    trading_system = await trading_system_factory(get_default_strategy_config())
    strategy: HpManager = trading_system.model
    strategy.client.create_order.side_effect = get_new_orders(
        price_low=strategy.buy_position.config.price_low,
        price_high=strategy.buy_position.config.price_high,
    )
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT, current_order_status=ORDER_STATUS_FILLED
    )
    assert strategy.conditions_for_order_filled_buy()


async def test_conditions_for_order_partially_filled_buy(
    trading_system_factory,
) -> None:
    trading_system = await trading_system_factory(get_default_strategy_config())
    strategy: HpManager = trading_system.model
    strategy.client.create_order.side_effect = get_new_orders(
        price_low=strategy.buy_position.config.price_low,
        price_high=strategy.buy_position.config.price_high,
    )
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT, current_order_status=ORDER_STATUS_PARTIALLY_FILLED
    )
    assert strategy.conditions_for_order_partially_filled_buy()


async def test_conditions_for_sending_buy_orders(trading_system_factory) -> None:
    trading_system = await trading_system_factory(get_default_strategy_config())
    strategy: HpManager = trading_system.model
    strategy.client.create_order.side_effect = get_new_orders(
        price_low=strategy.buy_position.config.price_low,
        price_high=strategy.buy_position.config.price_high,
    )
    strategy.buy_position.state_info.state = State.NEW
    strategy.buy_position.state_info.side = PositionSide.LONG
    strategy.ticker_update = MagicMock(last_price=1300)
    assert strategy.conditions_for_sending_buy_orders()


async def test_conditions_for_sending_sell_orders(spot_sell) -> None:
    strategy = spot_sell.model
    strategy.state = State.NEW
    strategy.config.side = PositionSide.SHORT
    strategy.ticker_update = MagicMock(last_price=1500)
    assert strategy.conditions_for_sending_sell_orders()


# async def test_conditions_for_cancelling_buy_orders(spot_buy) -> None:
#     strategy = spot_buy.model
#     strategy.state = State.OPEN
#     strategy.position_handler.config.side = PositionSide.LONG
#     strategy.position_handler.stagnation_counter = 8

#     # Condition met
#     strategy.ticker_update = MagicMock(last_price=1429)
#     assert strategy.conditions_for_cancelling_buy_orders() is True

#     # Condition not met
#     strategy.ticker_update = MagicMock(last_price=1428)
#     assert strategy.conditions_for_cancelling_buy_orders() is False


# async def test_conditions_for_cancelling_sell_orders(spot_sell) -> None:
#     strategy = spot_sell.model
#     strategy.state = State.OPEN
#     strategy.config.side = PositionSide.SHORT
#     strategy.position_handler.config.side = PositionSide.SHORT
#     strategy.position_handler.stagnation_counter = 8

#     # Condition met
#     strategy.ticker_update = MagicMock(
#         last_price=979
#     )  # price_low * (1 - order_trigger / 100) - 1

#     assert strategy.conditions_for_cancelling_sell_orders() is True

#     # Condition not met
#     strategy.ticker_update = MagicMock(
#         last_price=980
#     )  # price_low * (1 - order_trigger / 100)
#     assert strategy.conditions_for_cancelling_sell_orders() is False


# async def test_handle_ticker(spot_buy):
#     strategy = spot_buy.model
#     strategy.state = State.OPEN
#     strategy.position_handler.next_monitor_position_time = datetime.now().strftime(
#         "%Y-%m-%d %H:%M:%S"
#     )
#     await strategy.increase_stagnation_counter()
#     assert strategy.position_handler.stagnation_counter == 1


# async def test_process_ticker_updates_state(spot_buy):
#     # Set initial conditions
#     strategy = spot_buy.model
#     strategy.buy_position.state_info.state = State.OPEN
#     strategy.buy_position.state_info.next_monitor_time = datetime.now().strftime(
#         "%Y-%m-%d %H:%M:%S"
#     )
#     strategy.ticker_update = MagicMock(last_price=1200)  # Mocked TickerUpdate
#     initial_stagnation_counter = strategy.buy_position.state_info.stagnation_counter

#     # Execute the process_ticker method
#     await strategy.process_ticker()

#     # Assertions
#     assert (
#         strategy.buy_position.state_info.stagnation_counter
#         == initial_stagnation_counter + 1
#     )
#     assert strategy.buy_position.state_info.next_monitor_time > datetime.now().strftime(
#         "%Y-%m-%d %H:%M:%S"
#     )

#     strategy.logger.info(
#         "Stagnation counter increase due to crossing stagnation timer: %s, time now: %s, stagnation counter: %s",
#         strategy.buy_position.state_info.next_monitor_time,
#         datetime.now(),
#         initial_stagnation_counter + 1,
#     )
