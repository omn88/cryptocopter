import asyncio
import logging
from typing import Dict, List
from binance.enums import (
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_NEW,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_EXPIRED,
)
from src.gui.identifiers import HPGuiDataBuy, HPGuiDataSell
from src.identifiers import (
    Event,
    EventName,
    ExecutionReport,
    Signal,
    SignalUpdate,
    State,
    StateInfo,
    TickerUpdate,
    UiState,
    PositionSide,
)
from src.strategies.hp_manager.hp_manager import HpStrategy
from src.gui.hp_manager.hpfront import HpFront
from tests.helpers import get_new_orders
from tests.strategies.hp_manager_helpers import (
    assert_default_buy_position_data,
    cancel_partially_bought_position_first_order_filled,
    cancel_partially_bought_position_first_order_filled_partially,
    cancel_sell_position_part_bought_part_sold,
    cancel_unfilled_sell_orders_for_partially_bought_position,
    cancel_untouched_buy_position,
    cancel_untouched_sell_position,
    get_default_buy_position,
    move_to_buy_position_active,
    reopen_buy_part_bought_part_sold,
    reopen_buy_part_bought_sold,
    resend_part_bought_first_order_filled,
    resend_part_bought_first_order_filled_partially,
    resend_part_bought_first_order_filled_with_sell_price,
    sell_partially_partially_bought_position,
    send_sell_order_for_bought_position,
    send_sell_order_for_partially_bought_position,
    simulate_bought_position,
    simulate_cancel_sell_position,
    simulate_first_buy_order_fill,
    simulate_partial_fill,
    simulate_partial_fill_sell,
    simulate_resend_sell_position,
    simulate_second_buy_order_fill,
    simulate_second_buy_order_fill_after_selling_first_order,
    simulate_second_buy_order_fill_after_selling_half_of_first_order,
    simulate_second_buy_order_fill_with_sell_price,
    simulate_second_buy_order_partial_fill,
    simulate_third_buy_order_fill,
    simulate_third_buy_order_fill_after_selling_first_order,
    simulate_third_buy_order_fill_after_selling_half_of_first_order,
    simulate_third_buy_order_fill_with_sell_price,
    prepare_hp_update_for_collapse,
    wait_for_condition,
)

logger = logging.getLogger("test_hp_manager")


async def test_default_position(hp_gui: HpFront, trading_system_factory) -> None:
    """
    This test purpose is to instantiate basic buy position and assert on
    the default values

    Path 0
    """
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)
    assert isinstance(strategy, HpStrategy)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_default_position_send_orders(
    hp_gui: HpFront, trading_system_factory
) -> None:
    """
    Path 1
    """

    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_cancel_default_position_untouched(
    hp_gui: HpFront, trading_system_factory
) -> None:
    """
    This test purpose is to instantiate basic buy position then trigger
    the conditions with which the position will be cancelled untouched and the states
    will get back to State.NEW
    Path 1 -> 2 -> 1
    """

    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await cancel_untouched_buy_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_cancel_default_position_untouched_then_resend_orders(
    trading_system_factory, hp_gui: HpFront
) -> None:
    """
    This test purpose is to instantiate basic buy position then trigger
    the conditions with which the position will be cancelled untouched and the states
    will get back to State.NEW
    """

    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await cancel_untouched_buy_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Resend buy orders

    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_default_position_first_order_filled_partially(
    trading_system_factory, hp_gui: HpFront
) -> None:
    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    # Simulate partial fill
    strategy = await simulate_partial_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_default_position_first_order_filled_partially_then_cancel(
    trading_system_factory, hp_gui: HpFront
) -> None:
    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    # Simulate partial fill
    strategy = await simulate_partial_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Cancel position
    strategy = await cancel_partially_bought_position_first_order_filled_partially(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_default_position_first_order_filled(
    trading_system_factory, hp_gui: HpFront
) -> None:
    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    # Simulate full order fill
    strategy, hp_list = await simulate_first_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=132729677
    )


async def test_default_position_first_order_filled_then_cancel(
    trading_system_factory, hp_gui: HpFront
) -> None:
    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    # Simulate full order fill
    strategy, hp_list = await simulate_first_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=132729677
    )

    # Cancel partially bought position
    strategy = await cancel_partially_bought_position_first_order_filled(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_default_position_all_buy_orders_filled(
    trading_system_factory, hp_gui: HpFront
) -> None:
    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    # Simulate full order fill
    strategy, hp_list = await simulate_first_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=132729677
    )

    strategy, hp_list = await simulate_second_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=95830862
    )
    strategy, hp_list = await simulate_third_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=40613711
    )


async def test_conditions_for_new_buy_order_confirmation(
    hp_gui: HpFront, trading_system_factory
) -> None:
    """
    Path 1
    """

    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_NEW,
        symbol=strategy.buy.data.config.symbol.name,
    )
    assert strategy.conditions_for_new_order_confirmation()


async def test_conditions_for_buy_order_cancellation(
    hp_gui: HpFront, trading_system_factory
) -> None:
    """
    Path 1
    """

    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_CANCELED,
        symbol=strategy.buy.data.config.symbol.name,
    )
    assert strategy.conditions_for_order_cancellation()


async def test_conditions_for_buy_order_expiration(
    hp_gui: HpFront, trading_system_factory
) -> None:
    """
    Path 1
    """

    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT, current_order_status=ORDER_STATUS_EXPIRED
    )
    assert strategy.conditions_for_order_expiration()


async def test_default_position_first_order_filled_partially_then_cancel_then_resend(
    trading_system_factory, hp_gui: HpFront
) -> None:
    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    # Simulate partial fill
    strategy = await simulate_partial_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Cancel position
    strategy = await cancel_partially_bought_position_first_order_filled_partially(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Reopen position
    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )

    strategy = await resend_part_bought_first_order_filled_partially(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_default_position_first_order_filled_then_cancel_then_resend(
    trading_system_factory, hp_gui: HpFront
) -> None:
    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    # Simulate full order fill
    strategy, hp_list = await simulate_first_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=132729677
    )

    # Cancel partially bought position
    strategy = await cancel_partially_bought_position_first_order_filled(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Resend buy orders after 1st order was filled
    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )

    strategy, hp_list = await resend_part_bought_first_order_filled(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_send_sell_order_for_bought_position(
    trading_system_factory, hp_gui: HpFront
) -> None:
    hp_list: List[Dict] = []
    strategy, hp_list = await simulate_bought_position(
        trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
    )
    assert isinstance(strategy, HpStrategy)

    logger.info("Strategy state before sending sell order: %s", strategy.state)

    logger.info("Strategy sell current position: %s", strategy.sell.current_position)

    strategy, hp_list = await send_sell_order_for_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_cancel_unfilled_sell_orders(
    trading_system_factory, hp_gui: HpFront
) -> None:
    hp_list: List[Dict] = []
    strategy, hp_list = await simulate_bought_position(
        trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
    )
    assert isinstance(strategy, HpStrategy)

    strategy, hp_list = await send_sell_order_for_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy = await cancel_untouched_sell_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_resend_unfilled_sell_orders(
    trading_system_factory, hp_gui: HpFront
) -> None:
    hp_list: List[Dict] = []
    strategy, hp_list = await simulate_bought_position(
        trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
    )
    assert isinstance(strategy, HpStrategy)

    strategy, hp_list = await send_sell_order_for_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy = await cancel_untouched_sell_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    assert strategy.calculate_trigger_send_orders_price_sell() == 4032
    strategy.ticker_update = TickerUpdate(last_price=4032.0, symbol="BTCUSDC")
    assert strategy.conditions_for_sending_sell_orders()

    strategy.client.create_order.side_effect = get_new_orders(
        [strategy.sell.current_position.sell_order]
    )

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.SELLING
    assert strategy.sell.current_position.state_info.state == State.NEW

    assert strategy.sell.current_position.sell_order.quantity == 0.85
    assert strategy.sell.current_position.sell_order.realized_quantity == 0.0

    assert strategy.sell.current_position.sell_order.status == ORDER_STATUS_NEW

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.NEW
    assert state_info.side == PositionSide.SHORT
    assert state_info.ui_state == UiState.OPEN
    assert state_info.completeness == 0.00

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 3
    parent = next(
        item
        for item in hp_list
        if item["hp_id"] == "1000" and not item.get("is_child", False)
    )
    assert parent["hp_id"] == "1000"
    assert parent["coin"] == "BTCUSD"
    assert parent["buy_price"] == "1178.82"
    assert parent["quantity"] == "0.85"
    assert parent["sell_price"] == "4200.0"
    assert parent["expected_return"] == "2568.0"
    assert parent["current_price"] == "0.0"
    assert parent["net"] == "0.0"
    assert parent["net_percent"] == "0.0"
    # Note: parent doesn't have state field, only children do

    logger.info("HP List after the update: %s", hp_list)


async def test_sell_position_first_order_filled_partially(
    trading_system_factory, hp_gui: HpFront
) -> None:
    hp_list: List[Dict] = []
    strategy, hp_list = await simulate_bought_position(
        trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
    )
    assert isinstance(strategy, HpStrategy)

    strategy, hp_list = await send_sell_order_for_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await simulate_partial_fill_sell(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_sell_position_first_order_filled(
    trading_system_factory, hp_gui: HpFront
) -> None:
    hp_list: List[Dict] = []
    strategy, hp_list = await simulate_bought_position(
        trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
    )
    assert isinstance(strategy, HpStrategy)

    strategy, hp_list = await send_sell_order_for_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Simulate first order fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=3570,
        last_executed_quantity=0.85,
        last_executed_price=4200.0,
        cumulative_filled_quantity=0.85,
    )
    await strategy.process_order()  # type: ignore[attr-defined]

    logger.info("Orders: %s", strategy.sell.current_position.sell_order)
    assert strategy.sell.current_position.sell_order.status == ORDER_STATUS_FILLED
    assert strategy.state == State.SELLING
    assert strategy.sell.current_position.state_info.state == State.SOLD

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.SOLD
    assert state_info.side == PositionSide.SHORT
    assert state_info.ui_state == UiState.CLOSED
    assert state_info.completeness == 1.00

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 3  # parent + buy child + sell child (container approach)
    # Find parent container
    parent_item = next(
        item
        for item in hp_list
        if item["hp_id"] == "1000" and not item.get("is_child", False)
    )
    assert parent_item["coin"] == "BTCUSD"
    assert parent_item["buy_price"] == "1178.82"
    assert (
        parent_item["quantity"] == "0.85"
    )  # Shows total bought amount, not net remaining
    assert parent_item["quantity_usd"] == "1002.0"
    assert parent_item["sell_price"] == "4200.0"
    assert parent_item["expected_return"] == "2568.0"
    assert parent_item["current_price"] == "0.0"
    assert parent_item["net"] == "0.0"
    assert parent_item["net_percent"] == "0.0"
    assert parent_item["state"] == "SELLING"

    logger.info("HP List after the update: %s", hp_list)

    assert strategy.worker_queue.qsize() == 1
    event = strategy.worker_queue.get_nowait()

    assert isinstance(event, Event)
    assert event.name == EventName.SIGNAL
    assert isinstance(event.content, SignalUpdate)

    strategy.signal_update = event.content

    await strategy.process_signal()  # type: ignore[attr-defined]

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)
    assert state_info.state == State.SOLD
    assert state_info.side == PositionSide.SHORT
    assert state_info.ui_state == UiState.CLOSED
    assert state_info.completeness == 1.00

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 3
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["coin"] == "BTCUSD"
    assert item["buy_price"] == "1178.82"
    assert item["quantity"] == "0.85"
    assert item["quantity_usd"] == "1002.0"
    assert item["sell_price"] == "4200.0"
    assert item["expected_return"] == "2568.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "SOLD"

    logger.info("HP List after the update: %s", hp_list)


async def test_cancel_sell_position_first_order_filled_partially(
    trading_system_factory, hp_gui: HpFront
) -> None:
    hp_list: List[Dict] = []
    strategy, hp_list = await simulate_bought_position(
        trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
    )
    assert isinstance(strategy, HpStrategy)

    strategy, hp_list = await send_sell_order_for_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await simulate_partial_fill_sell(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await simulate_cancel_sell_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_resend_sell_position_first_order_filled_partially(
    trading_system_factory, hp_gui: HpFront
) -> None:
    hp_list: List[Dict] = []
    strategy, hp_list = await simulate_bought_position(
        trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
    )
    assert isinstance(strategy, HpStrategy)

    strategy, hp_list = await send_sell_order_for_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await simulate_partial_fill_sell(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await simulate_cancel_sell_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await simulate_resend_sell_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_conditions_for_new_sell_order_confirmation(
    trading_system_factory, hp_gui: HpFront
) -> None:
    hp_list: List[Dict] = []
    strategy, hp_list = await simulate_bought_position(
        trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
    )
    assert isinstance(strategy, HpStrategy)

    strategy, hp_list = await send_sell_order_for_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_NEW,
        symbol=strategy.buy.data.config.symbol.name,
    )
    assert strategy.conditions_for_new_order_confirmation()


async def test_conditions_for_sell_order_cancellation(
    trading_system_factory, hp_gui: HpFront
) -> None:
    hp_list: List[Dict] = []
    strategy, hp_list = await simulate_bought_position(
        trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
    )
    assert isinstance(strategy, HpStrategy)

    strategy, hp_list = await send_sell_order_for_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_CANCELED,
        symbol=strategy.buy.data.config.symbol.name,
    )
    assert strategy.conditions_for_order_cancellation()


async def test_conditions_for_sell_order_expiration(
    trading_system_factory, hp_gui: HpFront
) -> None:
    hp_list: List[Dict] = []
    strategy, hp_list = await simulate_bought_position(
        trading_system_factory=trading_system_factory, hp_gui=hp_gui, hp_list=hp_list
    )
    assert isinstance(strategy, HpStrategy)

    strategy, hp_list = await send_sell_order_for_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT, current_order_status=ORDER_STATUS_EXPIRED
    )
    assert strategy.conditions_for_order_expiration()


async def test_send_sell_order_for_partially_bought_position(
    trading_system_factory, hp_gui: HpFront
) -> None:
    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    # Simulate full order fill
    strategy, hp_list = await simulate_first_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=132729677
    )

    # Cancel partially bought position
    strategy = await cancel_partially_bought_position_first_order_filled(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await send_sell_order_for_partially_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_cancel_unfilled_sell_orders_for_partially_bought_position(
    trading_system_factory, hp_gui: HpFront
) -> None:
    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    # Simulate full order fill
    strategy, hp_list = await simulate_first_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=132729677
    )

    # Cancel partially bought position
    strategy = await cancel_partially_bought_position_first_order_filled(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await send_sell_order_for_partially_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await cancel_unfilled_sell_orders_for_partially_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_fill_orders_for_previously_partially_bought_position(
    trading_system_factory, hp_gui: HpFront
) -> None:
    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    # Simulate full order fill
    strategy, hp_list = await simulate_first_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=132729677
    )

    # Cancel partially bought position
    strategy = await cancel_partially_bought_position_first_order_filled(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await send_sell_order_for_partially_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await cancel_unfilled_sell_orders_for_partially_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await resend_part_bought_first_order_filled_with_sell_price(
        strategy=strategy,
        hp_gui=hp_gui,
        hp_list=hp_list,
    )

    strategy, hp_list = await simulate_second_buy_order_fill_with_sell_price(
        strategy=strategy,
        hp_gui=hp_gui,
        hp_list=hp_list,
        order_id=95830862,
    )
    strategy, hp_list = await simulate_third_buy_order_fill_with_sell_price(
        strategy=strategy,
        hp_gui=hp_gui,
        hp_list=hp_list,
        order_id=40613711,
    )


async def test_sell_partially_partially_bought_position(
    trading_system_factory, hp_gui: HpFront
) -> None:
    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )
    # Simulate full order fill
    strategy, hp_list = await simulate_first_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=132729677
    )

    # Cancel partially bought position
    strategy = await cancel_partially_bought_position_first_order_filled(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await send_sell_order_for_partially_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await sell_partially_partially_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_buy_partially_partially_sold_position(
    trading_system_factory, hp_gui: HpFront
) -> None:
    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    # Simulate full order fill
    strategy, hp_list = await simulate_first_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=132729677
    )

    # Cancel partially bought position
    strategy = await cancel_partially_bought_position_first_order_filled(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await send_sell_order_for_partially_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await sell_partially_partially_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Cancel Sell position
    strategy, hp_list = await cancel_sell_position_part_bought_part_sold(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Reopen Buy position
    strategy.client.create_order.side_effect = get_new_orders(strategy.buy.orders)
    strategy, hp_list = await reopen_buy_part_bought_part_sold(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Buy partially second order
    strategy, hp_list = await simulate_second_buy_order_partial_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )


async def test_cancel_buy_to_part_sold_part_bought(
    trading_system_factory, hp_gui: HpFront
) -> None:
    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    # Simulate full order fill
    strategy, hp_list = await simulate_first_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=132729677
    )

    # Cancel partially bought position
    strategy = await cancel_partially_bought_position_first_order_filled(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await send_sell_order_for_partially_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=1008,
        last_executed_quantity=0.12,
        last_executed_price=4200,
        cumulative_filled_quantity=0.12,
    )

    assert strategy.state == State.SELLING
    await strategy.process_order()  # type: ignore[attr-defined]

    logger.info("Orders: %s", strategy.sell.current_position.sell_order)
    assert (
        strategy.sell.current_position.sell_order.status
        == ORDER_STATUS_PARTIALLY_FILLED
    )
    assert strategy.sell.current_position.sell_order.quantity == 0.24
    assert strategy.sell.current_position.sell_order.realized_quantity == 0.12
    assert strategy.state == State.SELLING
    assert strategy.sell.current_position.state_info.state == State.PARTIALLY_SOLD
    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_SOLD
    assert state_info.side == PositionSide.SHORT
    assert state_info.ui_state == UiState.OPEN
    assert state_info.completeness == 0.5

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 3
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["coin"] == "BTCUSD"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.24"
    assert item["quantity_usd"] == "336.0"  # Parent shows 0 for USD quantity
    assert item["sell_price"] == "4200.0"
    assert item["expected_return"] == "672.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "SELLING"

    logger.info("HP List after the update: %s", hp_list)

    # Cancel Sell position
    strategy, hp_list = await cancel_sell_position_part_bought_part_sold(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Reopen Buy position
    strategy.client.create_order.side_effect = get_new_orders(strategy.buy.orders)
    strategy, hp_list = await reopen_buy_part_bought_part_sold(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Buy partially second order
    strategy, hp_list = await simulate_second_buy_order_partial_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    assert strategy.buy.orders_cancel_price == 1224.0
    strategy.ticker_update = TickerUpdate(last_price=1224.0, symbol="BTCUSDC")
    assert (
        strategy.conditions_for_cancelling_partially_sold_and_bought_orders_buy_position()
    )

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.PART_SOLD_PART_BOUGHT
    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.sell.current_position.state_info.state == State.PARTIALLY_SOLD

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataBuy)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.side == PositionSide.LONG
    assert state_info.ui_state == UiState.STAGNATED
    assert state_info.completeness == 0.45

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 3
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["coin"] == "BTCUSD"
    assert item["buy_price"] == "1326.32"
    assert item["quantity"] == "0.38"
    assert item["quantity_usd"] == "504.0"  # Parent shows 0 for USD quantity
    assert item["sell_price"] == "4200.0"
    assert (
        item["expected_return"] == "1092.0"
    )  # Parent shows original sell value, not updated
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "PART_SOLD_PART_BOUGHT"

    logger.info("HP List after the update: %s", hp_list)


async def test_buy_fully_partially_sold_position(
    trading_system_factory, hp_gui: HpFront
) -> None:
    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    # Simulate full order fill
    strategy, hp_list = await simulate_first_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=132729677
    )

    # Cancel partially bought position
    strategy = await cancel_partially_bought_position_first_order_filled(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await send_sell_order_for_partially_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=1008,
        last_executed_quantity=0.12,
        last_executed_price=4200,
        cumulative_filled_quantity=0.12,
    )

    assert strategy.state == State.SELLING
    await strategy.process_order()  # type: ignore[attr-defined]

    logger.info("Orders: %s", strategy.sell.current_position.sell_order)
    assert (
        strategy.sell.current_position.sell_order.status
        == ORDER_STATUS_PARTIALLY_FILLED
    )
    assert strategy.sell.current_position.sell_order.quantity == 0.24
    assert strategy.sell.current_position.sell_order.realized_quantity == 0.12
    assert strategy.state == State.SELLING
    assert strategy.sell.current_position.state_info.state == State.PARTIALLY_SOLD
    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT

    assert strategy.ui_queue.qsize() == 1
    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)

    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_SOLD
    assert state_info.side == PositionSide.SHORT
    assert state_info.ui_state == UiState.OPEN
    assert state_info.completeness == 0.5

    assert strategy.ui_queue.qsize() == 0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 3  # Parent + BUY child + SELL child
    # Parent item (aggregated view)
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["coin"] == "BTCUSD"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.24"
    assert item["quantity_usd"] == "336.0"  # Parent shows aggregated USD
    assert item["sell_price"] == "4200.0"
    assert item["expected_return"] == "672.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "SELLING"

    logger.info("HP List after the update: %s", hp_list)

    # Cancel Sell position
    strategy, hp_list = await cancel_sell_position_part_bought_part_sold(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Reopen Buy position
    strategy.client.create_order.side_effect = get_new_orders(strategy.buy.orders)
    strategy, hp_list = await reopen_buy_part_bought_part_sold(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    (
        strategy,
        hp_list,
    ) = await simulate_second_buy_order_fill_after_selling_half_of_first_order(
        strategy=strategy,
        hp_gui=hp_gui,
        hp_list=hp_list,
        order_id=95830862,
    )
    (
        strategy,
        hp_list,
    ) = await simulate_third_buy_order_fill_after_selling_half_of_first_order(
        strategy=strategy,
        hp_gui=hp_gui,
        hp_list=hp_list,
        order_id=40613711,
    )


async def test_sell_fully_partially_bought_position(
    trading_system_factory, hp_gui: HpFront
) -> None:
    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    # Simulate full order fill
    strategy, hp_list = await simulate_first_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=132729677
    )

    # Cancel partially bought position
    strategy = await cancel_partially_bought_position_first_order_filled(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await send_sell_order_for_partially_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=1008,
        last_executed_quantity=0.24,
        last_executed_price=4200,
        cumulative_filled_quantity=0.24,
    )
    await strategy.process_order()  # type: ignore[attr-defined]

    logger.info("Orders: %s", strategy.sell.current_position.sell_order)
    assert strategy.sell.current_position.sell_order.status == ORDER_STATUS_FILLED
    assert strategy.sell.current_position.sell_order.quantity == 0.24
    assert strategy.sell.current_position.sell_order.realized_quantity == 0.24
    assert strategy.state == State.SELLING
    assert strategy.sell.current_position.state_info.state == State.SOLD
    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT

    assert strategy.ui_queue.qsize() == 1

    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)
    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.SOLD
    assert state_info.side == PositionSide.SHORT

    assert state_info.ui_state == UiState.CLOSED
    assert state_info.completeness == 1.0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 3  # Parent + BUY child + SELL child
    # Parent item (aggregated view)
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["coin"] == "BTCUSD"
    assert item["buy_price"] == "1400.0"
    assert (
        item["quantity"] == "0.24"
    )  # Parent shows net remaining quantity (bought - sold = 0.24 - 0.24 = 0.0 when fully sold)
    assert item["quantity_usd"] == "336.0"  # Parent shows aggregated USD
    assert item["sell_price"] == "4200.0"
    assert item["expected_return"] == "672.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "SELLING"

    logger.info("HP List after the update: %s", hp_list)

    assert strategy.ui_queue.qsize() == 0

    assert strategy.worker_queue.qsize() == 1
    event = strategy.worker_queue.get_nowait()

    assert isinstance(event, Event)
    assert event.name == EventName.SIGNAL
    assert isinstance(event.content, SignalUpdate)

    strategy.signal_update = event.content

    assert strategy.conditions_for_closing_sold_position_which_is_part_bought()

    await strategy.process_signal()  # type: ignore[attr-defined]

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.sell.current_position.state_info.state == State.SOLD
    assert strategy.state == State.SOLD_PART_BOUGHT

    assert strategy.ui_queue.qsize() == 1

    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)
    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.SOLD
    assert state_info.side == PositionSide.SHORT

    assert state_info.ui_state == UiState.CLOSED
    assert state_info.completeness == 1.0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    assert len(hp_list) == 3
    item = hp_list[0]
    assert item["hp_id"] == "1000"
    assert item["coin"] == "BTCUSD"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.24"
    assert item["quantity_usd"] == "336.0"
    assert item["sell_price"] == "4200.0"
    assert item["expected_return"] == "672.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "SOLD_PART_BOUGHT"

    logger.info("HP List after the update: %s", hp_list)

    assert strategy.ui_queue.qsize() == 0


async def test_buy_fully_partially_bought_position_when_sold_position(
    trading_system_factory, hp_gui: HpFront
) -> None:
    # Path 0: Default buy position
    hp_list: List[Dict] = []
    strategy: HpStrategy = get_default_buy_position(trading_system_factory)
    assert isinstance(strategy, HpStrategy)

    strategy, hp_list = assert_default_buy_position_data(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    # Path 1: Send buy orders

    strategy, hp_list = await move_to_buy_position_active(
        strategy=strategy, trigger_price=1414, hp_gui=hp_gui, hp_list=hp_list
    )

    # Simulate full order fill
    strategy, hp_list = await simulate_first_buy_order_fill(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list, order_id=132729677
    )

    # Cancel partially bought position
    strategy = await cancel_partially_bought_position_first_order_filled(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy, hp_list = await send_sell_order_for_partially_bought_position(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=1008,
        last_executed_quantity=0.24,
        last_executed_price=4200,
        cumulative_filled_quantity=0.24,
    )
    await strategy.process_order()  # type: ignore[attr-defined]

    # Wait for the HP_ALL_ORDERS_FILLED signal to be processed from the queue
    # The signal is sent to the queue during process_order() and processed asynchronously
    # In test environment, manually process the signal from the worker queue
    await asyncio.sleep(0.1)  # Brief wait for signal to be queued

    # Manually process the signal from worker queue (no worker thread in tests)
    assert strategy.worker_queue.qsize() == 1
    event = strategy.worker_queue.get_nowait()
    assert isinstance(event, Event)
    assert event.name == EventName.SIGNAL
    assert isinstance(event.content, SignalUpdate)
    assert event.content.signal == Signal.HP_ALL_ORDERS_FILLED

    # Set the signal and trigger the state machine
    strategy.signal_update = event.content
    await strategy.process_signal()  # type: ignore[attr-defined]

    logger.info("Orders: %s", strategy.sell.current_position.sell_order)
    assert strategy.sell.current_position.sell_order.status == ORDER_STATUS_FILLED
    assert strategy.sell.current_position.sell_order.quantity == 0.24
    assert strategy.sell.current_position.sell_order.realized_quantity == 0.24
    assert strategy.state == State.SOLD_PART_BOUGHT
    assert strategy.sell.current_position.state_info.state == State.SOLD
    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT

    # Process the intermediate PARTIALLY_SOLD update first
    assert strategy.ui_queue.qsize() == 2
    intermediate_content = strategy.ui_queue.get_nowait()
    logger.info("Content 1: %s", intermediate_content)
    assert isinstance(intermediate_content, HPGuiDataSell)

    # Leave the final SOLD_PART_BOUGHT update for the original test logic
    assert strategy.ui_queue.qsize() == 1

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.sell.current_position.state_info.state == State.SOLD
    assert strategy.state == State.SOLD_PART_BOUGHT

    assert strategy.ui_queue.qsize() == 1

    content = strategy.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, HPGuiDataSell)
    state_info = content.data.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.SOLD
    assert state_info.side == PositionSide.SHORT

    assert state_info.ui_state == UiState.CLOSED
    assert state_info.completeness == 1.0

    hp_list = hp_gui.update_hp_list(update=content.hp_update, hp_list=hp_list)

    # SOLD_PART_BOUGHT is a continuing state, so container should maintain 3-item structure
    assert len(hp_list) == 3  # Parent + buy child + sell child for continuing position

    # Verify parent container
    parent_item = next(item for item in hp_list if item.get("children"))
    assert parent_item["hp_id"] == "1000"
    assert parent_item["coin"] == "BTCUSD"
    assert parent_item["buy_price"] == "1400.0"
    assert parent_item["quantity"] == "0.24"  # Parent shows total bought quantity
    assert parent_item["quantity_usd"] == "336.0"  # Parent shows aggregated USD
    assert parent_item["sell_price"] == "4200.0"
    assert parent_item["expected_return"] == "672.0"
    assert parent_item["current_price"] == "0.0"
    assert parent_item["net"] == "0.0"
    assert parent_item["net_percent"] == "0.0"
    assert (
        parent_item["state"] == "SOLD_PART_BOUGHT"
    )  # Parent reflects the overall operation state
    assert parent_item["children"] == ["1000_BUY", "1000_SELL"]

    # Verify buy child shows the completed buy operation
    buy_child = next(item for item in hp_list if item["hp_id"] == "1000_BUY")
    assert (
        buy_child["state"] == "PARTIALLY_BOUGHT"
    )  # Shows current buy state for continuing position

    # Verify sell child shows the completed sell operation
    sell_child = next(item for item in hp_list if item["hp_id"] == "1000_SELL")
    assert sell_child["state"] == "SOLD"  # Shows completed sell state

    logger.info("HP List after the update: %s", hp_list)

    assert strategy.ui_queue.qsize() == 0

    # Reopen Buy position
    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )

    strategy, hp_list = await reopen_buy_part_bought_sold(
        strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
    )

    (
        strategy,
        hp_list,
    ) = await simulate_second_buy_order_fill_after_selling_first_order(
        strategy=strategy,
        hp_gui=hp_gui,
        hp_list=hp_list,
        order_id=95830862,
    )
    (
        strategy,
        hp_list,
    ) = await simulate_third_buy_order_fill_after_selling_first_order(
        strategy=strategy,
        hp_gui=hp_gui,
        hp_list=hp_list,
        order_id=40613711,
    )
