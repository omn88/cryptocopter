import asyncio
import logging
from unittest.mock import AsyncMock
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_PARTIALLY_FILLED,
)
from src.common.symbol_info import SymbolInfo
from src.strategy_executor import StrategyExecutor
from src.gui.hp_manager.hpfront import HpFront
from src.identifiers import (
    HPSellConfig,
    HPSellData,
    State,
    StateInfo,
    PositionSide,
)
from tests.helpers import get_new_orders
from tests.strategies.hp_simulator import HPSimulator
from tests.strategies.hp_manager_helpers import (
    wait_for_condition,
    get_buy_positions,
    wait_for_active_buy_positions,
    wait_for_no_idle_buy_positions,
    wait_for_idle_buy_positions,
    wait_for_no_active_buy_positions,
    wait_for_active_sell_positions,
    wait_for_no_idle_sell_positions,
    wait_for_idle_sell_positions,
    wait_for_no_active_sell_positions,
)

logger = logging.getLogger("hp_e2e_test")


async def test_get_default_buy_position(frontend_backend_setup):
    front, back = frontend_backend_setup

    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    assert len(back.strategies) == 0

    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()


async def test_default_buy_position_send_orders(frontend_backend_setup):
    front, back = frontend_backend_setup
    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    # Open position and send orders
    strategy = back.strategies["1000"]
    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )
    sim.new_price(price=1410)

    # Assert new opened position data
    await wait_for_condition(condition_func=lambda: strategy.state == State.BUYING)
    await wait_for_active_buy_positions(front)
    await wait_for_no_idle_buy_positions(front)
    assert strategy.buy.data.state_info.state == State.NEW
    assert all(order.order_id for order in strategy.buy.orders)
    assert all(order.status == ORDER_STATUS_NEW for order in strategy.buy.orders)

    # Comprehensive validation for position with orders sent
    sim.validate_parent(
        "1000",
        quantity="0.0",
        realized_quantity="0.0",
        state="BUYING",
        buy_price="1400.0",
        quantity_usd="0.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.84921", realized_quantity="0.0", state="NEW"
    )
    sim.validate_buy_orders(
        strategy,
        [
            {"realized_quantity": 0.0, "status": ORDER_STATUS_NEW},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_NEW},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_NEW},
        ],
    )
    sim.validate_strategy_state(strategy, "BUYING", expected_buy_state="NEW")

    logger.info("Active buy positions: %s", get_buy_positions(front, state="BUYING"))
    logger.info("Idle buy positions: %s", get_buy_positions(front, state="NEW"))


async def test_cancel_default_position_untouched(frontend_backend_setup):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)

    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()
    strategy = back.strategies["1000"]

    assert strategy.buy.orders_cancel_price == 1428.0
    sim.new_price(price=1428)

    await wait_for_condition(
        condition_func=lambda: all(
            order.status == ORDER_STATUS_CANCELED for order in strategy.buy.orders
        )
    )

    assert len(strategy.buy.orders) == 3
    assert strategy.buy.data.state_info.state == State.NEW
    assert strategy.state == State.NEW

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == State.NEW.value
    )

    # Validate using comprehensive helper methods from simulator
    sim.validate_parent(
        "1000",
        quantity="0.0",
        realized_quantity="0.0",
        state="NEW",
        buy_price="1400.0",
        quantity_usd="0.0",
        sell_price="0.0",
        expected_return="0.0",
        current_price="0.0",
        net="0.0",
        net_percent="0.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.84921", realized_quantity="0.0", state="NEW"
    )
    sim.validate_buy_orders(
        strategy,
        [
            {"realized_quantity": 0.0, "status": ORDER_STATUS_CANCELED},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_CANCELED},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_CANCELED},
        ],
    )
    sim.validate_strategy_state(strategy, "NEW", expected_buy_state="NEW")


async def test_cancel_default_position_untouched_then_resend_orders(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)

    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    await sim.cancel_buy_position_untouched()

    # Path 1: Resend buy orders
    await sim.move_to_position_active_buy()


async def test_default_position_first_order_filled_then_cancel(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)

    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = (
        await sim.simulate_first_buy_order_fill()
    )  # Cancel partially bought position

    assert strategy.buy.orders_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert len(strategy.buy.orders) == 3

    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED

    await wait_for_condition(
        condition_func=lambda: strategy.buy.orders[1].status == ORDER_STATUS_CANCELED
    )
    await wait_for_condition(
        condition_func=lambda: strategy.buy.orders[2].status == ORDER_STATUS_CANCELED
    )

    # Wait for state transition to complete
    await wait_for_condition(
        condition_func=lambda: strategy.state == State.PARTIALLY_BOUGHT
    )

    # Wait for frontend data to be updated with the correct state
    await wait_for_condition(
        condition_func=lambda: len(front.hp_list_data) > 0
        and front.hp_list_data[0].get("state") == "PARTIALLY_BOUGHT"
    )

    # Validate using comprehensive helper methods from simulator
    sim.validate_parent(
        "1000",
        quantity="0.24",
        realized_quantity="0.0",
        state="PARTIALLY_BOUGHT",
        buy_price="1400.0",
        quantity_usd="336.0",
        sell_price="0.0",
        expected_return="0.0",
        current_price="0.0",
        net="0.0",
        net_percent="0.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.84921", realized_quantity="0.24", state="PARTIALLY_BOUGHT"
    )
    sim.validate_buy_orders(
        strategy,
        [
            {"realized_quantity": 0.24, "status": ORDER_STATUS_FILLED},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_CANCELED},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_CANCELED},
        ],
    )
    sim.validate_strategy_state(
        strategy, "PARTIALLY_BOUGHT", expected_buy_state="PARTIALLY_BOUGHT"
    )

    logger.info("HP List after the update: %s", front.hp_list_data)


async def test_default_position_first_order_filled_partially(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)

    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate partial fill
    strategy = await sim.simulate_partial_fill()

    # Comprehensive validation for partial fill
    sim.validate_parent(
        "1000",
        quantity="0.12",
        realized_quantity="0.0",
        state="BUYING",
        buy_price="1400.0",
        quantity_usd="168.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.84921", realized_quantity="0.12", state="PARTIALLY_BOUGHT"
    )
    sim.validate_buy_orders(
        strategy,
        [
            {"realized_quantity": 0.12, "status": ORDER_STATUS_PARTIALLY_FILLED},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_NEW},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_NEW},
        ],
    )
    sim.validate_strategy_state(
        strategy, "BUYING", expected_buy_state="PARTIALLY_BOUGHT"
    )


async def test_default_position_first_order_filled_partially_then_cancel(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)

    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate partial fill
    strategy = await sim.simulate_partial_fill()  # Cancel position

    assert strategy.buy.orders_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert len(strategy.buy.orders) == 3

    await wait_for_condition(
        lambda: strategy.buy.orders[0].status == ORDER_STATUS_CANCELED
    )
    assert strategy.buy.orders[1].status == ORDER_STATUS_CANCELED
    assert strategy.buy.orders[2].status == ORDER_STATUS_CANCELED

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "PARTIALLY_BOUGHT"
    )

    # Validate using comprehensive helper methods
    sim.validate_parent(
        "1000",
        quantity="0.12",
        realized_quantity="0.0",
        state="PARTIALLY_BOUGHT",
        buy_price="1400.0",
        quantity_usd="168.0",
    )
    sim.validate_child_buy(
        "1000",
        quantity="0.84921",
        realized_quantity="0.12",
        state="PARTIALLY_BOUGHT",
    )
    sim.validate_buy_orders(
        strategy,
        [
            {"realized_quantity": 0.12, "status": ORDER_STATUS_CANCELED},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_CANCELED},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_CANCELED},
        ],
    )
    sim.validate_strategy_state(
        strategy, "PARTIALLY_BOUGHT", expected_buy_state="PARTIALLY_BOUGHT"
    )

    logger.info("HP List after the update: %s", front.hp_list_data)


async def test_default_position_first_order_filled(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first order fill
    strategy = await sim.simulate_first_buy_order_fill()

    # Comprehensive validation for first order filled
    sim.validate_parent(
        "1000",
        quantity="0.24",
        realized_quantity="0.0",
        state="BUYING",
        buy_price="1400.0",
        quantity_usd="336.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.84921", realized_quantity="0.24", state="PARTIALLY_BOUGHT"
    )
    sim.validate_buy_orders(
        strategy,
        [
            {"realized_quantity": 0.24, "status": ORDER_STATUS_FILLED},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_NEW},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_NEW},
        ],
    )
    sim.validate_strategy_state(
        strategy, "BUYING", expected_buy_state="PARTIALLY_BOUGHT"
    )


async def test_default_position_all_buy_orders_filled(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    strategy = await sim.simulate_bought_position()

    # Comprehensive validation for fully bought position
    sim.validate_parent(
        "1000",
        quantity="0.85",
        realized_quantity="0.0",
        state="BOUGHT",
        buy_price="1178.82",
        quantity_usd="1002.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.84921", realized_quantity="0.85", state="BOUGHT"
    )
    sim.validate_buy_orders(
        strategy,
        [
            {"realized_quantity": 0.24, "status": ORDER_STATUS_FILLED},
            {"realized_quantity": 0.28, "status": ORDER_STATUS_FILLED},
            {"realized_quantity": 0.33, "status": ORDER_STATUS_FILLED},
        ],
    )
    sim.validate_strategy_state(strategy, "BOUGHT", expected_buy_state="BOUGHT")


async def test_default_position_first_order_filled_partially_then_cancel_then_resend(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    # Path 0: Default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    # Path 1: Send buy orders
    await sim.move_to_position_active_buy()
    # Simulate partial fill    # Simulate partial fill
    strategy = await sim.simulate_partial_fill()

    # Cancel position
    assert strategy.buy.orders_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert len(strategy.buy.orders) == 3

    await wait_for_condition(
        lambda: strategy.buy.orders[0].status == ORDER_STATUS_CANCELED
    )
    await wait_for_condition(
        lambda: strategy.buy.orders[1].status == ORDER_STATUS_CANCELED
    )
    await wait_for_condition(
        lambda: strategy.buy.orders[2].status == ORDER_STATUS_CANCELED
    )

    assert strategy.buy.orders[0].realized_quantity == 0.12
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "PARTIALLY_BOUGHT"
    )

    # Validate using comprehensive helper methods from simulator
    sim.validate_parent(
        "1000",
        quantity="0.12",
        realized_quantity="0.0",
        state="PARTIALLY_BOUGHT",
        buy_price="1400.0",
        quantity_usd="168.0",
        sell_price="0.0",
        expected_return="0.0",
        current_price="0.0",
        net="0.0",
        net_percent="0.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.84921", realized_quantity="0.12", state="PARTIALLY_BOUGHT"
    )
    sim.validate_buy_orders(
        strategy,
        [
            {"realized_quantity": 0.12, "status": ORDER_STATUS_CANCELED},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_CANCELED},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_CANCELED},
        ],
    )
    sim.validate_strategy_state(
        strategy, "PARTIALLY_BOUGHT", expected_buy_state="PARTIALLY_BOUGHT"
    )

    logger.info("HP List after the update: %s", front.hp_list_data)

    # Reopen position
    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )
    sim.new_price(price=1414)

    await wait_for_condition(lambda: strategy.buy.orders[0].status == ORDER_STATUS_NEW)
    assert strategy.buy.orders[1].status == ORDER_STATUS_NEW
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy.orders[0].realized_quantity == 0.12
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
    )

    # Comprehensive validation for resent orders state
    sim.validate_parent(
        "1000",
        quantity="0.12",
        realized_quantity="0.0",
        state="BUYING",
        buy_price="1400.0",
        quantity_usd="168.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.84921", realized_quantity="0.12", state="PARTIALLY_BOUGHT"
    )
    sim.validate_buy_orders(
        strategy,
        [
            {"realized_quantity": 0.12, "status": ORDER_STATUS_NEW},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_NEW},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_NEW},
        ],
    )
    sim.validate_strategy_state(
        strategy, "BUYING", expected_buy_state="PARTIALLY_BOUGHT"
    )


async def test_default_position_first_order_filled_then_cancel_then_resend(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()  # Simulate first buy order fill
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    assert strategy.buy.orders_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert len(strategy.buy.orders) == 3

    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED

    await wait_for_condition(
        condition_func=lambda: strategy.buy.orders[1].status == ORDER_STATUS_CANCELED
    )
    assert strategy.buy.orders[2].status == ORDER_STATUS_CANCELED

    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "PARTIALLY_BOUGHT"
    )

    # Validate using comprehensive helper methods from simulator
    sim.validate_parent(
        "1000",
        quantity="0.24",
        realized_quantity="0.0",
        state="PARTIALLY_BOUGHT",
        buy_price="1400.0",
        quantity_usd="336.0",
        sell_price="0.0",
        expected_return="0.0",
        current_price="0.0",
        net="0.0",
        net_percent="0.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.84921", realized_quantity="0.24", state="PARTIALLY_BOUGHT"
    )
    sim.validate_buy_orders(
        strategy,
        [
            {"realized_quantity": 0.24, "status": ORDER_STATUS_FILLED},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_CANCELED},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_CANCELED},
        ],
    )
    sim.validate_strategy_state(
        strategy, "PARTIALLY_BOUGHT", expected_buy_state="PARTIALLY_BOUGHT"
    )

    logger.info("HP List after the update: %s", front.hp_list_data)

    # Reopen position
    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )

    # Price trigger is now related to the middle order as the top order is already filled.
    sim.new_price(price=1212)

    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    await wait_for_condition(lambda: strategy.buy.orders[1].status == ORDER_STATUS_NEW)
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
    )

    # Comprehensive validation for resent orders state (first order filled scenario)
    sim.validate_parent(
        "1000",
        quantity="0.24",
        realized_quantity="0.0",
        state="BUYING",
        buy_price="1400.0",
        quantity_usd="336.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.84921", realized_quantity="0.24", state="PARTIALLY_BOUGHT"
    )
    sim.validate_buy_orders(
        strategy,
        [
            {"realized_quantity": 0.24, "status": ORDER_STATUS_FILLED},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_NEW},
            {"realized_quantity": 0.0, "status": ORDER_STATUS_NEW},
        ],
    )
    sim.validate_strategy_state(
        strategy, "BUYING", expected_buy_state="PARTIALLY_BOUGHT"
    )


async def test_setup_sell_position_for_bought_position(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)
    await sim.simulate_bought_position()

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.85,
        buy_price=1178.82,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    # Comprehensive validation for sell position setup
    strategy = back.strategies["1000"]
    sim.validate_parent(
        "1000",
        quantity="0.85",
        realized_quantity="0.0",
        state="BOUGHT",
        buy_price="1178.82",
        sell_price="4200.0",
        quantity_usd="1002.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.84921", realized_quantity="0.85", state="BOUGHT"
    )
    sim.validate_child_sell(
        "1000",
        quantity="0.85",
        realized_quantity="0.0",
        state="NEW",
        sell_price="4200.0",
    )
    sim.validate_strategy_state(strategy, "BOUGHT")


async def test_send_sell_order_for_bought_position(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)
    await sim.simulate_bought_position()
    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.85,
        buy_price=1178.82,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    strategy = back.strategies["1000"]

    strategy.client.create_order.side_effect = get_new_orders(
        [strategy.sell.current_position.sell_order]
    )
    sim.new_price(price=4156)

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "SELLING"
    )
    # Validate using comprehensive helper methods from simulator
    sim.validate_parent(
        "1000",
        quantity="0.85",
        realized_quantity="0.0",
        state="SELLING",
        buy_price="1178.82",
        sell_price="4200.0",
        quantity_usd="1002.0",
        expected_return="2568.0",
        current_price="0.0",
        net="0.0",
        net_percent="0.0",
    )

    await wait_for_condition(
        condition_func=lambda: strategy.sell.current_position.sell_order.status
        == ORDER_STATUS_NEW
    )
    assert strategy.sell.current_position.sell_order.quantity == 0.85
    assert strategy.sell.current_position.sell_order.realized_quantity == 0.0

    # Validate sell child based on the hierarchical approach - try both patterns
    sim.validate_child_sell(
        "1000",
        quantity="0.85",
        realized_quantity="0.0",
        state="SELLING",
        sell_price="4200.0",
    )


async def test_cancel_unfilled_sell_orders(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)
    await sim.simulate_bought_position()

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.85,
        buy_price=1178.82,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_bought_position()

    # Cancel unfilled sell orders
    await sim.cancel_unfilled_sell_position()


async def test_resend_unfilled_sell_orders(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)
    await sim.simulate_bought_position()

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.85,
        buy_price=1178.82,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_bought_position()

    # Cancel unfilled sell orders
    await sim.cancel_unfilled_sell_position()

    await sim.send_sell_order_for_bought_position()


async def test_sell_position_first_order_filled_partially(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)
    await sim.simulate_bought_position()

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.85,
        buy_price=1178.82,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_bought_position()

    await sim.simulate_sell_order_partial_fill()


async def test_sell_position_first_order_filled(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)
    await sim.simulate_bought_position()

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.85,
        buy_price=1178.82,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_bought_position()

    await sim.simulate_sell_order_fill()


async def test_cancel_sell_position_first_order_filled_partially(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)
    await sim.simulate_bought_position()

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.85,
        buy_price=1178.82,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_bought_position()

    await sim.simulate_sell_order_partial_fill()

    await sim.cancel_partially_sold_position()


async def test_resend_sell_position_first_order_filled_partially(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)
    await sim.simulate_bought_position()

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=0.85,
        buy_price=1178.82,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_bought_position()

    await sim.simulate_sell_order_partial_fill()

    await sim.cancel_partially_sold_position()

    await sim.resend_sell_order_for_partially_sold_position()


async def test_send_sell_order_for_partially_bought_position(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    await sim.setup_sell_position_after_first_buy_order_filled(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()


async def test_cancel_unfilled_sell_orders_for_partially_bought_position(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    await sim.setup_sell_position_after_first_buy_order_filled(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()

    await sim.cancel_unfilled_sell_position_from_part_filled_buy()


async def test_fill_orders_for_previously_partially_bought_position(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    await sim.setup_sell_position_after_first_buy_order_filled(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()

    await sim.cancel_unfilled_sell_position_from_part_filled_buy()

    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )

    # Price trigger is now related to the middle order as the top order is already filled.
    sim.new_price(price=1212)

    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    await wait_for_condition(lambda: strategy.buy.orders[1].status == ORDER_STATUS_NEW)
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
    )

    await sim.simulate_second_buy_order_fill_with_sell_price_no_fill()
    await sim.simulate_third_buy_order_fill_with_sell_price_no_fill()


async def test_sell_partially_partially_bought_position(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    await sim.setup_sell_position_after_first_buy_order_filled(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()

    await sim.simulate_sell_order_partial_fill_from_part_bought()


async def test_buy_partially_partially_sold_position(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    await sim.setup_sell_position_after_first_buy_order_filled(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()

    await sim.simulate_sell_order_partial_fill_from_part_bought()

    # Cancel Sell position
    await sim.cancel_sell_position_filled_partially()

    # Reopen Buy position
    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )

    # Price trigger is now related to the middle order as the top order is already filled.
    sim.new_price(price=1212)

    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    await wait_for_condition(lambda: strategy.buy.orders[1].status == ORDER_STATUS_NEW)
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
    )

    # Buy partially second order
    await sim.simulate_second_buy_order_partial_fill()


async def test_cancel_buy_to_part_sold_part_bought(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    await sim.setup_sell_position_after_first_buy_order_filled(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()

    await sim.simulate_sell_order_partial_fill_from_part_bought()

    # Cancel Sell position
    await sim.cancel_sell_position_filled_partially()

    # Reopen Buy position
    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )

    # Price trigger is now related to the middle order as the top order is already filled.
    sim.new_price(price=1212)

    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    await wait_for_condition(lambda: strategy.buy.orders[1].status == ORDER_STATUS_NEW)
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
    )

    # Buy partially second order
    await sim.simulate_second_buy_order_partial_fill()

    # Cancel Buy orders
    await sim.cancel_buy_position_filled_partially_sold_partially()


async def test_buy_fully_partially_sold_position(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    await sim.setup_sell_position_after_first_buy_order_filled(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()

    await sim.simulate_sell_order_partial_fill_from_part_bought()

    # Cancel Sell position
    await sim.cancel_sell_position_filled_partially()

    # Reopen Buy position
    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )

    # Price trigger is now related to the middle order as the top order is already filled.
    sim.new_price(price=1212)

    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    await wait_for_condition(lambda: strategy.buy.orders[1].status == ORDER_STATUS_NEW)
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
    )

    await sim.simulate_second_buy_order_fill_after_selling_half_of_first_order()
    await sim.simulate_third_buy_order_fill_after_selling_half_of_first_order()


async def test_sell_fully_partially_bought_position(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    await sim.setup_sell_position_after_first_buy_order_filled(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()

    await sim.simulate_sell_order_fill_from_part_bought()


async def test_buy_fully_partially_bought_position_when_sold_position(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    await sim.cancel_buy_position_after_first_order_filled()

    await sim.setup_sell_position_after_first_buy_order_filled(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()

    await sim.simulate_sell_order_fill_from_part_bought()

    # Reopen Buy position
    strategy.client.create_order.side_effect = get_new_orders(
        orders=strategy.buy.orders
    )

    # Price trigger is now related to the middle order as the top order is already filled.
    sim.new_price(price=1212)

    assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
    await wait_for_condition(lambda: strategy.buy.orders[1].status == ORDER_STATUS_NEW)
    assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

    assert strategy.buy.orders[0].realized_quantity == 0.24
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
    )

    await sim.simulate_second_buy_order_fill_after_selling_first_order()
    await sim.simulate_third_buy_order_fill_after_selling_first_order()


async def test_start_new_sell_position_for_two_hop_trade(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    await sim.open_first_sell_position_from_two_hop_trade()


async def test_send_order_for_first_sell_position_in_two_hop_trade(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    await sim.open_first_sell_position_from_two_hop_trade()

    await sim.send_orders_for_first_position_from_two_hop_trade()


async def test_fill_partially_first_sell_position_in_two_hop_trade(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    await sim.open_first_sell_position_from_two_hop_trade()

    await sim.send_orders_for_first_position_from_two_hop_trade()

    await sim.simulate_sell_order_partial_fill_in_first_hop()


async def test_fill_first_sell_position_in_two_hop_trade(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    await sim.open_first_sell_position_from_two_hop_trade()

    await sim.send_orders_for_first_position_from_two_hop_trade()

    await sim.simulate_sell_order_fill_in_first_hop()


async def test_start_second_sell_position_in_two_hop_trade(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    await sim.open_first_sell_position_from_two_hop_trade()

    await sim.send_orders_for_first_position_from_two_hop_trade()

    await sim.simulate_sell_order_fill_in_first_hop()

    await sim.open_second_sell_position_from_two_hop_trade()


async def test_partial_fill_second_sell_position_in_two_hop_trade(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    await sim.open_first_sell_position_from_two_hop_trade()

    await sim.send_orders_for_first_position_from_two_hop_trade()

    await sim.simulate_sell_order_fill_in_first_hop()

    await sim.open_second_sell_position_from_two_hop_trade()

    await sim.simulate_sell_order_partial_fill_in_second_hop()


async def test_fill_second_sell_position_in_two_hop_trade(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    await sim.open_first_sell_position_from_two_hop_trade()

    await sim.send_orders_for_first_position_from_two_hop_trade()

    await sim.simulate_sell_order_fill_in_first_hop()

    await sim.open_second_sell_position_from_two_hop_trade()

    await sim.simulate_sell_order_fill_in_second_hop()


async def test_no_sell_orders_send_if_buy_position_not_realized(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    strategy = back.strategies["1000"]
    sell_config = HPSellData(
        config=HPSellConfig(
            hp_id="1000",
            coin="BTC",
            buy_price=0.0,
            sell_price=4200.0,
            quantity=0.0,
            symbol_info=SymbolInfo(symbol="BTCUSDC", precision=2, price_precision=2),
        ),
        state_info=StateInfo(side=PositionSide.SHORT),
    )
    front.config_queue.put_nowait(sell_config)
    logger.info("Sell config added to the queue: %s", sell_config.config)

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["sell_price"] == "4200.0"
    )

    item = front.hp_list_data[0]
    assert item["hp_id"] == "1000"
    assert item["coin"] == "BTCUSD"
    assert item["buy_price"] == "1400.0", item["buy_price"]
    assert item["quantity"] == "0.0"
    assert item["quantity_usd"] == "0.0"
    assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "NEW"

    await wait_for_condition(
        condition_func=lambda: back.strategies["1000"].sell.current_position.sell_order
    )

    sim.new_price(price=4200.0)

    await asyncio.sleep(0.1)

    item = front.hp_list_data[0]
    assert item["hp_id"] == "1000"
    assert item["coin"] == "BTCUSD"
    assert item["buy_price"] == "1400.0", item["buy_price"]
    assert item["quantity"] == "0.0"
    assert item["quantity_usd"] == "0.0"
    assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "NEW"


async def test_sell_orders_send_if_buy_position_realized_partially(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    strategy = back.strategies["1000"]
    sell_config = HPSellData(
        config=HPSellConfig(
            hp_id="1000",
            coin="BTC",
            buy_price=0.0,
            sell_price=4200.0,
            quantity=0.0,
            symbol_info=SymbolInfo(symbol="BTCUSDC", precision=2, price_precision=2),
        ),
        state_info=StateInfo(side=PositionSide.SHORT),
    )
    front.config_queue.put_nowait(sell_config)
    logger.info("Sell config added to the queue: %s", sell_config.config)

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["sell_price"] == "4200.0"
    )

    item = front.hp_list_data[0]
    assert item["hp_id"] == "1000"
    assert item["coin"] == "BTCUSD"
    assert item["buy_price"] == "1400.0", item["buy_price"]
    assert item["quantity"] == "0.0"
    assert item["quantity_usd"] == "0.0"
    assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "NEW"

    await wait_for_condition(
        condition_func=lambda: back.strategies["1000"].sell.current_position.sell_order
    )

    await sim.move_to_position_active_buy()  # Simulate partial fill
    strategy = await sim.simulate_partial_fill_with_sell_price()

    # Cancel position
    assert strategy.buy.orders_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert len(strategy.buy.orders) == 3

    await wait_for_condition(
        lambda: strategy.buy.orders[0].status == ORDER_STATUS_CANCELED
    )
    await wait_for_condition(
        lambda: strategy.buy.orders[1].status == ORDER_STATUS_CANCELED
    )
    await wait_for_condition(
        lambda: strategy.buy.orders[2].status == ORDER_STATUS_CANCELED
    )

    assert strategy.buy.orders[0].realized_quantity == 0.12
    assert strategy.buy.orders[1].realized_quantity == 0.0
    assert strategy.buy.orders[2].realized_quantity == 0.0

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "PARTIALLY_BOUGHT"
    )

    item = front.hp_list_data[0]
    assert item["hp_id"] == "1000"
    assert item["coin"] == "BTCUSD"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.12"
    assert item["quantity_usd"] == "168.0"
    assert item["sell_price"] == "4200.0"
    assert item["expected_return"] == "336.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "PARTIALLY_BOUGHT"

    logger.info("HP List after the update: %s", front.hp_list_data)

    strategy.client.create_order.side_effect = get_new_orders(
        orders=[strategy.sell.current_position.sell_order]
    )
    sim.new_price(price=4200.0)

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "SELLING"
    )

    item = front.hp_list_data[0]
    assert item["hp_id"] == "1000"
    assert item["coin"] == "BTCUSD"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.12"
    assert item["quantity_usd"] == "168.0"
    assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
    assert item["expected_return"] == "336.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "SELLING"


async def test_default_convert_position(frontend_backend_setup):
    front, back = frontend_backend_setup
    sim = HPSimulator(front=front, back=back)

    buy_price = 10.0
    sell_price = 12.0
    quantity = 100.0

    # Simulate convert-only position (DYM/USDC)
    await sim.simulate_convert_only_position(
        coin="DYM",
        buy_price=buy_price,
        sell_price=sell_price,
        quantity=quantity,
    )

    # Wait for frontend to reflect the convert-only position
    await wait_for_condition(condition_func=lambda: front.hp_list_data)
    item = front.hp_list_data[0]
    # Find the convert-only item
    assert item["buy_price"] == str(buy_price), f"buy price: {item['buy_price']}"
    assert item["quantity"] == str(quantity), f"quantity: {item['quantity']}"
    assert item["quantity_usd"] == str(
        round(quantity * buy_price, 2)
    ), f"quantity_usd: {item['quantity_usd']}"
    assert item["sell_price"] == str(sell_price), f"sell price: {item['sell_price']}"
    assert item["expected_return"] == "200.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "BOUGHT"

    strategy = back.strategies["1000"]

    # Mock convert quote/accept methods on the client
    convert_quote_result = {
        "quoteId": "mock-quote-id",
        "fromAsset": "DYM",
        "toAsset": "USDC",
        "fromAmount": str(quantity),
        "toAmount": str(round(quantity * sell_price, 2)),
        "ratio": str(sell_price),
    }
    convert_accept_result = {
        "orderId": "mock-convert-order-id",
        "status": "SUCCESS",
        "filledAmount": str(quantity),
        "receivedAmount": str(round(quantity * sell_price, 2)),
    }
    strategy.client.convert_request_quote = AsyncMock(return_value=convert_quote_result)
    strategy.client.convert_accept_quote = AsyncMock(return_value=convert_accept_result)

    # Trigger conversion by price
    sim.new_price(price=12.0, symbol="DYMUSDT")

    # Wait for conversion to be reflected in frontend
    await wait_for_condition(lambda: front.hp_list_data[0]["state"] == "SOLD")

    # Wait for realized_quantity to be updated
    await wait_for_condition(
        lambda: front.hp_list_data[0]["realized_quantity"] == str(quantity)
    )

    item = front.hp_list_data[0]
    assert item["state"] == "SOLD"
    assert item["quantity"] == str(
        quantity
    ), f"quantity: {item['quantity']}"  # Should remain original quantity
    assert item["realized_quantity"] == str(
        quantity
    ), f"realized_quantity: {item['realized_quantity']}"  # Should show what was sold
    assert item["quantity_usd"] == str(
        round(quantity * buy_price, 2)
    ), f"quantity_usd: {item['quantity_usd']}"  # Should remain original USD value
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["buy_price"] == str(buy_price)
    assert item["sell_price"] == str(sell_price)
    assert item["expected_return"] == "200.0"


async def test_convert_position_spread_too_high(frontend_backend_setup):
    front, back = frontend_backend_setup
    sim = HPSimulator(front=front, back=back)

    buy_price = 10.0
    sell_price = 12.0
    quantity = 100.0

    # Simulate convert-only position (DYM/USDC)
    await sim.simulate_convert_only_position(
        coin="DYM",
        buy_price=buy_price,
        sell_price=sell_price,
        quantity=quantity,
    )

    # Wait for frontend to reflect the convert-only position
    await wait_for_condition(condition_func=lambda: front.hp_list_data)
    item = front.hp_list_data[0]
    assert item["state"] == "BOUGHT"

    strategy = back.strategies["1000"]

    # Mock convert quote/accept methods on the client with a high spread (market price much lower than effective price)
    convert_quote_result = {
        "quoteId": "mock-quote-id",
        "fromAsset": "DYM",
        "toAsset": "USDC",
        "fromAmount": str(quantity),
        "toAmount": "1162.32",
    }
    strategy.client.convert_request_quote = AsyncMock(return_value=convert_quote_result)

    # Set a market price much lower than the effective price to create a spread > 1%
    sim.new_price(price=12.0, symbol="DYMUSDT")

    # Wait a short time to ensure no state change
    await asyncio.sleep(0.2)
    item = front.hp_list_data[0]
    assert (
        item["state"] == "BOUGHT"
    ), f"Expected state to remain BOUGHT, got {item['state']}"
    assert item["quantity"] == str(quantity)
    assert item["quantity_usd"] == str(round(quantity * buy_price, 2))
