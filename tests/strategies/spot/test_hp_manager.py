import datetime
import logging
from unittest.mock import MagicMock

from binance.enums import (
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_NEW,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_EXPIRED,
)
from src.common.identifiers.common import Mode, PositionSide
from src.common.identifiers.spot import (
    Event,
    EventName,
    ExecutionReport,
    HPConfig,
    SignalUpdate,
    State,
    StateInfo,
    TickerUpdate,
)
from src.common.symbol_info import SymbolInfo
from src.position_handler.spot import PositionHandler
from src.strategies.spot.hp_manager import HpManager
from tests.spot import get_cancel_order, get_new_orders
from tests.strategies.spot.hp_manager import (
    get_default_buy_position,
    move_to_buy_position_active,
    simulate_cancel_buy_position,
    simulate_first_order_fill,
    simulate_partial_fill,
    simulate_second_order_fill,
    simulate_third_order_fill,
)

logger = logging.getLogger("test_hp_manager")


async def test_default_position(trading_system_factory) -> None:
    """
    This test purpose is to instantiate basic buy position and assert on
    the default values
    """

    trading_system = trading_system_factory(
        hp_config=HPConfig(
            hp_id=1000,
            symbol_info=SymbolInfo(symbol="BTCUSDT", precision=2, price_precision=2),
            price_low=1000,
            price_high=1400,
            order_trigger=1.0,
            budget=1000,
        ),
        state_info=StateInfo(),
    )

    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    assert strategy.buy_position.config.hp_id == 1000
    assert strategy.buy_position.config.price_low == 1000
    assert strategy.buy_position.config.price_high == 1400
    assert strategy.buy_position.config.order_trigger == 1
    assert strategy.buy_position.config.budget == 1000
    assert strategy.buy_position.config.mode == Mode.DCA
    assert strategy.buy_position.config.symbol_info.symbol == "BTCUSDT"

    assert strategy.buy_position.state_info.side == PositionSide.LONG
    assert strategy.buy_position.state_info.state == State.NEW
    assert strategy.buy_position.state_info.stagnation_counter == 0
    assert strategy.buy_position.state_info.stagnation_limit == 8

    assert strategy.calculate_trigger_send_orders_price_buy() == 1414
    assert strategy.state == State.NEW
    assert len(strategy.buy_position.orders) == 3

    assert strategy.buy_position.orders[0].quantity == 0.24
    assert strategy.buy_position.orders[1].quantity == 0.28
    assert strategy.buy_position.orders[2].quantity == 0.33

    assert strategy.sell_position.config.hp_id == 1000
    assert strategy.sell_position.config.price_low == 0
    assert strategy.sell_position.config.price_high == 0
    assert strategy.sell_position.config.order_trigger == 0
    assert strategy.sell_position.config.budget == 0
    assert strategy.sell_position.config.mode == Mode.DCA
    assert strategy.sell_position.config.symbol_info.symbol == "BTCUSDT"

    assert strategy.sell_position.state_info.side == PositionSide.SHORT
    assert strategy.sell_position.state_info.state == State.NEW
    assert strategy.sell_position.state_info.stagnation_counter == 0
    assert strategy.sell_position.state_info.stagnation_limit == 8

    assert len(strategy.sell_position.orders) == 0


async def test_cancel_default_position_untouched(trading_system_factory) -> None:
    """
    This test purpose is to instantiate basic buy position then trigger
    the conditions with which the position will be cancelled untouched and the states
    will get back to State.NEW
    """

    strategy: HpManager = get_default_buy_position(trading_system_factory)
    strategy = await move_to_buy_position_active(strategy=strategy)

    strategy.buy_position.state_info.stagnation_counter = (
        strategy.buy_position.state_info.stagnation_limit
    )

    time = datetime.datetime.now() + datetime.timedelta(hours=1)
    strategy.buy_position.state_info.next_monitor_time = time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
    strategy.ticker_update = TickerUpdate(last_price=1428.0)
    assert strategy.conditions_for_cancelling_unfilled_buy_orders()

    await strategy.process_ticker()

    assert len(strategy.buy_position.orders) == 3
    assert all(order.status == "PREPARED" for order in strategy.buy_position.orders)
    assert strategy.buy_position.state_info.state == State.NEW
    assert strategy.state == State.NEW


async def test_cancel_default_position_untouched_then_resend_orders(
    trading_system_factory,
) -> None:
    """
    This test purpose is to instantiate basic buy position then trigger
    the conditions with which the position will be cancelled untouched and the states
    will get back to State.NEW
    """

    strategy: HpManager = get_default_buy_position(trading_system_factory)
    strategy = await move_to_buy_position_active(strategy=strategy)

    strategy.buy_position.state_info.stagnation_counter = (
        strategy.buy_position.state_info.stagnation_limit
    )

    time = datetime.datetime.now() + datetime.timedelta(hours=1)
    strategy.buy_position.state_info.next_monitor_time = time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
    strategy.ticker_update = TickerUpdate(last_price=1428.0)
    assert strategy.conditions_for_cancelling_unfilled_buy_orders()

    await strategy.process_ticker()

    assert strategy.buy_position.state_info.state == State.NEW
    assert strategy.state == State.NEW
    assert len(strategy.buy_position.orders) == 3
    assert all(order.status == "PREPARED" for order in strategy.buy_position.orders)

    strategy = await move_to_buy_position_active(strategy=strategy)

    assert strategy.buy_position.orders[0].quantity == 0.24
    assert strategy.buy_position.orders[1].quantity == 0.28
    assert strategy.buy_position.orders[2].quantity == 0.33
    assert all(order.realized_quantity == 0.0 for order in strategy.buy_position.orders)


async def test_default_position_first_order_filled_partially(
    trading_system_factory,
) -> None:
    strategy: HpManager = get_default_buy_position(trading_system_factory)
    strategy = await move_to_buy_position_active(strategy=strategy)

    # Simulate partial fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=445860,
        last_executed_quantity=0.05,
        last_executed_price=1400,
    )
    await strategy.process_order()
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy_position.orders)
    assert strategy.buy_position.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert strategy.buy_position.orders[1].status == ORDER_STATUS_NEW
    assert strategy.buy_position.orders[2].status == ORDER_STATUS_NEW


async def test_default_position_first_order_filled_partially_then_cancel(
    trading_system_factory,
) -> None:
    strategy: HpManager = get_default_buy_position(trading_system_factory)
    strategy = await move_to_buy_position_active(strategy=strategy)
    strategy = await simulate_partial_fill(strategy=strategy)

    strategy.buy_position.state_info.stagnation_counter = (
        strategy.buy_position.state_info.stagnation_limit
    )

    time = datetime.datetime.now() + datetime.timedelta(hours=1)
    strategy.buy_position.state_info.next_monitor_time = time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
    strategy.ticker_update = TickerUpdate(last_price=1428.0)
    assert not strategy.conditions_for_cancelling_unfilled_buy_orders()
    assert strategy.conditions_for_cancelling_partially_bought_orders()

    await strategy.process_ticker()

    assert len(strategy.buy_position.orders) == 3
    assert all(
        order.status == ORDER_STATUS_CANCELED for order in strategy.buy_position.orders
    )

    assert strategy.buy_position.orders[0].quantity == 0.24
    assert strategy.buy_position.orders[1].quantity == 0.28
    assert strategy.buy_position.orders[2].quantity == 0.33

    assert strategy.buy_position.orders[0].realized_quantity == 0.12
    assert strategy.buy_position.orders[1].realized_quantity == 0.0
    assert strategy.buy_position.orders[2].realized_quantity == 0.0

    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT


async def test_default_position_first_order_filled(trading_system_factory) -> None:
    strategy: HpManager = get_default_buy_position(trading_system_factory)
    strategy = await move_to_buy_position_active(strategy=strategy)

    # Simulate full order fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445860,
        last_executed_quantity=0.1,
        last_executed_price=1400,
    )
    await strategy.process_order()
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy_position.orders)
    assert strategy.buy_position.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[1].status == ORDER_STATUS_NEW
    assert strategy.buy_position.orders[2].status == ORDER_STATUS_NEW


async def test_default_position_first_order_filled_then_cancel(
    trading_system_factory,
) -> None:
    strategy: HpManager = get_default_buy_position(trading_system_factory)
    strategy = await move_to_buy_position_active(strategy=strategy)
    strategy = await simulate_first_order_fill(strategy=strategy)
    strategy = await simulate_cancel_buy_position(strategy=strategy)

    assert strategy.buy_position.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[1].status == ORDER_STATUS_CANCELED
    assert strategy.buy_position.orders[2].status == ORDER_STATUS_CANCELED

    assert strategy.buy_position.orders[0].quantity == 0.24
    assert strategy.buy_position.orders[1].quantity == 0.28
    assert strategy.buy_position.orders[2].quantity == 0.33

    assert strategy.buy_position.orders[0].realized_quantity == 0.24
    assert strategy.buy_position.orders[1].realized_quantity == 0.0
    assert strategy.buy_position.orders[2].realized_quantity == 0.0

    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT


async def test_default_position_all_orders_filled(trading_system_factory) -> None:
    strategy: HpManager = get_default_buy_position(trading_system_factory)
    strategy = await move_to_buy_position_active(strategy=strategy)
    strategy = await simulate_first_order_fill(strategy=strategy)
    strategy = await simulate_second_order_fill(strategy=strategy)
    strategy = await simulate_third_order_fill(strategy=strategy)

    assert strategy.core_queue.qsize() == 1
    event = strategy.core_queue.get_nowait()

    assert isinstance(event, Event)
    assert event.name == EventName.SIGNAL
    assert isinstance(event.content, SignalUpdate)

    strategy.signal_update = event.content

    await strategy.process_signal()

    assert strategy.buy_position.state_info.state == State.BOUGHT
    assert strategy.state == State.BOUGHT


async def test_conditions_for_new_order_confirmation(trading_system_factory) -> None:
    strategy: HpManager = get_default_buy_position(trading_system_factory)
    strategy = await move_to_buy_position_active(strategy=strategy)

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_NEW,
        symbol=strategy.buy_position.config.symbol_info.symbol,
    )
    assert strategy.conditions_for_new_order_confirmation()


async def test_conditions_for_order_cancellation(trading_system_factory) -> None:
    strategy: HpManager = get_default_buy_position(trading_system_factory)
    strategy = await move_to_buy_position_active(strategy=strategy)
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_CANCELED,
        symbol=strategy.buy_position.config.symbol_info.symbol,
    )
    assert strategy.conditions_for_order_cancellation()


async def test_conditions_for_order_expiration(trading_system_factory) -> None:
    strategy: HpManager = get_default_buy_position(trading_system_factory)
    strategy = await move_to_buy_position_active(strategy=strategy)
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT, current_order_status=ORDER_STATUS_EXPIRED
    )
    assert strategy.conditions_for_order_expiration()


async def test_stagnation_counter_increase_buy(trading_system_factory) -> None:
    """
    This test purpose is to instantiate basic buy position then trigger
    the conditions with which the position will be cancelled untouched and the states
    will get back to State.NEW
    """

    strategy: HpManager = get_default_buy_position(trading_system_factory)
    strategy = await move_to_buy_position_active(strategy=strategy)

    assert strategy.buy_position.state_info.stagnation_counter == 0
    assert strategy.buy_position.state_info.stagnation_limit == 8

    time = datetime.datetime.now()
    strategy.buy_position.state_info.next_monitor_time = time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    assert strategy.buy_position.state_info.next_monitor_time == time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    assert strategy.conditions_for_position_stagnation_buy()
    await strategy.process_ticker()

    assert strategy.buy_position.state_info.stagnation_counter == 1
    assert strategy.buy_position.state_info.stagnation_limit == 8

    assert strategy.buy_position.state_info.next_monitor_time != time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )


async def test_default_position_first_order_filled_partially_then_cancel_then_resend(
    trading_system_factory,
) -> None:
    strategy: HpManager = get_default_buy_position(trading_system_factory)
    strategy = await move_to_buy_position_active(strategy=strategy)
    strategy = await simulate_partial_fill(strategy=strategy)
    strategy = await simulate_cancel_buy_position(strategy=strategy)

    assert all(
        order.status == ORDER_STATUS_CANCELED for order in strategy.buy_position.orders
    )

    assert strategy.buy_position.orders[0].quantity == 0.24
    assert strategy.buy_position.orders[1].quantity == 0.28
    assert strategy.buy_position.orders[2].quantity == 0.33

    assert strategy.buy_position.orders[0].realized_quantity == 0.12
    assert strategy.buy_position.orders[1].realized_quantity == 0.0
    assert strategy.buy_position.orders[2].realized_quantity == 0.0

    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT

    strategy = await move_to_buy_position_active(strategy=strategy)

    assert strategy.buy_position.orders[0].quantity == 0.12
    assert strategy.buy_position.orders[1].quantity == 0.28
    assert strategy.buy_position.orders[2].quantity == 0.33


async def test_default_position_first_order_filled_then_cancel_then_resend(
    trading_system_factory,
) -> None:
    strategy: HpManager = get_default_buy_position(trading_system_factory)
    strategy = await move_to_buy_position_active(strategy=strategy)
    strategy = await simulate_first_order_fill(strategy=strategy)
    strategy = await simulate_cancel_buy_position(strategy=strategy)

    assert strategy.buy_position.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[1].status == ORDER_STATUS_CANCELED
    assert strategy.buy_position.orders[2].status == ORDER_STATUS_CANCELED

    assert strategy.buy_position.orders[0].quantity == 0.24
    assert strategy.buy_position.orders[1].quantity == 0.28
    assert strategy.buy_position.orders[2].quantity == 0.33

    assert strategy.buy_position.orders[0].realized_quantity == 0.24
    assert strategy.buy_position.orders[1].realized_quantity == 0.0
    assert strategy.buy_position.orders[2].realized_quantity == 0.0

    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT

    assert strategy.calculate_trigger_send_orders_price_buy() == 1212
    strategy.ticker_update = TickerUpdate(last_price=1212)
    await strategy.process_ticker()

    assert strategy.buy_position.state_info.state == State.BUYING
    assert strategy.state == State.BUYING
    assert len(strategy.buy_position.orders) == 2

    assert strategy.buy_position.orders[0].status == ORDER_STATUS_NEW
    assert strategy.buy_position.orders[1].status == ORDER_STATUS_NEW

    assert strategy.buy_position.orders[0].quantity == 0.28
    assert strategy.buy_position.orders[1].quantity == 0.33


# async def test_default_scenario_buy(trading_system_factory):
#     trading_system = await trading_system_factory(
#         get_default_strategy_config(), StateInfo(side=PositionSide.LONG)
#     )

#     strategy = trading_system.model
#     assert isinstance(strategy, HpManager)
#     assert strategy.calculate_trigger_send_orders_price_buy() == 1414
#     assert strategy.state == State.NEW
#     assert strategy.buy_position.state_info.side == PositionSide.LONG

#     last_price = 1500
#     logger.info(
#         "Processing ticker with last price outside of threshold: %s", last_price
#     )
#     strategy.ticker_update = TickerUpdate(last_price=last_price)

#     # Simulate no state change
#     await strategy.process_ticker()
#     assert strategy.state == State.NEW

#     # Simulate no state change but on the price edge
#     last_price = 1415
#     logger.info(
#         "Processing ticker with last price on the edge of threshold: %s", last_price
#     )
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     await strategy.process_ticker()
#     assert strategy.state == State.NEW

#     # Simulate process_signal triggering
#     last_price = 1414
#     logger.info(
#         "Processing ticker with last price touching the threshold: %s", last_price
#     )
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     await strategy.process_ticker()
#     assert strategy.state == State.BUYING

#     assert all(
#         order.status == ORDER_STATUS_NEW for order in strategy.buy_position.orders
#     )

#     # Simulate order confirmation
#     await strategy.process_order()

#     # Simulate position closure
#     for order in strategy.buy_position.orders:
#         order.status = ORDER_STATUS_FILLED
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_FILLED,
#         order_id=strategy.buy_position.orders[0].order_id,
#     )

#     # Simulate order confirmation
#     await strategy.process_order()

#     assert strategy.core_queue.qsize() == 1

#     event = strategy.core_queue.get()
#     strategy.signal_update = event.content
#     await strategy.process_signal()

#     assert strategy.state == State.BOUGHT


# async def test_default_scenario_sell(trading_system_factory):
#     trading_system = await trading_system_factory(
#         get_default_strategy_config(),
#         StateInfo(side=PositionSide.LONG, state=State.NEW),
#     )

#     strategy = trading_system.model
#     assert isinstance(strategy, HpManager)

#     # Simulate process_ticker triggering
#     last_price = 1414
#     logger.info(
#         "Processing ticker with last price touching the threshold: %s", last_price
#     )
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     await strategy.process_ticker()

#     # Simulate order confirmation
#     await strategy.process_order()

#     # Simulate position closure
#     for order in strategy.buy_position.orders:
#         order.status = ORDER_STATUS_FILLED
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_FILLED,
#         order_id=strategy.buy_position.orders[0].order_id,
#     )

#     # Simulate order confirmation
#     await strategy.process_order()

#     event = strategy.core_queue.get()
#     strategy.signal_update = event.content
#     await strategy.process_signal()

#     assert strategy.buy_position.state_info.state == State.BOUGHT
#     assert strategy.state == State.BOUGHT

#     sell_config = HPConfig(
#         hp_id=1000,
#         symbol_info=SymbolInfo(symbol="BTCUSDT", precision=2, price_precision=2),
#         price_high=4200,
#         price_low=4200,
#         mode=Mode.SINGLE,
#         order_trigger=1.0,
#         budget=1000,
#     )
#     sell_state_info = StateInfo(side=PositionSide.SHORT, state=State.NEW)
#     strategy.sell_position = PositionHandler(
#         client=strategy.client,
#         strategy_logger=strategy.logger,
#         config=sell_config,
#         ui_queue=strategy.buy_position.ui_queue,
#         db=strategy.db,
#         state_info=sell_state_info,
#     )
#     strategy.sell_position.orders = strategy.sell_position.order_handler.prepare_orders(
#         state_info=sell_state_info, config=sell_config
#     )

#     last_price = 3140
#     logger.info(
#         "Processing ticker with last price away from the threshold: %s", last_price
#     )
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     await strategy.process_ticker()

#     assert strategy.buy_position.state_info.state == State.BOUGHT
#     assert strategy.sell_position.state_info.state == State.NEW

#     strategy.ticker_update = MagicMock(last_price=4157)
#     assert not strategy.conditions_for_sending_sell_orders()

#     strategy.ticker_update = MagicMock(last_price=4158)
#     assert strategy.conditions_for_sending_sell_orders()

#     last_price = 4158
#     strategy.ticker_update = TickerUpdate(last_price=last_price)

#     # Simulate no state change
#     await strategy.process_ticker()
#     assert strategy.state == State.SELLING

#     assert all(
#         order.status == ORDER_STATUS_NEW for order in strategy.sell_position.orders
#     )

#     # Simulate order confirmation
#     await strategy.process_order()

#     # Simulate position closure
#     for order in strategy.sell_position.orders:
#         order.status = ORDER_STATUS_FILLED
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_FILLED,
#         order_id=strategy.sell_position.orders[0].order_id,
#     )

#     # Simulate order confirmation
#     await strategy.process_order()

#     assert strategy.core_queue.qsize() == 1

#     event = strategy.core_queue.get()
#     strategy.signal_update = event.content
#     await strategy.process_signal()

#     assert strategy.state == State.SOLD


# async def test_partial_order_fill_buy(trading_system_factory):
#     trading_system = await trading_system_factory(get_default_strategy_config(), StateInfo(side=PositionSide.LONG))
#     strategy = trading_system.model
#     buy_position = strategy.buy_position
#     sell_position = strategy.sell_position

#     strategy.client.create_order.side_effect = get_new_orders(
#         price_low=buy_position.config.price_low,
#         price_high=buy_position.config.price_high,
#     )

#     assert isinstance(strategy, HpManager)
#     last_price = 1000
#     strategy.ticker_update = TickerUpdate(last_price=last_price)

#     # Simulate order creation
#     await strategy.process_ticker()
#     assert strategy.state == State.BUYING
#     assert all(
#         order.status == ORDER_STATUS_NEW for order in buy_position.orders
#     )

#     # Simulate partial fill
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
#         order_id=445862,
#     )
#     await strategy.process_order()
#     assert strategy.state == State.BUYING

#     # Simulate full fill order 1
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_FILLED,
#         order_id=445862,
#     )
#     await strategy.process_order()
#     assert strategy.state == State.BUYING

#     # Simulate full fill order 2
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_FILLED,
#         order_id=445861,
#     )
#     await strategy.process_order()
#     assert strategy.state == State.BUYING

#     # Simulate full fill order 3
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_FILLED,
#         order_id=445860,
#     )
#     await strategy.process_order()
#     assert all(
#         order.status == ORDER_STATUS_FILLED
#         for order in buy_position.orders
#     )
#     assert strategy.core_queue.qsize() == 1
#     event = strategy.core_queue.get()
#     strategy.signal_update = event.content
#     await strategy.process_signal()
#     assert strategy.state == State.BOUGHT


# async def test_partial_order_fill_sell(trading_system_factory):
#     trading_system = await trading_system_factory(get_default_strategy_config(), StateInfo(side=PositionSide.SHORT))
#     strategy = trading_system.model
#     buy_position = strategy.buy_position
#     sell_position = strategy.sell_position

#     strategy.client.create_order.side_effect = get_new_orders(
#         price_low=sell_position.config.price_low,
#         price_high=sell_position.config.price_high,
#     )

#     assert isinstance(strategy, HpManager)
#     last_price = 1000
#     strategy.ticker_update = TickerUpdate(last_price=last_price)

#     # Simulate order creation
#     await strategy.process_ticker()
#     assert strategy.state == State.BUYING
#     assert all(
#         order.status == ORDER_STATUS_NEW for order in sell_position.orders
#     )

#     # Simulate partial fill
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
#         order_id=445860,
#     )
#     await strategy.process_order()
#     assert strategy.state == State.BUYING

#     # Simulate full fill order 1
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_FILLED,
#         order_id=445860,
#     )
#     await strategy.process_order()
#     assert strategy.state == State.BUYING

#     # Simulate full fill order 2
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_FILLED,
#         order_id=445861,
#     )
#     await strategy.process_order()
#     assert strategy.state == State.BUYING

#     # Simulate full fill order 3
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_FILLED,
#         order_id=445862,
#     )
#     await strategy.process_order()
#     assert all(
#         order.status == ORDER_STATUS_FILLED
#         for order in sell_position.orders
#     )
#     assert strategy.core_queue.qsize() == 1
#     event = strategy.core_queue.get()
#     strategy.signal_update = event.content
#     await strategy.process_signal()
#     assert strategy.state == State.BOUGHT

# async def test_order_cancellation_sell(spot_sell):
#     spot_sell.model.client.create_order.side_effect = get_new_orders(
#         price_low=spot_sell.model.config.price_low,
#         price_high=spot_sell.model.config.price_high,
#     )
#     spot_sell.model.client.cancel_order.side_effect = get_cancel_order()
#     strategy = spot_sell.model
#     assert isinstance(strategy, HpManager)
#     assert strategy.calculate_trigger_cancel_orders_price() == 980
#     last_price = 1000
#     strategy.ticker_update = TickerUpdate(last_price=last_price)

#     # Simulate order creation
#     await strategy.process_ticker()
#     assert strategy.state == State.OPEN
#     assert all(
#         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
#     )

#     # Simulate stagnation counter increase
#     assert strategy.position_handler.stagnation_counter == 0

#     time_date = datetime.datetime.strptime(
#         strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
#     )

#     time_date -= datetime.timedelta(hours=8)
#     strategy.position_handler.next_monitor_position_time = time_date.strftime(
#         "%Y-%m-%d %H:%M:%S"
#     )
#     strategy.ticker_update = TickerUpdate(last_price=1014)

#     # Simulate reaching the stagnation limit
#     for _ in range(STAGNATION_LIMIT):
#         await strategy.process_ticker()

#     assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

#     # Simulate price being outside the threshold
#     strategy.ticker_update = TickerUpdate(last_price=979)
#     await strategy.process_ticker()

#     assert strategy.state == State.STAGNATED

#     last_price = 900
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     # Simulate nothing happening
#     await strategy.process_ticker()

#     logger.info("Ticker outside, nothing should happen: %s", last_price)

#     last_price = 1000
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     # Simulate nothing happening
#     await strategy.process_ticker()

#     logger.info("Ticker inside, reopen orders: %s", last_price)

#     assert strategy.state == State.OPEN

#     assert all(
#         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
#     )


# async def test_order_cancellation_buy(spot_buy):
#     spot_buy.model.client.create_order.side_effect = get_new_orders(
#         price_low=spot_buy.model.config.price_low,
#         price_high=spot_buy.model.config.price_high,
#     )
#     spot_buy.model.client.cancel_order.side_effect = get_cancel_order()
#     strategy = spot_buy.model
#     assert isinstance(strategy, HpManager)
#     assert strategy.calculate_trigger_cancel_orders_price() == 1428
#     last_price = 1400
#     strategy.ticker_update = TickerUpdate(last_price=last_price)

#     # Simulate order creation
#     await strategy.process_ticker()
#     assert strategy.state == State.OPEN
#     assert all(
#         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
#     )

#     time_date = datetime.datetime.strptime(
#         strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
#     )

#     time_date -= datetime.timedelta(hours=8)
#     strategy.position_handler.next_monitor_position_time = time_date.strftime(
#         "%Y-%m-%d %H:%M:%S"
#     )

#     # Simulate reaching the stagnation limit
#     for _ in range(STAGNATION_LIMIT):
#         await strategy.process_ticker()

#     assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

#     # Simulate price being outside the threshold
#     strategy.ticker_update = TickerUpdate(last_price=1429)
#     await strategy.process_ticker()

#     assert strategy.state == State.STAGNATED

#     last_price = 1500
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     # Simulate nothing happening
#     await strategy.process_ticker()

#     logger.info("Ticker outside, nothing should happen: %s", last_price)

#     last_price = 1400
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     # Simulate nothing happening
#     await strategy.process_ticker()

#     logger.info("Ticker inside, reopen orders: %s", last_price)

#     assert strategy.state == State.OPEN

#     assert all(
#         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
#     )


# async def test_order_reopen_with_filled_orders_sell(spot_sell):
#     spot_sell.model.client.create_order.side_effect = get_new_orders(
#         price_low=spot_sell.model.config.price_low,
#         price_high=spot_sell.model.config.price_high,
#     )
#     spot_sell.model.client.cancel_order.side_effect = get_cancel_order()
#     strategy = spot_sell.model
#     assert isinstance(strategy, HpManager)
#     assert strategy.calculate_trigger_cancel_orders_price() == 980
#     last_price = 1000
#     strategy.ticker_update = TickerUpdate(last_price=last_price)

#     # Simulate order creation
#     await strategy.process_ticker()
#     assert strategy.state == State.OPEN
#     assert all(
#         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
#     )

#     # Simulate full fill order 1
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_FILLED,
#         order_id=445860,
#         cumulative_filled_quantity=strategy.position_handler.orders[0].quantity,
#         quantity=strategy.position_handler.orders[0].quantity,
#     )
#     await strategy.process_order()
#     assert strategy.state == State.OPEN

#     # Simulate partial fill
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
#         order_id=445861,
#         cumulative_filled_quantity=(strategy.position_handler.orders[1].quantity / 2),
#     )
#     await strategy.process_order()
#     assert strategy.state == State.OPEN

#     # Simulate stagnation counter increase
#     assert strategy.position_handler.stagnation_counter == 0

#     time_date = datetime.datetime.strptime(
#         strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
#     )

#     time_date -= datetime.timedelta(hours=8)
#     strategy.position_handler.next_monitor_position_time = time_date.strftime(
#         "%Y-%m-%d %H:%M:%S"
#     )
#     strategy.ticker_update = TickerUpdate(last_price=1014)

#     # Simulate reaching the stagnation limit
#     for _ in range(STAGNATION_LIMIT):
#         await strategy.process_ticker()

#     assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

#     # Simulate price being outside the threshold
#     strategy.ticker_update = TickerUpdate(last_price=979)
#     await strategy.process_ticker()

#     assert strategy.state == State.STAGNATED

#     last_price = 900
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     # Simulate nothing happening
#     await strategy.process_ticker()

#     logger.info("Ticker outside, nothing should happen: %s", last_price)

#     last_price = 1000
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     # Simulate nothing happening
#     await strategy.process_ticker()

#     logger.info("Ticker inside, reopen orders: %s", last_price)

#     assert strategy.state == State.OPEN

#     assert all(
#         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
#     )

#     assert len(strategy.position_handler.orders) == 2

#     logger.info("All valid orders reopened.")


# async def test_order_reopen_with_filled_orders_buy(spot_buy):
#     spot_buy.model.client.create_order.side_effect = get_new_orders(
#         price_low=spot_buy.model.config.price_low,
#         price_high=spot_buy.model.config.price_high,
#     )
#     spot_buy.model.client.cancel_order.side_effect = get_cancel_order()
#     strategy = spot_buy.model
#     assert isinstance(strategy, HpManager)
#     assert strategy.calculate_trigger_cancel_orders_price() == 1428
#     last_price = 1400
#     strategy.ticker_update = TickerUpdate(last_price=last_price)

#     # Simulate order creation
#     await strategy.process_ticker()
#     assert strategy.state == State.OPEN
#     assert all(
#         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
#     )

#     # Simulate full fill order 1
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_FILLED,
#         order_id=445860,
#         cumulative_filled_quantity=strategy.position_handler.orders[0].quantity,
#         quantity=strategy.position_handler.orders[0].quantity,
#         symbol=strategy.config.symbol_info.symbol,
#         price=strategy.position_handler.orders[0].price,
#     )
#     await strategy.process_order()
#     assert strategy.state == State.OPEN

#     # Simulate partial fill
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
#         order_id=445861,
#         cumulative_filled_quantity=(strategy.position_handler.orders[1].quantity / 2),
#         symbol=strategy.config.symbol_info.symbol,
#         price=strategy.position_handler.orders[1].price,
#     )
#     await strategy.process_order()
#     assert strategy.state == State.OPEN

#     # Simulate stagnation counter increase
#     assert strategy.position_handler.stagnation_counter == 0

#     time_date = datetime.datetime.strptime(
#         strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
#     )

#     time_date -= datetime.timedelta(hours=8)
#     strategy.position_handler.next_monitor_position_time = time_date.strftime(
#         "%Y-%m-%d %H:%M:%S"
#     )

#     # Simulate reaching the stagnation limit
#     for _ in range(STAGNATION_LIMIT):
#         await strategy.process_ticker()

#     assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

#     # Simulate price being outside the threshold
#     last_price = 1429
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     await strategy.process_ticker()
#     assert strategy.state == State.STAGNATED

#     logger.info("Ticker outside, nothing should happen: %s", last_price)
#     last_price = 1500
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     # Simulate nothing happening
#     await strategy.process_ticker()

#     logger.info("Ticker inside, reopen orders: %s", last_price)
#     last_price = 1400
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     await strategy.process_ticker()

#     assert strategy.state == State.OPEN
#     assert all(
#         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
#     )
#     assert len(strategy.position_handler.orders) == 2
#     logger.info("All valid orders reopened.")


# async def test_default_scenario_buy_with_low_budget(spot_buy):
#     spot_buy.model.client.create_order.side_effect = get_new_orders(
#         price_low=spot_buy.model.config.price_low,
#         price_high=spot_buy.model.config.price_high,
#     )

#     # Set initial condition
#     strategy = spot_buy.model
#     assert isinstance(strategy, HpManager)
#     assert strategy.calculate_trigger_send_orders_price() == 1414
#     last_price = 1500
#     logger.info(
#         "Processing ticker with last price outside of threshold: %s", last_price
#     )
#     strategy.ticker_update = TickerUpdate(last_price=last_price)

#     # Simulate no state change
#     await strategy.process_ticker()
#     assert strategy.state == State.NEW

#     # Simulate no state change but on the price edge
#     last_price = 1415
#     logger.info(
#         "Processing ticker with last price on the edge of threshold: %s", last_price
#     )
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     await strategy.process_ticker()
#     assert strategy.state == State.NEW

#     # Price is within the range but the balance is too little so position is not opened
#     strategy.balance = 100
#     last_price = 1414
#     logger.info(
#         "Processing ticker with last price touching the threshold: %s, but balance: %s is too low for this position budget: %s",
#         last_price,
#         strategy.balance,
#         strategy.config.budget,
#     )
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     await strategy.process_ticker()
#     assert strategy.state == State.NEW

#     strategy.balance = 10000
#     logger.info(
#         "After balance is enough for sending orders: %s, budget: %s",
#         strategy.balance,
#         strategy.config.budget,
#     )
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     await strategy.process_ticker()
#     assert strategy.state == State.OPEN

#     assert all(
#         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
#     )

#     # Simulate order confirmation
#     await strategy.process_order()

#     # Simulate position closure
#     for order in strategy.position_handler.orders:
#         order.status = ORDER_STATUS_FILLED
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_FILLED,
#         order_id=strategy.position_handler.orders[0].order_id,
#     )

#     # Simulate order confirmation
#     await strategy.process_order()

#     assert strategy.core_queue.qsize() == 1

#     event = strategy.core_queue.get()
#     strategy.signal_update = event.content
#     await strategy.process_signal()

#     assert strategy.state == State.CLOSED


# async def test_order_reopen_with_filled_orders_low_budget_buy(spot_buy):
#     spot_buy.model.client.create_order.side_effect = get_new_orders(
#         price_low=spot_buy.model.config.price_low,
#         price_high=spot_buy.model.config.price_high,
#     )
#     spot_buy.model.client.cancel_order.side_effect = get_cancel_order()
#     strategy = spot_buy.model
#     assert isinstance(strategy, HpManager)
#     assert strategy.calculate_trigger_cancel_orders_price() == 1428
#     last_price = 1400
#     strategy.ticker_update = TickerUpdate(last_price=last_price)

#     # Simulate order creation
#     await strategy.process_ticker()
#     assert strategy.state == State.OPEN
#     assert all(
#         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
#     )

#     # Simulate full fill order 1
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_FILLED,
#         order_id=445860,
#         cumulative_filled_quantity=strategy.position_handler.orders[0].quantity,
#         quantity=strategy.position_handler.orders[0].quantity,
#         symbol=strategy.config.symbol_info.symbol,
#         price=strategy.position_handler.orders[0].price,
#     )
#     await strategy.process_order()
#     assert strategy.state == State.OPEN

#     # Simulate partial fill
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
#         order_id=445861,
#         cumulative_filled_quantity=(strategy.position_handler.orders[1].quantity / 2),
#         symbol=strategy.config.symbol_info.symbol,
#         price=strategy.position_handler.orders[1].price,
#     )
#     await strategy.process_order()
#     assert strategy.state == State.OPEN

#     # Simulate stagnation counter increase
#     assert strategy.position_handler.stagnation_counter == 0

#     time_date = datetime.datetime.strptime(
#         strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
#     )

#     time_date -= datetime.timedelta(hours=8)
#     strategy.position_handler.next_monitor_position_time = time_date.strftime(
#         "%Y-%m-%d %H:%M:%S"
#     )

#     # Simulate reaching the stagnation limit
#     for _ in range(STAGNATION_LIMIT):
#         await strategy.process_ticker()

#     assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

#     # Simulate price being outside the threshold
#     last_price = 1429
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     await strategy.process_ticker()
#     assert strategy.state == State.STAGNATED

#     logger.info("Ticker outside, nothing should happen: %s", last_price)
#     last_price = 1500
#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     # Simulate nothing happening
#     await strategy.process_ticker()

#     strategy.balance = 30
#     last_price = 1400
#     logger.info(
#         "Ticker inside: %s, but do not reopen orders due to low balance: %s",
#         last_price,
#         strategy.balance,
#     )

#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     await strategy.process_ticker()

#     assert strategy.state == State.STAGNATED

#     strategy.balance = 30000
#     last_price = 1400
#     logger.info(
#         "Ticker inside: %s, reopen orders due to sufficient balance: %s",
#         last_price,
#         strategy.balance,
#     )

#     strategy.ticker_update = TickerUpdate(last_price=last_price)
#     await strategy.process_ticker()

#     assert strategy.state == State.OPEN

#     assert all(
#         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
#     )
#     assert len(strategy.position_handler.orders) == 2
#     logger.info("All valid orders reopened.")
