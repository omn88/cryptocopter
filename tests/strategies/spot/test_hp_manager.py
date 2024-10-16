import datetime
import logging
from unittest.mock import MagicMock

from binance.enums import (
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_NEW,
    ORDER_STATUS_PARTIALLY_FILLED,
)
from src.common.identifiers.common import Mode, PositionSide
from src.common.identifiers.spot import (
    ExecutionReport,
    HPConfig,
    State,
    StateInfo,
    TickerUpdate,
)
from src.common.symbol_info import SymbolInfo
from src.position_handler.spot import PositionHandler
from src.strategies.spot.hp_manager import HpManager
from tests.spot import get_cancel_order, get_new_orders
from tests.strategies.spot.hp_manager import get_default_strategy_config

logger = logging.getLogger("test_hp_manager")


async def test_default_scenario_buy(trading_system_factory):
    trading_system = await trading_system_factory(
        get_default_strategy_config(), StateInfo(side=PositionSide.LONG)
    )
    trading_system.model.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.model.buy_position.config.price_low,
        price_high=trading_system.model.buy_position.config.price_high,
    )

    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    assert strategy.calculate_trigger_send_orders_price_buy() == 1414
    assert strategy.state == State.NEW
    assert strategy.buy_position.state_info.side == PositionSide.LONG

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
    assert strategy.state == State.BUYING

    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.buy_position.orders
    )

    # Simulate order confirmation
    await strategy.process_order()

    # Simulate position closure
    for order in strategy.buy_position.orders:
        order.status = ORDER_STATUS_FILLED
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.buy_position.orders[0].order_id,
    )

    # Simulate order confirmation
    await strategy.process_order()

    assert strategy.core_queue.qsize() == 1

    event = strategy.core_queue.get()
    strategy.signal_update = event.content
    await strategy.process_signal()

    assert strategy.state == State.BOUGHT


async def test_default_scenario_sell(trading_system_factory):
    trading_system = await trading_system_factory(
        get_default_strategy_config(), StateInfo(side=PositionSide.LONG)
    )
    trading_system.model.client.create_order.side_effect = get_new_orders(
        price_low=trading_system.model.buy_position.config.price_low,
        price_high=trading_system.model.buy_position.config.price_high,
    )

    strategy = trading_system.model
    assert isinstance(strategy, HpManager)

    # Simulate process_signal triggering
    last_price = 1414
    logger.info(
        "Processing ticker with last price touching the threshold: %s", last_price
    )
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()

    # Simulate order confirmation
    await strategy.process_order()

    # Simulate position closure
    for order in strategy.buy_position.orders:
        order.status = ORDER_STATUS_FILLED
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.buy_position.orders[0].order_id,
    )

    # Simulate order confirmation
    await strategy.process_order()

    event = strategy.core_queue.get()
    strategy.signal_update = event.content
    await strategy.process_signal()

    assert strategy.state == State.BOUGHT

    sell_config = HPConfig(
        hp_id=1000,
        symbol_info=SymbolInfo(symbol="BTCUSDT", precision=2, price_precision=2),
        price_high=4200,
        price_low=4200,
        mode=Mode.SINGLE,
        order_trigger=1.0,
        budget=1000,
    )
    sell_state_info = StateInfo(side=PositionSide.SHORT)
    strategy.sell_position = PositionHandler(
        client=strategy.client,
        strategy_logger=strategy.logger,
        config=sell_config,
        ui_queue=strategy.buy_position.ui_queue,
        db=strategy.db,
        state_info=sell_state_info,
    )
    strategy.client.create_order.side_effect = get_new_orders(
        price_low=strategy.sell_position.config.price_low,
        price_high=strategy.sell_position.config.price_high,
    )
    strategy.sell_position.orders = strategy.sell_position.order_handler.prepare_orders(
        state_info=sell_state_info, config=sell_config
    )
    strategy.sell_position.state_info.state = State.SELLING
    strategy.sell_position.state_info.side = PositionSide.SHORT
    strategy.ticker_update = MagicMock(last_price=4158)
    assert strategy.conditions_for_sending_sell_orders()

    last_price = 4114
    strategy.ticker_update = TickerUpdate(last_price=last_price)

    # Simulate no state change
    await strategy.process_ticker()
    assert strategy.state == State.BOUGHT

    # Simulate no state change but on the price edge
    last_price = 4157
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()
    assert strategy.state == State.BOUGHT

    last_price = 4158
    logger.info(
        "Processing ticker with last price touching the threshold: %s", last_price
    )
    strategy.ticker_update = TickerUpdate(last_price=last_price)
    await strategy.process_ticker()
    assert strategy.state == State.SELLING

    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.sell_position.orders
    )

    # Simulate order confirmation
    await strategy.process_order()

    # Simulate position closure
    for order in strategy.sell_position.orders:
        order.status = ORDER_STATUS_FILLED
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=strategy.sell_position.orders[0].order_id,
    )

    # Simulate order confirmation
    await strategy.process_order()

    assert strategy.core_queue.qsize() == 1

    event = strategy.core_queue.get()
    strategy.signal_update = event.content
    await strategy.process_signal()

    assert strategy.state == State.SOLD


# # async def test_partial_order_fill_buy(spot_buy):
# #     spot_buy.model.client.create_order.side_effect = get_new_orders(
# #         price_low=spot_buy.model.config.price_low,
# #         price_high=spot_buy.model.config.price_high,
# #     )
# #     strategy = spot_buy.model
# #     assert isinstance(strategy, HpManager)
# #     last_price = 1000
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)

# #     # Simulate order creation
# #     await strategy.process_ticker()
# #     assert strategy.state == State.OPEN
# #     assert all(
# #         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
# #     )

# #     # Simulate partial fill
# #     strategy.execution_report = ExecutionReport(
# #         order_type=ORDER_TYPE_LIMIT,
# #         current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
# #         order_id=445862,
# #     )
# #     await strategy.process_order()
# #     assert strategy.state == State.OPEN

# #     # Simulate full fill order 1
# #     strategy.execution_report = ExecutionReport(
# #         order_type=ORDER_TYPE_LIMIT,
# #         current_order_status=ORDER_STATUS_FILLED,
# #         order_id=445862,
# #     )
# #     await strategy.process_order()
# #     assert strategy.state == State.OPEN

# #     # Simulate full fill order 2
# #     strategy.execution_report = ExecutionReport(
# #         order_type=ORDER_TYPE_LIMIT,
# #         current_order_status=ORDER_STATUS_FILLED,
# #         order_id=445861,
# #     )
# #     await strategy.process_order()
# #     assert strategy.state == State.OPEN

# #     # Simulate full fill order 3
# #     strategy.execution_report = ExecutionReport(
# #         order_type=ORDER_TYPE_LIMIT,
# #         current_order_status=ORDER_STATUS_FILLED,
# #         order_id=445860,
# #     )
# #     await strategy.process_order()
# #     assert all(
# #         order.status == ORDER_STATUS_FILLED
# #         for order in strategy.position_handler.orders
# #     )
# #     assert strategy.core_queue.qsize() == 1
# #     event = strategy.core_queue.get()
# #     strategy.signal_update = event.content
# #     await strategy.process_signal()
# #     assert strategy.state == State.CLOSED


# # async def test_partial_order_fill_sell(spot_sell):
# #     spot_sell.model.client.create_order.side_effect = get_new_orders(
# #         price_low=spot_sell.model.config.price_low,
# #         price_high=spot_sell.model.config.price_high,
# #     )
# #     strategy = spot_sell.model
# #     assert isinstance(strategy, HpManager)
# #     last_price = 1000
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)

# #     # Simulate order creation
# #     await strategy.process_ticker()
# #     assert strategy.state == State.OPEN
# #     assert all(
# #         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
# #     )

# #     # Simulate partial fill
# #     strategy.execution_report = ExecutionReport(
# #         order_type=ORDER_TYPE_LIMIT,
# #         current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
# #         order_id=445860,
# #     )
# #     await strategy.process_order()
# #     assert strategy.state == State.OPEN

# #     # Simulate full fill order 1
# #     strategy.execution_report = ExecutionReport(
# #         order_type=ORDER_TYPE_LIMIT,
# #         current_order_status=ORDER_STATUS_FILLED,
# #         order_id=445860,
# #     )
# #     await strategy.process_order()
# #     assert strategy.state == State.OPEN

# #     # Simulate full fill order 2
# #     strategy.execution_report = ExecutionReport(
# #         order_type=ORDER_TYPE_LIMIT,
# #         current_order_status=ORDER_STATUS_FILLED,
# #         order_id=445861,
# #     )
# #     await strategy.process_order()
# #     assert strategy.state == State.OPEN

# #     # Simulate full fill order 3
# #     strategy.execution_report = ExecutionReport(
# #         order_type=ORDER_TYPE_LIMIT,
# #         current_order_status=ORDER_STATUS_FILLED,
# #         order_id=445862,
# #     )
# #     await strategy.process_order()
# #     assert all(
# #         order.status == ORDER_STATUS_FILLED
# #         for order in strategy.position_handler.orders
# #     )
# #     assert strategy.core_queue.qsize() == 1
# #     event = strategy.core_queue.get()
# #     strategy.signal_update = event.content
# #     await strategy.process_signal()
# #     assert strategy.state == State.CLOSED


# # async def test_order_cancellation_sell(spot_sell):
# #     spot_sell.model.client.create_order.side_effect = get_new_orders(
# #         price_low=spot_sell.model.config.price_low,
# #         price_high=spot_sell.model.config.price_high,
# #     )
# #     spot_sell.model.client.cancel_order.side_effect = get_cancel_order()
# #     strategy = spot_sell.model
# #     assert isinstance(strategy, HpManager)
# #     assert strategy.calculate_trigger_cancel_orders_price() == 980
# #     last_price = 1000
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)

# #     # Simulate order creation
# #     await strategy.process_ticker()
# #     assert strategy.state == State.OPEN
# #     assert all(
# #         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
# #     )

# #     # Simulate stagnation counter increase
# #     assert strategy.position_handler.stagnation_counter == 0

# #     time_date = datetime.datetime.strptime(
# #         strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
# #     )

# #     time_date -= datetime.timedelta(hours=8)
# #     strategy.position_handler.next_monitor_position_time = time_date.strftime(
# #         "%Y-%m-%d %H:%M:%S"
# #     )
# #     strategy.ticker_update = TickerUpdate(last_price=1014)

# #     # Simulate reaching the stagnation limit
# #     for _ in range(STAGNATION_LIMIT):
# #         await strategy.process_ticker()

# #     assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

# #     # Simulate price being outside the threshold
# #     strategy.ticker_update = TickerUpdate(last_price=979)
# #     await strategy.process_ticker()

# #     assert strategy.state == State.STAGNATED

# #     last_price = 900
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)
# #     # Simulate nothing happening
# #     await strategy.process_ticker()

# #     logger.info("Ticker outside, nothing should happen: %s", last_price)

# #     last_price = 1000
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)
# #     # Simulate nothing happening
# #     await strategy.process_ticker()

# #     logger.info("Ticker inside, reopen orders: %s", last_price)

# #     assert strategy.state == State.OPEN

# #     assert all(
# #         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
# #     )


# # async def test_order_cancellation_buy(spot_buy):
# #     spot_buy.model.client.create_order.side_effect = get_new_orders(
# #         price_low=spot_buy.model.config.price_low,
# #         price_high=spot_buy.model.config.price_high,
# #     )
# #     spot_buy.model.client.cancel_order.side_effect = get_cancel_order()
# #     strategy = spot_buy.model
# #     assert isinstance(strategy, HpManager)
# #     assert strategy.calculate_trigger_cancel_orders_price() == 1428
# #     last_price = 1400
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)

# #     # Simulate order creation
# #     await strategy.process_ticker()
# #     assert strategy.state == State.OPEN
# #     assert all(
# #         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
# #     )

# #     time_date = datetime.datetime.strptime(
# #         strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
# #     )

# #     time_date -= datetime.timedelta(hours=8)
# #     strategy.position_handler.next_monitor_position_time = time_date.strftime(
# #         "%Y-%m-%d %H:%M:%S"
# #     )

# #     # Simulate reaching the stagnation limit
# #     for _ in range(STAGNATION_LIMIT):
# #         await strategy.process_ticker()

# #     assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

# #     # Simulate price being outside the threshold
# #     strategy.ticker_update = TickerUpdate(last_price=1429)
# #     await strategy.process_ticker()

# #     assert strategy.state == State.STAGNATED

# #     last_price = 1500
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)
# #     # Simulate nothing happening
# #     await strategy.process_ticker()

# #     logger.info("Ticker outside, nothing should happen: %s", last_price)

# #     last_price = 1400
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)
# #     # Simulate nothing happening
# #     await strategy.process_ticker()

# #     logger.info("Ticker inside, reopen orders: %s", last_price)

# #     assert strategy.state == State.OPEN

# #     assert all(
# #         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
# #     )


# # async def test_order_reopen_with_filled_orders_sell(spot_sell):
# #     spot_sell.model.client.create_order.side_effect = get_new_orders(
# #         price_low=spot_sell.model.config.price_low,
# #         price_high=spot_sell.model.config.price_high,
# #     )
# #     spot_sell.model.client.cancel_order.side_effect = get_cancel_order()
# #     strategy = spot_sell.model
# #     assert isinstance(strategy, HpManager)
# #     assert strategy.calculate_trigger_cancel_orders_price() == 980
# #     last_price = 1000
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)

# #     # Simulate order creation
# #     await strategy.process_ticker()
# #     assert strategy.state == State.OPEN
# #     assert all(
# #         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
# #     )

# #     # Simulate full fill order 1
# #     strategy.execution_report = ExecutionReport(
# #         order_type=ORDER_TYPE_LIMIT,
# #         current_order_status=ORDER_STATUS_FILLED,
# #         order_id=445860,
# #         cumulative_filled_quantity=strategy.position_handler.orders[0].quantity,
# #         quantity=strategy.position_handler.orders[0].quantity,
# #     )
# #     await strategy.process_order()
# #     assert strategy.state == State.OPEN

# #     # Simulate partial fill
# #     strategy.execution_report = ExecutionReport(
# #         order_type=ORDER_TYPE_LIMIT,
# #         current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
# #         order_id=445861,
# #         cumulative_filled_quantity=(strategy.position_handler.orders[1].quantity / 2),
# #     )
# #     await strategy.process_order()
# #     assert strategy.state == State.OPEN

# #     # Simulate stagnation counter increase
# #     assert strategy.position_handler.stagnation_counter == 0

# #     time_date = datetime.datetime.strptime(
# #         strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
# #     )

# #     time_date -= datetime.timedelta(hours=8)
# #     strategy.position_handler.next_monitor_position_time = time_date.strftime(
# #         "%Y-%m-%d %H:%M:%S"
# #     )
# #     strategy.ticker_update = TickerUpdate(last_price=1014)

# #     # Simulate reaching the stagnation limit
# #     for _ in range(STAGNATION_LIMIT):
# #         await strategy.process_ticker()

# #     assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

# #     # Simulate price being outside the threshold
# #     strategy.ticker_update = TickerUpdate(last_price=979)
# #     await strategy.process_ticker()

# #     assert strategy.state == State.STAGNATED

# #     last_price = 900
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)
# #     # Simulate nothing happening
# #     await strategy.process_ticker()

# #     logger.info("Ticker outside, nothing should happen: %s", last_price)

# #     last_price = 1000
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)
# #     # Simulate nothing happening
# #     await strategy.process_ticker()

# #     logger.info("Ticker inside, reopen orders: %s", last_price)

# #     assert strategy.state == State.OPEN

# #     assert all(
# #         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
# #     )

# #     assert len(strategy.position_handler.orders) == 2

# #     logger.info("All valid orders reopened.")


# # async def test_order_reopen_with_filled_orders_buy(spot_buy):
# #     spot_buy.model.client.create_order.side_effect = get_new_orders(
# #         price_low=spot_buy.model.config.price_low,
# #         price_high=spot_buy.model.config.price_high,
# #     )
# #     spot_buy.model.client.cancel_order.side_effect = get_cancel_order()
# #     strategy = spot_buy.model
# #     assert isinstance(strategy, HpManager)
# #     assert strategy.calculate_trigger_cancel_orders_price() == 1428
# #     last_price = 1400
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)

# #     # Simulate order creation
# #     await strategy.process_ticker()
# #     assert strategy.state == State.OPEN
# #     assert all(
# #         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
# #     )

# #     # Simulate full fill order 1
# #     strategy.execution_report = ExecutionReport(
# #         order_type=ORDER_TYPE_LIMIT,
# #         current_order_status=ORDER_STATUS_FILLED,
# #         order_id=445860,
# #         cumulative_filled_quantity=strategy.position_handler.orders[0].quantity,
# #         quantity=strategy.position_handler.orders[0].quantity,
# #         symbol=strategy.config.symbol_info.symbol,
# #         price=strategy.position_handler.orders[0].price,
# #     )
# #     await strategy.process_order()
# #     assert strategy.state == State.OPEN

# #     # Simulate partial fill
# #     strategy.execution_report = ExecutionReport(
# #         order_type=ORDER_TYPE_LIMIT,
# #         current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
# #         order_id=445861,
# #         cumulative_filled_quantity=(strategy.position_handler.orders[1].quantity / 2),
# #         symbol=strategy.config.symbol_info.symbol,
# #         price=strategy.position_handler.orders[1].price,
# #     )
# #     await strategy.process_order()
# #     assert strategy.state == State.OPEN

# #     # Simulate stagnation counter increase
# #     assert strategy.position_handler.stagnation_counter == 0

# #     time_date = datetime.datetime.strptime(
# #         strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
# #     )

# #     time_date -= datetime.timedelta(hours=8)
# #     strategy.position_handler.next_monitor_position_time = time_date.strftime(
# #         "%Y-%m-%d %H:%M:%S"
# #     )

# #     # Simulate reaching the stagnation limit
# #     for _ in range(STAGNATION_LIMIT):
# #         await strategy.process_ticker()

# #     assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

# #     # Simulate price being outside the threshold
# #     last_price = 1429
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)
# #     await strategy.process_ticker()
# #     assert strategy.state == State.STAGNATED

# #     logger.info("Ticker outside, nothing should happen: %s", last_price)
# #     last_price = 1500
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)
# #     # Simulate nothing happening
# #     await strategy.process_ticker()

# #     logger.info("Ticker inside, reopen orders: %s", last_price)
# #     last_price = 1400
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)
# #     await strategy.process_ticker()

# #     assert strategy.state == State.OPEN
# #     assert all(
# #         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
# #     )
# #     assert len(strategy.position_handler.orders) == 2
# #     logger.info("All valid orders reopened.")


# # async def test_default_scenario_buy_with_low_budget(spot_buy):
# #     spot_buy.model.client.create_order.side_effect = get_new_orders(
# #         price_low=spot_buy.model.config.price_low,
# #         price_high=spot_buy.model.config.price_high,
# #     )

# #     # Set initial condition
# #     strategy = spot_buy.model
# #     assert isinstance(strategy, HpManager)
# #     assert strategy.calculate_trigger_send_orders_price() == 1414
# #     last_price = 1500
# #     logger.info(
# #         "Processing ticker with last price outside of threshold: %s", last_price
# #     )
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)

# #     # Simulate no state change
# #     await strategy.process_ticker()
# #     assert strategy.state == State.NEW

# #     # Simulate no state change but on the price edge
# #     last_price = 1415
# #     logger.info(
# #         "Processing ticker with last price on the edge of threshold: %s", last_price
# #     )
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)
# #     await strategy.process_ticker()
# #     assert strategy.state == State.NEW

# #     # Price is within the range but the balance is too little so position is not opened
# #     strategy.balance = 100
# #     last_price = 1414
# #     logger.info(
# #         "Processing ticker with last price touching the threshold: %s, but balance: %s is too low for this position budget: %s",
# #         last_price,
# #         strategy.balance,
# #         strategy.config.budget,
# #     )
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)
# #     await strategy.process_ticker()
# #     assert strategy.state == State.NEW

# #     strategy.balance = 10000
# #     logger.info(
# #         "After balance is enough for sending orders: %s, budget: %s",
# #         strategy.balance,
# #         strategy.config.budget,
# #     )
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)
# #     await strategy.process_ticker()
# #     assert strategy.state == State.OPEN

# #     assert all(
# #         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
# #     )

# #     # Simulate order confirmation
# #     await strategy.process_order()

# #     # Simulate position closure
# #     for order in strategy.position_handler.orders:
# #         order.status = ORDER_STATUS_FILLED
# #     strategy.execution_report = ExecutionReport(
# #         order_type=ORDER_TYPE_LIMIT,
# #         current_order_status=ORDER_STATUS_FILLED,
# #         order_id=strategy.position_handler.orders[0].order_id,
# #     )

# #     # Simulate order confirmation
# #     await strategy.process_order()

# #     assert strategy.core_queue.qsize() == 1

# #     event = strategy.core_queue.get()
# #     strategy.signal_update = event.content
# #     await strategy.process_signal()

# #     assert strategy.state == State.CLOSED


# # async def test_order_reopen_with_filled_orders_low_budget_buy(spot_buy):
# #     spot_buy.model.client.create_order.side_effect = get_new_orders(
# #         price_low=spot_buy.model.config.price_low,
# #         price_high=spot_buy.model.config.price_high,
# #     )
# #     spot_buy.model.client.cancel_order.side_effect = get_cancel_order()
# #     strategy = spot_buy.model
# #     assert isinstance(strategy, HpManager)
# #     assert strategy.calculate_trigger_cancel_orders_price() == 1428
# #     last_price = 1400
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)

# #     # Simulate order creation
# #     await strategy.process_ticker()
# #     assert strategy.state == State.OPEN
# #     assert all(
# #         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
# #     )

# #     # Simulate full fill order 1
# #     strategy.execution_report = ExecutionReport(
# #         order_type=ORDER_TYPE_LIMIT,
# #         current_order_status=ORDER_STATUS_FILLED,
# #         order_id=445860,
# #         cumulative_filled_quantity=strategy.position_handler.orders[0].quantity,
# #         quantity=strategy.position_handler.orders[0].quantity,
# #         symbol=strategy.config.symbol_info.symbol,
# #         price=strategy.position_handler.orders[0].price,
# #     )
# #     await strategy.process_order()
# #     assert strategy.state == State.OPEN

# #     # Simulate partial fill
# #     strategy.execution_report = ExecutionReport(
# #         order_type=ORDER_TYPE_LIMIT,
# #         current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
# #         order_id=445861,
# #         cumulative_filled_quantity=(strategy.position_handler.orders[1].quantity / 2),
# #         symbol=strategy.config.symbol_info.symbol,
# #         price=strategy.position_handler.orders[1].price,
# #     )
# #     await strategy.process_order()
# #     assert strategy.state == State.OPEN

# #     # Simulate stagnation counter increase
# #     assert strategy.position_handler.stagnation_counter == 0

# #     time_date = datetime.datetime.strptime(
# #         strategy.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
# #     )

# #     time_date -= datetime.timedelta(hours=8)
# #     strategy.position_handler.next_monitor_position_time = time_date.strftime(
# #         "%Y-%m-%d %H:%M:%S"
# #     )

# #     # Simulate reaching the stagnation limit
# #     for _ in range(STAGNATION_LIMIT):
# #         await strategy.process_ticker()

# #     assert strategy.position_handler.stagnation_counter == STAGNATION_LIMIT

# #     # Simulate price being outside the threshold
# #     last_price = 1429
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)
# #     await strategy.process_ticker()
# #     assert strategy.state == State.STAGNATED

# #     logger.info("Ticker outside, nothing should happen: %s", last_price)
# #     last_price = 1500
# #     strategy.ticker_update = TickerUpdate(last_price=last_price)
# #     # Simulate nothing happening
# #     await strategy.process_ticker()

# #     strategy.balance = 30
# #     last_price = 1400
# #     logger.info(
# #         "Ticker inside: %s, but do not reopen orders due to low balance: %s",
# #         last_price,
# #         strategy.balance,
# #     )

# #     strategy.ticker_update = TickerUpdate(last_price=last_price)
# #     await strategy.process_ticker()

# #     assert strategy.state == State.STAGNATED

# #     strategy.balance = 30000
# #     last_price = 1400
# #     logger.info(
# #         "Ticker inside: %s, reopen orders due to sufficient balance: %s",
# #         last_price,
# #         strategy.balance,
# #     )

# #     strategy.ticker_update = TickerUpdate(last_price=last_price)
# #     await strategy.process_ticker()

# #     assert strategy.state == State.OPEN

# #     assert all(
# #         order.status == ORDER_STATUS_NEW for order in strategy.position_handler.orders
# #     )
# #     assert len(strategy.position_handler.orders) == 2
# #     logger.info("All valid orders reopened.")
