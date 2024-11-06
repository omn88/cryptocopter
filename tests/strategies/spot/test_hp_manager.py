import datetime
import logging

from binance.enums import (
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_NEW,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_EXPIRED,
)
from transitions.extensions.asyncio import AsyncMachine
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
    UiState,
)
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import PositionData
from src.strategies.spot.hp_manager import HpManager
from tests.strategies.spot.hp_manager import (
    assert_default_buy_position_data,
    cancel_sell_position,
    cancel_sell_position_part_bought_part_sold,
    get_default_buy_position,
    move_to_buy_position_active,
    move_to_partially_sold,
    move_to_sell_position_active,
    reopen_buy_part_bought_part_sold,
    simulate_bought_position,
    simulate_cancel_buy_position,
    simulate_cancel_sell_position,
    simulate_cancel_unfilled_buy_position,
    simulate_first_buy_order_fill,
    simulate_move_to_sell_from_partially_bought_position,
    simulate_partial_fill,
    simulate_partial_fill_sell,
    simulate_partially_bought_position,
    simulate_second_buy_order_fill,
    simulate_third_buy_order_fill,
    simulate_third_buy_order_partial_fill,
)

logger = logging.getLogger("test_hp_manager")


async def test_default_position(trading_system_factory) -> None:
    """
    This test purpose is to instantiate basic buy position and assert on
    the default values

    Path 1
    """

    trading_system = trading_system_factory(
        hp_config=HPConfig(
            hp_id="1000",
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
    assert strategy.buy_position.config.hp_id == "1000"
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

    assert len(strategy.buy_position.orders) == 3

    assert strategy.buy_position.orders[0].quantity == 0.24
    assert strategy.buy_position.orders[1].quantity == 0.28
    assert strategy.buy_position.orders[2].quantity == 0.33

    assert strategy.sell_position.config.hp_id == "1000"
    assert strategy.sell_position.config.price_low == 0
    assert strategy.sell_position.config.price_high == 0
    assert strategy.sell_position.config.order_trigger == 0
    assert strategy.sell_position.config.budget == 0
    assert strategy.sell_position.config.mode == Mode.DCA
    assert strategy.sell_position.config.symbol_info.symbol == "BTCUSDT"

    assert strategy.sell_position.state_info.side == PositionSide.SHORT

    assert strategy.sell_position.state_info.stagnation_counter == 0
    assert strategy.sell_position.state_info.stagnation_limit == 8
    assert len(strategy.sell_position.orders) == 0
    assert strategy.sell_position.state_info.state == State.NEW
    assert strategy.state == State.NEW

    assert strategy.buy_position.ui_queue.qsize() == 0


async def test_default_position_send_orders(trading_system_factory) -> None:
    """
    Path 1 -> 2
    """

    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)

    strategy = await move_to_buy_position_active(strategy=strategy, trigger_price=1414)

    assert strategy.buy_position.state_info.state == State.NEW
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.buy_position.orders
    )

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    config = content.config
    assert isinstance(config, HPConfig)

    assert config.hp_id == "1000"
    assert config.price_low == 1000
    assert config.price_high == 1400
    assert config.budget == 1000
    assert config.order_trigger == 1.0
    assert config.mode == Mode.DCA
    assert config.symbol_info.symbol == "BTCUSDT"
    assert config.symbol_info.precision == 2
    assert config.symbol_info.price_precision == 2

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.NEW
    assert state_info.stagnation_counter == 0
    assert state_info.stagnation_limit == 8
    assert state_info.side == PositionSide.LONG
    assert state_info.next_monitor_time

    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.00
    assert content.recovering is False

    assert strategy.buy_position.ui_queue.qsize() == 0


async def test_cancel_default_position_untouched(trading_system_factory) -> None:
    """
    This test purpose is to instantiate basic buy position then trigger
    the conditions with which the position will be cancelled untouched and the states
    will get back to State.NEW
    Path 1 -> 2 -> 1
    """

    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await move_to_buy_position_active(strategy=strategy, trigger_price=1414)

    strategy = assert_default_buy_position_data(strategy=strategy)

    assert strategy.buy_position.state_info.state == State.NEW
    assert all(
        order.status == ORDER_STATUS_NEW for order in strategy.buy_position.orders
    )

    strategy.buy_position.state_info.stagnation_counter = (
        strategy.buy_position.state_info.stagnation_limit
    )

    strategy.buy_position.state_info.generate_next_monitor_time()

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
    strategy.ticker_update = TickerUpdate(last_price=1428.0)
    assert strategy.conditions_for_cancelling_unfilled_buy_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.buy_position.orders) == 3
    assert all(
        order.status == ORDER_STATUS_CANCELED for order in strategy.buy_position.orders
    )
    assert strategy.buy_position.state_info.state == State.NEW
    assert strategy.state == State.NEW

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)
    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.NEW
    assert state_info.stagnation_counter == 8
    assert state_info.stagnation_limit == 8
    assert state_info.side == PositionSide.LONG
    assert state_info.next_monitor_time

    assert content.ui_state == UiState.STAGNATED
    assert content.order_cancel == 2.0
    assert content.completeness == 0.00
    assert content.recovering is False

    assert strategy.buy_position.ui_queue.qsize() == 0


async def test_cancel_default_position_untouched_then_resend_orders(
    trading_system_factory,
) -> None:
    """
    This test purpose is to instantiate basic buy position then trigger
    the conditions with which the position will be cancelled untouched and the states
    will get back to State.NEW
    """

    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await move_to_buy_position_active(strategy=strategy, trigger_price=1414)

    strategy = assert_default_buy_position_data(strategy=strategy)

    strategy = await simulate_cancel_unfilled_buy_position(strategy=strategy)

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)
    state_info = content.state_info
    assert isinstance(state_info, StateInfo)
    assert state_info.state == State.NEW
    assert state_info.stagnation_counter == 8
    assert content.ui_state == UiState.STAGNATED
    assert strategy.buy_position.ui_queue.qsize() == 0

    assert strategy.buy_position.state_info.state == State.NEW
    assert strategy.state == State.NEW
    assert len(strategy.buy_position.orders) == 3
    assert all(
        order.status == ORDER_STATUS_CANCELED for order in strategy.buy_position.orders
    )

    strategy = await move_to_buy_position_active(strategy=strategy, trigger_price=1414)

    assert strategy.buy_position.orders[0].quantity == 0.24
    assert strategy.buy_position.orders[1].quantity == 0.28
    assert strategy.buy_position.orders[2].quantity == 0.33
    assert all(order.realized_quantity == 0.0 for order in strategy.buy_position.orders)

    strategy = assert_default_buy_position_data(strategy=strategy)


async def test_default_position_first_order_filled_partially(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await move_to_buy_position_active(strategy=strategy, trigger_price=1414)

    strategy = assert_default_buy_position_data(strategy=strategy)

    # Simulate partial fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=445860,
        last_executed_quantity=0.12,
        last_executed_price=1400,
        cumulative_filled_quantity=0.12,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy_position.orders)
    assert strategy.buy_position.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert strategy.buy_position.orders[1].status == ORDER_STATUS_NEW
    assert strategy.buy_position.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.14
    assert content.recovering is False

    assert strategy.buy_position.ui_queue.qsize() == 0


async def test_default_position_first_order_filled_partially_then_cancel(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await move_to_buy_position_active(strategy=strategy, trigger_price=1414)
    strategy = assert_default_buy_position_data(strategy=strategy)
    strategy = await simulate_partial_fill(strategy=strategy)

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.14
    assert strategy.buy_position.ui_queue.qsize() == 0

    strategy.buy_position.state_info.stagnation_counter = (
        strategy.buy_position.state_info.stagnation_limit
    )

    strategy.buy_position.state_info.generate_next_monitor_time()

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
    strategy.ticker_update = TickerUpdate(last_price=1428.0)
    assert not strategy.conditions_for_cancelling_unfilled_buy_orders()
    assert strategy.conditions_for_cancelling_partially_bought_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

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
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await move_to_buy_position_active(strategy=strategy, trigger_price=1414)
    strategy = assert_default_buy_position_data(strategy=strategy)

    # Simulate full order fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445860,
        last_executed_quantity=0.1,
        last_executed_price=1400,
        cumulative_filled_quantity=0.24,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy_position.orders)
    assert strategy.buy_position.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[1].status == ORDER_STATUS_NEW
    assert strategy.buy_position.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.28

    assert strategy.buy_position.ui_queue.qsize() == 0


async def test_default_position_first_order_filled_then_cancel(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await move_to_buy_position_active(strategy=strategy, trigger_price=1414)
    strategy = assert_default_buy_position_data(strategy=strategy)
    strategy = await simulate_first_buy_order_fill(strategy=strategy)

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.28

    assert strategy.buy_position.ui_queue.qsize() == 0

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

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.ui_state == UiState.STAGNATED
    assert content.order_cancel == 2.0
    assert content.completeness == 0.28

    assert strategy.buy_position.ui_queue.qsize() == 0


async def test_default_position_all_buy_orders_filled(trading_system_factory) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await move_to_buy_position_active(strategy=strategy, trigger_price=1414)
    strategy = assert_default_buy_position_data(strategy=strategy)
    strategy = await simulate_first_buy_order_fill(strategy=strategy)

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.28

    assert strategy.buy_position.ui_queue.qsize() == 0

    strategy = await simulate_second_buy_order_fill(strategy=strategy)
    strategy = await simulate_third_buy_order_fill(strategy=strategy)


async def test_conditions_for_new_buy_order_confirmation(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await move_to_buy_position_active(strategy=strategy, trigger_price=1414)
    strategy = assert_default_buy_position_data(strategy=strategy)

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_NEW,
        symbol=strategy.buy_position.config.symbol_info.symbol,
    )
    assert strategy.conditions_for_new_order_confirmation()


async def test_conditions_for_buy_order_cancellation(trading_system_factory) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    assert isinstance(strategy, HpManager)
    strategy = await move_to_buy_position_active(strategy=strategy, trigger_price=1414)
    strategy = assert_default_buy_position_data(strategy=strategy)
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_CANCELED,
        symbol=strategy.buy_position.config.symbol_info.symbol,
    )
    assert strategy.conditions_for_order_cancellation()


async def test_conditions_for_buy_order_expiration(trading_system_factory) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    assert isinstance(strategy, HpManager)
    strategy = await move_to_buy_position_active(strategy=strategy, trigger_price=1414)
    strategy = assert_default_buy_position_data(strategy=strategy)
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

    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await move_to_buy_position_active(strategy=strategy, trigger_price=1414)
    strategy = assert_default_buy_position_data(strategy=strategy)

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
    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.buy_position.state_info.stagnation_counter == 1
    assert strategy.buy_position.state_info.stagnation_limit == 8

    assert strategy.buy_position.state_info.next_monitor_time != time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.NEW
    assert state_info.next_monitor_time

    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.00

    assert strategy.buy_position.ui_queue.qsize() == 0


async def test_default_position_first_order_filled_partially_then_cancel_then_resend(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await move_to_buy_position_active(strategy=strategy, trigger_price=1414)
    strategy = assert_default_buy_position_data(strategy=strategy)
    strategy = await simulate_partial_fill(strategy=strategy)

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.14

    assert strategy.buy_position.ui_queue.qsize() == 0

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

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.ui_state == UiState.STAGNATED
    assert content.order_cancel == 2.0
    assert content.completeness == 0.14

    assert strategy.buy_position.ui_queue.qsize() == 0

    assert strategy.calculate_trigger_send_orders_price_buy() == 1414
    strategy.ticker_update = TickerUpdate(last_price=1414)

    await strategy.process_ticker()  # type: ignore[attr-defined]

    logger.info("State: %s", strategy.state)
    assert strategy.state == State.BUYING
    assert len(strategy.buy_position.orders) == 3

    assert strategy.buy_position.orders[0].quantity == 0.24
    assert strategy.buy_position.orders[1].quantity == 0.28
    assert strategy.buy_position.orders[2].quantity == 0.33

    assert strategy.buy_position.orders[0].realized_quantity == 0.12
    assert strategy.buy_position.orders[1].realized_quantity == 0.0
    assert strategy.buy_position.orders[2].realized_quantity == 0.0

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.14

    assert strategy.buy_position.ui_queue.qsize() == 0


async def test_default_position_first_order_filled_then_cancel_then_resend(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await move_to_buy_position_active(strategy=strategy, trigger_price=1414)
    strategy = assert_default_buy_position_data(strategy=strategy)
    strategy = await simulate_first_buy_order_fill(strategy=strategy)

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.28

    assert strategy.buy_position.ui_queue.qsize() == 0

    strategy = await simulate_cancel_buy_position(strategy=strategy)

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.ui_state == UiState.STAGNATED
    assert content.order_cancel == 2.0
    assert content.completeness == 0.28

    assert strategy.buy_position.ui_queue.qsize() == 0

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
    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING
    assert len(strategy.buy_position.orders) == 3

    assert strategy.buy_position.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[1].status == ORDER_STATUS_NEW
    assert strategy.buy_position.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy_position.orders[0].quantity == 0.24
    assert strategy.buy_position.orders[1].quantity == 0.28
    assert strategy.buy_position.orders[2].quantity == 0.33

    assert strategy.buy_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.state == State.PARTIALLY_BOUGHT
    assert state_info.next_monitor_time

    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.28

    assert strategy.buy_position.ui_queue.qsize() == 0


async def test_send_sell_orders_for_bought_position(trading_system_factory) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_bought_position(strategy=strategy)

    strategy.sell_position.config = HPConfig(
        hp_id=strategy.buy_position.config.hp_id,
        symbol_info=strategy.buy_position.config.symbol_info,
        price_low=4200,
        price_high=4200,
        order_trigger=1.0,
        budget=round(
            sum(order.realized_quantity for order in strategy.buy_position.orders), 2
        ),
        mode=Mode.SINGLE,
    )
    strategy.sell_position.state_info = StateInfo(side=PositionSide.SHORT)
    strategy.sell_position.orders = (
        strategy.sell_position.order_handler.prepare_sell_orders(
            config=strategy.sell_position.config,
            buy_orders=strategy.buy_position.orders,
            sell_orders=strategy.sell_position.orders,
        )
    )

    assert strategy.sell_position.config.hp_id == "1000"
    assert strategy.sell_position.config.price_low == 4200
    assert strategy.sell_position.config.price_high == 4200
    assert strategy.sell_position.config.order_trigger == 1
    assert strategy.sell_position.config.budget == 0.85
    assert strategy.sell_position.config.mode == Mode.SINGLE
    assert strategy.sell_position.config.symbol_info.symbol == "BTCUSDT"

    assert strategy.sell_position.state_info.side == PositionSide.SHORT
    assert strategy.sell_position.state_info.state == State.NEW
    assert strategy.sell_position.state_info.stagnation_counter == 0
    assert strategy.sell_position.state_info.stagnation_limit == 8

    assert len(strategy.sell_position.orders) == 1
    assert strategy.sell_position.orders[0].quantity == 0.85
    assert strategy.sell_position.orders[0].status == ORDER_STATUS_NEW

    assert strategy.calculate_trigger_send_orders_price_sell() == 4158
    assert strategy.state == State.BOUGHT

    strategy.ticker_update = TickerUpdate(last_price=4158.0)
    assert strategy.conditions_for_sending_sell_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.SELLING
    assert strategy.sell_position.state_info.state == State.NEW

    assert strategy.sell_position.orders[0].quantity == 0.85
    assert strategy.sell_position.orders[0].realized_quantity == 0.0

    assert strategy.sell_position.orders[0].status == ORDER_STATUS_NEW

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.NEW
    assert state_info.stagnation_counter == 0
    assert state_info.stagnation_limit == 8
    assert content.state_info.side == PositionSide.SHORT
    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.00
    assert content.recovering is False

    assert strategy.buy_position.ui_queue.qsize() == 0


async def test_sell_orders_stagnation_increase(trading_system_factory) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_bought_position(strategy=strategy)

    strategy = await move_to_sell_position_active(strategy)

    assert strategy.sell_position.orders[0].quantity == 0.85
    assert strategy.sell_position.orders[0].realized_quantity == 0.0

    assert strategy.sell_position.orders[0].status == ORDER_STATUS_NEW

    assert strategy.sell_position.state_info.stagnation_counter == 0
    assert strategy.sell_position.state_info.stagnation_limit == 8

    time = datetime.datetime.now()
    strategy.sell_position.state_info.next_monitor_time = time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    assert strategy.sell_position.state_info.next_monitor_time == time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    assert strategy.conditions_for_position_stagnation_sell()
    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.sell_position.state_info.stagnation_counter == 1
    assert strategy.sell_position.state_info.stagnation_limit == 8

    assert strategy.sell_position.state_info.next_monitor_time != time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.NEW
    assert content.state_info.side == PositionSide.SHORT
    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.00
    assert content.recovering is False

    assert strategy.buy_position.ui_queue.qsize() == 0


async def test_cancel_unfilled_sell_orders(trading_system_factory) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_bought_position(strategy=strategy)

    strategy = await move_to_sell_position_active(strategy)

    assert strategy.sell_position.orders[0].quantity == 0.85
    assert strategy.sell_position.orders[0].realized_quantity == 0.0

    assert strategy.sell_position.orders[0].status == ORDER_STATUS_NEW

    assert strategy.sell_position.state_info.stagnation_counter == 0
    assert strategy.sell_position.state_info.stagnation_limit == 8

    strategy.sell_position.state_info.stagnation_counter = (
        strategy.sell_position.state_info.stagnation_limit
    )

    strategy.sell_position.state_info.generate_next_monitor_time()

    assert strategy.calculate_trigger_cancel_orders_price_sell() == 4116.0
    strategy.ticker_update = TickerUpdate(last_price=4116.0)
    assert strategy.conditions_for_cancelling_unfilled_sell_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.sell_position.orders) == 1

    logger.info("Orders: %s", strategy.sell_position.orders)
    assert all(
        order.status == ORDER_STATUS_CANCELED for order in strategy.sell_position.orders
    )
    assert strategy.sell_position.state_info.state == State.NEW
    assert strategy.state == State.BOUGHT

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.NEW
    assert content.state_info.side == PositionSide.SHORT
    assert content.ui_state == UiState.STAGNATED
    assert content.order_cancel == 2.0
    assert content.completeness == 0.00
    assert content.recovering is False

    assert strategy.buy_position.ui_queue.qsize() == 0


async def test_resend_unfilled_sell_orders(trading_system_factory) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_bought_position(strategy=strategy)

    strategy = await move_to_sell_position_active(strategy)

    assert strategy.sell_position.orders[0].quantity == 0.85
    assert strategy.sell_position.orders[0].realized_quantity == 0.0

    assert strategy.sell_position.orders[0].status == ORDER_STATUS_NEW

    assert strategy.sell_position.state_info.stagnation_counter == 0
    assert strategy.sell_position.state_info.stagnation_limit == 8

    strategy.sell_position.state_info.stagnation_counter = (
        strategy.sell_position.state_info.stagnation_limit
    )

    strategy.sell_position.state_info.generate_next_monitor_time()

    assert strategy.calculate_trigger_cancel_orders_price_sell() == 4116.0
    strategy.ticker_update = TickerUpdate(last_price=4116.0)
    assert strategy.conditions_for_cancelling_unfilled_sell_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.sell_position.orders) == 1

    logger.info("Orders: %s", strategy.sell_position.orders)
    assert all(
        order.status == ORDER_STATUS_CANCELED for order in strategy.sell_position.orders
    )
    assert strategy.sell_position.state_info.state == State.NEW
    assert strategy.state == State.BOUGHT

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.NEW
    assert content.state_info.side == PositionSide.SHORT
    assert content.ui_state == UiState.STAGNATED
    assert content.order_cancel == 2.0
    assert content.completeness == 0.00
    assert content.recovering is False

    assert strategy.buy_position.ui_queue.qsize() == 0

    assert strategy.calculate_trigger_send_orders_price_sell() == 4158
    strategy.ticker_update = TickerUpdate(last_price=4158.0)
    assert strategy.conditions_for_sending_sell_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.SELLING
    assert strategy.sell_position.state_info.state == State.NEW

    assert strategy.sell_position.orders[0].quantity == 0.85
    assert strategy.sell_position.orders[0].realized_quantity == 0.0

    assert strategy.sell_position.orders[0].status == ORDER_STATUS_NEW

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.NEW
    assert content.state_info.side == PositionSide.SHORT
    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.00
    assert content.recovering is False

    assert strategy.buy_position.ui_queue.qsize() == 0


async def test_sell_position_first_order_filled_partially(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_bought_position(strategy=strategy)

    strategy = await move_to_sell_position_active(strategy)

    # Simulate partial fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=5617834,
        last_executed_quantity=0.425,
        last_executed_price=4200,
        cumulative_filled_quantity=0.425,
    )
    await strategy.process_order()  # type: ignore[attr-defined]

    logger.info("Orders: %s", strategy.buy_position.orders)
    assert strategy.sell_position.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert strategy.state == State.SELLING
    assert strategy.sell_position.state_info.state == State.PARTIALLY_SOLD

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_SOLD
    assert content.state_info.side == PositionSide.SHORT
    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.5
    assert content.recovering is False

    assert strategy.buy_position.ui_queue.qsize() == 0


async def test_sell_position_first_order_filled(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_bought_position(strategy=strategy)

    strategy = await move_to_sell_position_active(strategy)

    # Simulate first order fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=5617834,
        last_executed_quantity=0.85,
        last_executed_price=4200,
    )
    await strategy.process_order()  # type: ignore[attr-defined]

    logger.info("Orders: %s", strategy.sell_position.orders)
    assert strategy.sell_position.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.state == State.SELLING
    assert strategy.sell_position.state_info.state == State.SOLD

    assert strategy.sell_position.ui_queue.qsize() == 2
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.SOLD
    assert content.state_info.side == PositionSide.SHORT
    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.00
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 1

    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.SOLD
    assert content.state_info.side == PositionSide.SHORT
    assert content.ui_state == UiState.CLOSED
    assert content.order_cancel == 2.0
    assert content.completeness == 1.00
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0

    assert strategy.core_queue.qsize() == 1
    event = strategy.core_queue.get_nowait()

    assert isinstance(event, Event)
    assert event.name == EventName.SIGNAL
    assert isinstance(event.content, SignalUpdate)

    strategy.signal_update = event.content

    await strategy.process_signal()  # type: ignore[attr-defined]

    assert strategy.sell_position.state_info.state == State.SOLD
    assert strategy.state == State.SOLD


async def test_cancel_sell_position_first_order_filled_partially(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_bought_position(strategy=strategy)

    strategy = await move_to_sell_position_active(strategy)

    strategy = await simulate_partial_fill_sell(strategy)

    strategy.sell_position.state_info.stagnation_counter = (
        strategy.sell_position.state_info.stagnation_limit
    )

    strategy.sell_position.state_info.generate_next_monitor_time()

    assert strategy.calculate_trigger_cancel_orders_price_sell() == 4116.0
    strategy.ticker_update = TickerUpdate(last_price=4116.0)
    assert strategy.conditions_for_cancelling_partially_sold_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.sell_position.orders) == 1

    logger.info("Orders: %s", strategy.sell_position.orders)
    assert all(
        order.status == ORDER_STATUS_CANCELED for order in strategy.sell_position.orders
    )
    assert strategy.sell_position.state_info.state == State.PARTIALLY_SOLD
    assert strategy.state == State.PARTIALLY_SOLD

    assert strategy.sell_position.ui_queue.qsize() == 1

    content = strategy.sell_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_SOLD
    assert content.state_info.side == PositionSide.SHORT
    assert content.ui_state == UiState.STAGNATED
    assert content.order_cancel == 2.0
    assert content.completeness == 0.5
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0


async def test_resend_sell_position_first_order_filled_partially(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_bought_position(strategy=strategy)

    strategy = await move_to_sell_position_active(strategy)

    strategy = await simulate_partial_fill_sell(strategy)

    strategy = await move_to_partially_sold(strategy)

    assert strategy.calculate_trigger_send_orders_price_sell() == 4158
    assert strategy.state == State.PARTIALLY_SOLD
    assert strategy.sell_position.state_info.state == State.PARTIALLY_SOLD

    strategy.ticker_update = TickerUpdate(last_price=4158.0)
    assert not strategy.conditions_for_sending_sell_orders()
    assert strategy.conditions_for_resending_partially_sold_orders()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.SELLING
    assert strategy.sell_position.state_info.state == State.PARTIALLY_SOLD

    assert strategy.sell_position.ui_queue.qsize() == 1

    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_SOLD
    assert content.state_info.side == PositionSide.SHORT
    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.5
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0


async def test_conditions_for_new_sell_order_confirmation(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_bought_position(strategy=strategy)

    strategy = await move_to_sell_position_active(strategy)

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_NEW,
        symbol=strategy.buy_position.config.symbol_info.symbol,
    )
    assert strategy.conditions_for_new_order_confirmation()


async def test_conditions_for_sell_order_cancellation(trading_system_factory) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_bought_position(strategy=strategy)

    strategy = await move_to_sell_position_active(strategy)

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_CANCELED,
        symbol=strategy.buy_position.config.symbol_info.symbol,
    )
    assert strategy.conditions_for_order_cancellation()


async def test_conditions_for_sell_order_expiration(trading_system_factory) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_bought_position(strategy=strategy)

    strategy = await move_to_sell_position_active(strategy)

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT, current_order_status=ORDER_STATUS_EXPIRED
    )
    assert strategy.conditions_for_order_expiration()


async def test_close_mode_single_generated_position(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_bought_position(strategy=strategy)

    strategy = await move_to_sell_position_active(strategy)

    # Simulate first order fill
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=5617834,
        last_executed_quantity=0.85,
        last_executed_price=4200,
    )
    await strategy.process_order()  # type: ignore[attr-defined]

    logger.info("Orders: %s", strategy.buy_position.orders)
    assert strategy.sell_position.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.state == State.SELLING
    assert strategy.sell_position.state_info.state == State.SOLD

    assert strategy.sell_position.ui_queue.qsize() == 2
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.SOLD
    assert content.state_info.side == PositionSide.SHORT
    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.00
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 1

    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.SOLD
    assert content.state_info.side == PositionSide.SHORT
    assert content.ui_state == UiState.CLOSED
    assert content.order_cancel == 2.0
    assert content.completeness == 1.00
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0

    assert strategy.core_queue.qsize() == 1
    event = strategy.core_queue.get_nowait()

    assert isinstance(event, Event)
    assert event.name == EventName.SIGNAL
    assert isinstance(event.content, SignalUpdate)

    strategy.signal_update = event.content

    await strategy.process_signal()  # type: ignore[attr-defined]

    assert strategy.sell_position.state_info.state == State.SOLD
    assert strategy.state == State.SOLD


async def test_send_sell_orders_for_partially_bought_position(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_partially_bought_position(strategy=strategy)

    assert strategy.state == State.PARTIALLY_BOUGHT

    strategy.sell_position.config = HPConfig(
        hp_id=strategy.buy_position.config.hp_id,
        symbol_info=strategy.buy_position.config.symbol_info,
        price_low=4200,
        price_high=4200,
        order_trigger=1.0,
        budget=round(
            sum(order.realized_quantity for order in strategy.buy_position.orders), 2
        ),
        mode=Mode.SINGLE,
    )
    strategy.sell_position.state_info = StateInfo(side=PositionSide.SHORT)
    strategy.sell_position.orders = (
        strategy.sell_position.order_handler.prepare_sell_orders(
            config=strategy.sell_position.config,
            buy_orders=strategy.buy_position.orders,
            sell_orders=strategy.sell_position.orders,
        )
    )

    assert strategy.sell_position.config.hp_id == "1000"
    assert strategy.sell_position.config.price_low == 4200
    assert strategy.sell_position.config.price_high == 4200
    assert strategy.sell_position.config.order_trigger == 1
    assert strategy.sell_position.config.budget == 0.52
    assert strategy.sell_position.config.mode == Mode.SINGLE
    assert strategy.sell_position.config.symbol_info.symbol == "BTCUSDT"

    assert strategy.sell_position.state_info.side == PositionSide.SHORT
    assert strategy.sell_position.state_info.state == State.NEW
    assert strategy.sell_position.state_info.stagnation_counter == 0
    assert strategy.sell_position.state_info.stagnation_limit == 8

    assert len(strategy.sell_position.orders) == 1
    assert strategy.sell_position.orders[0].quantity == 0.52
    assert strategy.sell_position.orders[0].status == ORDER_STATUS_NEW

    assert strategy.calculate_trigger_send_orders_price_sell() == 4158
    assert strategy.state == State.PARTIALLY_BOUGHT

    strategy.ticker_update = TickerUpdate(last_price=4158.0)
    assert strategy.conditions_for_sending_sell_orders_for_partially_bought_position()

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.SELLING
    assert strategy.sell_position.state_info.state == State.NEW

    assert strategy.sell_position.orders[0].quantity == 0.52
    assert strategy.sell_position.orders[0].realized_quantity == 0.0

    assert strategy.sell_position.orders[0].status == ORDER_STATUS_NEW

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.NEW
    assert content.state_info.side == PositionSide.SHORT
    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.00
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0


async def test_cancel_unfilled_sell_orders_for_partially_bought_position(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_partially_bought_position(strategy=strategy)
    strategy = await simulate_move_to_sell_from_partially_bought_position(
        strategy=strategy
    )

    assert strategy.state == State.SELLING
    strategy.sell_position.state_info.stagnation_counter = (
        strategy.sell_position.state_info.stagnation_limit
    )

    strategy.sell_position.state_info.generate_next_monitor_time()

    assert strategy.calculate_trigger_cancel_orders_price_sell() == 4116.0
    strategy.ticker_update = TickerUpdate(last_price=4116.0)
    assert (
        strategy.conditions_for_cancelling_unfilled_sell_orders_from_partially_bought_position()
    )

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert len(strategy.sell_position.orders) == 1

    logger.info("Orders: %s", strategy.sell_position.orders)
    assert all(
        order.status == ORDER_STATUS_CANCELED for order in strategy.sell_position.orders
    )
    assert strategy.sell_position.state_info.state == State.NEW
    assert strategy.state == State.PARTIALLY_BOUGHT

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.NEW
    assert content.state_info.side == PositionSide.SHORT
    assert content.ui_state == UiState.STAGNATED
    assert content.order_cancel == 2.0
    assert content.completeness == 0.00
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0


async def test_fill_orders_for_previously_partially_bought_position(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_partially_bought_position(strategy=strategy)
    strategy = await simulate_move_to_sell_from_partially_bought_position(
        strategy=strategy
    )
    strategy = await simulate_cancel_sell_position(strategy=strategy)

    assert strategy.calculate_trigger_send_orders_price_buy() == 1010
    strategy.ticker_update = TickerUpdate(last_price=1010)
    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_BOUGHT
    assert content.state_info.side == PositionSide.LONG
    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.61
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0

    assert not all(
        order.status == ORDER_STATUS_NEW for order in strategy.buy_position.orders
    )

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445864,
        last_executed_quantity=0.1,
        last_executed_price=1000,
        cumulative_filled_quantity=0.33,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy_position.orders)
    assert strategy.buy_position.orders[0].status == ORDER_STATUS_FILLED

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_BOUGHT
    assert content.state_info.side == PositionSide.LONG
    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 1.00
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0

    assert strategy.core_queue.qsize() == 1
    event = strategy.core_queue.get_nowait()

    assert isinstance(event, Event)
    assert event.name == EventName.SIGNAL
    assert isinstance(event.content, SignalUpdate)

    strategy.signal_update = event.content

    await strategy.process_signal()  # type: ignore[attr-defined]

    assert strategy.buy_position.state_info.state == State.BOUGHT
    assert strategy.state == State.BOUGHT

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.BOUGHT
    assert content.state_info.side == PositionSide.LONG
    assert content.ui_state == UiState.CLOSED
    assert content.order_cancel == 2.0
    assert content.completeness == 1.00
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0


async def test_sell_partially_partially_bought_position(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_partially_bought_position(strategy=strategy)
    strategy = await simulate_move_to_sell_from_partially_bought_position(
        strategy=strategy
    )

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=445863,
        last_executed_quantity=0.26,
        last_executed_price=4200,
        cumulative_filled_quantity=0.26,
    )
    await strategy.process_order()  # type: ignore[attr-defined]

    logger.info("Orders: %s", strategy.sell_position.orders)
    assert strategy.sell_position.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert strategy.sell_position.orders[0].quantity == 0.52
    assert strategy.sell_position.orders[0].realized_quantity == 0.26
    assert strategy.state == State.SELLING
    assert strategy.sell_position.state_info.state == State.PARTIALLY_SOLD

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_SOLD
    assert content.state_info.side == PositionSide.SHORT
    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.5
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0


async def test_buy_partially_partially_sold_position(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_partially_bought_position(strategy=strategy)

    assert strategy.state == State.PARTIALLY_BOUGHT
    strategy = await simulate_move_to_sell_from_partially_bought_position(
        strategy=strategy
    )

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=445863,
        last_executed_quantity=0.26,
        last_executed_price=4200,
        cumulative_filled_quantity=0.26,
    )

    assert strategy.state == State.SELLING
    await strategy.process_order()  # type: ignore[attr-defined]

    logger.info("Orders: %s", strategy.sell_position.orders)
    assert strategy.sell_position.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert strategy.sell_position.orders[0].quantity == 0.52
    assert strategy.sell_position.orders[0].realized_quantity == 0.26
    assert strategy.state == State.SELLING
    assert strategy.sell_position.state_info.state == State.PARTIALLY_SOLD
    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_SOLD
    assert content.state_info.side == PositionSide.SHORT
    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.5
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0

    # Cancel Sell position
    strategy = await cancel_sell_position_part_bought_part_sold(strategy=strategy)

    # Reopen Buy position
    strategy = await reopen_buy_part_bought_part_sold(strategy=strategy)

    # Buy partially last order
    strategy = await simulate_third_buy_order_partial_fill(strategy)

    assert strategy.buy_position.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[1].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[2].status == ORDER_STATUS_PARTIALLY_FILLED

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_BOUGHT
    assert content.state_info.side == PositionSide.LONG
    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.82
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0


async def test_cancel_buy_to_part_sold_part_bought(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_partially_bought_position(strategy=strategy)

    assert strategy.state == State.PARTIALLY_BOUGHT
    strategy = await simulate_move_to_sell_from_partially_bought_position(
        strategy=strategy
    )

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=445863,
        last_executed_quantity=0.26,
        last_executed_price=4200,
        cumulative_filled_quantity=0.26,
    )

    assert strategy.state == State.SELLING
    await strategy.process_order()  # type: ignore[attr-defined]

    logger.info("Orders: %s", strategy.sell_position.orders)
    assert strategy.sell_position.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert strategy.sell_position.orders[0].quantity == 0.52
    assert strategy.sell_position.orders[0].realized_quantity == 0.26
    assert strategy.state == State.SELLING
    assert strategy.sell_position.state_info.state == State.PARTIALLY_SOLD
    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_SOLD
    assert content.state_info.side == PositionSide.SHORT
    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.5
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0

    # Cancel Sell position
    strategy = await cancel_sell_position_part_bought_part_sold(strategy=strategy)

    # Reopen Buy position
    strategy = await reopen_buy_part_bought_part_sold(strategy=strategy)

    # Buy partially last order
    strategy = await simulate_third_buy_order_partial_fill(strategy)

    assert strategy.buy_position.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[1].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[2].status == ORDER_STATUS_PARTIALLY_FILLED

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_BOUGHT
    assert content.state_info.side == PositionSide.LONG
    assert content.ui_state == UiState.OPEN
    assert content.order_cancel == 2.0
    assert content.completeness == 0.82
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0

    # Cancel Buy orders
    strategy.buy_position.state_info.stagnation_counter = (
        strategy.buy_position.state_info.stagnation_limit
    )

    strategy.buy_position.state_info.generate_next_monitor_time()

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
    strategy.ticker_update = TickerUpdate(last_price=1428.0)
    assert (
        strategy.conditions_for_cancelling_partially_sold_and_bought_orders_buy_position()
    )

    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.PART_SOLD_PART_BOUGHT
    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.sell_position.state_info.state == State.PARTIALLY_SOLD

    assert strategy.sell_position.ui_queue.qsize() == 1
    content = strategy.buy_position.ui_queue.get_nowait()
    logger.info("Content: %s", content)
    assert isinstance(content, PositionData)

    state_info = content.state_info
    assert isinstance(state_info, StateInfo)

    assert state_info.next_monitor_time
    assert state_info.state == State.PARTIALLY_BOUGHT
    assert content.state_info.side == PositionSide.LONG
    assert content.ui_state == UiState.STAGNATED
    assert content.order_cancel == 2.0
    assert content.completeness == 0.82
    assert content.recovering is False

    assert strategy.sell_position.ui_queue.qsize() == 0


async def test_buy_fully_partially_sold_position(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_partially_bought_position(strategy=strategy)

    assert strategy.state == State.PARTIALLY_BOUGHT
    strategy = await simulate_move_to_sell_from_partially_bought_position(
        strategy=strategy
    )

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
        order_id=445863,
        last_executed_quantity=0.26,
        last_executed_price=4200,
        cumulative_filled_quantity=0.26,
    )

    assert strategy.state == State.SELLING
    await strategy.process_order()  # type: ignore[attr-defined]

    logger.info("Orders: %s", strategy.sell_position.orders)
    assert strategy.sell_position.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert strategy.sell_position.orders[0].quantity == 0.52
    assert strategy.sell_position.orders[0].realized_quantity == 0.26
    assert strategy.state == State.SELLING
    assert strategy.sell_position.state_info.state == State.PARTIALLY_SOLD
    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT

    # Cancel Sell position
    strategy = await cancel_sell_position_part_bought_part_sold(strategy=strategy)

    # Reopen Buy position
    strategy = await reopen_buy_part_bought_part_sold(strategy=strategy)

    # Buy fully last order
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445864,
        last_executed_quantity=0.1,
        last_executed_price=1000,
        cumulative_filled_quantity=0.33,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy_position.orders)
    assert strategy.buy_position.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[1].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[2].status == ORDER_STATUS_FILLED

    assert strategy.core_queue.qsize() == 1
    event = strategy.core_queue.get_nowait()

    assert isinstance(event, Event)
    assert event.name == EventName.SIGNAL
    assert isinstance(event.content, SignalUpdate)

    strategy.signal_update = event.content

    await strategy.process_signal()  # type: ignore[attr-defined]

    assert strategy.state == State.PARTIALLY_SOLD


async def test_sell_fully_partially_bought_position(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_partially_bought_position(strategy=strategy)
    strategy = await simulate_move_to_sell_from_partially_bought_position(
        strategy=strategy
    )

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445863,
        last_executed_quantity=0.52,
        last_executed_price=4200,
        cumulative_filled_quantity=0.52,
    )
    await strategy.process_order()  # type: ignore[attr-defined]

    logger.info("Orders: %s", strategy.sell_position.orders)
    assert strategy.sell_position.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.sell_position.orders[0].quantity == 0.52
    assert strategy.sell_position.orders[0].realized_quantity == 0.52
    assert strategy.state == State.SELLING
    assert strategy.sell_position.state_info.state == State.SOLD
    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT

    assert strategy.core_queue.qsize() == 1
    event = strategy.core_queue.get_nowait()

    assert isinstance(event, Event)
    assert event.name == EventName.SIGNAL
    assert isinstance(event.content, SignalUpdate)

    strategy.signal_update = event.content

    assert strategy.conditions_for_closing_sold_position_which_is_part_bought()

    await strategy.process_signal()  # type: ignore[attr-defined]

    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.sell_position.state_info.state == State.SOLD
    assert strategy.state == State.SOLD_PART_BOUGHT


async def test_buy_fully_partially_bought_position_when_sold_position(
    trading_system_factory,
) -> None:
    trading_system: AsyncMachine = get_default_buy_position(trading_system_factory)
    strategy = trading_system.model
    assert isinstance(strategy, HpManager)
    strategy = await simulate_partially_bought_position(strategy=strategy)
    strategy = await simulate_move_to_sell_from_partially_bought_position(
        strategy=strategy
    )

    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445863,
        last_executed_quantity=0.52,
        last_executed_price=4200,
        cumulative_filled_quantity=0.52,
    )
    await strategy.process_order()  # type: ignore[attr-defined]

    logger.info("Orders: %s", strategy.sell_position.orders)
    assert strategy.sell_position.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.sell_position.orders[0].quantity == 0.52
    assert strategy.sell_position.orders[0].realized_quantity == 0.52
    assert strategy.state == State.SELLING
    assert strategy.sell_position.state_info.state == State.SOLD
    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT

    assert strategy.core_queue.qsize() == 1
    event = strategy.core_queue.get_nowait()

    assert isinstance(event, Event)
    assert event.name == EventName.SIGNAL
    assert isinstance(event.content, SignalUpdate)

    strategy.signal_update = event.content

    assert strategy.conditions_for_closing_sold_position_which_is_part_bought()

    await strategy.process_signal()  # type: ignore[attr-defined]

    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.sell_position.state_info.state == State.SOLD
    assert strategy.state == State.SOLD_PART_BOUGHT

    # Reopen Buy position

    assert strategy.calculate_trigger_send_orders_price_buy() == 1010
    strategy.ticker_update = TickerUpdate(last_price=1010)

    assert not strategy.conditions_for_sending_buy_orders()
    assert strategy.conditions_for_resending_buy_orders_for_sold_position()
    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.state == State.BUYING
    assert strategy.buy_position.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.sell_position.state_info.state == State.SOLD

    # Buy fully last order
    strategy.execution_report = ExecutionReport(
        order_type=ORDER_TYPE_LIMIT,
        current_order_status=ORDER_STATUS_FILLED,
        order_id=445864,
        last_executed_quantity=0.1,
        last_executed_price=1000,
        cumulative_filled_quantity=0.33,
    )
    await strategy.process_order()  # type: ignore[attr-defined]
    assert strategy.state == State.BUYING
    logger.info("Orders: %s", strategy.buy_position.orders)
    assert strategy.buy_position.orders[0].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[1].status == ORDER_STATUS_FILLED
    assert strategy.buy_position.orders[2].status == ORDER_STATUS_FILLED

    assert strategy.core_queue.qsize() == 1
    event = strategy.core_queue.get_nowait()

    assert isinstance(event, Event)
    assert event.name == EventName.SIGNAL
    assert isinstance(event.content, SignalUpdate)

    strategy.signal_update = event.content
    assert strategy.state == State.BUYING
    await strategy.process_signal()  # type: ignore[attr-defined]

    assert strategy.buy_position.state_info.state == State.BOUGHT
    assert strategy.sell_position.state_info.state == State.PARTIALLY_SOLD
