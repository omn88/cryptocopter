import asyncio
import logging
import pytest
from src.gui.hpfront import HpFront
from src.identifiers.spot import State
from src.strategies.hp_manager import HpStrategy
from src.strategy_executor import StrategyExecutor
from tests.spot import get_new_orders, simulate_buy_position, simulate_new_price
from tests.strategies.spot.hp_manager_helpers import wait_for_condition


logger = logging.getLogger("hp_e2e_test")


@pytest.mark.database_integration
async def test_get_default_buy_position(frontend_backend_setup):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    assert len(back.strategies) == 0

    simulate_buy_position(config_queue=front.config_queue, symbol="BTCUSDC")

    await wait_for_condition(condition_func=lambda: len(back.strategies) == 1)
    assert not back.config_queue.qsize()
    assert len(back.strategies) == 1
    strategy = back.strategies["1000"]

    assert isinstance(strategy, HpStrategy)
    assert strategy.state == State.NEW
    assert len(strategy.buy.orders) == 3

    strategy.stop_event.set()
    logger.info("DONE")


@pytest.mark.database_integration
async def test_default_buy_position_send_orders(frontend_backend_setup):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)

    assert len(back.strategies) == 0

    simulate_buy_position(config_queue=front.config_queue, symbol="BTCUSDC")

    await wait_for_condition(condition_func=lambda: len(back.strategies) == 1)
    assert not back.config_queue.qsize()

    strategy = back.strategies["1000"]
    assert isinstance(strategy, HpStrategy)
    assert strategy.state == State.NEW

    buy_pos = strategy.buy.data
    assert len(strategy.buy.orders) == 3

    strategy.client.create_order.side_effect = get_new_orders(
        price_low=buy_pos.config.price_low,
        price_high=buy_pos.config.price_high,
        number_of_orders=3,
    )

    simulate_new_price(worker_queue=strategy.worker_queue, price=1410)

    await wait_for_condition(condition_func=lambda: strategy.state == State.BUYING)

    assert buy_pos.state_info.state == State.NEW
    assert all(order.order_id for order in strategy.buy.orders)

    logger.info("Active records: %s", front.active_records_buy)
    logger.info("Idle records: %s", front.idle_records_buy)

    await wait_for_condition(condition_func=lambda: front.active_records_buy)

    strategy.stop_event.set()
    await asyncio.sleep(0.1)
    logger.info("DONE")


# async def test_default_position(hp_gui: HpFront, trading_system_factory) -> None:
# """
# This test purpose is to instantiate basic buy position and assert on
# the default values

# Path 0
# """
# hp_list: List[Dict] = []
# strategy: HpStrategy = get_default_buy_position(trading_system_factory)
# assert isinstance(strategy, HpStrategy)

# strategy, hp_list = assert_default_buy_position_data(
#     strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
# )


# async def test_default_position_send_orders(
#     hp_gui: HpFront, trading_system_factory
# ) -> None:
#     """
#     Path 1
#     """

#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )


# async def test_cancel_default_position_untouched(
#     hp_gui: HpFront, trading_system_factory
# ) -> None:
#     """
#     This test purpose is to instantiate basic buy position then trigger
#     the conditions with which the position will be cancelled untouched and the states
#     will get back to State.NEW
#     Path 1 -> 2 -> 1
#     """

#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await cancel_untouched_buy_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )


# async def test_cancel_default_position_untouched_then_resend_orders(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     """
#     This test purpose is to instantiate basic buy position then trigger
#     the conditions with which the position will be cancelled untouched and the states
#     will get back to State.NEW
#     """

#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await cancel_untouched_buy_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Resend buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )


# async def test_default_position_first_order_filled_partially(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Simulate partial fill
#     strategy = await simulate_partial_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )


# async def test_default_position_first_order_filled_partially_then_cancel(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Simulate partial fill
#     strategy = await simulate_partial_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Cancel position
#     strategy = await cancel_partially_bought_position_first_order_filled_partially(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )


# async def test_default_position_first_order_filled(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Simulate full order fill
#     strategy, hp_list = await simulate_first_buy_order_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445860
#     )


# async def test_default_position_first_order_filled_then_cancel(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Simulate full order fill
#     strategy, hp_list = await simulate_first_buy_order_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445860
#     )

#     # Cancel partially bought position
#     strategy = await cancel_partially_bought_position_first_order_filled(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )


# async def test_default_position_all_buy_orders_filled(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Simulate full order fill
#     strategy, hp_list = await simulate_first_buy_order_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445860
#     )

#     strategy, hp_list = await simulate_second_buy_order_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445861
#     )
#     strategy, hp_list = await simulate_third_buy_order_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445862
#     )


# async def test_conditions_for_new_buy_order_confirmation(
#     hp_gui: HpFront, trading_system_factory
# ) -> None:
#     """
#     Path 1
#     """

#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_NEW,
#         symbol=strategy.buy.data.config.symbol_info.symbol,
#     )
#     assert strategy.conditions_for_new_order_confirmation()


# async def test_conditions_for_buy_order_cancellation(
#     hp_gui: HpFront, trading_system_factory
# ) -> None:
#     """
#     Path 1
#     """

#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_CANCELED,
#         symbol=strategy.buy.data.config.symbol_info.symbol,
#     )
#     assert strategy.conditions_for_order_cancellation()


# async def test_conditions_for_buy_order_expiration(
#     hp_gui: HpFront, trading_system_factory
# ) -> None:
#     """
#     Path 1
#     """

#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT, current_order_status=ORDER_STATUS_EXPIRED
#     )
#     assert strategy.conditions_for_order_expiration()


# async def test_stagnation_counter_increase_buy(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     """
#     This test purpose is to instantiate basic buy position then trigger
#     the conditions with which the position will be cancelled untouched and the states
#     will get back to State.NEW
#     """

#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     assert strategy.buy.data.state_info.stagnation_counter == 0
#     assert strategy.buy.data.state_info.stagnation_limit == 8

#     time = datetime.datetime.now()
#     strategy.buy.data.state_info.next_monitor_time = time.strftime("%Y-%m-%d %H:%M:%S")

#     assert strategy.buy.data.state_info.next_monitor_time == time.strftime(
#         "%Y-%m-%d %H:%M:%S"
#     )

#     assert strategy.conditions_for_position_stagnation_buy()
#     await strategy.process_ticker()  # type: ignore[attr-defined]

#     assert strategy.buy.data.state_info.stagnation_counter == 1
#     assert strategy.buy.data.state_info.stagnation_limit == 8

#     assert strategy.buy.data.state_info.next_monitor_time != time.strftime(
#         "%Y-%m-%d %H:%M:%S"
#     )

#     assert strategy.ui_queue.qsize() == 1
#     content = strategy.ui_queue.get_nowait()
#     logger.info("Content123: %s", content)
#     assert isinstance(content, HPGuiDataBuy)

#     state_info = content.data.state_info
#     assert isinstance(state_info, StateInfo)

#     assert state_info.state == State.NEW
#     assert state_info.next_monitor_time

#     assert content.data.state_info.ui_state == UiState.OPEN
#     assert content.data.config.order_cancel == 2.0
#     assert content.data.state_info.completeness == 0.00

#     assert strategy.ui_queue.qsize() == 0

#     hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)
#     assert len(hp_list) == 1
#     item = hp_list[0]
#     assert item["hp_id"] == "1000"
#     assert item["asset"] == "BTC"
#     assert item["buy_price"] == "0.0"
#     assert item["quantity"] == "0.0"
#     assert item["quantity_usdt"] == "0.0"
#     assert item["sell_price"] == "0.0"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "BUYING"


# async def test_default_position_first_order_filled_partially_then_cancel_then_resend(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Simulate partial fill
#     strategy = await simulate_partial_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Cancel position
#     strategy = await cancel_partially_bought_position_first_order_filled_partially(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Reopen position
#     strategy = await resend_part_bought_first_order_filled_partially(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )


# async def test_default_position_first_order_filled_then_cancel_then_resend(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Simulate full order fill
#     strategy, hp_list = await simulate_first_buy_order_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445860
#     )

#     # Cancel partially bought position
#     strategy = await cancel_partially_bought_position_first_order_filled(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Resend buy orders after 1st order was filled
#     strategy, hp_list = await resend_part_bought_first_order_filled(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )


# async def test_send_sell_orders_for_bought_position(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     hp_list: List[Dict] = []
#     strategy, hp_list = await simulate_bought_position(
#         trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
#     )
#     assert isinstance(strategy, HpStrategy)

#     strategy, hp_list = await send_sell_orders_for_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )


# async def test_sell_orders_stagnation_increase(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     hp_list: List[Dict] = []
#     strategy, hp_list = await simulate_bought_position(
#         trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
#     )
#     assert isinstance(strategy, HpStrategy)

#     strategy, hp_list = await send_sell_orders_for_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     assert strategy.sell.data.state_info.stagnation_counter == 0
#     assert strategy.sell.data.state_info.stagnation_limit == 8

#     time = datetime.datetime.now()
#     strategy.sell.data.state_info.next_monitor_time = time.strftime("%Y-%m-%d %H:%M:%S")

#     assert strategy.sell.data.state_info.next_monitor_time == time.strftime(
#         "%Y-%m-%d %H:%M:%S"
#     )

#     assert strategy.conditions_for_position_stagnation_sell()
#     await strategy.process_ticker()  # type: ignore[attr-defined]

#     assert strategy.sell.data.state_info.stagnation_counter == 1
#     assert strategy.sell.data.state_info.stagnation_limit == 8

#     assert strategy.sell.data.state_info.next_monitor_time != time.strftime(
#         "%Y-%m-%d %H:%M:%S"
#     )

#     assert strategy.ui_queue.qsize() == 1
#     content = strategy.ui_queue.get_nowait()
#     logger.info("Content: %s", content)
#     assert isinstance(content, HPGuiDataSell)

#     state_info = content.data.state_info
#     assert isinstance(state_info, StateInfo)

#     assert state_info.next_monitor_time
#     assert state_info.state == State.NEW
#     assert state_info.side == PositionSide.SHORT
#     assert state_info.ui_state == UiState.OPEN
#     assert state_info.completeness == 0.00

#     assert strategy.ui_queue.qsize() == 0

#     hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

#     assert len(hp_list) == 1
#     item = hp_list[0]
#     assert item["hp_id"] == "1000"
#     assert item["asset"] == "BTC"
#     assert item["buy_price"] == "1178.82"
#     assert item["quantity"] == "0.85"
#     assert item["quantity_usdt"] == "1002.0"
#     assert item["sell_price"] == "4200.0"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "SELLING"

#     logger.info("HP List after the update: %s", hp_list)


# async def test_cancel_unfilled_sell_orders(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     hp_list: List[Dict] = []
#     strategy, hp_list = await simulate_bought_position(
#         trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
#     )
#     assert isinstance(strategy, HpStrategy)

#     strategy, hp_list = await send_sell_orders_for_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy = await cancel_untouched_sell_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )


# async def test_resend_unfilled_sell_orders(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     hp_list: List[Dict] = []
#     strategy, hp_list = await simulate_bought_position(
#         trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
#     )
#     assert isinstance(strategy, HpStrategy)

#     strategy, hp_list = await send_sell_orders_for_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy = await cancel_untouched_sell_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     assert strategy.calculate_trigger_send_orders_price_sell() == 4032
#     strategy.ticker_update = TickerUpdate(last_price=4032.0)
#     assert strategy.conditions_for_sending_sell_orders()

#     await strategy.process_ticker()  # type: ignore[attr-defined]

#     assert strategy.state == State.SELLING
#     assert strategy.sell.data.state_info.state == State.NEW

#     assert strategy.sell.orders[0].quantity == 0.85
#     assert strategy.sell.orders[0].realized_quantity == 0.0

#     assert strategy.sell.orders[0].status == ORDER_STATUS_NEW

#     assert strategy.ui_queue.qsize() == 1
#     content = strategy.ui_queue.get_nowait()
#     logger.info("Content: %s", content)
#     assert isinstance(content, HPGuiDataSell)

#     state_info = content.data.state_info
#     assert isinstance(state_info, StateInfo)

#     assert state_info.next_monitor_time
#     assert state_info.state == State.NEW
#     assert state_info.side == PositionSide.SHORT
#     assert state_info.ui_state == UiState.OPEN
#     assert state_info.completeness == 0.00

#     assert strategy.ui_queue.qsize() == 0

#     hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

#     assert len(hp_list) == 1
#     item = hp_list[0]
#     assert item["hp_id"] == "1000"
#     assert item["asset"] == "BTC"
#     assert item["buy_price"] == "1178.82"
#     assert item["quantity"] == "0.85"
#     assert item["quantity_usdt"] == "1002.0"
#     assert item["sell_price"] == "4200.0"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "SELLING"

#     logger.info("HP List after the update: %s", hp_list)


# async def test_sell_position_first_order_filled_partially(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     hp_list: List[Dict] = []
#     strategy, hp_list = await simulate_bought_position(
#         trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
#     )
#     assert isinstance(strategy, HpStrategy)

#     strategy, hp_list = await send_sell_orders_for_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await simulate_partial_fill_sell(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )


# async def test_sell_position_first_order_filled(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     hp_list: List[Dict] = []
#     strategy, hp_list = await simulate_bought_position(
#         trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
#     )
#     assert isinstance(strategy, HpStrategy)

#     strategy, hp_list = await send_sell_orders_for_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Simulate first order fill
#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_FILLED,
#         order_id=445863,
#         last_executed_quantity=0.85,
#         last_executed_price=4200.0,
#         cumulative_filled_quantity=0.85,
#     )
#     await strategy.process_order()  # type: ignore[attr-defined]

#     logger.info("Orders: %s", strategy.sell.orders)
#     assert strategy.sell.orders[0].status == ORDER_STATUS_FILLED
#     assert strategy.state == State.SELLING
#     assert strategy.sell.data.state_info.state == State.SOLD

#     assert strategy.ui_queue.qsize() == 1
#     content = strategy.ui_queue.get_nowait()
#     logger.info("Content: %s", content)
#     assert isinstance(content, HPGuiDataSell)

#     state_info = content.data.state_info
#     assert isinstance(state_info, StateInfo)

#     assert state_info.next_monitor_time
#     assert state_info.state == State.SOLD
#     assert state_info.side == PositionSide.SHORT
#     assert state_info.ui_state == UiState.CLOSED
#     assert state_info.completeness == 1.00

#     assert strategy.ui_queue.qsize() == 0

#     hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

#     assert len(hp_list) == 1
#     item = hp_list[0]
#     assert item["hp_id"] == "1000"
#     assert item["asset"] == "BTC"
#     assert item["buy_price"] == "1178.82"
#     assert item["quantity"] == "0.0"
#     assert item["quantity_usdt"] == "0.0"
#     assert item["sell_price"] == "4200.0"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "SELLING"

#     logger.info("HP List after the update: %s", hp_list)

#     assert strategy.worker_queue.qsize() == 1
#     event = strategy.worker_queue.get_nowait()

#     assert isinstance(event, Event)
#     assert event.name == EventName.SIGNAL
#     assert isinstance(event.content, SignalUpdate)

#     strategy.signal_update = event.content

#     await strategy.process_signal()  # type: ignore[attr-defined]

#     assert strategy.ui_queue.qsize() == 1
#     content = strategy.ui_queue.get_nowait()
#     logger.info("Content: %s", content)
#     assert isinstance(content, HPGuiDataSell)

#     state_info = content.data.state_info
#     assert isinstance(state_info, StateInfo)

#     assert state_info.next_monitor_time
#     assert state_info.state == State.SOLD
#     assert state_info.side == PositionSide.SHORT
#     assert state_info.ui_state == UiState.CLOSED
#     assert state_info.completeness == 1.00

#     assert strategy.ui_queue.qsize() == 0

#     hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

#     assert len(hp_list) == 1
#     item = hp_list[0]
#     assert item["hp_id"] == "1000"
#     assert item["asset"] == "BTC"
#     assert item["buy_price"] == "1178.82"
#     assert item["quantity"] == "0.0"
#     assert item["quantity_usdt"] == "0.0"
#     assert item["sell_price"] == "4200.0"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "SOLD"

#     logger.info("HP List after the update: %s", hp_list)


# async def test_cancel_sell_position_first_order_filled_partially(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     hp_list: List[Dict] = []
#     strategy, hp_list = await simulate_bought_position(
#         trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
#     )
#     assert isinstance(strategy, HpStrategy)

#     strategy, hp_list = await send_sell_orders_for_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await simulate_partial_fill_sell(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await simulate_cancel_sell_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )


# async def test_resend_sell_position_first_order_filled_partially(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     hp_list: List[Dict] = []
#     strategy, hp_list = await simulate_bought_position(
#         trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
#     )
#     assert isinstance(strategy, HpStrategy)

#     strategy, hp_list = await send_sell_orders_for_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await simulate_partial_fill_sell(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await simulate_cancel_sell_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await simulate_resend_sell_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )


# async def test_conditions_for_new_sell_order_confirmation(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     hp_list: List[Dict] = []
#     strategy, hp_list = await simulate_bought_position(
#         trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
#     )
#     assert isinstance(strategy, HpStrategy)

#     strategy, hp_list = await send_sell_orders_for_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_NEW,
#         symbol=strategy.buy.data.config.symbol_info.symbol,
#     )
#     assert strategy.conditions_for_new_order_confirmation()


# async def test_conditions_for_sell_order_cancellation(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     hp_list: List[Dict] = []
#     strategy, hp_list = await simulate_bought_position(
#         trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
#     )
#     assert isinstance(strategy, HpStrategy)

#     strategy, hp_list = await send_sell_orders_for_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_CANCELED,
#         symbol=strategy.buy.data.config.symbol_info.symbol,
#     )
#     assert strategy.conditions_for_order_cancellation()


# async def test_conditions_for_sell_order_expiration(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     hp_list: List[Dict] = []
#     strategy, hp_list = await simulate_bought_position(
#         trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
#     )
#     assert isinstance(strategy, HpStrategy)

#     strategy, hp_list = await send_sell_orders_for_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT, current_order_status=ORDER_STATUS_EXPIRED
#     )
#     assert strategy.conditions_for_order_expiration()


# async def test_send_sell_orders_for_partially_bought_position(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Simulate full order fill
#     strategy, hp_list = await simulate_first_buy_order_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445860
#     )

#     # Cancel partially bought position
#     strategy = await cancel_partially_bought_position_first_order_filled(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await send_sell_orders_for_partially_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )


# async def test_cancel_unfilled_sell_orders_for_partially_bought_position(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Simulate full order fill
#     strategy, hp_list = await simulate_first_buy_order_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445860
#     )

#     # Cancel partially bought position
#     strategy = await cancel_partially_bought_position_first_order_filled(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await send_sell_orders_for_partially_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await cancel_unfilled_sell_orders_for_partially_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )


# async def test_fill_orders_for_previously_partially_bought_position(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Simulate full order fill
#     strategy, hp_list = await simulate_first_buy_order_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445860
#     )

#     # Cancel partially bought position
#     strategy = await cancel_partially_bought_position_first_order_filled(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await send_sell_orders_for_partially_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await cancel_unfilled_sell_orders_for_partially_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await resend_part_bought_first_order_filled_with_sell_price(
#         strategy=strategy,
#         hp_gui=hp_gui,
#         hp_list=hp_list,
#     )

#     strategy, hp_list = await simulate_second_buy_order_fill(
#         strategy=strategy,
#         hp_gui=hp_gui,
#         hp_list=hp_list,
#         order_id=445864,
#         sell_price="4200",
#     )
#     strategy, hp_list = await simulate_third_buy_order_fill(
#         strategy=strategy,
#         hp_gui=hp_gui,
#         hp_list=hp_list,
#         order_id=445865,
#         sell_price="4200",
#     )


# async def test_sell_partially_partially_bought_position(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )
#     # Simulate full order fill
#     strategy, hp_list = await simulate_first_buy_order_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445860
#     )

#     # Cancel partially bought position
#     strategy = await cancel_partially_bought_position_first_order_filled(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await send_sell_orders_for_partially_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await sell_partially_partially_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )


# async def test_buy_partially_partially_sold_position(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Simulate full order fill
#     strategy, hp_list = await simulate_first_buy_order_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445860
#     )

#     # Cancel partially bought position
#     strategy = await cancel_partially_bought_position_first_order_filled(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await send_sell_orders_for_partially_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await sell_partially_partially_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Cancel Sell position
#     strategy, hp_list = await cancel_sell_position_part_bought_part_sold(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Reopen Buy position
#     strategy, hp_list = await reopen_buy_part_bought_part_sold(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Buy partially second order
#     strategy, hp_list = await simulate_second_buy_order_partial_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )


# async def test_cancel_buy_to_part_sold_part_bought(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Simulate full order fill
#     strategy, hp_list = await simulate_first_buy_order_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445860
#     )

#     # Cancel partially bought position
#     strategy = await cancel_partially_bought_position_first_order_filled(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await send_sell_orders_for_partially_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
#         order_id=445863,
#         last_executed_quantity=0.12,
#         last_executed_price=4200,
#         cumulative_filled_quantity=0.12,
#     )

#     assert strategy.state == State.SELLING
#     await strategy.process_order()  # type: ignore[attr-defined]

#     logger.info("Orders: %s", strategy.sell.orders)
#     assert strategy.sell.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
#     assert strategy.sell.orders[0].quantity == 0.24
#     assert strategy.sell.orders[0].realized_quantity == 0.12
#     assert strategy.state == State.SELLING
#     assert strategy.sell.data.state_info.state == State.PARTIALLY_SOLD
#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT

#     assert strategy.ui_queue.qsize() == 1
#     content = strategy.ui_queue.get_nowait()
#     logger.info("Content: %s", content)
#     assert isinstance(content, HPGuiDataSell)

#     state_info = content.data.state_info
#     assert isinstance(state_info, StateInfo)

#     assert state_info.next_monitor_time
#     assert state_info.state == State.PARTIALLY_SOLD
#     assert state_info.side == PositionSide.SHORT
#     assert state_info.ui_state == UiState.OPEN
#     assert state_info.completeness == 0.5

#     assert strategy.ui_queue.qsize() == 0

#     hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

#     assert len(hp_list) == 1
#     item = hp_list[0]
#     assert item["hp_id"] == "1000"
#     assert item["asset"] == "BTC"
#     assert item["buy_price"] == "1400.0"
#     assert item["quantity"] == "0.12"
#     assert item["quantity_usdt"] == "168.0"
#     assert item["sell_price"] == "4200"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "SELLING"

#     logger.info("HP List after the update: %s", hp_list)

#     # Cancel Sell position
#     strategy, hp_list = await cancel_sell_position_part_bought_part_sold(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Reopen Buy position
#     strategy, hp_list = await reopen_buy_part_bought_part_sold(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Buy partially second order
#     strategy, hp_list = await simulate_second_buy_order_partial_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Cancel Buy orders
#     strategy.buy.data.state_info.stagnation_counter = (
#         strategy.buy.data.state_info.stagnation_limit
#     )

#     strategy.buy.data.state_info.generate_next_monitor_time()

#     assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
#     strategy.ticker_update = TickerUpdate(last_price=1428.0)
#     assert (
#         strategy.conditions_for_cancelling_partially_sold_and_bought_orders_buy_position()
#     )

#     await strategy.process_ticker()  # type: ignore[attr-defined]

#     assert strategy.state == State.PART_SOLD_PART_BOUGHT
#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
#     assert strategy.sell.data.state_info.state == State.PARTIALLY_SOLD

#     assert strategy.ui_queue.qsize() == 1
#     content = strategy.ui_queue.get_nowait()
#     logger.info("Content: %s", content)
#     assert isinstance(content, HPGuiDataBuy)

#     state_info = content.data.state_info
#     assert isinstance(state_info, StateInfo)

#     assert state_info.next_monitor_time
#     assert state_info.state == State.PARTIALLY_BOUGHT
#     assert state_info.side == PositionSide.LONG
#     assert state_info.ui_state == UiState.STAGNATED
#     assert state_info.completeness == 0.45

#     assert strategy.ui_queue.qsize() == 0

#     hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

#     assert len(hp_list) == 1
#     item = hp_list[0]
#     assert item["hp_id"] == "1000"
#     assert item["asset"] == "BTC"
#     assert item["buy_price"] == "1292.31"
#     assert item["quantity"] == "0.26"
#     assert item["quantity_usdt"] == "336.0"
#     assert item["sell_price"] == "4200"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "PART_SOLD_PART_BOUGHT"

#     logger.info("HP List after the update: %s", hp_list)


# async def test_buy_fully_partially_sold_position(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Simulate full order fill
#     strategy, hp_list = await simulate_first_buy_order_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445860
#     )

#     # Cancel partially bought position
#     strategy = await cancel_partially_bought_position_first_order_filled(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await send_sell_orders_for_partially_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
#         order_id=445863,
#         last_executed_quantity=0.12,
#         last_executed_price=4200,
#         cumulative_filled_quantity=0.12,
#     )

#     assert strategy.state == State.SELLING
#     await strategy.process_order()  # type: ignore[attr-defined]

#     logger.info("Orders: %s", strategy.sell.orders)
#     assert strategy.sell.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
#     assert strategy.sell.orders[0].quantity == 0.24
#     assert strategy.sell.orders[0].realized_quantity == 0.12
#     assert strategy.state == State.SELLING
#     assert strategy.sell.data.state_info.state == State.PARTIALLY_SOLD
#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT

#     assert strategy.ui_queue.qsize() == 1
#     content = strategy.ui_queue.get_nowait()
#     logger.info("Content: %s", content)
#     assert isinstance(content, HPGuiDataSell)

#     state_info = content.data.state_info
#     assert isinstance(state_info, StateInfo)

#     assert state_info.next_monitor_time
#     assert state_info.state == State.PARTIALLY_SOLD
#     assert state_info.side == PositionSide.SHORT
#     assert state_info.ui_state == UiState.OPEN
#     assert state_info.completeness == 0.5

#     assert strategy.ui_queue.qsize() == 0

#     hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

#     assert len(hp_list) == 1
#     item = hp_list[0]
#     assert item["hp_id"] == "1000"
#     assert item["asset"] == "BTC"
#     assert item["buy_price"] == "1400.0"
#     assert item["quantity"] == "0.12"
#     assert item["quantity_usdt"] == "168.0"
#     assert item["sell_price"] == "4200"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "SELLING"

#     logger.info("HP List after the update: %s", hp_list)

#     # Cancel Sell position
#     strategy, hp_list = await cancel_sell_position_part_bought_part_sold(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Reopen Buy position
#     strategy, hp_list = await reopen_buy_part_bought_part_sold(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     (
#         strategy,
#         hp_list,
#     ) = await simulate_second_buy_order_fill_after_selling_half_of_first_order(
#         strategy=strategy,
#         hp_gui=hp_gui,
#         hp_list=hp_list,
#         order_id=445864,
#         sell_price="4200",
#     )
#     (
#         strategy,
#         hp_list,
#     ) = await simulate_third_buy_order_fill_after_selling_half_of_first_order(
#         strategy=strategy,
#         hp_gui=hp_gui,
#         hp_list=hp_list,
#         order_id=445865,
#         sell_price="4200",
#     )


# async def test_sell_fully_partially_bought_position(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Simulate full order fill
#     strategy, hp_list = await simulate_first_buy_order_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445860
#     )

#     # Cancel partially bought position
#     strategy = await cancel_partially_bought_position_first_order_filled(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await send_sell_orders_for_partially_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_FILLED,
#         order_id=445863,
#         last_executed_quantity=0.24,
#         last_executed_price=4200,
#         cumulative_filled_quantity=0.24,
#     )
#     await strategy.process_order()  # type: ignore[attr-defined]

#     logger.info("Orders: %s", strategy.sell.orders)
#     assert strategy.sell.orders[0].status == ORDER_STATUS_FILLED
#     assert strategy.sell.orders[0].quantity == 0.24
#     assert strategy.sell.orders[0].realized_quantity == 0.24
#     assert strategy.state == State.SELLING
#     assert strategy.sell.data.state_info.state == State.SOLD
#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT

#     assert strategy.ui_queue.qsize() == 1

#     content = strategy.ui_queue.get_nowait()
#     logger.info("Content: %s", content)
#     assert isinstance(content, HPGuiDataSell)
#     state_info = content.data.state_info
#     assert isinstance(state_info, StateInfo)

#     assert state_info.state == State.SOLD
#     assert state_info.stagnation_counter == 0
#     assert state_info.stagnation_limit == 8
#     assert state_info.side == PositionSide.SHORT
#     assert state_info.next_monitor_time

#     assert state_info.ui_state == UiState.CLOSED
#     assert state_info.completeness == 1.0

#     hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

#     assert len(hp_list) == 1
#     item = hp_list[0]
#     assert item["hp_id"] == "1000"
#     assert item["asset"] == "BTC"
#     assert item["buy_price"] == "1400.0"
#     assert item["quantity"] == "0.0"
#     assert item["quantity_usdt"] == "0.0"
#     assert item["sell_price"] == "4200"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "SELLING"

#     logger.info("HP List after the update: %s", hp_list)

#     assert strategy.ui_queue.qsize() == 0

#     assert strategy.worker_queue.qsize() == 1
#     event = strategy.worker_queue.get_nowait()

#     assert isinstance(event, Event)
#     assert event.name == EventName.SIGNAL
#     assert isinstance(event.content, SignalUpdate)

#     strategy.signal_update = event.content

#     assert strategy.conditions_for_closing_sold_position_which_is_part_bought()

#     await strategy.process_signal()  # type: ignore[attr-defined]

#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
#     assert strategy.sell.data.state_info.state == State.SOLD
#     assert strategy.state == State.SOLD_PART_BOUGHT

#     assert strategy.ui_queue.qsize() == 1

#     content = strategy.ui_queue.get_nowait()
#     logger.info("Content: %s", content)
#     assert isinstance(content, HPGuiDataSell)
#     state_info = content.data.state_info
#     assert isinstance(state_info, StateInfo)

#     assert state_info.state == State.SOLD
#     assert state_info.stagnation_counter == 0
#     assert state_info.stagnation_limit == 8
#     assert state_info.side == PositionSide.SHORT
#     assert state_info.next_monitor_time

#     assert state_info.ui_state == UiState.CLOSED
#     assert state_info.completeness == 0.28

#     hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

#     assert len(hp_list) == 1
#     item = hp_list[0]
#     assert item["hp_id"] == "1000"
#     assert item["asset"] == "BTC"
#     assert item["buy_price"] == "1400.0"
#     assert item["quantity"] == "0.0"
#     assert item["quantity_usdt"] == "0.0"
#     assert item["sell_price"] == "4200"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "SOLD_PART_BOUGHT"

#     logger.info("HP List after the update: %s", hp_list)

#     assert strategy.ui_queue.qsize() == 0


# async def test_buy_fully_partially_bought_position_when_sold_position(
#     trading_system_factory, hp_gui: HpFront
# ) -> None:
#     # Path 0: Default buy position
#     hp_list: List[Dict] = []
#     strategy: HpStrategy = get_default_buy_position(trading_system_factory)
#     assert isinstance(strategy, HpStrategy)

#     strategy, hp_list = assert_default_buy_position_data(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Path 1: Send buy orders

#     strategy, hp_list = await move_to_buy_position_active(
#         strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
#     )

#     # Simulate full order fill
#     strategy, hp_list = await simulate_first_buy_order_fill(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=445860
#     )

#     # Cancel partially bought position
#     strategy = await cancel_partially_bought_position_first_order_filled(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await send_sell_orders_for_partially_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy.execution_report = ExecutionReport(
#         order_type=ORDER_TYPE_LIMIT,
#         current_order_status=ORDER_STATUS_FILLED,
#         order_id=445863,
#         last_executed_quantity=0.24,
#         last_executed_price=4200,
#         cumulative_filled_quantity=0.24,
#     )
#     await strategy.process_order()  # type: ignore[attr-defined]

#     logger.info("Orders: %s", strategy.sell.orders)
#     assert strategy.sell.orders[0].status == ORDER_STATUS_FILLED
#     assert strategy.sell.orders[0].quantity == 0.24
#     assert strategy.sell.orders[0].realized_quantity == 0.24
#     assert strategy.state == State.SELLING
#     assert strategy.sell.data.state_info.state == State.SOLD
#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT

#     assert strategy.ui_queue.qsize() == 1

#     content = strategy.ui_queue.get_nowait()
#     logger.info("Content: %s", content)
#     assert isinstance(content, HPGuiDataSell)
#     state_info = content.data.state_info
#     assert isinstance(state_info, StateInfo)

#     assert state_info.state == State.SOLD
#     assert state_info.stagnation_counter == 0
#     assert state_info.stagnation_limit == 8
#     assert state_info.side == PositionSide.SHORT
#     assert state_info.next_monitor_time

#     assert state_info.ui_state == UiState.CLOSED
#     assert state_info.completeness == 1.0

#     hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

#     assert len(hp_list) == 1
#     item = hp_list[0]
#     assert item["hp_id"] == "1000"
#     assert item["asset"] == "BTC"
#     assert item["buy_price"] == "1400.0"
#     assert item["quantity"] == "0.0"
#     assert item["quantity_usdt"] == "0.0"
#     assert item["sell_price"] == "4200"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "SELLING"

#     logger.info("HP List after the update: %s", hp_list)

#     assert strategy.ui_queue.qsize() == 0

#     assert strategy.worker_queue.qsize() == 1
#     event = strategy.worker_queue.get_nowait()

#     assert isinstance(event, Event)
#     assert event.name == EventName.SIGNAL
#     assert isinstance(event.content, SignalUpdate)

#     strategy.signal_update = event.content

#     assert strategy.conditions_for_closing_sold_position_which_is_part_bought()

#     await strategy.process_signal()  # type: ignore[attr-defined]

#     assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
#     assert strategy.sell.data.state_info.state == State.SOLD
#     assert strategy.state == State.SOLD_PART_BOUGHT

#     assert strategy.ui_queue.qsize() == 1

#     content = strategy.ui_queue.get_nowait()
#     logger.info("Content: %s", content)
#     assert isinstance(content, HPGuiDataSell)
#     state_info = content.data.state_info
#     assert isinstance(state_info, StateInfo)

#     assert state_info.state == State.SOLD
#     assert state_info.stagnation_counter == 0
#     assert state_info.stagnation_limit == 8
#     assert state_info.side == PositionSide.SHORT
#     assert state_info.next_monitor_time

#     assert state_info.ui_state == UiState.CLOSED
#     assert state_info.completeness == 0.28

#     hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

#     assert len(hp_list) == 1
#     item = hp_list[0]
#     assert item["hp_id"] == "1000"
#     assert item["asset"] == "BTC"
#     assert item["buy_price"] == "1400.0"
#     assert item["quantity"] == "0.0"
#     assert item["quantity_usdt"] == "0.0"
#     assert item["sell_price"] == "4200"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "SOLD_PART_BOUGHT"

#     logger.info("HP List after the update: %s", hp_list)

#     assert strategy.ui_queue.qsize() == 0

#     # Reopen Buy position
#     strategy, hp_list = await reopen_buy_part_bought_sold(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     (
#         strategy,
#         hp_list,
#     ) = await simulate_second_buy_order_fill_after_selling_first_order(
#         strategy=strategy,
#         hp_gui=hp_gui,
#         hp_list=hp_list,
#         order_id=445864,
#         sell_price="4200",
#     )
#     (
#         strategy,
#         hp_list,
#     ) = await simulate_third_buy_order_fill_after_selling_first_order(
#         strategy=strategy,
#         hp_gui=hp_gui,
#         hp_list=hp_list,
#         order_id=445865,
#         sell_price="4200",
#     )
