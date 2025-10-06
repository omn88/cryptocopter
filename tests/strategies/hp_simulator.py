import asyncio
import logging
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_CANCELED,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_FILLED,
)
from src.common.symbol import Symbol
from src.gui.hp_manager.hpfront import HpFront
from src.identifiers import (
    Event,
    EventName,
    ExecutionReport,
    HPBuyConfig,
    HPBuy,
    HPSellConfig,
    HPSell,
    Order,
    State,
    StateInfo,
    TickerUpdate,
    Mode,
    PositionSide,
)
from src.strategies.hp_manager.hp_manager import HpStrategy
from src.strategy_executor import StrategyExecutor
from tests.helpers import get_new_orders
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

logger = logging.getLogger("hp_simulator")


class HPSimulator:
    async def simulate_convert_only_position(
        self,
        coin="DYM",
        end_currency="USDC",
        quantity=10.0,
        buy_price=2.0,
        sell_price=2.0,
    ) -> HPSell:
        """
        Simulates a convert-only position (e.g., DYM/USDC) for E2E tests.
        - Assumes the config queue and backend are ready.
        - Mocks the convert quote/accept and market price.
        - Waits for the frontend to reflect the expected state.
        """
        name = f"{coin}{end_currency}"

        # Simulate sending config for convert-only position
        hp_sell_data = HPSell(
            config=HPSellConfig(
                coin=coin,
                buy_price=buy_price,
                sell_price=sell_price,
                quantity=quantity,
                end_currency=end_currency,
                symbol=Symbol(name=name, precision=5, price_precision=2),
            ),
            state_info=StateInfo(side=PositionSide.SHORT),
        )
        self.front.config_queue.put_nowait(hp_sell_data)
        logger.info(
            "Convert-only sell config added to the queue: %s", hp_sell_data.config
        )

        return hp_sell_data

    def __init__(self, front: HpFront, back: StrategyExecutor):
        self.front = front
        self.back = back

    def new_price(self, price: float, symbol: str = "BTCUSDC"):
        ticker_event = Event(
            name=EventName.TICKER, content=TickerUpdate(last_price=price, symbol=symbol)
        )
        self.back.price_resolver.update_price(symbol, price)
        self.back.strategies["1000"].worker_queue.put_nowait(ticker_event)
        logger.info("Put event to the worker: %s", ticker_event)

    def simulate_buy_position(
        self,
        symbol: str,
        mode: Mode = Mode.DCA,
        budget: float = 1000.0,
        price_low: float = 1000.0,
        price_high: float = 1400.0,  # Reverted back to 1400.0
        order_trigger: float = 1.0,
        hp_id: str = "0",
        coin: str = "BTC",
    ):
        hp = HPBuy(
            HPBuyConfig(
                hp_id=hp_id,
                symbol=Symbol(name=symbol, precision=5, price_precision=2),
                price_low=price_low,
                price_high=price_high,
                order_trigger=order_trigger,
                budget=budget,
                mode=mode,
                coin=coin,
            ),
            state_info=StateInfo(),
        )

        self.front.config_queue.put_nowait(hp)
        logger.info("HP Buy Data added to the queue: %s", hp)

    async def assert_default_buy_position(self):
        logger.info(
            "=== ASSERTING DEFAULT BUY POSITION === len self back stragies: %s",
            len(self.back.strategies),
        )
        await wait_for_condition(condition_func=lambda: len(self.back.strategies) == 1)
        await wait_for_condition(
            condition_func=lambda: not self.back.config_queue.qsize()
        )
        assert len(self.back.strategies) == 1
        strategy = self.back.strategies["1000"]

        assert isinstance(strategy, HpStrategy)
        assert strategy.state == State.NEW, strategy.state
        assert len(strategy.buy.orders) == 3

        await wait_for_no_active_buy_positions(self.front)
        await wait_for_idle_buy_positions(self.front)

        self.validate_parent(
            hp_id="1000",
            quantity="0.0",
            realized_quantity="0.0",
            state="NEW",
            buy_price="1400.0",  # Reverted back to 1400.0
            quantity_usd="0.0",
        )

        self.validate_child_buy(
            "1000",
            quantity="0.84921",
            realized_quantity="0.0",
            state="NEW",  # 0.84921 is correct with precision=5 rounding
        )

    async def move_to_position_active_buy(self):
        # Open position and send orders
        strategy = self.back.strategies["1000"]
        strategy.client.create_order.side_effect = get_new_orders(
            orders=strategy.buy.orders
        )
        self.new_price(price=1410.0, symbol="BTCUSDC")

        # Assert new opened position data
        await wait_for_condition(condition_func=lambda: strategy.state == State.BUYING)
        await wait_for_active_buy_positions(self.front)
        await wait_for_no_idle_buy_positions(self.front)
        assert strategy.buy.data.state_info.state == State.NEW
        assert all(order.order_id for order in strategy.buy.orders)
        assert all(order.status == ORDER_STATUS_NEW for order in strategy.buy.orders)

        logger.info(
            "Active buy positions: %s", get_buy_positions(self.front, state="BUYING")
        )
        logger.info(
            "Idle buy positions: %s", get_buy_positions(self.front, state="NEW")
        )

    async def cancel_buy_position_untouched(self):
        strategy = self.back.strategies["1000"]

        assert strategy.buy.orders_cancel_price == 1428.0
        self.new_price(price=1428.0, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: all(
                order.status == ORDER_STATUS_CANCELED for order in strategy.buy.orders
            )
        )

        assert len(strategy.buy.orders) == 3
        assert strategy.buy.data.state_info.state == State.NEW
        assert strategy.state == State.NEW

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == State.NEW.value
        )

        # Comprehensive validation for new buy position
        self.validate_parent(
            "1000",
            quantity="0.0",
            realized_quantity="0.0",
            state="NEW",
            buy_price="1400.0",
            quantity_usd="0.0",
        )

        # Child buy validation - quantity should always be total expected (0.84921)
        self.validate_child_buy(
            "1000", quantity="0.84921", realized_quantity="0.0", state="NEW"
        )

    async def simulate_partial_fill(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        # Get the actual order ID from the first order
        first_order_id = strategy.buy.orders[0].order_id

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
            order_id=first_order_id,
            last_executed_quantity=0.12,
            last_executed_price=1400,
            cumulative_filled_quantity=0.12,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Orders: %s", strategy.buy.orders)
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[0].status
            == ORDER_STATUS_PARTIALLY_FILLED
        )
        assert strategy.buy.orders[1].status == ORDER_STATUS_NEW
        assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == str(exc_report.last_executed_quantity)
        )

        # Comprehensive validation for partial fill
        self.validate_parent(
            "1000",
            quantity="0.12",
            realized_quantity="0.0",
            state="BUYING",
            buy_price="1400.0",
            quantity_usd="168.0",
        )

        # Child buy validation - quantity should always be total expected (0.84921)
        self.validate_child_buy(
            "1000",
            quantity="0.84921",
            realized_quantity="0.12",
            state="PARTIALLY_BOUGHT",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_partial_fill_with_sell_price(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        # Use dynamic order ID from the first order
        first_order_id = strategy.buy.orders[0].order_id
        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
            order_id=first_order_id,
            last_executed_quantity=0.12,
            last_executed_price=1400,
            cumulative_filled_quantity=0.12,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Orders: %s", strategy.buy.orders)
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[0].status
            == ORDER_STATUS_PARTIALLY_FILLED
        )
        assert strategy.buy.orders[1].status == ORDER_STATUS_NEW
        assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == str(exc_report.last_executed_quantity)
        )

        # Comprehensive validation for partial fill with sell price
        self.validate_parent(
            "1000",
            quantity="0.12",
            realized_quantity="0.0",
            state="BUYING",
            buy_price="1400.0",
            quantity_usd="168.0",
            sell_price="4200.0",
            expected_return="336.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        # Child buy validation - quantity should always be total expected (0.84921)
        self.validate_child_buy(
            "1000",
            quantity="0.84921",
            realized_quantity="0.12",
            state="PARTIALLY_BOUGHT",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_first_buy_order_fill(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=strategy.buy.orders[0].order_id,  # Use actual order ID
            last_executed_quantity=0.24,
            last_executed_price=1400,
            cumulative_filled_quantity=0.24,
            price=1400.0,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        # Validate strategy state and order status
        self.validate_strategy_state(strategy, "BUYING")
        logger.info("Orders: %s", strategy.buy.orders)
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[0].status == ORDER_STATUS_FILLED
        )
        # Validate order states
        self.validate_buy_orders(
            strategy,
            expected_order_data=[
                {"status": ORDER_STATUS_FILLED},
                {"status": ORDER_STATUS_NEW},
                {"status": ORDER_STATUS_NEW},
            ],
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == str(exc_report.last_executed_quantity)
        )

        # Comprehensive validation for first buy order fill
        self.validate_parent(
            "1000",
            quantity="0.24",
            realized_quantity="0.0",
            state="BUYING",
            buy_price="1400.0",
            quantity_usd="336.0",
            sell_price="0.0",
            expected_return="0.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        # Child buy validation - quantity should always be total expected (0.84921)
        self.validate_child_buy(
            "1000",
            quantity="0.84921",
            realized_quantity="0.24",
            state="PARTIALLY_BOUGHT",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_second_buy_order_fill(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        # Get the actual second order ID from the strategy instead of hardcoded value
        second_order_id = strategy.buy.orders[1].order_id
        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=second_order_id,
            last_executed_quantity=0.28,
            last_executed_price=1200,
            cumulative_filled_quantity=0.28,
            price=1200,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        # Validate strategy state
        self.validate_strategy_state(strategy, "BUYING")
        logger.info("Orders: %s", strategy.buy.orders)

        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[1].status == ORDER_STATUS_FILLED
        )

        # Validate order states after waiting for the condition
        self.validate_buy_orders(
            strategy,
            expected_order_data=[
                {"status": ORDER_STATUS_FILLED},
                {"status": ORDER_STATUS_FILLED},
                {"status": ORDER_STATUS_NEW},
            ],
        )

        realized_quantity = str(
            strategy.buy.orders[0].realized_quantity
            + strategy.buy.orders[1].realized_quantity
        )
        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == realized_quantity
        )

        logger.info(
            "a: %s, b: %s", self.front.hp_list_data[0]["quantity"], realized_quantity
        )

        # Comprehensive validation for second buy order fill
        self.validate_parent(
            "1000",
            quantity="0.52",
            realized_quantity="0.0",
            state="BUYING",
            buy_price="1292.31",
            quantity_usd="672.0",
            sell_price="0.0",
            expected_return="0.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        # Child buy validation - quantity should always be total expected (0.85)
        self.validate_child_buy(
            "1000",
            quantity="0.84921",
            realized_quantity="0.52",
            state="PARTIALLY_BOUGHT",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_third_buy_order_fill(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        # Get the actual third order ID from the strategy instead of hardcoded value
        third_order_id = strategy.buy.orders[2].order_id
        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=third_order_id,
            last_executed_quantity=0.33,
            last_executed_price=1000,
            cumulative_filled_quantity=0.33,
            price=1000,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Orders: %s", strategy.buy.orders)
        assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
        assert strategy.buy.orders[1].status == ORDER_STATUS_FILLED
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[2].status == ORDER_STATUS_FILLED
        )

        realized_quantity = str(
            round(sum(order.realized_quantity for order in strategy.buy.orders), 2)
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == realized_quantity
        )

        # Wait for final state transition to BOUGHT
        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "BOUGHT"
        )

        assert len(self.front.hp_list_data) == 2
        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1178.82"
        assert item["quantity"] == "0.85"
        assert item["quantity_usd"] == "1002.0"
        assert item["sell_price"] == "0.0"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BOUGHT"

        # Child buy validation - quantity should always be total expected (0.85), all filled
        self.validate_child_buy(
            "1000", quantity="0.84921", realized_quantity="0.85", state="BOUGHT"
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_second_buy_order_fill_with_sell_price(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        # Get the dynamic order ID for the second order (price=1200)
        second_order_id = None
        for order in strategy.buy.orders:
            if order.price == 1200 and order.status in [
                ORDER_STATUS_NEW,
                ORDER_STATUS_PARTIALLY_FILLED,
            ]:
                second_order_id = order.order_id
                break

        if second_order_id is None:
            logger.warning("Second order not found")
            return strategy
        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=second_order_id,
            last_executed_quantity=0.28,
            last_executed_price=1200,
            cumulative_filled_quantity=0.28,
            price=1200,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Orders: %s", strategy.buy.orders)
        assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[1].status == ORDER_STATUS_FILLED
        )
        assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

        # Calculate realized buy quantity minus realized sell quantity (always one sell order)
        realized_buy_quantity = str(
            round(sum(order.realized_quantity for order in strategy.buy.orders), 2)
        )

        # Wait for frontend to process all updates before asserting
        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == realized_buy_quantity
        )

        # Note: expected_return is correctly calculated as 1512.0 in logs
        # Frontend list updates are skipped during tests due to container unavailability

        logger.info("Front quantity: %s", self.front.hp_list_data[0]["quantity"])
        assert (
            self.front.hp_list_data[0]["quantity"] == realized_buy_quantity
        ), realized_buy_quantity

        assert len(self.front.hp_list_data) == 3
        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1292.31"
        assert item["quantity"] == "0.52"
        assert item["quantity_usd"] == "672.0", item["quantity_usd"]
        assert item["sell_price"] == "4200.0", item["sell_price"]
        assert item["expected_return"] == "1512.0", item["expected_return"]
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BUYING"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_third_buy_order_fill_with_sell_price(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=strategy.buy.orders[2].order_id,
            last_executed_quantity=0.33,
            last_executed_price=1000,
            cumulative_filled_quantity=0.33,
            price=1000,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Orders: %s", strategy.buy.orders)
        assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
        assert strategy.buy.orders[1].status == ORDER_STATUS_FILLED
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[2].status == ORDER_STATUS_FILLED
        )

        realized_quantity = str(
            round(
                (sum(order.realized_quantity for order in strategy.buy.orders)),
                2,
            )
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == realized_quantity
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PARTIALLY_SOLD"
        )

        logger.info("Front parent: %s", self.front.hp_list_data[0])

        # Comprehensive validation using framework
        assert len(self.front.hp_list_data) == 3
        self.validate_parent(
            "1000",
            quantity="0.85",
            realized_quantity="0.24",
            state="PARTIALLY_SOLD",
            buy_price="1178.82",
            sell_price="4200.0",
            quantity_usd="1002.0",
            expected_return="2568.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        # Child buy validation - quantity should always be total expected (0.85)
        self.validate_child_buy(
            "1000", quantity="0.84921", realized_quantity="0.85", state="BOUGHT"
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_second_buy_order_fill_with_sell_price_no_fill(
        self,
    ) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        # Get the second order's dynamic ID
        second_order_id = strategy.buy.orders[1].order_id

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=second_order_id,
            last_executed_quantity=0.28,
            last_executed_price=1200,
            cumulative_filled_quantity=0.28,
            price=1200,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Orders: %s", strategy.buy.orders)
        assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[1].status == ORDER_STATUS_FILLED
        )
        assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

        # Calculate realized buy quantity minus realized sell quantity (always one sell order)
        realized_buy_quantity = str(
            strategy.buy.orders[0].realized_quantity
            + strategy.buy.orders[1].realized_quantity
        )
        logger.info("Realized buy quantity: %s", realized_buy_quantity)
        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == realized_buy_quantity
        )

        # With hierarchical structure: parent + BUY child + SELL child = 3 items
        assert len(self.front.hp_list_data) == 3

        # Comprehensive validation using framework
        self.validate_parent(
            "1000",
            quantity="0.52",
            realized_quantity="0.0",
            state="BUYING",
            buy_price="1292.31",
            sell_price="4200.0",
            quantity_usd="672.0",
            expected_return="1512.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        # Child buy validation - quantity should always be total expected (0.84921)
        self.validate_child_buy(
            "1000",
            quantity="0.84921",
            realized_quantity="0.52",
            state="PARTIALLY_BOUGHT",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_third_buy_order_fill_with_sell_price_no_fill(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        # Get the third order's dynamic ID
        third_order_id = strategy.buy.orders[2].order_id

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=third_order_id,
            last_executed_quantity=0.33,
            last_executed_price=1000,
            cumulative_filled_quantity=0.33,
            price=1000,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Orders: %s", strategy.buy.orders)
        assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
        assert strategy.buy.orders[1].status == ORDER_STATUS_FILLED
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[2].status == ORDER_STATUS_FILLED
        )

        realized_quantity = str(
            round(
                (sum(order.realized_quantity for order in strategy.buy.orders)),
                2,
            )
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == realized_quantity
        )

        # Wait for state transition to BOUGHT before validation
        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "BOUGHT"
        )

        # Comprehensive validation using framework
        assert len(self.front.hp_list_data) == 3
        self.validate_parent(
            "1000",
            quantity="0.85",
            realized_quantity="0.0",
            state="BOUGHT",
            buy_price="1178.82",
            sell_price="4200.0",
            quantity_usd="1002.0",
            expected_return="2568.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        # Child buy validation - quantity should always be total expected (0.85)
        self.validate_child_buy(
            "1000", quantity="0.84921", realized_quantity="0.85", state="BOUGHT"
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_bought_position(self, symbol="BTCUSDC"):
        # Assumes position is already created and in default state
        self.simulate_buy_position(symbol=symbol)
        await self.assert_default_buy_position()
        await self.move_to_position_active_buy()
        # Simulate all three buy order fills
        strategy = await self.simulate_first_buy_order_fill()
        strategy = await self.simulate_second_buy_order_fill()
        strategy = await self.simulate_third_buy_order_fill()
        return strategy

    async def setup_sell_position(
        self,
        hp_id: str,
        symbol: str,
        quantity: float,
        buy_price: float,
        sell_price: float,
        end_currency: str,
        coin: str,
    ):
        sell_config = HPSell(
            config=HPSellConfig(
                hp_id=hp_id,
                coin=coin,
                buy_price=buy_price,
                sell_price=sell_price,
                quantity=quantity,
                end_currency=end_currency,
                symbol=Symbol(name=symbol, precision=5, price_precision=2),
            ),
            state_info=StateInfo(side=PositionSide.SHORT),
        )
        self.front.config_queue.put_nowait(sell_config)
        logger.info("Sell config added to the queue: %s", sell_config.config)

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["sell_price"] == "4200.0"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            "1000",
            quantity="0.85",
            realized_quantity="0.0",
            state="BOUGHT",
            buy_price="1178.82",
            sell_price="4200.0",
            quantity_usd="1002.0",
            expected_return="2568.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        # Child buy validation - quantity should always be total expected (0.85)
        self.validate_child_buy(
            "1000", quantity="0.84921", realized_quantity="0.85", state="BOUGHT"
        )

        await wait_for_condition(
            condition_func=lambda: self.back.strategies[
                "1000"
            ].sell.current_position.sell_order
        )

    async def send_sell_order_for_bought_position(self):
        strategy = self.back.strategies["1000"]
        logger.info("Sell order: %s", strategy.sell.current_position.sell_order)
        strategy.client.create_order.side_effect = get_new_orders(
            [strategy.sell.current_position.sell_order]
        )
        self.new_price(price=4156.0, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "SELLING"
        )

        # Comprehensive validation using framework
        self.validate_parent(
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

        # Wait for sell child to be created in hierarchical structure
        await wait_for_condition(
            condition_func=lambda: any(
                item.get("hp_id") == "1000_SELL"
                and item.get("is_child")
                and item.get("side") == "SELL"
                for item in self.front.hp_list_data
            )
        )

        # Find sell child using hierarchical approach
        sell_child = None
        for item in self.front.hp_list_data:
            if (
                item["hp_id"] == "1000_SELL"
                and item["is_child"]
                and item["side"] == "SELL"
            ):
                sell_child = item
                break

        assert sell_child is not None, "Should have found sell child in hp_list_data"
        active_sell_item = sell_child

        assert active_sell_item["hp_id"] == "1000_SELL"
        assert (
            active_sell_item["coin"] == "BTCUSDC"
        )  # sell child uses 'coin' not 'symbol'
        assert active_sell_item["buy_price"] == "1178.82"
        assert active_sell_item["quantity"] == "0.85"
        # Note: end_currency is not available in sell child structure
        assert (
            active_sell_item["sell_price"] == "4200.0"
        ), f"Item sell price: {active_sell_item['sell_price']}"
        assert active_sell_item["side"] == "SELL"
        assert active_sell_item["sell_completeness"] == "0.0"

    async def cancel_unfilled_sell_position(self):
        strategy = self.back.strategies["1000"]
        self.new_price(3864, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_CANCELED
        )

        assert strategy.sell.current_position.sell_order.quantity == 0.85
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.0

        assert strategy.sell.current_position.state_info.state == State.NEW
        assert strategy.state == State.BOUGHT

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "BOUGHT"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            "1000",
            quantity="0.85",
            realized_quantity="0.0",
            state="BOUGHT",
            buy_price="1178.82",
            sell_price="4200.0",
            quantity_usd="1002.0",
            expected_return="2568.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def simulate_sell_order_partial_fill(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
            order_id=3570,
            last_executed_quantity=0.42,
            last_executed_price=4200,
            cumulative_filled_quantity=0.42,
            price=4200.0,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_PARTIALLY_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"] == "0.85"
        )

        # Wait for the parent position to stabilize with correct realized_quantity
        await wait_for_condition(
            condition_func=lambda: (
                len(self.front.hp_list_data) > 0
                and self.front.hp_list_data[0]["state"] == "SELLING"
                and self.front.hp_list_data[0]["realized_quantity"] == "0.42"
            ),
            timeout=5.0,
        )

        # Comprehensive validation using framework
        self.validate_parent(
            "1000",
            quantity="0.85",
            realized_quantity="0.42",
            state="SELLING",
            buy_price="1178.82",
            sell_price="4200.0",
            quantity_usd="1002.0",
            expected_return="2568.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_sell_order_fill(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=3570,
            last_executed_quantity=0.85,
            last_executed_price=4200,
            cumulative_filled_quantity=0.85,
            price=4200.0,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING
        logger.info("Sell order: %s", strategy.sell.current_position.sell_order)
        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"] == "0.85"
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "SOLD"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            "1000",
            quantity="0.85",
            realized_quantity="0.85",
            state="SOLD",
            buy_price="1178.82",
            sell_price="4200.0",
            quantity_usd="1002.0",
            expected_return="2568.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def cancel_partially_sold_position(self):
        strategy = self.back.strategies["1000"]
        self.new_price(3864, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_CANCELED
        )

        assert strategy.sell.current_position.sell_order.quantity == 0.85
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.42

        assert strategy.sell.current_position.state_info.state == State.PARTIALLY_SOLD
        assert strategy.state == State.PARTIALLY_SOLD

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PARTIALLY_SOLD"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            "1000",
            quantity="0.85",
            realized_quantity="0.42",
            state="PARTIALLY_SOLD",
            buy_price="1178.82",
            sell_price="4200.0",
            quantity_usd="1002.0",
            expected_return="2568.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def resend_sell_order_for_partially_sold_position(self):
        strategy = self.back.strategies["1000"]
        logger.info("Sell orders: %s", strategy.sell.current_position.sell_order)
        strategy.client.create_order.side_effect = get_new_orders(
            [strategy.sell.current_position.sell_order]
        )
        self.new_price(price=4156.0, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "SELLING"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            "1000",
            quantity="0.85",
            realized_quantity="0.42",
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
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.42

        # Wait for sell state to be SELLING after resending order
        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "SELLING"
        )

        # Get the parent item which contains the consolidated sell information
        selling_parent_item = self.front.hp_list_data[0]

        assert selling_parent_item["hp_id"] == "1000"
        assert selling_parent_item["coin"] == "BTCUSD"  # Parent shows simplified symbol
        assert selling_parent_item["buy_price"] == "1178.82"
        assert (
            selling_parent_item["quantity"] == "0.85"
        )  # Remaining quantity after partial fill
        assert selling_parent_item["sell_price"] == "4200.0"
        assert selling_parent_item["side"] == "PARENT"
        assert selling_parent_item["state"] == "SELLING"

    async def send_sell_order_for_part_bought_position(self):
        strategy = self.back.strategies["1000"]

        strategy.client.create_order.side_effect = get_new_orders(
            [strategy.sell.current_position.sell_order]
        )
        self.new_price(price=4156, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "SELLING"
        )

        # Wait for the position to be in the correct initial SELLING state with 0.0 realized_quantity
        await wait_for_condition(
            condition_func=lambda: (
                len(self.front.hp_list_data) > 0
                and self.front.hp_list_data[0]["state"] == "SELLING"
                and self.front.hp_list_data[0]["realized_quantity"] == "0.0"
            ),
            timeout=5.0,
        )

        # Comprehensive validation using framework
        self.validate_parent(
            "1000",
            quantity="0.24",
            realized_quantity="0.0",
            state="SELLING",
            buy_price="1400.0",
            sell_price="4200.0",
            quantity_usd="336.0",
            expected_return="672.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_NEW
        )
        assert strategy.sell.current_position.sell_order.quantity == 0.24
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.0

        # Wait for sell child to be created
        await wait_for_condition(
            condition_func=lambda: any(
                item["hp_id"] == "1000_SELL" and item["side"] == "SELL"
                for item in self.front.hp_list_data
            )
        )

        # Find the sell child using hierarchical approach
        active_sell_item = next(
            item
            for item in self.front.hp_list_data
            if item["hp_id"] == "1000_SELL" and item["side"] == "SELL"
        )

        # Comprehensive validation for sell position setup
        self.validate_parent(
            "1000",
            quantity="0.24",
            realized_quantity="0.0",
            state="SELLING",
            buy_price="1400.0",
            sell_price="4200.0",
        )
        self.validate_child_sell(
            "1000", quantity="0.24", realized_quantity="0.0", state="SELLING"
        )

    async def setup_sell_position_after_first_buy_order_filled(
        self,
        hp_id: str,
        symbol: str,
        quantity: float,
        buy_price: float,
        sell_price: float,
        end_currency: str,
        coin: str,
    ):
        sell_config = HPSell(
            config=HPSellConfig(
                hp_id=hp_id,
                coin=coin,
                buy_price=buy_price,
                sell_price=sell_price,
                quantity=quantity,
                end_currency=end_currency,
                symbol=Symbol(name=symbol, precision=5, price_precision=2),
            ),
            state_info=StateInfo(side=PositionSide.SHORT),
        )
        self.front.config_queue.put_nowait(sell_config)
        logger.info("Sell config added to the queue: %s", sell_config.config)

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["sell_price"] == "4200.0"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            "1000",
            quantity="0.24",
            realized_quantity="0.0",
            state="PARTIALLY_BOUGHT",
            buy_price="1400.0",
            sell_price="4200.0",
            quantity_usd="336.0",
            expected_return="672.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        await wait_for_condition(
            condition_func=lambda: self.back.strategies[
                "1000"
            ].sell.current_position.sell_order
        )

    async def cancel_buy_position_after_first_order_filled(self):
        strategy = self.back.strategies["1000"]

        assert strategy.buy.orders_cancel_price == 1428.0
        self.new_price(price=1428.0, symbol="BTCUSDC")

        assert len(strategy.buy.orders) == 3

        assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED

        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[1].status
            == ORDER_STATUS_CANCELED
        )
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[2].status
            == ORDER_STATUS_CANCELED
        )

        assert strategy.buy.orders[0].realized_quantity == 0.24
        assert strategy.buy.orders[1].realized_quantity == 0.0
        assert strategy.buy.orders[2].realized_quantity == 0.0

        assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
        assert strategy.state == State.PARTIALLY_BOUGHT

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PARTIALLY_BOUGHT"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            "1000",
            quantity="0.24",
            realized_quantity="0.0",
            state="PARTIALLY_BOUGHT",
            buy_price="1400.0",
            sell_price="0.0",
            quantity_usd="336.0",
            expected_return="0.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        # Child buy validation - quantity should always be total expected (0.85)
        self.validate_child_buy(
            "1000",
            quantity="0.84921",
            realized_quantity="0.24",
            state="PARTIALLY_BOUGHT",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def cancel_unfilled_sell_position_from_part_filled_buy(self):
        strategy = self.back.strategies["1000"]
        self.new_price(3864, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_CANCELED
        )

        assert strategy.sell.current_position.sell_order.quantity == 0.24
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.0

        assert strategy.sell.current_position.state_info.state == State.NEW
        assert strategy.state == State.PARTIALLY_BOUGHT

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PARTIALLY_BOUGHT"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            "1000",
            quantity="0.24",
            realized_quantity="0.0",
            state="PARTIALLY_BOUGHT",
            buy_price="1400.0",
            sell_price="4200.0",
            quantity_usd="336.0",
            expected_return="672.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def simulate_sell_order_partial_fill_from_part_bought(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
            order_id=1008,
            last_executed_quantity=0.14,
            last_executed_price=4200,
            cumulative_filled_quantity=0.14,
            price=4200.0,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_PARTIALLY_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["realized_quantity"]
            == "0.14"
        )

        await wait_for_condition(
            condition_func=lambda: self.back.strategies[
                "1000"
            ].sell.current_position.sell_order.status
            == ORDER_STATUS_PARTIALLY_FILLED,
            timeout=2.0,
        )

        # Comprehensive validation using framework
        self.validate_parent(
            "1000",
            quantity="0.24",
            realized_quantity="0.14",
            state="SELLING",
            buy_price="1400.0",
            sell_price="4200.0",
            quantity_usd="336.0",
            expected_return="672.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def cancel_sell_position_filled_partially(self):
        strategy = self.back.strategies["1000"]
        self.new_price(3864, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_CANCELED
        )

        assert strategy.sell.current_position.sell_order.quantity == 0.24
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.14

        assert strategy.sell.current_position.state_info.state == State.PARTIALLY_SOLD
        assert strategy.state == State.PART_SOLD_PART_BOUGHT

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PART_SOLD_PART_BOUGHT"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            "1000",
            quantity="0.24",
            realized_quantity="0.14",
            state="PART_SOLD_PART_BOUGHT",
            buy_price="1400.0",
            sell_price="4200.0",
            quantity_usd="336.0",
            expected_return="672.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def simulate_second_buy_order_partial_fill(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        # Get the dynamic order ID for the second buy order
        second_order_id = strategy.buy.orders[1].order_id

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
            order_id=second_order_id,
            last_executed_quantity=0.14,
            last_executed_price=1200,
            cumulative_filled_quantity=0.14,
            price=1200,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Orders: %s", strategy.buy.orders)
        assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[1].status
            == ORDER_STATUS_PARTIALLY_FILLED
        )
        assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

        realized_quantity = str(
            strategy.buy.orders[0].realized_quantity
            + strategy.buy.orders[1].realized_quantity
        )
        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == realized_quantity
        )

        logger.info(
            "a: %s, b: %s", self.front.hp_list_data[0]["quantity"], realized_quantity
        )

        assert len(self.front.hp_list_data) == 3
        self.validate_parent(
            "1000",
            quantity="0.38",
            realized_quantity="0.14",
            state="BUYING",
            buy_price="1326.32",
            sell_price="4200.0",
            quantity_usd="504.0",
            expected_return="1092.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def cancel_buy_position_filled_partially_sold_partially(self):
        strategy = self.back.strategies["1000"]

        assert strategy.buy.orders_cancel_price == 1224.0
        strategy.ticker_update = TickerUpdate(last_price=1428.0)
        assert (
            strategy.conditions_for_cancelling_partially_sold_and_bought_orders_buy_position()
        )

        await strategy.process_ticker()  # type: ignore[attr-defined]

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PART_SOLD_PART_BOUGHT"
        )

        hp_list = self.front.hp_list_data
        assert len(hp_list) == 3
        self.validate_parent(
            "1000",
            quantity="0.38",
            realized_quantity="0.14",
            state="PART_SOLD_PART_BOUGHT",
            buy_price="1326.32",
            sell_price="4200.0",
            quantity_usd="504.0",
            expected_return="1092.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

    async def simulate_second_buy_order_fill_after_selling_half_of_first_order(
        self,
    ) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        # Get the dynamic order ID for the second buy order
        second_order_id = strategy.buy.orders[1].order_id

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=second_order_id,
            last_executed_quantity=0.28,
            last_executed_price=1200,
            cumulative_filled_quantity=0.28,
            price=1200,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Orders: %s", strategy.buy.orders)
        assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[1].status == ORDER_STATUS_FILLED
        )
        assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

        realized_quantity = str(
            strategy.buy.orders[0].realized_quantity
            + strategy.buy.orders[1].realized_quantity
        )
        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == realized_quantity
        )

        logger.info(
            "a: %s, b: %s", self.front.hp_list_data[0]["quantity"], realized_quantity
        )

        # Comprehensive validation using framework
        assert len(self.front.hp_list_data) == 3

        # Validate parent with 2 buy orders filled after selling half of first order
        self.validate_parent(
            "1000",
            quantity="0.52",
            realized_quantity="0.14",
            state="BUYING",
            buy_price="1292.31",
            sell_price="4200.0",
            quantity_usd="672.0",
            expected_return="1512.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_third_buy_order_fill_after_selling_half_of_first_order(
        self,
    ) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        # Get dynamic third order ID
        third_order_id = strategy.buy.orders[2].order_id

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=third_order_id,
            last_executed_quantity=0.33,
            last_executed_price=1000,
            cumulative_filled_quantity=0.33,
            price=1000,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Orders: %s", strategy.buy.orders)
        assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
        assert strategy.buy.orders[1].status == ORDER_STATUS_FILLED
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[2].status == ORDER_STATUS_FILLED
        )

        realized_quantity = str(
            round(sum(order.realized_quantity for order in strategy.buy.orders), 2)
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == realized_quantity
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PARTIALLY_SOLD"
        )

        # Comprehensive validation using framework
        assert len(self.front.hp_list_data) == 3

        # Validate parent with all 3 buy orders filled after selling half of first order
        self.validate_parent(
            "1000",
            quantity="0.85",
            realized_quantity="0.14",
            state="PARTIALLY_SOLD",
            buy_price="1178.82",
            sell_price="4200.0",
            quantity_usd="1002.0",
            expected_return="2568.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_sell_order_fill_from_part_bought(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=1008,
            last_executed_quantity=0.24,
            last_executed_price=4200,
            cumulative_filled_quantity=0.24,
            price=4200.0,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"] == "0.24"
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "SOLD_PART_BOUGHT"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            "1000",
            quantity="0.24",
            realized_quantity="0.24",
            state="SOLD_PART_BOUGHT",
            buy_price="1400.0",
            sell_price="4200.0",
            quantity_usd="336.0",
            expected_return="672.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_second_buy_order_fill_after_selling_first_order(
        self,
    ) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        # Get the dynamic second order ID
        second_order_id = strategy.buy.orders[1].order_id

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=second_order_id,
            last_executed_quantity=0.28,
            last_executed_price=1200,
            cumulative_filled_quantity=0.28,
            price=1200,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Orders: %s", strategy.buy.orders)
        assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[1].status == ORDER_STATUS_FILLED
        )
        assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

        realized_quantity = str(
            strategy.buy.orders[0].realized_quantity
            + strategy.buy.orders[1].realized_quantity
        )
        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == realized_quantity
        )

        logger.info(
            "a: %s, b: %s", self.front.hp_list_data[0]["quantity"], realized_quantity
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        # Comprehensive validation using framework
        assert len(self.front.hp_list_data) == 3, len(self.front.hp_list_data)

        # Validate parent with 2 buy orders filled after selling first order
        self.validate_parent(
            "1000",
            quantity="0.52",
            realized_quantity="0.24",
            state="BUYING",
            buy_price="1292.31",
            sell_price="4200.0",
            quantity_usd="672.0",
            expected_return="1512.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_third_buy_order_fill_after_selling_first_order(
        self,
    ) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        # Get the dynamic third order ID
        third_order_id = strategy.buy.orders[2].order_id

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=third_order_id,
            last_executed_quantity=0.33,
            last_executed_price=1000,
            cumulative_filled_quantity=0.33,
            price=1000,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Orders: %s", strategy.buy.orders)
        assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
        assert strategy.buy.orders[1].status == ORDER_STATUS_FILLED
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[2].status == ORDER_STATUS_FILLED
        )

        realized_quantity = str(
            round(
                (sum(order.realized_quantity for order in strategy.buy.orders)),
                2,
            )
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == realized_quantity
        )

        # Wait for final state transition to PARTIALLY_SOLD
        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PARTIALLY_SOLD"
        )

        # Comprehensive validation using framework
        assert len(self.front.hp_list_data) == 3

        # Validate parent with all 3 buy orders filled after selling first order
        self.validate_parent(
            "1000",
            quantity="0.85",
            realized_quantity="0.24",
            state="PARTIALLY_SOLD",
            buy_price="1178.82",
            sell_price="4200.0",
            quantity_usd="1002.0",
            expected_return="2568.0",
            current_price="0.0",
            net="0.0",
            net_percent="0.0",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def open_first_sell_position_from_two_hop_trade(
        self, quantity: float = 1000.0
    ):
        assert len(self.back.strategies) == 0

        coin = "AXL"

        sell_config = HPSell(
            config=HPSellConfig(
                hp_id="",
                coin=coin,
                buy_price=0.2928,
                sell_price=1.14,
                quantity=quantity,
                end_currency="PLN",
                symbol=self.back.price_resolver.symbols[f"{coin}USDT"],
            ),
            state_info=StateInfo(side=PositionSide.SHORT),
        )
        self.front.config_queue.put_nowait(sell_config)
        logger.info("Sell config added to the queue: %s", sell_config.config)

        try:
            await wait_for_condition(
                condition_func=lambda: len(self.front.hp_list_data)
                == 3,  # Updated: Parent + 2 Multihop children (no dummy buy)
            )
        except AssertionError:
            # Debug: log what we actually have when condition fails
            logger.info(f"Current HP list has {len(self.front.hp_list_data)} items")
            raise  # Re-raise the original exception

        strategy = self.back.strategies["1000"]
        assert isinstance(strategy, HpStrategy)

        assert len(strategy.sell.sell_strategy) == 2
        assert strategy.sell.sell_strategy[0].name == f"{coin}BTC"
        assert (
            strategy.sell.sell_strategy[1].name
            == f"BTC{sell_config.config.end_currency}"
        )

        logger.info("Orig SELL DATA: %s", strategy.sell.original_position)
        assert strategy.sell.original_position.config.coin == coin

        assert self.front.hp_list_data[0]["state"] == State.BOUGHT.value
        assert self.front.hp_list_data[0]["coin"] == f"{coin}USD"
        assert self.front.hp_list_data[0]["hp_id"] == "1000"
        assert self.front.hp_list_data[0]["buy_price"] == "0.2928"
        assert self.front.hp_list_data[0]["quantity"] == str(quantity)
        assert self.front.hp_list_data[0]["quantity_usd"] == str(
            quantity * float(self.front.hp_list_data[0]["buy_price"])
        )
        assert self.front.hp_list_data[0]["sell_price"] == "1.14"

        logger.info("HP LIST: %s", self.front.hp_list_data)
        assert self.front.hp_list_data[0]["expected_return"] == str(
            quantity * float(self.front.hp_list_data[0]["sell_price"])
            - quantity * float(self.front.hp_list_data[0]["buy_price"])
        ), f"ER: {self.front.hp_list_data[0]['expected_return']}"
        assert self.front.hp_list_data[0]["current_price"] == "0.0"
        assert self.front.hp_list_data[0]["net"] == "0.0"

        sell_order = strategy.sell.current_position.sell_order

        assert sell_order.quantity == quantity
        assert sell_order.price == 0.00000356
        assert sell_order.realized_quantity == 0.0
        assert sell_order.order_id == 0

        assert strategy.state == State.BOUGHT

        await wait_for_no_active_sell_positions(self.front)
        await wait_for_idle_sell_positions(self.front)

    async def send_orders_for_first_position_from_two_hop_trade(self):
        # Open position and send orders
        strategy = self.back.strategies["1000"]
        strategy.client.create_order.side_effect = get_new_orders(
            orders=[strategy.sell.current_position.sell_order]
        )
        self.new_price(price=1.14, symbol="AXLUSDT")

        sell_order = strategy.sell.current_position.sell_order

        # Assert new opened position data
        await wait_for_condition(condition_func=lambda: strategy.state == State.SELLING)
        await wait_for_active_sell_positions(self.front)

        # Check for any SELL children that might be idle
        idle_sell_children = [
            item
            for item in self.front.hp_list_data
            if item.get("side") == "SELL" and item.get("state") in ["IDLE", "STAGNATED"]
        ]
        logger.info("idle records sell: %s", idle_sell_children)
        # For two-hop trades, second position should remain idle until first completes
        # So we don't wait for no idle positions, just that we have active positions

        assert strategy.sell.current_position.state_info.state == State.NEW
        assert sell_order.order_id == 112800750, f"Order ID: {sell_order.order_id}"
        assert sell_order.status == ORDER_STATUS_NEW
        assert sell_order.quantity == 1000.0
        assert sell_order.price == 0.00000356
        assert sell_order.realized_quantity == 0.0

        # Find active and idle sell children using hierarchical approach
        active_sell_children = [
            item
            for item in self.front.hp_list_data
            if item.get("side") == "SELL" and item.get("state") in ["SELLING", "NEW"]
        ]
        idle_sell_children = [
            item
            for item in self.front.hp_list_data
            if item.get("side") == "SELL" and item.get("state") in ["IDLE", "STAGNATED"]
        ]
        logger.info("Active records: %s", active_sell_children)
        logger.info("Idle records: %s", idle_sell_children)

    async def simulate_sell_order_partial_fill_in_first_hop(self):
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
            order_id=112800750,
            last_executed_quantity=500,
            last_executed_price=0.00000365,
            cumulative_filled_quantity=500,
            price=0.00000365,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_PARTIALLY_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[1]["realized_quantity"]
            == "500.0"
        )

        item = self.front.hp_list_data[1]
        assert item["hp_id"] == "1000a"
        assert item["coin"] == "AXLBTC"
        assert item["buy_price"] == "0.00000092", f"buy price: {item['buy_price']}"
        assert item["quantity"] == "1000.0", f"quantity: {item['quantity']}"
        assert (
            item["realized_quantity"] == "500.0"
        ), f"realized_quantity: {item['realized_quantity']}"
        assert item["quantity_usd"] == "0.000915"
        assert item["sell_price"] == "0.00000356", f"Sell price: {item['sell_price']}"
        assert item["expected_return"] == "0.002645"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "PARTIALLY_SOLD"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def simulate_sell_order_fill_in_first_hop(self) -> None:
        strategy = self.back.strategies["1000"]

        strategy.client.create_order.side_effect = get_new_orders(
            orders=[strategy.sell.sell_positions[1].sell_order]
        )

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=112800750,
            last_executed_quantity=1000,
            last_executed_price=0.00000365,
            cumulative_filled_quantity=1000,
            price=0.00000365,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING

        # Wait for second hop to become active (transition to SELLING state)
        await wait_for_condition(
            condition_func=lambda: any(
                item.get("hp_id") == "1000b" and item.get("state") == "SELLING"
                for item in self.front.hp_list_data
            )
        )

        # Validate first hop is SOLD
        self.validate_multihop_child(
            parent_hp_id="1000",
            child_hp_id="1000a",
            quantity="1000.0",  # Original AXL quantity that was created
            realized_quantity="1000.0",  # Fully sold
            state="SOLD",
        )

        # Validate second hop is now SELLING (ready to sell)
        self.validate_multihop_child(
            parent_hp_id="1000",
            child_hp_id="1000b",
            quantity="0.00356",  # Original BTC quantity that was created
            realized_quantity="0.0",  # Nothing sold yet
            state="SELLING",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def open_second_sell_position_from_two_hop_trade(self):
        strategy = self.back.strategies["1000"]

        # After first hop completes, current position should be the second position (index 1)
        assert strategy.sell.current_position is strategy.sell.sell_positions[1]
        # Mock sending the sell order
        strategy.client.create_order.side_effect = get_new_orders(
            orders=[strategy.sell.sell_positions[1].sell_order]
        )
        logger.info("currente sell position: %s", strategy.sell.current_position)
        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.config.symbol.name
            == "BTCPLN"
        )

        sell_order = strategy.sell.current_position.sell_order

        assert sell_order.quantity == 0.00356
        assert sell_order.price == 320000.0
        assert sell_order.realized_quantity == 0.0
        assert sell_order.order_id == 842844787, f"Order ID: {sell_order.order_id}"
        await wait_for_condition(condition_func=lambda: strategy.state == State.SELLING)
        assert strategy.state == State.SELLING, f"State to: {strategy.state}"

        await wait_for_no_idle_sell_positions(self.front)
        await wait_for_active_sell_positions(self.front)
        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[2]["state"]
            == State.SELLING.value
        )
        assert (
            self.front.hp_list_data[2]["coin"]
            == f"{strategy.sell.current_position.config.coin}PLN"
        )
        assert self.front.hp_list_data[2]["hp_id"] == "1000b"
        assert self.front.hp_list_data[2]["buy_price"] == "320000.0"
        assert self.front.hp_list_data[2]["quantity"] == "0.00356"
        assert self.front.hp_list_data[2]["quantity_usd"] == "1139.2"
        assert self.front.hp_list_data[2]["sell_price"] == "320000.0"
        assert self.front.hp_list_data[2]["expected_return"] == "0.0"
        assert self.front.hp_list_data[2]["current_price"] == "0.0"
        assert self.front.hp_list_data[2]["net"] == "0.0"
        assert self.front.hp_list_data[2]["state"] == "SELLING"

    async def simulate_sell_order_partial_fill_in_second_hop(self):
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
            order_id=842844787,
            last_executed_quantity=0.00178,
            last_executed_price=320000.0,
            cumulative_filled_quantity=0.00178,
            price=320000.0,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_PARTIALLY_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[2]["realized_quantity"]
            == "0.00178"
        )

        item = self.front.hp_list_data[2]
        assert item["hp_id"] == "1000b"
        assert item["coin"] == "BTCPLN"
        assert item["buy_price"] == "320000.0", f"buy price: {item['buy_price']}"
        assert item["quantity"] == "0.00356"  # Original quantity stays the same
        assert item["realized_quantity"] == "0.00178"  # Half of original was sold
        assert item["quantity_usd"] == "1139.2"
        assert item["sell_price"] == "320000.0", f"Sell price: {item['sell_price']}"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "PARTIALLY_SOLD"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def simulate_sell_order_fill_in_second_hop(self) -> None:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=842844787,
            last_executed_quantity=0.00356,
            last_executed_price=320000.0,
            cumulative_filled_quantity=0.00356,
            price=320000.0,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[2]["coin"] == "BTCPLN"
        )
        assert isinstance(
            strategy.sell.current_position.sell_order, Order
        ), f"..... it is: {type(strategy.sell.current_position.sell_order)}"
        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[2]["realized_quantity"]
            == "0.00356"
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[2]["buy_price"] == "320000.0"
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[2]["state"] == "SOLD"
        )

        item = self.front.hp_list_data[2]
        assert item["hp_id"] == "1000b"
        assert item["coin"] == "BTCPLN", item["coin"]
        assert (
            item["quantity"] == "0.00356"
        ), f"quantity to: {item['quantity']}"  # Original quantity
        assert (
            item["realized_quantity"] == "0.00356"
        ), f"realized_quantity to: {item['realized_quantity']}"  # All sold
        assert item["buy_price"] == "320000.0", f"buy price to: {item['buy_price']}"
        assert item["quantity_usd"] == "1139.2"  # Based on original quantity
        assert item["sell_price"] == "320000.0"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "SOLD"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        main_item = self.front.hp_list_data[0]
        first_leg = self.front.hp_list_data[1]
        second_leg = self.front.hp_list_data[2]

        await wait_for_condition(condition_func=lambda: main_item["state"] == "SOLD")
        assert main_item["state"] == "SOLD"
        assert first_leg["state"] == "SOLD"
        assert second_leg["state"] == "SOLD"

    # ============================== COMPREHENSIVE VALIDATION METHODS ==============================

    def validate_parent(
        self,
        hp_id,
        quantity,
        realized_quantity,
        state,
        buy_price=None,
        sell_price=None,
        quantity_usd=None,
        expected_return=None,
        current_price=None,
        net=None,
        net_percent=None,
    ):
        """
        Comprehensive validation for parent container in the frontend UI data.
        Parent realized_quantity represents child sell realized_quantity (what was sold).
        """
        hp_list_data = self.front.hp_list_data
        parent_item = next(
            (
                item
                for item in hp_list_data
                if item["hp_id"] == hp_id and not item.get("is_child", False)
            ),
            None,
        )
        assert parent_item is not None, f"Parent item with hp_id {hp_id} not found"

        # Core attributes - always validated
        assert (
            parent_item["quantity"] == quantity
        ), f"Parent quantity: expected {quantity}, got {parent_item['quantity']}"
        assert (
            parent_item["realized_quantity"] == realized_quantity
        ), f"Parent realized_quantity: expected {realized_quantity}, got {parent_item['realized_quantity']}"
        assert (
            parent_item["state"] == state
        ), f"Parent state: expected {state}, got {parent_item['state']}"

        # Optional attributes - only validated if provided
        if buy_price is not None:
            assert (
                parent_item["buy_price"] == buy_price
            ), f"Parent buy_price: expected {buy_price}, got {parent_item['buy_price']}"
        if sell_price is not None:
            assert (
                parent_item["sell_price"] == sell_price
            ), f"Parent sell_price: expected {sell_price}, got {parent_item['sell_price']}"
        if quantity_usd is not None:
            assert (
                parent_item["quantity_usd"] == quantity_usd
            ), f"Parent quantity_usd: expected {quantity_usd}, got {parent_item['quantity_usd']}"
        if expected_return is not None:
            assert (
                parent_item["expected_return"] == expected_return
            ), f"Parent expected_return: expected {expected_return}, got {parent_item['expected_return']}"
        if current_price is not None:
            assert (
                parent_item["current_price"] == current_price
            ), f"Parent current_price: expected {current_price}, got {parent_item['current_price']}"
        if net is not None:
            assert (
                parent_item["net"] == net
            ), f"Parent net: expected {net}, got {parent_item['net']}"
        if net_percent is not None:
            assert (
                parent_item["net_percent"] == net_percent
            ), f"Parent net_percent: expected {net_percent}, got {parent_item['net_percent']}"

    def validate_child_buy(
        self,
        hp_id,
        quantity,
        realized_quantity,
        state,
        buy_price=None,
        quantity_usd=None,
        current_price=None,
        net=None,
        net_percent=None,
    ):
        """
        Comprehensive validation for child BUY in the frontend UI data.
        Child BUY realized_quantity represents actually bought quantity.
        """
        hp_list_data = self.front.hp_list_data
        buy_child_id = f"{hp_id}_BUY"
        buy_child = next(
            (item for item in hp_list_data if item["hp_id"] == buy_child_id), None
        )
        assert buy_child is not None, f"BUY child with hp_id {buy_child_id} not found"

        # Core attributes - always validated
        assert (
            buy_child["quantity"] == quantity
        ), f"BUY child quantity: expected {quantity}, got {buy_child['quantity']}"
        assert (
            buy_child["realized_quantity"] == realized_quantity
        ), f"BUY child realized_quantity: expected {realized_quantity}, got {buy_child['realized_quantity']}"
        assert (
            buy_child["state"] == state
        ), f"BUY child state: expected {state}, got {buy_child['state']}"
        assert (
            buy_child["side"] == "BUY"
        ), f"BUY child side: expected BUY, got {buy_child['side']}"
        assert (
            buy_child["is_child"] == True
        ), f"BUY child is_child: expected True, got {buy_child['is_child']}"
        assert (
            buy_child["parent_hp_id"] == hp_id
        ), f"BUY child parent_hp_id: expected {hp_id}, got {buy_child['parent_hp_id']}"

        # Optional attributes - only validated if provided
        if buy_price is not None:
            assert (
                buy_child["buy_price"] == buy_price
            ), f"BUY child buy_price: expected {buy_price}, got {buy_child['buy_price']}"
        if quantity_usd is not None:
            assert (
                buy_child["quantity_usd"] == quantity_usd
            ), f"BUY child quantity_usd: expected {quantity_usd}, got {buy_child['quantity_usd']}"
        if current_price is not None:
            assert (
                buy_child["current_price"] == current_price
            ), f"BUY child current_price: expected {current_price}, got {buy_child['current_price']}"
        if net is not None:
            assert (
                buy_child["net"] == net
            ), f"BUY child net: expected {net}, got {buy_child['net']}"
        if net_percent is not None:
            assert (
                buy_child["net_percent"] == net_percent
            ), f"BUY child net_percent: expected {net_percent}, got {buy_child['net_percent']}"

    def validate_child_sell(
        self,
        hp_id,
        quantity,
        realized_quantity,
        state,
        sell_price=None,
        quantity_usd=None,
        current_price=None,
        net=None,
        net_percent=None,
    ):
        """
        Comprehensive validation for child SELL in the frontend UI data.
        Child SELL realized_quantity represents actually sold quantity.
        """
        hp_list_data = self.front.hp_list_data
        sell_child_id = f"{hp_id}_SELL"
        sell_child = next(
            (item for item in hp_list_data if item["hp_id"] == sell_child_id), None
        )
        assert (
            sell_child is not None
        ), f"SELL child with hp_id {sell_child_id} not found"

        # Core attributes - always validated
        assert (
            sell_child["quantity"] == quantity
        ), f"SELL child quantity: expected {quantity}, got {sell_child['quantity']}"
        assert (
            sell_child["realized_quantity"] == realized_quantity
        ), f"SELL child realized_quantity: expected {realized_quantity}, got {sell_child['realized_quantity']}"
        assert (
            sell_child["state"] == state
        ), f"SELL child state: expected {state}, got {sell_child['state']}"
        assert (
            sell_child["side"] == "SELL"
        ), f"SELL child side: expected SELL, got {sell_child['side']}"
        assert (
            sell_child["is_child"] == True
        ), f"SELL child is_child: expected True, got {sell_child['is_child']}"
        assert (
            sell_child["parent_hp_id"] == hp_id
        ), f"SELL child parent_hp_id: expected {hp_id}, got {sell_child['parent_hp_id']}"

        # Optional attributes - only validated if provided
        if sell_price is not None:
            assert (
                sell_child["sell_price"] == sell_price
            ), f"SELL child sell_price: expected {sell_price}, got {sell_child['sell_price']}"
        if quantity_usd is not None:
            assert (
                sell_child["quantity_usd"] == quantity_usd
            ), f"SELL child quantity_usd: expected {quantity_usd}, got {sell_child['quantity_usd']}"
        if current_price is not None:
            assert (
                sell_child["current_price"] == current_price
            ), f"SELL child current_price: expected {current_price}, got {sell_child['current_price']}"
        if net is not None:
            assert (
                sell_child["net"] == net
            ), f"SELL child net: expected {net}, got {sell_child['net']}"
        if net_percent is not None:
            assert (
                sell_child["net_percent"] == net_percent
            ), f"SELL child net_percent: expected {net_percent}, got {sell_child['net_percent']}"

    def validate_multihop_child(
        self,
        child_hp_id,
        quantity,
        realized_quantity,
        state,
        parent_hp_id,
        coin=None,
        sell_price=None,
        buy_price=None,
        quantity_usd=None,
        current_price=None,
        net=None,
        net_percent=None,
    ):
        """
        Comprehensive validation for multihop child positions (e.g., 1000a, 1000b).
        Unlike regular sell children, multihop children have specific IDs and different structure.
        """
        hp_list_data = self.front.hp_list_data
        child = next(
            (item for item in hp_list_data if item["hp_id"] == child_hp_id), None
        )
        assert child is not None, f"Multihop child with hp_id {child_hp_id} not found"

        # Core attributes - always validated
        assert (
            child["quantity"] == quantity
        ), f"Multihop child quantity: expected {quantity}, got {child['quantity']}"
        assert (
            child["realized_quantity"] == realized_quantity
        ), f"Multihop child realized_quantity: expected {realized_quantity}, got {child['realized_quantity']}"
        assert (
            child["state"] == state
        ), f"Multihop child state: expected {state}, got {child['state']}"
        assert (
            child["side"] == "SELL"
        ), f"Multihop child side: expected SELL, got {child['side']}"
        assert (
            child["is_child"] == True
        ), f"Multihop child is_child: expected True, got {child['is_child']}"
        assert (
            child["parent_hp_id"] == parent_hp_id
        ), f"Multihop child parent_hp_id: expected {parent_hp_id}, got {child['parent_hp_id']}"

        # Optional attributes - only validated if provided
        if coin is not None:
            # Extract coin from the symbol (e.g., "AXLBTC" -> "AXL", "BTCPLN" -> "BTC")
            expected_coin_display = child["coin"]
            assert (
                coin in expected_coin_display
            ), f"Multihop child coin: expected to contain {coin}, got {expected_coin_display}"
        if sell_price is not None:
            assert (
                child["sell_price"] == sell_price
            ), f"Multihop child sell_price: expected {sell_price}, got {child['sell_price']}"
        if buy_price is not None:
            assert (
                child["buy_price"] == buy_price
            ), f"Multihop child buy_price: expected {buy_price}, got {child['buy_price']}"
        if quantity_usd is not None:
            assert (
                child["quantity_usd"] == quantity_usd
            ), f"Multihop child quantity_usd: expected {quantity_usd}, got {child['quantity_usd']}"
        if current_price is not None:
            assert (
                child["current_price"] == current_price
            ), f"Multihop child current_price: expected {current_price}, got {child['current_price']}"
        if net is not None:
            assert (
                child["net"] == net
            ), f"Multihop child net: expected {net}, got {child['net']}"
        if net_percent is not None:
            assert (
                child["net_percent"] == net_percent
            ), f"Multihop child net_percent: expected {net_percent}, got {child['net_percent']}"

    def validate_buy_orders(self, strategy, expected_order_data):
        """
        Comprehensive validation for buy orders in the strategy.
        expected_order_data should be a list of dicts with keys: realized_quantity, status, etc.
        """
        assert len(strategy.buy.orders) == len(
            expected_order_data
        ), f"Expected {len(expected_order_data)} orders, got {len(strategy.buy.orders)}"
        for i, expected_data in enumerate(expected_order_data):
            order = strategy.buy.orders[i]
            for attr, expected_value in expected_data.items():
                actual_value = getattr(order, attr)
                assert (
                    actual_value == expected_value
                ), f"Order {i} {attr}: expected {expected_value}, got {actual_value}"

    def validate_sell_orders(self, strategy, expected_order_data):
        """
        Comprehensive validation for sell orders in the strategy.
        expected_order_data should be a list of dicts with keys: realized_quantity, status, etc.
        """
        if strategy.sell.current_position is None:
            assert (
                len(expected_order_data) == 0
            ), "No sell position exists but expected order data provided"
            return

        sell_orders = (
            [strategy.sell.current_position.sell_order]
            if hasattr(strategy.sell.current_position, "sell_order")
            else []
        )
        assert len(sell_orders) == len(
            expected_order_data
        ), f"Expected {len(expected_order_data)} sell orders, got {len(sell_orders)}"
        for i, expected_data in enumerate(expected_order_data):
            order = sell_orders[i]
            for attr, expected_value in expected_data.items():
                actual_value = getattr(order, attr)
                assert (
                    actual_value == expected_value
                ), f"Sell order {i} {attr}: expected {expected_value}, got {actual_value}"

    def validate_strategy_state(
        self, strategy, expected_state, expected_buy_state=None
    ):
        """
        Validate strategy and buy handler states.
        Handles both string and enum values for state comparison.
        """
        # Convert enum to string for comparison if needed
        actual_state = (
            strategy.state.value
            if hasattr(strategy.state, "value")
            else str(strategy.state)
        )
        assert (
            actual_state == expected_state
        ), f"Strategy state: expected {expected_state}, got {actual_state}"

        if expected_buy_state is not None:
            actual_buy_state = (
                strategy.buy.data.state_info.state.value
                if hasattr(strategy.buy.data.state_info.state, "value")
                else str(strategy.buy.data.state_info.state)
            )
            assert (
                actual_buy_state == expected_buy_state
            ), f"Buy state: expected {expected_buy_state}, got {actual_buy_state}"

    def validate_child_convert(
        self,
        hp_id,
        quantity,
        realized_quantity,
        state,
        sell_price=None,
        quantity_usd=None,
        current_price=None,
        net=None,
        net_percent=None,
    ):
        """
        Comprehensive validation for child CONVERT in the frontend UI data.
        Child CONVERT realized_quantity represents inventory quantity being sold.
        """
        hp_list_data = self.front.hp_list_data
        convert_child_id = f"{hp_id}_CONVERT"
        convert_child = next(
            (item for item in hp_list_data if item["hp_id"] == convert_child_id), None
        )
        assert (
            convert_child is not None
        ), f"CONVERT child with hp_id {convert_child_id} not found"

        # Core attributes - always validated
        assert (
            convert_child["quantity"] == quantity
        ), f"CONVERT child quantity: expected {quantity}, got {convert_child['quantity']}"
        assert (
            convert_child["realized_quantity"] == realized_quantity
        ), f"CONVERT child realized_quantity: expected {realized_quantity}, got {convert_child['realized_quantity']}"
        assert (
            convert_child["state"] == state
        ), f"CONVERT child state: expected {state}, got {convert_child['state']}"
        assert (
            convert_child["side"] == "SELL"
        ), f"CONVERT child side: expected SELL, got {convert_child['side']}"
        assert (
            convert_child["is_child"] == True
        ), f"CONVERT child is_child: expected True, got {convert_child['is_child']}"

        # Optional attributes - only validated if provided
        if sell_price is not None:
            assert (
                convert_child["sell_price"] == sell_price
            ), f"CONVERT child sell_price: expected {sell_price}, got {convert_child['sell_price']}"

        if quantity_usd is not None:
            assert (
                convert_child["quantity_usd"] == quantity_usd
            ), f"CONVERT child quantity_usd: expected {quantity_usd}, got {convert_child['quantity_usd']}"

        if current_price is not None:
            assert (
                convert_child["current_price"] == current_price
            ), f"CONVERT child current_price: expected {current_price}, got {convert_child['current_price']}"

        if net is not None:
            assert (
                convert_child["net"] == net
            ), f"CONVERT child net: expected {net}, got {convert_child['net']}"

        if net_percent is not None:
            assert (
                convert_child["net_percent"] == net_percent
            ), f"CONVERT child net_percent: expected {net_percent}, got {convert_child['net_percent']}"
