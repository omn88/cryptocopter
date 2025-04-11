import os
import datetime
import logging
import pytest
from binance.enums import ORDER_STATUS_NEW, ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED
from src.strategy_executor import StrategyExecutor
from src.gui.hpfront import HpFront
from src.gui.identifiers.spot import HPGuiDataBuy
from src.identifiers.common import PositionSide
from src.identifiers.spot import State, StateInfo, UiState
from tests.spot import get_new_orders
from tests.strategies.spot.hp_simulator import HPSimulator
from tests.strategies.spot.hp_manager_helpers import wait_for_condition

logger = logging.getLogger("hp_e2e_test")


@pytest.mark.database_integration
async def test_get_default_buy_position(frontend_backend_setup):
    front, back = frontend_backend_setup

    sim = HPSimulator(front=front, back=back)
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    assert len(back.strategies) == 0

    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()


@pytest.mark.database_integration
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
    await wait_for_condition(condition_func=lambda: front.active_records_buy)
    await wait_for_condition(condition_func=lambda: not front.idle_records_buy)
    assert strategy.buy.data.state_info.state == State.NEW
    assert all(order.order_id for order in strategy.buy.orders)
    assert all(order.status == ORDER_STATUS_NEW for order in strategy.buy.orders)

    logger.info("Active records: %s", front.active_records_buy)
    logger.info("Idle records: %s", front.idle_records_buy)


@pytest.mark.database_integration
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
    strategy.buy.data.state_info.stagnation_counter = (
        strategy.buy.data.state_info.stagnation_limit
    )

    strategy.buy.data.state_info.generate_next_monitor_time()

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
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

    item = front.hp_list_data[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "0.0"
    assert item["quantity"] == "0.0"
    assert item["quantity_usd"] == "0.0"
    assert item["sell_price"] == "0.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "NEW"


@pytest.mark.database_integration
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


@pytest.mark.database_integration
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
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    strategy.buy.data.state_info.stagnation_counter = (
        strategy.buy.data.state_info.stagnation_limit
    )

    assert strategy.buy.data.state_info.next_monitor_time

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
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

    item = front.hp_list_data[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.24"
    assert item["quantity_usd"] == "336.0"
    assert item["sell_price"] == "0.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "PARTIALLY_BOUGHT"

    logger.info("HP List after the update: %s", front.hp_list_data)


@pytest.mark.database_integration
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


@pytest.mark.database_integration
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
    strategy = await sim.simulate_partial_fill()

    # Cancel position
    strategy.buy.data.state_info.stagnation_counter = (
        strategy.buy.data.state_info.stagnation_limit
    )

    assert strategy.buy.data.state_info.next_monitor_time

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
    sim.new_price(price=1428.0)

    assert len(strategy.buy.orders) == 3

    await wait_for_condition(
        lambda: strategy.buy.orders[0].status == ORDER_STATUS_CANCELED
    )
    assert strategy.buy.orders[1].status == ORDER_STATUS_CANCELED
    assert strategy.buy.orders[2].status == ORDER_STATUS_CANCELED

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
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.12"
    assert item["quantity_usd"] == "168.0"
    assert item["sell_price"] == "0.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "PARTIALLY_BOUGHT"

    logger.info("HP List after the update: %s", front.hp_list_data)


@pytest.mark.database_integration
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


@pytest.mark.database_integration
async def test_default_position_all_buy_orders_filled(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    assert len(back.strategies) == 0

    await sim.simulate_bought_position()


@pytest.mark.database_integration
async def test_stagnation_counter_increase_buy(
    frontend_backend_setup,
):
    front, back = frontend_backend_setup
    assert isinstance(front, HpFront)
    assert isinstance(back, StrategyExecutor)
    sim = HPSimulator(front=front, back=back)

    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()

    # Path 1: Send buy orders

    await sim.move_to_position_active_buy()

    strategy = back.strategies["1000"]
    assert strategy.buy.data.state_info.stagnation_counter == 0
    assert strategy.buy.data.state_info.stagnation_limit == 8

    time = datetime.datetime.now()
    strategy.buy.data.state_info.next_monitor_time = time.strftime("%Y-%m-%d %H:%M:%S")

    assert strategy.buy.data.state_info.next_monitor_time == time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    assert strategy.conditions_for_position_stagnation_buy()
    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.buy.data.state_info.stagnation_counter == 1
    assert strategy.buy.data.state_info.stagnation_limit == 8

    assert strategy.buy.data.state_info.next_monitor_time != time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    item = front.hp_list_data[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "0.0"
    assert item["quantity"] == "0.0"
    assert item["quantity_usd"] == "0.0"
    assert item["sell_price"] == "0.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "BUYING"

    assert len(front.active_records_buy) == 1
    assert len(front.idle_records_buy) == 0
    active_pos = front.active_records_buy[0]
    logger.info("active pos: %s", active_pos)

    await wait_for_condition(condition_func=lambda: active_pos["stagnation"] == "1/8")


@pytest.mark.database_integration
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
    # Simulate partial fill
    strategy = await sim.simulate_partial_fill()

    # Cancel position
    strategy.buy.data.state_info.stagnation_counter = (
        strategy.buy.data.state_info.stagnation_limit
    )

    assert strategy.buy.data.state_info.next_monitor_time

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
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
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.12"
    assert item["quantity_usd"] == "168.0"
    assert item["sell_price"] == "0.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "PARTIALLY_BOUGHT"

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


@pytest.mark.database_integration
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

    await sim.move_to_position_active_buy()

    # Simulate first buy order fill
    strategy = await sim.simulate_first_buy_order_fill()

    # Cancel partially bought position
    strategy.buy.data.state_info.stagnation_counter = (
        strategy.buy.data.state_info.stagnation_limit
    )

    assert strategy.buy.data.state_info.next_monitor_time

    assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
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

    item = front.hp_list_data[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1400.0"
    assert item["quantity"] == "0.24"
    assert item["quantity_usd"] == "336.0"
    assert item["sell_price"] == "0.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "PARTIALLY_BOUGHT"

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


@pytest.mark.database_integration
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
        asset="BTC",
    )


@pytest.mark.database_integration
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
        asset="BTC",
    )

    strategy = back.strategies["1000"]

    strategy.client.create_order.side_effect = get_new_orders(
        [strategy.sell.sell_order]
    )
    sim.new_price(price=4156)

    await wait_for_condition(
        condition_func=lambda: front.hp_list_data[0]["state"] == "SELLING"
    )
    item = front.hp_list_data[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1178.82"
    assert item["quantity"] == "0.85"
    assert item["quantity_usd"] == "1002.0"
    assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "SELLING"

    await wait_for_condition(
        condition_func=lambda: strategy.sell.sell_order.status == ORDER_STATUS_NEW
    )
    assert strategy.sell.sell_order.quantity == 0.85
    assert strategy.sell.sell_order.realized_quantity == 0.0

    active_sell_item = front.active_records_sell[0]

    assert active_sell_item["hp_id"] == "1000"
    assert active_sell_item["symbol"] == "BTCUSDC"
    assert active_sell_item["buy_price"] == "1178.82"
    assert active_sell_item["quantity"] == "0.85"
    assert active_sell_item["end_currency"] == "USDC"
    assert (
        active_sell_item["sell_price"] == "4200.0"
    ), f"Item sell price: {item['sell_price']}"
    assert active_sell_item["stagnation"] == "0/8"
    assert active_sell_item["side"] == "SELL"
    assert active_sell_item["completeness"] == "0.0"


@pytest.mark.database_integration
async def test_sell_orders_stagnation_increase(
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
        asset="BTC",
    )

    await sim.send_sell_order_for_bought_position()

    strategy = back.strategies["1000"]

    assert strategy.sell.data.state_info.stagnation_counter == 0
    assert strategy.sell.data.state_info.stagnation_limit == 8

    time = datetime.datetime.now()
    strategy.sell.data.state_info.next_monitor_time = time.strftime("%Y-%m-%d %H:%M:%S")

    assert strategy.sell.data.state_info.next_monitor_time == time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    assert strategy.conditions_for_position_stagnation_sell()
    await strategy.process_ticker()  # type: ignore[attr-defined]

    assert strategy.sell.data.state_info.stagnation_counter == 1
    assert strategy.sell.data.state_info.stagnation_limit == 8

    assert strategy.sell.data.state_info.next_monitor_time != time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    item = front.hp_list_data[0]
    assert item["hp_id"] == "1000"
    assert item["asset"] == "BTC"
    assert item["buy_price"] == "1178.82"
    assert item["quantity"] == "0.85"
    assert item["quantity_usd"] == "1002.0"
    assert item["sell_price"] == "4200.0"
    assert item["expected_return"] == "0.0"
    assert item["current_price"] == "0.0"
    assert item["net"] == "0.0"
    assert item["net_percent"] == "0.0"
    assert item["state"] == "SELLING"

    logger.info("HP List after the update: %s", front.hp_list_data)


@pytest.mark.database_integration
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
        asset="BTC",
    )

    await sim.send_sell_order_for_bought_position()

    # Cancel unfilled sell orders
    await sim.cancel_unfilled_sell_position()


@pytest.mark.database_integration
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
        asset="BTC",
    )

    await sim.send_sell_order_for_bought_position()

    # Cancel unfilled sell orders
    await sim.cancel_unfilled_sell_position()

    await sim.send_sell_order_for_bought_position()


@pytest.mark.database_integration
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
        asset="BTC",
    )

    await sim.send_sell_order_for_bought_position()

    await sim.simulate_sell_order_partial_fill()


@pytest.mark.database_integration
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
        asset="BTC",
    )

    await sim.send_sell_order_for_bought_position()

    await sim.simulate_sell_order_fill()


@pytest.mark.database_integration
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
        asset="BTC",
    )

    await sim.send_sell_order_for_bought_position()

    await sim.simulate_sell_order_partial_fill()

    await sim.cancel_partially_sold_position()


@pytest.mark.database_integration
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
        asset="BTC",
    )

    await sim.send_sell_order_for_bought_position()

    await sim.simulate_sell_order_partial_fill()

    await sim.cancel_partially_sold_position()

    await sim.resend_sell_order_for_partially_sold_position()


@pytest.mark.database_integration
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
        asset="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()


@pytest.mark.database_integration
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
        asset="BTC",
    )

    await sim.send_sell_order_for_part_bought_position()

    await sim.cancel_unfilled_sell_position_from_part_filled_buy()


@pytest.mark.database_integration
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
        asset="BTC",
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

    await sim.simulate_second_buy_order_fill(sell_price="4200.0")
    await sim.simulate_third_buy_order_fill(sell_price="4200.0")


# @pytest.mark.database_integration
# async def test_sell_partially_partially_bought_position(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)
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

#     strategy, hp_list = await send_sell_order_for_partially_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

#     strategy, hp_list = await sell_partially_partially_bought_position(
#         strategy=strategy, hp_gui=hp_gui, hp_list=hp_list
#     )

# @pytest.mark.database_integration
# async def test_buy_partially_partially_sold_position(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)
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

#     strategy, hp_list = await send_sell_order_for_partially_bought_position(
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

# @pytest.mark.database_integration
# async def test_cancel_buy_to_part_sold_part_bought(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)
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

#     strategy, hp_list = await send_sell_order_for_partially_bought_position(
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
#     assert strategy.sell.sell_order.status == ORDER_STATUS_PARTIALLY_FILLED
#     assert strategy.sell.sell_order.quantity == 0.24
#     assert strategy.sell.sell_order.realized_quantity == 0.12
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
#     assert item["quantity_usd"] == "168.0"
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
#     assert item["quantity_usd"] == "336.0"
#     assert item["sell_price"] == "4200"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "PART_SOLD_PART_BOUGHT"

#     logger.info("HP List after the update: %s", hp_list)

# @pytest.mark.database_integration
# async def test_buy_fully_partially_sold_position(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)
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

#     strategy, hp_list = await send_sell_order_for_partially_bought_position(
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
#     assert strategy.sell.sell_order.status == ORDER_STATUS_PARTIALLY_FILLED
#     assert strategy.sell.sell_order.quantity == 0.24
#     assert strategy.sell.sell_order.realized_quantity == 0.12
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
#     assert item["quantity_usd"] == "168.0"
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

# @pytest.mark.database_integration
# async def test_sell_fully_partially_bought_position(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)
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

#     strategy, hp_list = await send_sell_order_for_partially_bought_position(
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
#     assert strategy.sell.sell_order.status == ORDER_STATUS_FILLED
#     assert strategy.sell.sell_order.quantity == 0.24
#     assert strategy.sell.sell_order.realized_quantity == 0.24
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
#     assert item["quantity_usd"] == "0.0"
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
#     assert item["quantity_usd"] == "0.0"
#     assert item["sell_price"] == "4200"
#     assert item["expected_return"] == "0.0"
#     assert item["current_price"] == "0.0"
#     assert item["net"] == "0.0"
#     assert item["net_percent"] == "0.0"
#     assert item["state"] == "SOLD_PART_BOUGHT"

#     logger.info("HP List after the update: %s", hp_list)

#     assert strategy.ui_queue.qsize() == 0

# @pytest.mark.database_integration
# async def test_buy_fully_partially_bought_position_when_sold_position(
#     frontend_backend_setup,
# ):
#     front, back = frontend_backend_setup
#     assert isinstance(front, HpFront)
#     assert isinstance(back, StrategyExecutor)
#     sim = HPSimulator(front=front, back=back)
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

#     strategy, hp_list = await send_sell_order_for_partially_bought_position(
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
#     assert strategy.sell.sell_order.status == ORDER_STATUS_FILLED
#     assert strategy.sell.sell_order.quantity == 0.24
#     assert strategy.sell.sell_order.realized_quantity == 0.24
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
#     assert item["quantity_usd"] == "0.0"
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
#     assert item["quantity_usd"] == "0.0"
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
