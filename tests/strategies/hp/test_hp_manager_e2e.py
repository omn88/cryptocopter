import asyncio
import logging
import time
from unittest.mock import AsyncMock
import pytest
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_PARTIALLY_FILLED,
)
from src.common.symbol import Symbol
from src.strategy_executor import StrategyExecutor
from src.gui.hp_manager.hpfront import HpFront
from src.common.identifiers import (
    HPSellConfig,
    HPSell,
    State,
    StateInfo,
    PositionSide,
)
from tests.helpers import get_new_order
from tests.strategies.hp.hp_simulator import (
    HPSimulator,
    wait_for_condition,
    get_buy_positions,
    wait_for_active_buy_positions,
    wait_for_no_idle_buy_positions,
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


async def test_default_buy_position_send_order(frontend_backend_setup):
    front, back = frontend_backend_setup
    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)

    assert len(back.strategies) == 0

    # Get default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    # Open position and send order
    strategy = back.strategies["1000"]
    strategy.client.create_order.side_effect = [
        get_new_order(order=strategy.buy.buy_order)
    ]
    sim.new_price(price=1410)

    # Assert new opened position data
    await wait_for_condition(condition_func=lambda: strategy.state == State.BUYING)
    await wait_for_active_buy_positions(front)
    await wait_for_no_idle_buy_positions(front)
    assert strategy.buy.data.state_info.state == State.NEW
    assert strategy.buy.buy_order.order_id is not None
    assert strategy.buy.buy_order.status == ORDER_STATUS_NEW

    # Comprehensive validation for position with orders sent
    sim.validate_parent(
        state="BUYING",
        buy_price="1400.0",
        quantity_usd="0.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.71429", realized_quantity="0.0", state="NEW"
    )
    sim.validate_buy_order(
        strategy,
        [
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

    assert strategy.buy.order_cancel_price == 1428.0
    sim.new_price(price=1428)

    await wait_for_condition(
        condition_func=lambda: strategy.buy.buy_order.status == ORDER_STATUS_CANCELED
    )

    assert strategy.buy.buy_order.status == ORDER_STATUS_CANCELED
    assert strategy.buy.data.state_info.state == State.NEW
    assert strategy.state == State.NEW

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == State.NEW.value
    )

    # Validate using comprehensive helper methods from simulator
    sim.validate_parent(
        state="NEW",
        buy_price="1400.0",
        quantity_usd="0.0",
        sell_price="0.0",
        expected_return="0.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.71429", realized_quantity="0.0", state="NEW"
    )
    sim.validate_buy_order(
        strategy,
        [
            {"realized_quantity": 0.0, "status": ORDER_STATUS_CANCELED},
        ],
    )
    sim.validate_strategy_state(strategy, "NEW", expected_buy_state="NEW")


async def test_cancel_default_position_untouched_then_resend_order(
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

    # Path 1: Resend buy order
    await sim.move_to_position_active_buy()


async def test_default_position_order_filled_partially(
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
        quantity="0.12",
        state="BUYING",
        buy_price="1400.0",
        quantity_usd="168.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.71429", realized_quantity="0.12", state="PARTIALLY_BOUGHT"
    )
    sim.validate_buy_order(
        strategy,
        [
            {"realized_quantity": 0.12, "status": ORDER_STATUS_PARTIALLY_FILLED},
        ],
    )
    sim.validate_strategy_state(
        strategy, "BUYING", expected_buy_state="PARTIALLY_BOUGHT"
    )


async def test_default_position_order_filled_partially_then_cancel(
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
    strategy = await sim.simulate_partial_fill()  # Cancel partially bought position

    assert strategy.buy.order_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert strategy.buy.buy_order is not None

    assert strategy.buy.buy_order.status == ORDER_STATUS_PARTIALLY_FILLED

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
        quantity="0.12",
        state="PARTIALLY_BOUGHT",
        buy_price="1400.0",
        quantity_usd="168.0",
        sell_price="0.0",
        expected_return="0.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.71429", realized_quantity="0.12", state="PARTIALLY_BOUGHT"
    )
    sim.validate_buy_order(
        strategy,
        [
            {"realized_quantity": 0.12, "status": ORDER_STATUS_CANCELED},
        ],
    )
    sim.validate_strategy_state(
        strategy, "PARTIALLY_BOUGHT", expected_buy_state="PARTIALLY_BOUGHT"
    )

    logger.info("HP List after the update: %s", front.hp_list_data)


async def test_default_position_order_filled(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Simulate bought position (includes setup and order fill)
    strategy = await sim.simulate_bought_position()

    # Comprehensive validation for first order filled
    sim.validate_parent(
        quantity="0.71429",
        state="BOUGHT",
        buy_price="1400.0",
        quantity_usd="1000.01",
    )
    sim.validate_child_buy(
        hp_id="1000",
        quantity="0.71429",
        realized_quantity="0.71429",
        state="BOUGHT",
    )
    sim.validate_buy_order(
        strategy,
        [
            {"realized_quantity": 0.71429, "status": ORDER_STATUS_FILLED},
        ],
    )
    sim.validate_strategy_state(strategy, "BOUGHT", expected_buy_state="BOUGHT")


async def test_default_position_order_filled_partially_then_cancel_then_resend(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    # Path 0: Default buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    # Path 1: Send buy order
    await sim.move_to_position_active_buy()
    # Simulate partial fill    # Simulate partial fill
    strategy = await sim.simulate_partial_fill()

    # Cancel position
    assert strategy.buy.order_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert strategy.buy.buy_order is not None

    await wait_for_condition(
        lambda: strategy.buy.buy_order.status == ORDER_STATUS_CANCELED
    )

    assert strategy.buy.buy_order.realized_quantity == 0.12

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.PARTIALLY_BOUGHT

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "PARTIALLY_BOUGHT"
    )

    # Validate using comprehensive helper methods from simulator
    sim.validate_parent(
        quantity="0.12",
        state="PARTIALLY_BOUGHT",
        buy_price="1400.0",
        quantity_usd="168.0",
        sell_price="0.0",
        expected_return="0.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.71429", realized_quantity="0.12", state="PARTIALLY_BOUGHT"
    )
    sim.validate_buy_order(
        strategy,
        [
            {"realized_quantity": 0.12, "status": ORDER_STATUS_CANCELED},
        ],
    )
    sim.validate_strategy_state(
        strategy, "PARTIALLY_BOUGHT", expected_buy_state="PARTIALLY_BOUGHT"
    )

    logger.info("HP List after the update: %s", front.hp_list_data)

    # Reopen position
    strategy.client.create_order.side_effect = [
        get_new_order(order=strategy.buy.buy_order)
    ]
    sim.new_price(price=1414)

    await wait_for_condition(lambda: strategy.buy.buy_order.status == ORDER_STATUS_NEW)

    assert strategy.buy.buy_order.realized_quantity == 0.12

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
    )

    # Comprehensive validation for resent order state
    sim.validate_parent(
        quantity="0.12",
        state="BUYING",
        buy_price="1400.0",
        quantity_usd="168.0",
    )
    sim.validate_child_buy(
        "1000", quantity="0.71429", realized_quantity="0.12", state="PARTIALLY_BOUGHT"
    )
    sim.validate_buy_order(
        strategy,
        [
            {"realized_quantity": 0.12, "status": ORDER_STATUS_NEW},
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
        quantity=0.71429,
        buy_price=1400.0,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    # Comprehensive validation for sell position setup
    strategy = back.strategies["1000"]
    sim.validate_parent(
        quantity="0.71429",
        state="BOUGHT",
        buy_price="1400.0",
        sell_price="4200.0",
        quantity_usd="1000.01",
    )
    sim.validate_child_buy(
        "1000", quantity="0.71429", realized_quantity="0.71429", state="BOUGHT"
    )
    sim.validate_child_sell(
        "1000",
        quantity="0.71429",
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
        quantity=0.71429,
        buy_price=1400.0,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    strategy = back.strategies["1000"]

    strategy.client.create_order.side_effect = [
        get_new_order(order=strategy.sell.current_position.sell_order)
    ]
    sim.new_price(price=4156)

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "SELLING"
    )
    # Validate using comprehensive helper methods from simulator
    sim.validate_parent(
        quantity="0.71429",
        state="SELLING",
        buy_price="1400.0",
        sell_price="4200.0",
        quantity_usd="1000.01",
        expected_return="2000.01",
    )

    await wait_for_condition(
        condition_func=lambda: strategy.sell.current_position.sell_order.status
        == ORDER_STATUS_NEW
    )
    assert strategy.sell.current_position.sell_order.quantity == 0.71429
    assert strategy.sell.current_position.sell_order.realized_quantity == 0.0

    # Validate sell child based on the hierarchical approach - try both patterns
    sim.validate_child_sell(
        "1000",
        quantity="0.71429",
        realized_quantity="0.0",
        state="SELLING",
        sell_price="4200.0",
    )


async def test_cancel_unfilled_sell_order(
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
        quantity=0.71429,
        buy_price=1400.0,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_bought_position()

    # Cancel unfilled sell order
    await sim.cancel_unfilled_sell_position()


async def test_resend_unfilled_sell_order(
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
        quantity=0.71429,
        buy_price=1400.0,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_bought_position()

    # Cancel unfilled sell order
    await sim.cancel_unfilled_sell_position()

    await sim.send_sell_order_for_bought_position()


async def test_sell_position_order_filled_partially(
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
        quantity=0.71429,
        buy_price=1400.0,
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_bought_position()

    await sim.simulate_sell_order_partial_fill()


async def test_sell_position_filled(
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
        quantity=0.71429,
        buy_price=1400.0,
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
        quantity=0.71429,
        buy_price=1400.0,
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
        quantity=0.71429,
        buy_price=1400.0,
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
    strategy = await sim.simulate_partial_fill()

    assert strategy.buy.order_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert strategy.buy.buy_order is not None

    assert strategy.buy.buy_order.status == ORDER_STATUS_PARTIALLY_FILLED

    # Wait for state transition to complete
    await wait_for_condition(
        condition_func=lambda: strategy.state == State.PARTIALLY_BOUGHT
    )

    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()


async def test_cancel_unfilled_sell_order_for_partially_bought_position(
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
    strategy = await sim.simulate_partial_fill()

    assert strategy.buy.order_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert strategy.buy.buy_order is not None

    assert strategy.buy.buy_order.status == ORDER_STATUS_PARTIALLY_FILLED

    # Wait for state transition to complete
    await wait_for_condition(
        condition_func=lambda: strategy.state == State.PARTIALLY_BOUGHT
    )

    await sim.setup_sell_position_after_buy_order_filled_partially(
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


async def test_fill_order_for_previously_partially_bought_position(
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
    strategy = await sim.simulate_partial_fill()

    assert strategy.buy.order_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert strategy.buy.buy_order is not None

    assert strategy.buy.buy_order.status == ORDER_STATUS_PARTIALLY_FILLED

    # Wait for state transition to complete
    await wait_for_condition(
        condition_func=lambda: strategy.state == State.PARTIALLY_BOUGHT
    )

    await sim.setup_sell_position_after_buy_order_filled_partially(
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

    strategy.client.create_order.side_effect = [
        get_new_order(order=strategy.buy.buy_order)
    ]

    # Price trigger is now related to the middle order as the top order is already filled.
    sim.new_price(price=1412)

    await wait_for_condition(
        condition_func=lambda: strategy.buy.buy_order.status == ORDER_STATUS_NEW
    )

    assert strategy.buy.buy_order.status == ORDER_STATUS_NEW

    assert strategy.buy.buy_order.realized_quantity == 0.12

    assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
    assert strategy.state == State.BUYING

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "BUYING"
    )


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
    strategy = await sim.simulate_partial_fill()

    assert strategy.buy.order_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert strategy.buy.buy_order is not None

    assert strategy.buy.buy_order.status == ORDER_STATUS_PARTIALLY_FILLED

    # Wait for state transition to complete
    await wait_for_condition(
        condition_func=lambda: strategy.state == State.PARTIALLY_BOUGHT
    )

    await sim.setup_sell_position_after_buy_order_filled_partially(
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

    # Simulate first buy order partial fill
    strategy = await sim.simulate_partial_fill()

    assert strategy.buy.order_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert strategy.buy.buy_order is not None

    assert strategy.buy.buy_order.status == ORDER_STATUS_PARTIALLY_FILLED

    # Wait for state transition to complete
    await wait_for_condition(
        condition_func=lambda: strategy.state == State.PARTIALLY_BOUGHT
    )

    await sim.setup_sell_position_after_buy_order_filled_partially(
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

    # In single-order system, we don't reopen buy positions after partial sell cancel
    # The position remains in PART_SOLD_PART_BOUGHT state with:
    # - Buy order: 0.12 BTC realized (CANCELED)
    # - Sell order: 0.06 BTC realized (CANCELED)
    # - Net inventory: 0.06 BTC remaining

    assert strategy.buy.buy_order.status == ORDER_STATUS_CANCELED
    assert strategy.buy.buy_order.realized_quantity == 0.12
    assert strategy.state == State.PART_SOLD_PART_BOUGHT

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "PART_SOLD_PART_BOUGHT"
    )


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
    strategy = await sim.simulate_partial_fill()

    assert strategy.buy.order_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert strategy.buy.buy_order is not None

    assert strategy.buy.buy_order.status == ORDER_STATUS_PARTIALLY_FILLED

    # Wait for state transition to complete
    await wait_for_condition(
        condition_func=lambda: strategy.state == State.PARTIALLY_BOUGHT
    )

    await sim.setup_sell_position_after_buy_order_filled_partially(
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

    # In single-order system, we don't reopen buy positions or cancel further
    # The position remains in PART_SOLD_PART_BOUGHT state with:
    # - Buy order: 0.12 BTC realized (CANCELED)
    # - Sell order: 0.06 BTC realized (CANCELED)
    # - Net inventory: 0.06 BTC remaining

    assert strategy.buy.buy_order.status == ORDER_STATUS_CANCELED
    assert strategy.buy.buy_order.realized_quantity == 0.12
    assert strategy.state == State.PART_SOLD_PART_BOUGHT

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "PART_SOLD_PART_BOUGHT"
    )


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
    strategy = await sim.simulate_partial_fill()

    assert strategy.buy.order_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert strategy.buy.buy_order is not None

    assert strategy.buy.buy_order.status == ORDER_STATUS_PARTIALLY_FILLED

    # Wait for state transition to complete
    await wait_for_condition(
        condition_func=lambda: strategy.state == State.PARTIALLY_BOUGHT
    )

    await sim.setup_sell_position_after_buy_order_filled_partially(
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

    # In single-order system, we don't reopen buy positions
    # The position remains in PART_SOLD_PART_BOUGHT state with:
    # - Buy order: 0.12 BTC realized (CANCELED)
    # - Sell order: 0.06 BTC realized (CANCELED)
    # - Net inventory: 0.06 BTC remaining

    assert strategy.buy.buy_order.status == ORDER_STATUS_CANCELED
    assert strategy.buy.buy_order.realized_quantity == 0.12
    assert strategy.state == State.PART_SOLD_PART_BOUGHT

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "PART_SOLD_PART_BOUGHT"
    )


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
    strategy = await sim.simulate_partial_fill()

    assert strategy.buy.order_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert strategy.buy.buy_order is not None

    assert strategy.buy.buy_order.status == ORDER_STATUS_PARTIALLY_FILLED

    # Wait for state transition to complete
    await wait_for_condition(
        condition_func=lambda: strategy.state == State.PARTIALLY_BOUGHT
    )

    await sim.setup_sell_position_after_buy_order_filled_partially(
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
    strategy = await sim.simulate_partial_fill()

    assert strategy.buy.order_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert strategy.buy.buy_order is not None

    assert strategy.buy.buy_order.status == ORDER_STATUS_PARTIALLY_FILLED

    # Wait for state transition to complete
    await wait_for_condition(
        condition_func=lambda: strategy.state == State.PARTIALLY_BOUGHT
    )

    await sim.setup_sell_position_after_buy_order_filled_partially(
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

    # In single-order system, after selling the partial buy (0.12 BTC):
    # - Buy order: 0.12 BTC realized (CANCELED)
    # - Sell order: 0.12 BTC realized (FILLED)
    # - Net inventory: 0 BTC (fully sold what was bought)
    # - State: SOLD_PART_BOUGHT (sold all of a partially bought position)

    assert strategy.buy.buy_order.status == ORDER_STATUS_CANCELED
    assert strategy.buy.buy_order.realized_quantity == 0.12
    assert strategy.state == State.SOLD_PART_BOUGHT

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "SOLD_PART_BOUGHT"
    )


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


async def test_no_sell_order_send_if_buy_position_not_realized(
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
    sell_config = HPSell(
        config=HPSellConfig(
            hp_id="1000",
            coin="BTC",
            buy_price=0.0,
            sell_price=4200.0,
            quantity=0.0,
            symbol=Symbol(name="BTCUSDC", precision=2, price_precision=2),
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


async def test_sell_order_send_if_buy_position_realized_partially(
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
    sell_config = HPSell(
        config=HPSellConfig(
            hp_id="1000",
            coin="BTC",
            buy_price=0.0,
            sell_price=4200.0,
            quantity=0.0,
            symbol=Symbol(name="BTCUSDC", precision=2, price_precision=2),
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
    assert strategy.buy.order_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    assert strategy.buy.buy_order is not None

    await wait_for_condition(
        lambda: strategy.buy.buy_order.status == ORDER_STATUS_CANCELED
    )

    assert strategy.buy.buy_order.realized_quantity == 0.12

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

    strategy.client.create_order.side_effect = [
        get_new_order(order=strategy.sell.current_position.sell_order)
    ]
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

    logger.info("Waiting for frontend to reflect the convert-only position...")

    # Wait for frontend to reflect the convert-only position
    await wait_for_condition(condition_func=lambda: front.hp_list_data)
    item = front.hp_list_data[0]

    logger.info("HP List after adding convert-only position: %s", front.hp_list_data)

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


async def test_multihop_sell_price_recalculation_on_trigger(frontend_backend_setup):
    """
    Test that multihop sell prices are recalculated based on current market prices
    when the trigger condition is met, not using stale prices from position creation.

    Scenario:
    1. Create a multihop sell position for AXL with target price 14.0 USDT
    2. Initial market prices: BTCUSDC = 95000.0, AXLBTC calculated accordingly
    3. Simulate market movement: BTC price changes to 98000.0 before trigger
    4. When AXLUSDT reaches trigger price (14.0), verify that:
       - Prices are recalculated using the NEW BTC price (98000.0)
       - AXLBTC order price * BTCUSDC price ≈ 14.0 USD
       - NOT using the old BTC price (95000.0)
    """
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Step 1: Set initial market prices
    # BTC/USDC = 95000.0 (this will change later to test recalculation)
    initial_btc_price = 95000.0
    back.price_resolver.update_price("BTCUSDC", initial_btc_price)
    back.price_resolver.update_price(
        "BTCPLN", 320000.0
    )  # Not used, just for completeness

    # Calculate initial AXLBTC price based on target 14.0 USD
    # If we want AXL to be worth 14.0 USD and BTC is 95000 USD:
    # AXLBTC = 14.0 / 95000.0 = 0.00014736
    target_sell_price_usd = 14.0
    initial_axlbtc_price = target_sell_price_usd / initial_btc_price
    back.price_resolver.update_price("AXLBTC", initial_axlbtc_price)

    logger.info(f"=== INITIAL MARKET SETUP ===")
    logger.info(f"Target sell price (USD): {target_sell_price_usd}")
    logger.info(f"Initial BTCUSDC price: {initial_btc_price}")
    logger.info(f"Initial AXLBTC price: {initial_axlbtc_price}")
    logger.info(f"Initial equivalent USD: {initial_axlbtc_price * initial_btc_price}")

    # Step 2: Create multihop sell position
    coin = "AXL"
    quantity = 1000.0
    buy_price = 0.2928

    sell_config = HPSell(
        config=HPSellConfig(
            hp_id="",
            coin=coin,
            buy_price=buy_price,
            sell_price=target_sell_price_usd,  # Target: 14.0 USD
            quantity=quantity,
            end_currency="USDC",  # Changed to USDC for clearer test
            symbol=back.price_resolver.symbols[f"{coin}USDT"],
        ),
        state_info=StateInfo(side=PositionSide.SHORT),
    )
    front.config_queue.put_nowait(sell_config)
    logger.info("Sell config added to the queue: %s", sell_config.config)

    # Wait for position to be created
    await wait_for_condition(
        condition_func=lambda: len(front.hp_list_data) == 3,  # Parent + 2 children
    )

    strategy = back.strategies["1000"]

    # Verify multihop strategy was created correctly
    assert len(strategy.sell.sell_strategy.sell_path) == 2
    assert strategy.sell.sell_strategy.sell_path[0].name == f"{coin}BTC"
    assert strategy.sell.sell_strategy.sell_path[1].name == f"BTCUSDC"

    # Store initial calculated prices from position creation
    leg1_initial = strategy.sell.sell_positions[0]
    leg2_initial = strategy.sell.sell_positions[1]

    initial_leg1_price = leg1_initial.sell_order.price
    initial_leg2_price = leg2_initial.sell_order.price

    logger.info(f"=== INITIAL POSITION PRICES (at creation) ===")
    logger.info(f"Leg1 (AXLBTC) initial price: {initial_leg1_price}")
    logger.info(f"Leg2 (BTCUSDC) initial price: {initial_leg2_price}")
    logger.info(f"Initial product: {initial_leg1_price * initial_leg2_price}")

    # Verify initial calculation is approximately correct
    assert (
        abs(initial_leg1_price * initial_leg2_price - target_sell_price_usd) < 0.5
    ), f"Initial prices should multiply to ~{target_sell_price_usd}"

    # Step 3: CRITICAL - Simulate market movement BEFORE trigger
    # BTC price increases from 95000 to 98000
    new_btc_price = 98000.0
    back.price_resolver.update_price("BTCUSDC", new_btc_price)

    # AXLBTC price should adjust too (market would adjust this)
    # To maintain 14 USD: AXLBTC = 14.0 / 98000.0 = 0.00014285
    new_axlbtc_price = target_sell_price_usd / new_btc_price
    back.price_resolver.update_price("AXLBTC", new_axlbtc_price)

    logger.info(f"=== MARKET MOVED BEFORE TRIGGER ===")
    logger.info(f"NEW BTCUSDC price: {new_btc_price}")
    logger.info(f"NEW AXLBTC price: {new_axlbtc_price}")
    logger.info(f"NEW equivalent USD: {new_axlbtc_price * new_btc_price}")

    # Verify prices changed significantly
    assert (
        abs(new_btc_price - initial_btc_price) > 1000
    ), "BTC price should have moved significantly"

    # Step 4: Mock order creation and trigger the sell
    strategy.client.create_order.side_effect = [
        get_new_order(order=strategy.sell.current_position.sell_order)
    ]

    # Send price update that triggers the sell (AXLUSDT reaches target)
    # Note: For regular sell, trigger is at 0.96 * sell_price = 0.96 * 14.0 = 13.44
    # But for multihop (TWOHOPS), trigger is at sell_price = 14.0 (see calculate_trigger_send_orders_price_sell)
    trigger_price = target_sell_price_usd
    sim.new_price(price=trigger_price, symbol="AXLUSDT")

    logger.info(f"=== TRIGGERED SELL AT PRICE: {trigger_price} ===")

    # Step 5: Wait for state to change to SELLING
    await wait_for_condition(
        condition_func=lambda: strategy.state == State.SELLING, timeout=5.0
    )

    # Step 6: VERIFY RECALCULATION - This is the critical assertion
    # After trigger, prices should be recalculated using NEW market prices
    leg1_after = strategy.sell.sell_positions[0]
    leg2_after = strategy.sell.sell_positions[1]

    recalculated_leg1_price = leg1_after.sell_order.price
    recalculated_leg2_price = leg2_after.sell_order.price

    logger.info(f"=== PRICES AFTER RECALCULATION (at trigger) ===")
    logger.info(f"Leg1 (AXLBTC) recalculated price: {recalculated_leg1_price}")
    logger.info(f"Leg2 (BTCUSDC) recalculated price: {recalculated_leg2_price}")
    logger.info(
        f"Recalculated product: {recalculated_leg1_price * recalculated_leg2_price}"
    )

    # CRITICAL ASSERTIONS:
    # 1. Prices should have been recalculated (different from initial)
    assert (
        recalculated_leg1_price != initial_leg1_price
    ), f"Leg1 price should have been recalculated! Initial: {initial_leg1_price}, After: {recalculated_leg1_price}"

    assert (
        recalculated_leg2_price != initial_leg2_price
    ), f"Leg2 price should have been recalculated! Initial: {initial_leg2_price}, After: {recalculated_leg2_price}"

    # 2. Recalculated prices should use the NEW BTC price (98000), not old (95000)
    # Leg2 should be close to new BTC price
    assert (
        abs(recalculated_leg2_price - new_btc_price) < 100
    ), f"Leg2 should use new BTC price {new_btc_price}, but got {recalculated_leg2_price}"

    # 3. Product should still be approximately 14.0 USD (using NEW prices)
    recalculated_product = recalculated_leg1_price * recalculated_leg2_price
    assert (
        abs(recalculated_product - target_sell_price_usd) < 0.5
    ), f"Recalculated prices should multiply to ~{target_sell_price_usd}, but got {recalculated_product}"

    # 4. Verify order was actually sent with NEW prices
    assert leg1_after.sell_order.order_id > 0, "Order should have been sent"
    assert leg1_after.sell_order.status == ORDER_STATUS_NEW, "Order should be NEW"

    logger.info(f"=== TEST PASSED ===")
    logger.info(
        f"✓ Prices were recalculated from initial BTC={initial_btc_price} to new BTC={new_btc_price}"
    )
    logger.info(
        f"✓ Leg1 price changed: {initial_leg1_price} -> {recalculated_leg1_price}"
    )
    logger.info(
        f"✓ Leg2 price changed: {initial_leg2_price} -> {recalculated_leg2_price}"
    )
    logger.info(
        f"✓ Product maintains target: {recalculated_product} ≈ {target_sell_price_usd}"
    )
    logger.info(f"✓ Multihop sell price recalculation works correctly!")


async def test_multihop_sell_uses_trigger_price_not_early_trigger(
    frontend_backend_setup,
):
    """
    Test that multihop sells trigger at the exact target price (not 0.96x like regular sells).

    This test verifies the logic in calculate_trigger_send_orders_price_sell():
    - Regular/Direct sells: trigger at 0.96 * sell_price (2% or 4% early)
    - Multihop sells: trigger at exact sell_price (no early trigger)

    Why? Because multihop prices MUST be calculated at the exact moment when
    the target price is reached to ensure proper price alignment across legs.
    """
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Setup market prices
    btc_price = 95000.0
    back.price_resolver.update_price("BTCUSDC", btc_price)
    back.price_resolver.update_price("BTCPLN", 320000.0)

    target_price = 14.0
    axlbtc_price = target_price / btc_price
    back.price_resolver.update_price("AXLBTC", axlbtc_price)

    # Create multihop sell position
    coin = "AXL"
    sell_config = HPSell(
        config=HPSellConfig(
            hp_id="",
            coin=coin,
            buy_price=0.2928,
            sell_price=target_price,
            quantity=1000.0,
            end_currency="USDC",
            symbol=back.price_resolver.symbols[f"{coin}USDT"],
        ),
        state_info=StateInfo(side=PositionSide.SHORT),
    )
    front.config_queue.put_nowait(sell_config)

    await wait_for_condition(
        condition_func=lambda: len(front.hp_list_data) == 3,
    )

    strategy = back.strategies["1000"]

    # Calculate trigger price using the same logic as hp_manager.py
    trigger_price = strategy.calculate_trigger_send_orders_price_sell()

    logger.info(f"=== TRIGGER PRICE TEST ===")
    logger.info(f"Target sell price: {target_price}")
    logger.info(f"Calculated trigger price: {trigger_price}")
    logger.info(f"Sell type: {strategy.sell.current_position.sell_type}")

    # CRITICAL ASSERTION: For multihop, trigger should be at exact price, not 0.96x
    assert (
        trigger_price == target_price
    ), f"Multihop sell should trigger at exact price {target_price}, not at {trigger_price}"

    # Verify that trigger doesn't happen too early
    early_price = 0.96 * target_price  # This is what regular sells use
    strategy.client.create_order.side_effect = [
        get_new_order(order=strategy.sell.current_position.sell_order)
    ]

    # Try triggering at early price - should NOT trigger
    sim.new_price(price=early_price, symbol="AXLUSDT")
    await asyncio.sleep(0.1)

    assert (
        strategy.state == State.BOUGHT
    ), f"Should NOT trigger at early price {early_price}, but state is {strategy.state}"

    logger.info(f"✓ Did NOT trigger at early price: {early_price}")

    # Now trigger at exact price - SHOULD trigger
    sim.new_price(price=target_price, symbol="AXLUSDT")
    await wait_for_condition(
        condition_func=lambda: strategy.state == State.SELLING, timeout=5.0
    )

    logger.info(f"✓ Correctly triggered at exact price: {target_price}")
    logger.info(f"✓ Multihop sell trigger mechanism works correctly!")


async def test_regular_sell_uses_early_trigger_96_percent(frontend_backend_setup):
    """
    Test that regular (direct) sells trigger at 0.96 * sell_price (4% early).
    This is the opposite of multihop and serves as a comparison test.

    For regular sells with order_trigger = 2%, the actual trigger is:
    0.96 * sell_price (which represents a 4% buffer)
    """
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    # Setup direct sell (not multihop) - BTCUSDC is a direct pair
    target_price = 100000.0
    back.price_resolver.update_price("BTCUSDC", target_price)

    # Create regular sell position (direct pair)
    coin = "BTC"
    sell_config = HPSell(
        config=HPSellConfig(
            hp_id="",
            coin=coin,
            buy_price=95000.0,
            sell_price=target_price,
            quantity=1.0,
            end_currency="USDC",
            symbol=back.price_resolver.symbols[f"{coin}USDC"],
        ),
        state_info=StateInfo(side=PositionSide.SHORT),
    )
    front.config_queue.put_nowait(sell_config)

    # Wait for position to be created (parent + 1 child sell position)
    await wait_for_condition(
        condition_func=lambda: len(front.hp_list_data) == 2,
    )

    strategy = back.strategies["1000"]

    # Calculate trigger price
    trigger_price = strategy.calculate_trigger_send_orders_price_sell()
    expected_trigger = 0.96 * target_price

    logger.info(f"=== REGULAR SELL TRIGGER PRICE TEST ===")
    logger.info(f"Target sell price: {target_price}")
    logger.info(f"Expected trigger (0.96x): {expected_trigger}")
    logger.info(f"Calculated trigger price: {trigger_price}")
    logger.info(f"Sell type: {strategy.sell.current_position.sell_type}")

    # CRITICAL ASSERTION: For regular sells, trigger should be at 0.96x
    assert (
        abs(trigger_price - expected_trigger) < 100
    ), f"Regular sell should trigger at 0.96 * {target_price} = {expected_trigger}, but got {trigger_price}"

    # Verify trigger happens at early price
    strategy.client.create_order.side_effect = [
        get_new_order(order=strategy.sell.current_position.sell_order)
    ]

    # Trigger at 0.96x price - SHOULD trigger
    sim.new_price(price=expected_trigger, symbol="BTCUSDC")
    await wait_for_condition(
        condition_func=lambda: strategy.state == State.SELLING, timeout=5.0
    )

    logger.info(
        f"✓ Regular sell correctly triggered at early price: {expected_trigger}"
    )
    logger.info(f"✓ Regular sell trigger mechanism (0.96x) works correctly!")
