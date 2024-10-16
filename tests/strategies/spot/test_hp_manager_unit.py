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
from src.common.identifiers.spot import ExecutionReport, HPConfig, State, StateInfo
from src.common.identifiers.common import Mode, PositionSide
from src.common.symbol_info import SymbolInfo
from src.position_handler.spot import PositionHandler
from src.strategies.spot.hp_manager import HpManager
from tests.spot import get_new_orders
from tests.strategies.spot.hp_manager import get_default_strategy_config


async def test_initialize_strategy(trading_system_factory) -> None:
    trading_system = await trading_system_factory(
        get_default_strategy_config(), StateInfo(side=PositionSide.LONG)
    )

    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price_buy() == 1414
    assert strategy.state == State.NEW


async def test_configuration_settings(trading_system_factory) -> None:
    trading_system = await trading_system_factory(
        get_default_strategy_config(), StateInfo(side=PositionSide.LONG)
    )
    buy_position = trading_system.model.buy_position
    assert buy_position.config.price_low == 1000
    assert buy_position.config.price_high == 1400
    assert buy_position.config.order_trigger == 1
    assert buy_position.config.budget == 1000
    assert buy_position.config.mode == Mode.DCA
    assert buy_position.config.symbol_info.symbol == "BTCUSDT"
    assert buy_position.config.hp_id == 1000


async def test_conditions_for_new_order_confirmation(trading_system_factory) -> None:
    trading_system = await trading_system_factory(
        get_default_strategy_config(), StateInfo(side=PositionSide.LONG)
    )
    strategy: HpManager = trading_system.model
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_NEW,
        symbol=strategy.buy_position.config.symbol_info.symbol,
    )
    assert strategy.conditions_for_new_order_confirmation()


async def test_conditions_for_order_cancellation(trading_system_factory) -> None:
    trading_system = await trading_system_factory(
        get_default_strategy_config(), StateInfo(side=PositionSide.LONG)
    )
    strategy: HpManager = trading_system.model
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_CANCELED,
        symbol=strategy.buy_position.config.symbol_info.symbol,
    )
    assert strategy.conditions_for_order_cancellation()


async def test_conditions_for_order_expiration(trading_system_factory) -> None:
    trading_system = await trading_system_factory(
        get_default_strategy_config(), StateInfo(side=PositionSide.LONG)
    )
    strategy: HpManager = trading_system.model
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT, current_order_status=ORDER_STATUS_EXPIRED
    )
    assert strategy.conditions_for_order_expiration()


async def test_conditions_for_order_filled_buy(trading_system_factory) -> None:
    trading_system = await trading_system_factory(
        get_default_strategy_config(), StateInfo(side=PositionSide.LONG)
    )
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
    trading_system = await trading_system_factory(
        get_default_strategy_config(), StateInfo(side=PositionSide.LONG)
    )
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
    trading_system = await trading_system_factory(
        get_default_strategy_config(), StateInfo(side=PositionSide.LONG)
    )
    strategy: HpManager = trading_system.model
    strategy.client.create_order.side_effect = get_new_orders(
        price_low=strategy.buy_position.config.price_low,
        price_high=strategy.buy_position.config.price_high,
    )
    strategy.buy_position.state_info.state = State.NEW
    strategy.buy_position.state_info.side = PositionSide.LONG
    strategy.ticker_update = MagicMock(last_price=1300)
    assert strategy.conditions_for_sending_buy_orders()


async def test_conditions_for_sending_sell_orders(trading_system_factory) -> None:
    buy_state_info = StateInfo(side=PositionSide.LONG)
    sell_state_info = StateInfo(side=PositionSide.SHORT)
    trading_system = await trading_system_factory(
        get_default_strategy_config(), buy_state_info
    )
    strategy: HpManager = trading_system.model
    sell_config = HPConfig(
        hp_id=1000,
        symbol_info=SymbolInfo(symbol="BTCUSDT"),
        price_high=4200,
        price_low=4200,
        mode=Mode.SINGLE,
        order_trigger=1.0,
        budget=1000,
    )
    strategy.sell_position = PositionHandler(
        client=strategy.client,
        strategy_logger=strategy.logger,
        config=sell_config,
        ui_queue=strategy.buy_position.ui_queue,
        db=strategy.db,
        state_info=sell_state_info,
    )
    strategy.sell_position.orders = strategy.sell_position.order_handler.prepare_orders(
        config=sell_config, state_info=sell_state_info
    )
    strategy.client.create_order.side_effect = get_new_orders(
        price_low=strategy.sell_position.config.price_low,
        price_high=strategy.sell_position.config.price_high,
    )
    strategy.sell_position.state_info.state = State.SELLING
    strategy.sell_position.state_info.side = PositionSide.SHORT
    strategy.ticker_update = MagicMock(last_price=4158)
    assert strategy.conditions_for_sending_sell_orders()


async def test_conditions_for_cancelling_buy_orders(trading_system_factory) -> None:
    trading_system = await trading_system_factory(
        get_default_strategy_config(), StateInfo(side=PositionSide.LONG)
    )
    strategy: HpManager = trading_system.model
    strategy.client.create_order.side_effect = get_new_orders(
        price_low=strategy.buy_position.config.price_low,
        price_high=strategy.buy_position.config.price_high,
    )
    strategy.buy_position.state_info.state = State.NEW
    strategy.buy_position.state_info.side = PositionSide.LONG
    strategy.ticker_update = MagicMock(last_price=1300)
    assert strategy.conditions_for_sending_buy_orders()

    strategy.buy_position.state_info.state = State.BUYING
    strategy.buy_position.state_info.stagnation_counter = 8

    # Condition met

    strategy.ticker_update = MagicMock(last_price=1429)
    assert strategy.conditions_for_cancelling_buy_orders() is True

    # Condition not met
    strategy.ticker_update = MagicMock(last_price=1428)
    assert strategy.conditions_for_cancelling_buy_orders() is False


async def test_conditions_for_cancelling_sell_orders(trading_system_factory) -> None:
    sell_state_info = StateInfo(side=PositionSide.SHORT)
    trading_system = await trading_system_factory(
        get_default_strategy_config(), sell_state_info
    )
    strategy: HpManager = trading_system.model
    sell_config = HPConfig(
        hp_id=1000,
        symbol_info=SymbolInfo(symbol="BTCUSDT"),
        price_high=4200,
        price_low=4200,
        mode=Mode.SINGLE,
        order_trigger=1.0,
        budget=1000,
    )
    strategy.sell_position = PositionHandler(
        client=strategy.client,
        strategy_logger=strategy.logger,
        config=sell_config,
        ui_queue=strategy.buy_position.ui_queue,
        db=strategy.db,
        state_info=StateInfo(side=PositionSide.SHORT),
    )
    strategy.sell_position.orders = strategy.sell_position.order_handler.prepare_orders(
        config=sell_config, state_info=sell_state_info
    )
    strategy.client.create_order.side_effect = get_new_orders(
        price_low=strategy.sell_position.config.price_low,
        price_high=strategy.sell_position.config.price_high,
    )
    strategy.sell_position.state_info.state = State.SELLING
    strategy.sell_position.state_info.side = PositionSide.SHORT
    strategy.ticker_update = MagicMock(last_price=4158)
    assert strategy.conditions_for_sending_sell_orders()
    strategy.sell_position.state_info.stagnation_counter = 8

    # Condition met
    strategy.ticker_update = MagicMock(
        last_price=4115
    )  # price_low * (1 - order_trigger / 100) - 1

    assert strategy.conditions_for_cancelling_sell_orders() is True

    # Condition not met
    strategy.ticker_update = MagicMock(
        last_price=4116
    )  # price_low * (1 - order_trigger / 100)
    assert strategy.conditions_for_cancelling_sell_orders() is False


async def test_handle_ticker(trading_system_factory) -> None:
    trading_system = await trading_system_factory(
        get_default_strategy_config(), StateInfo(side=PositionSide.LONG)
    )
    strategy: HpManager = trading_system.model

    strategy.client.create_order.side_effect = get_new_orders(
        price_low=strategy.buy_position.config.price_low,
        price_high=strategy.buy_position.config.price_high,
    )
    strategy.buy_position.state_info.state = State.NEW
    strategy.buy_position.state_info.side = PositionSide.LONG
    strategy.ticker_update = MagicMock(last_price=1300)
    assert strategy.conditions_for_sending_buy_orders()
    strategy.buy_position.state_info.next_monitor_time = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    assert strategy.buy_position.orders
    await strategy.increase_stagnation_counter_buy()
    assert strategy.buy_position.state_info.stagnation_counter == 1
