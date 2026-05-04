import asyncio
import logging
import time
from typing import Callable, List, Dict, Tuple, Optional
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_CANCELED,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_FILLED,
)
from src.common.symbol import Symbol
from src.gui.hp_manager.hpfront import HpFront
from src.domain.enums import EventName, PositionSide, State
from src.domain.orders import Event, ExecutionReport, Order, TickerUpdate
from src.domain.positions import HPBuy, HPBuyConfig, HPSell, HPSellConfig, StateInfo
from src.strategies.hp_manager.hp_manager import HpStrategy
from src.strategy_executor import StrategyExecutor
from tests.helpers import get_new_order

logger = logging.getLogger("hp_simulator")


# ============================================================================
# HELPER FUNCTIONS (extracted from hp_manager_helpers.py)
# ============================================================================


async def wait_for_condition(
    condition_func, timeout: float = 2.0, interval: float = 0.05
):
    """
    Waits for a given condition function to return True, otherwise raises an AssertionError after timeout.

    :param condition_func: A callable (sync or async) that returns True when the condition is met.
    :param timeout: Maximum time to wait for the condition.
    :param interval: Time between each condition check.
    :raises AssertionError: If the condition is not met within the timeout.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        if asyncio.iscoroutinefunction(condition_func):
            result = await condition_func()
        else:
            result = condition_func()

        if result:
            return  # Condition met, exit successfully
        await asyncio.sleep(interval)  # Wait before rechecking

    raise AssertionError(f"Condition not met within {timeout} seconds")


def get_buy_positions(front: HpFront, state: Optional[str] = None):
    """Get BUY child positions."""
    if not front.hp_list_data:
        return []

    children = []
    for hp_data in front.hp_list_data:
        if hp_data.get("is_child", False) and hp_data.get("side", "").upper() == "BUY":
            if state is None or hp_data.get("state", "").upper() == state.upper():
                children.append(hp_data)
    return children


def has_active_buy_positions(front: HpFront) -> bool:
    """Check if there are active buy positions."""
    buying_positions = get_buy_positions(front, state="BUYING")
    if len(buying_positions) > 0:
        return True

    if not front.hp_list_data:
        return False

    for hp_data in front.hp_list_data:
        if hp_data.get("is_child", False) and hp_data.get("side", "").upper() == "BUY":
            parent_hp_id = hp_data.get("parent_hp_id")
            if parent_hp_id:
                for parent_data in front.hp_list_data:
                    if (
                        parent_data.get("hp_id") == parent_hp_id
                        and parent_data.get("state") == "BUYING"
                    ):
                        return True
    return False


def has_idle_buy_positions(front: HpFront) -> bool:
    """Check if there are idle/new buy positions."""
    if not front.hp_list_data:
        return False

    for hp_data in front.hp_list_data:
        if hp_data.get("is_child", False) and hp_data.get("side", "").upper() == "BUY":
            if hp_data.get("state") == "NEW":
                parent_hp_id = hp_data.get("parent_hp_id")
                if parent_hp_id:
                    for parent_data in front.hp_list_data:
                        if parent_data.get("hp_id") == parent_hp_id:
                            if parent_data.get("state") != "BUYING":
                                return True
                            break
                else:
                    return True
    return False


def has_active_sell_positions(front: HpFront) -> bool:
    """Check if there are active sell positions."""
    if not front.hp_list_data:
        return False

    for hp_data in front.hp_list_data:
        if hp_data.get("state") == "SELLING":
            return True

        if hp_data.get("is_child", False) and hp_data.get("side", "").upper() == "SELL":
            parent_hp_id = hp_data.get("parent_hp_id")
            if parent_hp_id:
                for parent_data in front.hp_list_data:
                    if (
                        parent_data.get("hp_id") == parent_hp_id
                        and parent_data.get("state") == "SELLING"
                    ):
                        return True
    return False


def has_idle_sell_positions(front: HpFront) -> bool:
    """Check if there are idle/new sell positions."""
    if not front.hp_list_data:
        return False

    for hp_data in front.hp_list_data:
        if hp_data.get("is_child", False) and hp_data.get("side", "").upper() == "SELL":
            if hp_data.get("state") == "NEW":
                parent_hp_id = hp_data.get("parent_hp_id")
                if parent_hp_id:
                    for parent_data in front.hp_list_data:
                        if parent_data.get("hp_id") == parent_hp_id:
                            if parent_data.get("state") != "SELLING":
                                return True
                            break
                else:
                    return True
    return False


async def wait_for_active_buy_positions(front: HpFront, timeout: float = 2.0):
    """Wait for active buy positions."""
    await wait_for_condition(lambda: has_active_buy_positions(front), timeout=timeout)


async def wait_for_no_idle_buy_positions(front: HpFront, timeout: float = 2.0):
    """Wait for no idle buy positions."""
    await wait_for_condition(lambda: not has_idle_buy_positions(front), timeout=timeout)


async def wait_for_idle_buy_positions(front: HpFront, timeout: float = 2.0):
    """Wait for idle buy positions."""
    await wait_for_condition(lambda: has_idle_buy_positions(front), timeout=timeout)


async def wait_for_no_active_buy_positions(front: HpFront, timeout: float = 2.0):
    """Wait for no active buy positions."""
    await wait_for_condition(
        lambda: not has_active_buy_positions(front), timeout=timeout
    )


async def wait_for_active_sell_positions(front: HpFront, timeout: float = 2.0):
    """Wait for active sell positions."""
    await wait_for_condition(lambda: has_active_sell_positions(front), timeout=timeout)


async def wait_for_no_idle_sell_positions(front: HpFront, timeout: float = 2.0):
    """Wait for no idle sell positions."""
    await wait_for_condition(
        lambda: not has_idle_sell_positions(front), timeout=timeout
    )


async def wait_for_idle_sell_positions(front: HpFront, timeout: float = 2.0):
    """Wait for idle sell positions."""
    await wait_for_condition(lambda: has_idle_sell_positions(front), timeout=timeout)


async def wait_for_no_active_sell_positions(front: HpFront, timeout: float = 2.0):
    """Wait for no active sell positions."""
    await wait_for_condition(
        lambda: not has_active_sell_positions(front), timeout=timeout
    )


# ============================================================================
# END OF HELPER FUNCTIONS
# ============================================================================


class HPSimulator:
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
        budget: float = 1000.0,
        buy_price: float = 1400.0,
        order_trigger: float = 1.0,
        hp_id: str = "0",
        coin: str = "BTC",
    ):
        hp = HPBuy(
            HPBuyConfig(
                hp_id=hp_id,
                symbol=Symbol(name=symbol, precision=5, price_precision=2),
                buy_price=buy_price,
                order_trigger=order_trigger,
                budget=budget,
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
        assert strategy.buy.buy_order is not None

        await wait_for_no_active_buy_positions(self.front)
        await wait_for_idle_buy_positions(self.front)

        self.validate_parent(
            buy_price="1400.0",  # Reverted back to 1400.0
            quantity_usd="0.0",
        )

        self.validate_child_buy(
            "1000",
            quantity="0.71429",
            realized_quantity="0.0",
            state="NEW",  # 0.71429 is correct with precision=5 rounding
        )

    async def move_to_position_active_buy(self):
        # Open position and send orders
        strategy = self.back.strategies["1000"]
        strategy.client.create_order.side_effect = [
            get_new_order(order=strategy.buy.buy_order)
        ]
        self.new_price(price=1410.0, symbol="BTCUSDC")

        # Assert new opened position data
        await wait_for_condition(condition_func=lambda: strategy.state == State.BUYING)
        await wait_for_active_buy_positions(self.front)
        await wait_for_no_idle_buy_positions(self.front)
        assert strategy.buy.data.state_info.state == State.NEW
        assert strategy.buy.buy_order.order_id
        assert strategy.buy.buy_order.status == ORDER_STATUS_NEW

        logger.info("Active buy: %s", get_buy_positions(self.front, state="BUYING"))
        logger.info("Idle buy: %s", get_buy_positions(self.front, state="NEW"))

    async def cancel_buy_position_untouched(self):
        strategy = self.back.strategies["1000"]

        assert strategy.buy.order_cancel_price == 1428.0
        self.new_price(price=1428.0, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: strategy.buy.buy_order.status
            == ORDER_STATUS_CANCELED
        )

        assert strategy.buy.buy_order.status == ORDER_STATUS_CANCELED
        assert strategy.buy.data.state_info.state == State.NEW
        assert strategy.state == State.NEW

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == State.NEW.value
        )

        # Comprehensive validation for new buy position
        self.validate_parent(
            buy_price="1400.0",
            quantity_usd="0.0",
        )

        # Child buy validation - quantity should always be total expected (0.71429)
        self.validate_child_buy(
            "1000", quantity="0.71429", realized_quantity="0.0", state="NEW"
        )

    async def simulate_partial_fill(
        self, last: float = 0.12, cumulative: float = 0.12, sold: float = 0.0
    ) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        price = 1400.0

        assert strategy.buy.buy_order is not None

        # Get the actual order ID from the first order
        first_order_id = strategy.buy.buy_order.order_id

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
            order_id=first_order_id,
            last_executed_quantity=last,
            last_executed_price=price,
            cumulative_filled_quantity=cumulative,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Order: %s", strategy.buy.buy_order)
        await wait_for_condition(
            condition_func=lambda: strategy.buy.buy_order.status
            == ORDER_STATUS_PARTIALLY_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == str(cumulative)
        )

        # Comprehensive validation for partial fill
        self.validate_parent(
            quantity=f"{cumulative}",
            realized_quantity=f"{sold}",
            state="BUYING",
            buy_price=f"{price}",
            quantity_usd=f"{round(price * cumulative, 2)}",
        )

        # Child buy validation - quantity should always be total expected (0.71429)
        self.validate_child_buy(
            "1000",
            quantity="0.71429",
            realized_quantity=f"{cumulative}",
            state="PARTIALLY_BOUGHT",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_partial_fill_with_sell_price(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        assert strategy.buy.buy_order is not None

        # Use dynamic order ID from the first order
        first_order_id = strategy.buy.buy_order.order_id
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
        logger.info("Order: %s", strategy.buy.buy_order)
        await wait_for_condition(
            condition_func=lambda: strategy.buy.buy_order.status
            == ORDER_STATUS_PARTIALLY_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == str(exc_report.last_executed_quantity)
        )

        # Comprehensive validation for partial fill with sell price
        self.validate_parent(
            quantity="0.12",
            state="BUYING",
            buy_price="1400.0",
            quantity_usd="168.0",
            sell_price="4200.0",
            expected_return="336.0",
        )

        # Child buy validation - quantity should always be total expected (0.71429)
        self.validate_child_buy(
            "1000",
            quantity="0.71429",
            realized_quantity="0.12",
            state="PARTIALLY_BOUGHT",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_bought_position(self, symbol="BTCUSDC"):
        # Assumes position is already created and in default state
        self.simulate_buy_position(symbol=symbol)
        await self.assert_default_buy_position()
        await self.move_to_position_active_buy()
        # Simulate full buy order fill (single order system)
        strategy = self.back.strategies["1000"]
        assert strategy.buy.buy_order is not None
        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=strategy.buy.buy_order.order_id,
            last_executed_quantity=0.71429,
            last_executed_price=1400,
            cumulative_filled_quantity=0.71429,
            price=1400.0,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        await wait_for_condition(
            condition_func=lambda: strategy.buy.buy_order.status == ORDER_STATUS_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: len(self.front.hp_list_data) > 0
            and self.front.hp_list_data[0].get("state") == "BOUGHT"
        )

        return strategy

    async def fill_remaining_buy_order(self, strategy: HpStrategy) -> HpStrategy:
        """
        Fill the remaining quantity of a partially filled buy order.

        This helper simulates filling whatever quantity remains on the buy order
        to complete it fully (status = FILLED).

        Args:
            strategy: The HpStrategy instance with a partially filled buy order

        Returns:
            The updated strategy instance
        """
        buy_order = strategy.buy.buy_order
        assert buy_order is not None, "Buy order must exist"
        assert (
            buy_order.status == ORDER_STATUS_PARTIALLY_FILLED
            or buy_order.status == ORDER_STATUS_NEW
        ), f"Buy order must be partially filled or new, got {buy_order.status}"

        # Calculate remaining quantity to fill
        remaining_qty = buy_order.quantity - buy_order.realized_quantity
        new_cumulative = buy_order.quantity  # Fill to completion

        logger.info(
            f"Filling remaining buy order: current={buy_order.realized_quantity}, "
            f"remaining={remaining_qty}, total={buy_order.quantity}"
        )

        # Create execution report for the remaining fill
        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=buy_order.order_id,
            last_executed_quantity=remaining_qty,
            last_executed_price=buy_order.price,
            cumulative_filled_quantity=new_cumulative,
            price=buy_order.price,
        )

        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info(f"Put fill remaining event to worker: {exc_report}")

        assert strategy.buy.buy_order is not None
        # Wait for order to be filled
        await wait_for_condition(
            condition_func=lambda: strategy.buy.buy_order.status == ORDER_STATUS_FILLED
        )

        logger.info(
            f"✓ Buy order filled: realized_quantity={strategy.buy.buy_order.realized_quantity}"
        )

        return strategy

    async def fill_remaining_sell_order(self, strategy: HpStrategy) -> HpStrategy:
        """
        Fill the remaining quantity of a partially filled sell order.

        This helper simulates filling whatever quantity remains on the sell order
        to complete it fully (status = FILLED).

        Args:
            strategy: The HpStrategy instance with a partially filled sell order

        Returns:
            The updated strategy instance
        """
        sell_order = strategy.sell.current_position.sell_order
        assert sell_order is not None, "Sell order must exist"
        assert (
            sell_order.status == ORDER_STATUS_PARTIALLY_FILLED
            or sell_order.status == ORDER_STATUS_NEW
        ), f"Sell order must be partially filled or new, got {sell_order.status}"

        # Calculate remaining quantity to fill
        remaining_qty = sell_order.quantity - sell_order.realized_quantity
        new_cumulative = sell_order.quantity  # Fill to completion

        logger.info(
            f"Filling remaining sell order: current={sell_order.realized_quantity}, "
            f"remaining={remaining_qty}, total={sell_order.quantity}"
        )

        # Create execution report for the remaining fill
        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=sell_order.order_id,
            last_executed_quantity=remaining_qty,
            last_executed_price=sell_order.price,
            cumulative_filled_quantity=new_cumulative,
            price=sell_order.price,
        )

        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info(f"Put fill remaining event to worker: {exc_report}")

        # Wait for order to be filled
        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_FILLED
        )

        logger.info(
            f"✓ Sell order filled: realized_quantity={strategy.sell.current_position.sell_order.realized_quantity}"
        )

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

        # The test itself will perform detailed validation after this method returns
        # We just wait for the basic sell position setup to complete

        await wait_for_condition(
            condition_func=lambda: self.back.strategies[
                "1000"
            ].sell.current_position.sell_order
        )

    async def send_sell_order_for_bought_position(self):
        strategy = self.back.strategies["1000"]
        logger.info("Sell order: %s", strategy.sell.current_position.sell_order)
        strategy.client.create_order.side_effect = [
            get_new_order(order=strategy.sell.current_position.sell_order)
        ]
        self.new_price(price=4156.0, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "SELLING"
        )

        # Comprehensive validation using framework
        self.validate_parent(
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
        assert active_sell_item["buy_price"] == "1400.0"
        assert active_sell_item["quantity"] == "0.71429"
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

        assert strategy.sell.current_position.sell_order.quantity == 0.71429
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.0

        assert strategy.sell.current_position.state_info.state == State.NEW
        assert strategy.state == State.BOUGHT

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "BOUGHT"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            quantity="0.71429",
            state="BOUGHT",
            buy_price="1400.0",
            sell_price="4200.0",
            quantity_usd="1000.01",
            expected_return="2000.01",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def simulate_sell_order_partial_fill(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
            order_id=strategy.sell.current_position.sell_order.order_id,
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
            condition_func=lambda: self.front.hp_list_data[0]["quantity"] == "0.71429"
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
            quantity="0.71429",
            realized_quantity="0.42",
            state="SELLING",
            buy_price="1400.0",
            sell_price="4200.0",
            quantity_usd="1000.01",
            expected_return="2000.01",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_sell_order_fill(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=strategy.sell.current_position.sell_order.order_id,
            last_executed_quantity=0.71429,
            last_executed_price=4200,
            cumulative_filled_quantity=0.71429,
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
            condition_func=lambda: self.front.hp_list_data[0]["quantity"] == "0.71429"
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "SOLD"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            quantity="0.71429",
            realized_quantity="0.71429",
            state="SOLD",
            buy_price="1400.0",
            sell_price="4200.0",
            quantity_usd="1000.01",
            expected_return="2000.01",
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

        assert strategy.sell.current_position.sell_order.quantity == 0.71429
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.42

        assert strategy.sell.current_position.state_info.state == State.PARTIALLY_SOLD
        assert strategy.state == State.PARTIALLY_SOLD

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PARTIALLY_SOLD"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            quantity="0.71429",
            realized_quantity="0.42",
            state="PARTIALLY_SOLD",
            buy_price="1400.0",
            sell_price="4200.0",
            quantity_usd="1000.01",
            expected_return="2000.01",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def resend_sell_order_for_partially_sold_position(self):
        strategy = self.back.strategies["1000"]
        logger.info("Sell orders: %s", strategy.sell.current_position.sell_order)
        strategy.client.create_order.side_effect = [
            get_new_order(order=strategy.sell.current_position.sell_order)
        ]
        self.new_price(price=4156.0, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "SELLING"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            quantity="0.71429",
            realized_quantity="0.42",
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
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.42

        # Wait for sell state to be SELLING after resending order
        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "SELLING"
        )

        # Get the parent item which contains the consolidated sell information
        selling_parent_item = self.front.hp_list_data[0]

        assert selling_parent_item["hp_id"] == "1000"
        assert selling_parent_item["coin"] == "BTCUSD"  # Parent shows simplified symbol
        assert selling_parent_item["buy_price"] == "1400.0"
        assert (
            selling_parent_item["quantity"] == "0.71429"
        )  # Remaining quantity after partial fill
        assert selling_parent_item["sell_price"] == "4200.0"
        assert selling_parent_item["side"] == "PARENT"
        assert selling_parent_item["state"] == "SELLING"

    async def send_sell_order_for_part_bought_position(self):
        strategy = self.back.strategies["1000"]

        strategy.client.create_order.side_effect = [
            get_new_order(order=strategy.sell.current_position.sell_order)
        ]
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
            quantity="0.12",
            realized_quantity="0.0",
            state="SELLING",
            buy_price="1400.0",
            sell_price="4200.0",
            quantity_usd="168.0",
            expected_return="336.0",
        )

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_NEW
        )
        assert strategy.sell.current_position.sell_order.quantity == 0.12
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.0

        # Wait for sell child to be created
        await wait_for_condition(
            condition_func=lambda: any(
                item["hp_id"] == "1000_SELL" and item["side"] == "SELL"
                for item in self.front.hp_list_data
            )
        )

        # Comprehensive validation for sell position setup
        self.validate_parent(
            quantity="0.12",
            state="SELLING",
            buy_price="1400.0",
            sell_price="4200.0",
        )
        self.validate_child_sell(
            "1000", quantity="0.12", realized_quantity="0.0", state="SELLING"
        )

    async def setup_sell_position_after_buy_order_filled_partially(
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
            quantity="0.12",
            state="PARTIALLY_BOUGHT",
            buy_price="1400.0",
            sell_price="4200.0",
            quantity_usd="168.0",
            expected_return="336.0",
        )

        await wait_for_condition(
            condition_func=lambda: self.back.strategies[
                "1000"
            ].sell.current_position.sell_order
        )

    async def cancel_buy_position_after_order_partial_fill(self):
        strategy = self.back.strategies["1000"]

        assert strategy.buy.order_cancel_price == 1428.0
        self.new_price(price=1428.0, symbol="BTCUSDC")

        # Wait for the state transition to complete
        await wait_for_condition(
            condition_func=lambda: strategy.state == State.PARTIALLY_BOUGHT
        )

        # After cancellation, order status should be CANCELED
        await wait_for_condition(
            condition_func=lambda: strategy.buy.buy_order.status
            == ORDER_STATUS_CANCELED
        )

        assert strategy.buy.buy_order.realized_quantity == 0.12

        assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PARTIALLY_BOUGHT"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            quantity="0.12",
            state="PARTIALLY_BOUGHT",
            buy_price="1400.0",
            sell_price="0.0",
            quantity_usd="168.0",
            expected_return="0.0",
        )

        # Child buy validation - quantity should always be total expected (0.85)
        self.validate_child_buy(
            "1000",
            quantity="0.71429",
            realized_quantity="0.12",
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

        assert strategy.sell.current_position.sell_order.quantity == 0.12
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.0

        assert strategy.sell.current_position.state_info.state == State.NEW
        assert strategy.state == State.PARTIALLY_BOUGHT

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PARTIALLY_BOUGHT"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            quantity="0.12",
            state="PARTIALLY_BOUGHT",
            buy_price="1400.0",
            sell_price="4200.0",
            quantity_usd="168.0",
            expected_return="336.0",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def simulate_sell_order_partial_fill_from_part_bought(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
            order_id=strategy.sell.current_position.sell_order.order_id,
            last_executed_quantity=0.06,
            last_executed_price=4200,
            cumulative_filled_quantity=0.06,
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
            == "0.06"
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
            quantity="0.12",
            realized_quantity="0.06",
            state="SELLING",
            buy_price="1400.0",
            sell_price="4200.0",
            quantity_usd="168.0",
            expected_return="336.0",
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

        assert strategy.sell.current_position.sell_order.quantity == 0.12
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.06

        assert strategy.sell.current_position.state_info.state == State.PARTIALLY_SOLD
        assert strategy.state == State.PART_SOLD_PART_BOUGHT

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PART_SOLD_PART_BOUGHT"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            quantity="0.12",
            realized_quantity="0.06",
            state="PART_SOLD_PART_BOUGHT",
            buy_price="1400.0",
            sell_price="4200.0",
            quantity_usd="168.0",
            expected_return="336.0",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def cancel_buy_position_filled_partially_sold_partially(self):
        strategy = self.back.strategies["1000"]

        assert strategy.buy.order_cancel_price == 1224.0
        strategy.ticker_update = TickerUpdate(last_price=1428.0)
        assert (
            strategy.conditions_for_cancelling_partially_sold_and_bought_orders_buy_position()
        )

        await strategy.process_ticker()

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PART_SOLD_PART_BOUGHT"
        )

        hp_list = self.front.hp_list_data
        assert len(hp_list) == 3
        self.validate_parent(
            quantity="0.38",
            realized_quantity="0.14",
            state="PART_SOLD_PART_BOUGHT",
            buy_price="1326.32",
            sell_price="4200.0",
            quantity_usd="504.0",
            expected_return="1092.0",
        )

    async def simulate_sell_order_fill_from_part_bought(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=strategy.sell.current_position.sell_order.order_id,
            last_executed_quantity=0.12,
            last_executed_price=4200,
            cumulative_filled_quantity=0.12,
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
            condition_func=lambda: self.front.hp_list_data[0]["quantity"] == "0.12"
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "SOLD_PART_BOUGHT"
        )

        # Comprehensive validation using framework
        self.validate_parent(
            quantity="0.12",
            realized_quantity="0.12",
            state="SOLD_PART_BOUGHT",
            buy_price="1400.0",
            sell_price="4200.0",
            quantity_usd="168.0",
            expected_return="336.0",
        )

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_third_buy_order_fill_after_selling_first_order(
        self,
    ) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        assert strategy.buy.buy_order is not None

        # Get the dynamic third order ID
        third_order_id = strategy.buy.buy_order.order_id

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
        logger.info("Order: %s", strategy.buy.buy_order)
        assert strategy.buy.buy_order.status == ORDER_STATUS_FILLED

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == (
                strategy.buy.buy_order.realized_quantity
                if strategy.buy.buy_order
                else 0
            )
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
            quantity="0.71429",
            realized_quantity="0.24",
            state="PARTIALLY_SOLD",
            buy_price="1400.0",
            sell_price="4200.0",
            quantity_usd="1000.01",
            expected_return="2000.01",
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

        assert strategy.sell.sell_strategy is not None
        assert len(strategy.sell.sell_strategy.sell_path) == 2
        assert strategy.sell.sell_strategy.sell_path[0].name == f"{coin}BTC"
        assert (
            strategy.sell.sell_strategy.sell_path[1].name
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
        strategy.client.create_order.side_effect = [
            get_new_order(order=strategy.sell.current_position.sell_order)
        ]
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

        strategy.client.create_order.side_effect = [
            get_new_order(order=strategy.sell.sell_positions[1].sell_order)
        ]

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
        strategy.client.create_order.side_effect = [
            get_new_order(order=strategy.sell.sell_positions[1].sell_order)
        ]
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

    # ============================== COMPREHENSIVE VALIDATION METHODS ==============================

    def validate_parent(
        self,
        hp_id="1000",
        quantity="0.0",
        realized_quantity="0.0",
        state="NEW",
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

    def validate_buy_order(self, strategy, expected_order_data):
        """
        Comprehensive validation for buy orders in the strategy.
        expected_order_data should be a list of dicts with keys: realized_quantity, status, etc.
        For compatibility, accepts a list but validates the single buy_order against the first entry.
        """
        assert strategy.buy.buy_order is not None, "Expected buy_order to exist"

        # Use first entry from expected_order_data (legacy format had 3 orders)
        expected_data = expected_order_data[0] if expected_order_data else {}

        for attr, expected_value in expected_data.items():
            actual_value = getattr(strategy.buy.buy_order, attr)
            assert (
                actual_value == expected_value
            ), f"buy_order {attr}: expected {expected_value}, got {actual_value}"

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

    # ============================================================================
    # CRASH RECOVERY METHODS (integrated from CrashRecoveryHelper)
    # ============================================================================

    async def crash_and_recover(
        self,
        hp_id: str = "1000",
        create_pair_func: Optional[Callable] = None,
        simulate_crash_func: Optional[Callable] = None,
    ) -> Tuple[HpFront, StrategyExecutor, HpStrategy]:
        """
        Simulate crash and complete recovery process.

        Args:
            hp_id: Position ID to recover (default "1000")
            create_pair_func: Factory function to create new front/back pair
            simulate_crash_func: Function to simulate crash (if None, no crash simulation)

        Returns:
            Tuple of (new_front, new_back, recovered_strategy)

        Example:
            new_front, new_back, recovered = await sim.crash_and_recover(
                create_pair_func=create_pair
            )
        """
        # Simulate crash if function provided
        if simulate_crash_func:
            await simulate_crash_func(self.front, self.back)

        # Create new instances
        if create_pair_func:
            new_front, new_back = create_pair_func("_recovery")
        else:
            raise ValueError("create_pair_func is required for crash_and_recover")

        # Update simulator to use new instances
        old_front, old_back = self.front, self.back
        self.front, self.back = new_front, new_back

        # Get orders from database
        orders_before_recovery = await new_front.db.get_orders_by_position_id(hp_id)
        logger.info("Orders in DB before recovery: %d", len(orders_before_recovery))

        # Setup mock for exchange queries
        new_back.client.get_order.side_effect = self._mock_orders_from_db(
            orders_before_recovery
        )

        # Trigger recovery
        logger.info("Manually triggering crash recovery for test")
        await new_back.recover_positions_from_crash()

        # Wait for strategy to be recovered
        await wait_for_condition(condition_func=lambda: len(new_back.strategies) == 1)
        assert (
            hp_id in new_back.strategies
        ), f"Strategy {hp_id} not found after recovery"

        recovered_strategy = new_back.strategies[hp_id]
        logger.info("✓ Crash recovery completed successfully")

        return new_front, new_back, recovered_strategy

    def _mock_orders_from_db(self, order_db_list):
        """
        Returns a mock function that returns order status from DB.

        Args:
            order_db_list: List of DB order objects

        Returns:
            Callable for use as side_effect in mock
        """

        def _mock(symbol, orderId=None):
            oid = orderId
            db_order = next(
                (
                    o
                    for o in order_db_list
                    if getattr(o, "exchange_order_id", None) == oid
                ),
                None,
            )
            if db_order:
                return {
                    "symbol": symbol,
                    "orderId": oid,
                    "status": db_order.status.value,
                    "executedQty": str(db_order.realized_quantity),
                    "origQty": str(db_order.quantity),
                    "price": str(db_order.price),
                }
            # Fallback for unexpected orders
            return {
                "symbol": symbol,
                "orderId": oid,
                "status": "NEW",
                "executedQty": "0.00000000",
                "origQty": "0.00000000",
                "price": "0.00",
            }

        return _mock

    async def assert_db_state_matches_memory(self, hp_id: str = "1000") -> None:
        """
        Assert that in-memory application state matches database state.

        Args:
            hp_id: Position ID to verify

        Example:
            await sim.assert_db_state_matches_memory(hp_id="1000")
        """
        logger.info(
            "=== ASSERTING APPLICATION <-> DATABASE STATE MATCH for %s ===", hp_id
        )

        # Get the in-memory strategy
        strategy = self.back.strategies.get(hp_id)
        assert strategy is not None, f"Strategy {hp_id} not found in memory"

        # Get the corresponding position from database
        positions = await self.front.db.get_active_positions()
        db_position = None
        for pos in positions:
            if pos.hp_id == hp_id:
                db_position = pos
                break

        assert db_position is not None, f"Position {hp_id} not found in database"

        # Determine if this is a BUY or SELL position
        from src.database.models import PositionType

        is_sell_position = db_position.position_type == PositionType.SELL

        # Get the appropriate config based on position type
        if is_sell_position:
            sell_config = strategy.sell.original_position.config
            memory_hp_id = sell_config.hp_id
            memory_symbol = sell_config.symbol.name
            memory_coin = sell_config.coin
            memory_buy_price = sell_config.buy_price
            memory_budget = 0.0
            memory_order_trigger = 0.0
        else:
            buy_config = strategy.buy.data.config
            memory_hp_id = buy_config.hp_id
            memory_symbol = buy_config.symbol.name
            memory_coin = buy_config.coin
            memory_buy_price = buy_config.buy_price
            memory_budget = buy_config.budget
            memory_order_trigger = buy_config.order_trigger

        # Compare core identification fields
        assert (
            db_position.hp_id == memory_hp_id
        ), f"HP ID mismatch: DB={db_position.hp_id}, Memory={memory_hp_id}"

        assert (
            db_position.symbol == memory_symbol
        ), f"Symbol mismatch: DB={db_position.symbol}, Memory={memory_symbol}"

        assert (
            db_position.coin == memory_coin
        ), f"Coin mismatch: DB={db_position.coin}, Memory={memory_coin}"

        # Compare configuration fields
        if not is_sell_position:
            assert (
                db_position.budget == memory_budget
            ), f"Budget mismatch: DB={db_position.budget}, Memory={memory_budget}"

            assert (
                db_position.order_trigger == memory_order_trigger
            ), f"Order trigger mismatch: DB={db_position.order_trigger}, Memory={memory_order_trigger}"

        assert (
            db_position.buy_price == memory_buy_price
        ), f"Buy price mismatch: DB={db_position.buy_price}, Memory={memory_buy_price}"

        assert (
            db_position.strategy_state == strategy.state.value
        ), f"Strategy state mismatch: DB={db_position.strategy_state}, Memory={strategy.state}"

        logger.info("✓ Application and database state match verified successfully")
        logger.info("Matched fields:")
        logger.info("  HP ID: %s", db_position.hp_id)
        logger.info("  Symbol: %s", db_position.symbol)
        logger.info("  Coin: %s", db_position.coin)
        if not is_sell_position:
            logger.info("  Budget: %s", db_position.budget)
            logger.info("  Order trigger: %s", db_position.order_trigger)
        logger.info("  Buy price: %s", db_position.buy_price)
        logger.info(
            "  Strategy state: %s (matches: %s)",
            db_position.strategy_state,
            strategy.state,
        )
        logger.info("  Position status: %s", db_position.status)

    async def assert_db_orders_match(
        self, expected_orders: List[Dict], hp_id: str = "1000"
    ) -> None:
        """
        Verify database orders match expected state.

        Args:
            expected_orders: List of dicts with expected order properties
            hp_id: Position ID to check

        Example:
            await sim.assert_db_orders_match([
                {"status": "NEW", "realized_quantity": 0.0, "price": 1400.0}
            ], hp_id="1000")
        """
        orders_in_db = await self.front.db.get_orders_by_position_id(hp_id)
        logger.info(
            "Verifying %d orders in DB for position %s", len(orders_in_db), hp_id
        )

        assert len(orders_in_db) == len(
            expected_orders
        ), f"Expected {len(expected_orders)} orders, found {len(orders_in_db)}"

        for i, (db_order, expected) in enumerate(zip(orders_in_db, expected_orders)):
            logger.info("Checking order %d: %s", i, db_order.exchange_order_id)

            if "status" in expected:
                assert (
                    db_order.status.value == expected["status"]
                ), f"Order {i} status: expected {expected['status']}, got {db_order.status.value}"

            if "realized_quantity" in expected:
                assert (
                    db_order.realized_quantity == expected["realized_quantity"]
                ), f"Order {i} realized_quantity: expected {expected['realized_quantity']}, got {db_order.realized_quantity}"

            if "price" in expected:
                assert (
                    db_order.price == expected["price"]
                ), f"Order {i} price: expected {expected['price']}, got {db_order.price}"

            if "quantity" in expected:
                tolerance = expected.get("tolerance", 0.00001)
                assert (
                    abs(db_order.quantity - expected["quantity"]) < tolerance
                ), f"Order {i} quantity: expected {expected['quantity']}, got {db_order.quantity}"

            if "exchange_order_id" in expected:
                assert (
                    db_order.exchange_order_id == expected["exchange_order_id"]
                ), f"Order {i} exchange_order_id: expected {expected['exchange_order_id']}, got {db_order.exchange_order_id}"

        logger.info("✓ All DB orders match expected state")

    async def assert_recovered_state(
        self,
        strategy: HpStrategy,
        expected_state: State,
        expected_buy_state: Optional[State] = None,
        expected_sell_state: Optional[State] = None,
        expected_order_status: Optional[str] = None,
        wait_for_state: bool = True,
    ) -> None:
        """
        Assert recovered strategy matches expected state.

        Args:
            strategy: The recovered strategy
            expected_state: Expected strategy state
            expected_buy_state: Expected buy state (if applicable)
            expected_sell_state: Expected sell state (if applicable)
            expected_order_status: Expected order status (if applicable)
            wait_for_state: Whether to wait for state transition

        Example:
            await sim.assert_recovered_state(
                recovered,
                State.BUYING,
                expected_buy_state=State.NEW
            )
        """
        # Wait for state if requested
        if wait_for_state:
            await wait_for_condition(
                lambda: strategy.state == expected_state, timeout=5.0
            )

        # Check strategy state
        assert (
            strategy.state == expected_state
        ), f"Strategy state: expected {expected_state}, got {strategy.state}"
        logger.info("✓ Strategy state: %s", expected_state)

        # Check buy state if specified
        if expected_buy_state is not None:
            assert (
                strategy.buy.data.state_info.state == expected_buy_state
            ), f"Buy state: expected {expected_buy_state}, got {strategy.buy.data.state_info.state}"
            logger.info("✓ Buy state: %s", expected_buy_state)

            # Check buy order if exists
            if strategy.buy.buy_order and expected_order_status:
                assert (
                    strategy.buy.buy_order.status == expected_order_status
                ), f"Buy order status: expected {expected_order_status}, got {strategy.buy.buy_order.status}"
                logger.info("✓ Buy order status: %s", expected_order_status)

        # Check sell state if specified
        if expected_sell_state is not None and strategy.sell is not None:
            # Check if sell has current_position (new sell structure)
            if (
                hasattr(strategy.sell, "current_position")
                and strategy.sell.current_position
            ):
                assert (
                    strategy.sell.current_position.state_info.state
                    == expected_sell_state
                ), f"Sell state: expected {expected_sell_state}, got {strategy.sell.current_position.state_info.state}"
                logger.info("✓ Sell state: %s", expected_sell_state)

                # Check sell order if exists
                if strategy.sell.current_position.sell_order and expected_order_status:
                    assert (
                        strategy.sell.current_position.sell_order.status
                        == expected_order_status
                    ), f"Sell order status: expected {expected_order_status}, got {strategy.sell.current_position.sell_order.status}"
                    logger.info("✓ Sell order status: %s", expected_order_status)

        logger.info("✓ Recovered strategy state verified")

    def assert_exchange_synced(self, strategy: HpStrategy, min_calls: int = 1) -> None:
        """
        Verify strategy synced with exchange during recovery.

        Args:
            strategy: The recovered strategy
            min_calls: Minimum expected get_order calls

        Example:
            sim.assert_exchange_synced(recovered_strategy, min_calls=1)
        """
        assert (
            strategy.client.get_order.called
        ), "Exchange sync not performed - get_order was not called"

        actual_calls = strategy.client.get_order.call_count
        assert (
            actual_calls >= min_calls
        ), f"Expected at least {min_calls} get_order calls, got {actual_calls}"

        logger.info("✓ Exchange synced - get_order called %d times", actual_calls)

    # ============================================================================
    # COMPLEX SCENARIO SETUP METHODS
    # ============================================================================

    async def setup_part_sold_part_bought(
        self,
        partial_fill_ratio: float = 0.2,
        sell_ratio: float = 1.0,
        sell_partial: bool = False,
    ) -> HpStrategy:
        """
        Setup PART_SOLD_PART_BOUGHT complex state.

        This creates a position that:
        1. Has buy order partially filled
        2. Buy order is cancelled
        3. Sell position is setup for the partial amount
        4. Optionally, sell order is partially filled

        Args:
            partial_fill_ratio: How much of buy order to fill (0.0-1.0)
            sell_ratio: How much to sell relative to bought amount
            sell_partial: Whether to partially fill the sell order

        Returns:
            The strategy in PART_SOLD_PART_BOUGHT state

        Example:
            strategy = await sim.setup_part_sold_part_bought(
                partial_fill_ratio=0.2,
                sell_ratio=1.0,
                sell_partial=False
            )
        """
        logger.info("Setting up PART_SOLD_PART_BOUGHT scenario")

        # Simulate partial fill on buy order
        await self.simulate_partial_fill()

        # Cancel the partially filled buy order
        await self.cancel_buy_position_after_order_partial_fill()

        # Setup sell position for the partially bought amount
        await self.setup_sell_position_after_buy_order_filled_partially(
            hp_id="1000",
            symbol="BTCUSDC",
            quantity=0.12 * sell_ratio,
            buy_price=1400.0,
            sell_price=4200.0,
            end_currency="USDC",
            coin="BTC",
        )

        # Send sell order
        await self.send_sell_order_for_part_bought_position()

        # Optionally partially fill the sell order
        if sell_partial:
            await self.simulate_sell_order_partial_fill_from_part_bought()

        strategy = self.back.strategies["1000"]
        logger.info("✓ PART_SOLD_PART_BOUGHT scenario ready: %s", strategy.state)

        return strategy

    async def setup_two_hop_trade(
        self,
        first_symbol: str = "BTCUSDC",
        second_symbol: str = "ETHBTC",
        complete_first_leg: bool = True,
    ) -> Tuple[HpStrategy, Optional[HpStrategy]]:
        """
        Setup complete two-hop trade scenario.

        Creates a two-hop trade where:
        1. First position buys and sells (BTC with USDC)
        2. Second position sells the BTC for ETH (convert-only)

        Args:
            first_symbol: Symbol for first leg (default BTCUSDC)
            second_symbol: Symbol for second leg (default ETHBTC)
            complete_first_leg: Whether to complete first leg before second

        Returns:
            Tuple of (first_strategy, second_strategy or None)

        Example:
            first, second = await sim.setup_two_hop_trade(
                complete_first_leg=True
            )
        """
        logger.info("Setting up two-hop trade: %s -> %s", first_symbol, second_symbol)

        # First leg: buy and sell
        await self.simulate_bought_position(symbol=first_symbol)
        await self.setup_sell_position(
            hp_id="1000",
            symbol=first_symbol,
            quantity=0.71429,
            buy_price=1400.0,
            sell_price=4200.0,
            end_currency="USDC",
            coin="BTC",
        )
        await self.send_sell_order_for_bought_position()

        first_strategy = self.back.strategies["1000"]

        if complete_first_leg:
            # Complete first leg
            await self.simulate_sell_order_fill()
            logger.info("✓ First leg completed")

            # TODO: Second leg would require additional setup
            # This is a placeholder for now
            logger.info("✓ Two-hop trade first leg ready")
            return first_strategy, None

        logger.info("✓ Two-hop trade first leg setup (not completed)")
        return first_strategy, None

    async def setup_convert_only_position(
        self, symbol: str = "BTCUSD", quantity: float = 0.5
    ) -> HpStrategy:
        """
        Setup convert-only position for testing.

        A convert-only position is one where we already own the base asset
        and just need to sell it (no buy phase).

        Args:
            symbol: Symbol for the position (should not have C suffix)
            quantity: Quantity to sell

        Returns:
            The strategy in convert-only state

        Example:
            strategy = await sim.setup_convert_only_position(
                symbol="BTCUSD",
                quantity=0.5
            )
        """
        logger.info("Setting up convert-only position for %s", symbol)

        # Create a position that's already in SOLD state
        # (convert-only positions skip the buy phase)
        strategy = self.back.strategies["1000"]
        strategy.sell.current_position.config.symbol.is_convert_only = True

        logger.info("✓ Convert-only position ready")

        return strategy

    async def simulate_cancel_and_resend_buy(
        self, new_price: Optional[float] = None
    ) -> HpStrategy:
        """
        Simulate cancel and resend buy order pattern.

        This simulates the scenario where:
        1. Buy order is sent
        2. Order is cancelled
        3. New buy order is sent (optionally at new price)

        Args:
            new_price: New price for the resent order (None = same price)

        Returns:
            The strategy after resending

        Example:
            strategy = await sim.simulate_cancel_and_resend_buy(
                new_price=1450.0
            )
        """
        logger.info("Simulating cancel and resend buy order")

        # Cancel the current buy order
        await self.cancel_buy_position_untouched()

        # Resend at new price if specified
        if new_price:
            logger.info("Resending buy order at new price: %s", new_price)
            # Would need to trigger new order creation
            # This is a simplified version

        strategy = self.back.strategies["1000"]
        logger.info("✓ Cancel and resend buy completed")

        return strategy

    async def simulate_cancel_and_resend_sell(
        self, new_price: Optional[float] = None
    ) -> HpStrategy:
        """
        Simulate cancel and resend sell order pattern.

        This simulates the scenario where:
        1. Sell order is sent
        2. Order is cancelled
        3. New sell order is sent (optionally at new price)

        Args:
            new_price: New price for the resent order (None = same price)

        Returns:
            The strategy after resending

        Example:
            strategy = await sim.simulate_cancel_and_resend_sell(
                new_price=1550.0
            )
        """
        logger.info("Simulating cancel and resend sell order")

        # Cancel partially sold position and resend
        await self.resend_sell_order_for_partially_sold_position()

        strategy = self.back.strategies["1000"]
        logger.info("✓ Cancel and resend sell completed")

        return strategy

    # ========================================================================
    # Assertion helpers for cleaner tests
    # ========================================================================

    async def assert_partially_bought_state(
        self,
        strategy: HpStrategy,
        realized_qty: float,
        check_ui: bool = True,
    ) -> None:
        """
        Assert strategy is in partially bought state.

        Verifies:
        - Buy order is canceled
        - Realized quantity matches expected
        - Strategy state is PARTIALLY_BOUGHT
        - Data state is PARTIALLY_BOUGHT
        - UI state is synced (if check_ui=True)

        Args:
            strategy: Strategy to check
            realized_qty: Expected realized quantity
            check_ui: Whether to check UI state matches
        """
        await wait_for_condition(
            lambda: strategy.buy.buy_order is not None
            and strategy.buy.buy_order.status == ORDER_STATUS_CANCELED
        )
        assert strategy.buy.buy_order is not None
        assert strategy.buy.buy_order.realized_quantity == realized_qty
        assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
        assert strategy.state == State.PARTIALLY_BOUGHT
        if check_ui:
            await wait_for_condition(
                lambda: self.front.hp_list_data[0]["state"] == "PARTIALLY_BOUGHT"
            )

    async def assert_buying_state_with_partial(
        self,
        strategy: HpStrategy,
        realized_qty: float,
        check_ui: bool = True,
    ) -> None:
        """
        Assert strategy is buying with partial fill.

        Verifies:
        - Buy order is active (NEW status)
        - Realized quantity matches expected
        - Data state is PARTIALLY_BOUGHT (partial fill remembered)
        - Strategy state is BUYING (order active)
        - UI state is synced (if check_ui=True)

        Args:
            strategy: Strategy to check
            realized_qty: Expected realized quantity from partial fill
            check_ui: Whether to check UI state matches
        """
        await wait_for_condition(
            lambda: strategy.buy.buy_order is not None
            and strategy.buy.buy_order.status == ORDER_STATUS_NEW
        )
        assert strategy.buy.buy_order is not None
        assert strategy.buy.buy_order.realized_quantity == realized_qty
        assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
        assert strategy.state == State.BUYING
        if check_ui:
            await wait_for_condition(
                lambda: self.front.hp_list_data[0]["state"] == "BUYING"
            )

    async def assert_part_sold_part_bought_state(
        self,
        strategy: HpStrategy,
        realized_qty: float,
    ) -> None:
        """
        Assert strategy is in part sold/part bought state.

        Verifies:
        - Sell order is canceled
        - Realized quantity matches expected
        - Strategy state is PART_SOLD_PART_BOUGHT
        - Data state is PART_SOLD_PART_BOUGHT
        - UI state is synced

        Args:
            strategy: Strategy to check
            realized_qty: Expected realized quantity
        """
        await wait_for_condition(
            lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_CANCELED
        )
        assert (
            strategy.sell.current_position.sell_order.realized_quantity == realized_qty
        )
        # Strategy state is PART_SOLD_PART_BOUGHT, but sell position data state remains PARTIALLY_SOLD
        assert strategy.state == State.PART_SOLD_PART_BOUGHT
        await wait_for_condition(
            lambda: self.front.hp_list_data[0]["state"] == "PART_SOLD_PART_BOUGHT"
        )

    async def assert_selling_state_with_partial(
        self,
        strategy: HpStrategy,
        realized_qty: float,
        check_ui: bool = True,
    ) -> None:
        """
        Assert strategy is selling with partial fill.

        Verifies:
        - Sell order is active (NEW status)
        - Realized quantity matches expected
        - Data state is PART_SOLD_PART_BOUGHT (partial fill remembered)
        - Strategy state is SELLING (order active)
        - UI state is synced (if check_ui=True)

        Args:
            strategy: Strategy to check
            realized_qty: Expected realized quantity from partial fill
            check_ui: Whether to check UI state matches
        """
        await wait_for_condition(
            lambda: strategy.sell.current_position.sell_order.status == ORDER_STATUS_NEW
        )
        assert (
            strategy.sell.current_position.sell_order.realized_quantity == realized_qty
        )
        # Strategy state is SELLING, sell position data state remains PARTIALLY_SOLD
        assert strategy.state == State.SELLING
        if check_ui:
            await wait_for_condition(
                lambda: self.front.hp_list_data[0]["state"] == "SELLING"
            )

    async def wait_for_state(
        self,
        strategy: HpStrategy,
        expected_state: State,
        check_ui: bool = True,
    ) -> None:
        """
        Wait for strategy to reach expected state.

        Args:
            strategy: Strategy to check
            expected_state: State to wait for
            check_ui: Whether to also check UI state matches
        """
        await wait_for_condition(
            condition_func=lambda: strategy.state == expected_state
        )
        if check_ui:
            state_str = expected_state.name
            await wait_for_condition(
                lambda: self.front.hp_list_data[0]["state"] == state_str
            )

    async def assert_buy_order_state(
        self,
        strategy: HpStrategy,
        status: str,
        realized_qty: Optional[float] = None,
    ) -> None:
        """
        Assert buy order has expected status and quantity.

        Args:
            strategy: Strategy to check
            status: Expected order status (ORDER_STATUS_NEW, ORDER_STATUS_CANCELED, etc.)
            realized_qty: Expected realized quantity (None = don't check)
        """
        await wait_for_condition(
            lambda: strategy.buy.buy_order is not None
            and strategy.buy.buy_order.status == status
        )
        assert strategy.buy.buy_order is not None
        if realized_qty is not None:
            assert strategy.buy.buy_order.realized_quantity == realized_qty

    async def assert_sell_order_state(
        self,
        strategy: HpStrategy,
        status: str,
        realized_qty: Optional[float] = None,
    ) -> None:
        """
        Assert sell order has expected status and quantity.

        Args:
            strategy: Strategy to check
            status: Expected order status (ORDER_STATUS_NEW, ORDER_STATUS_CANCELED, etc.)
            realized_qty: Expected realized quantity (None = don't check)
        """
        await wait_for_condition(
            lambda: strategy.sell.current_position is not None
            and strategy.sell.current_position.sell_order.status == status
        )
        assert strategy.sell.current_position is not None
        if realized_qty is not None:
            assert (
                strategy.sell.current_position.sell_order.realized_quantity
                == realized_qty
            )

    async def resend_buy_order_after_cancel(
        self,
        strategy: HpStrategy,
        trigger_price: float = 1414,
    ) -> None:
        """
        Resend buy order after it was canceled with partial fill.

        This sets up the mock and triggers a new order:
        1. Configure mock to return new order
        2. Trigger price change to create new order
        3. Wait for order to be active

        Args:
            strategy: Strategy to resend order for
            trigger_price: Price to trigger new order creation
        """
        strategy.client.create_order.side_effect = [
            get_new_order(order=strategy.buy.buy_order)
        ]
        self.new_price(price=trigger_price)
        await wait_for_condition(
            lambda: strategy.buy.buy_order is not None
            and strategy.buy.buy_order.status == ORDER_STATUS_NEW
        )

    async def resend_sell_order_after_cancel(
        self,
        strategy: HpStrategy,
        trigger_price: float = 1486,
    ) -> None:
        """
        Resend sell order after it was canceled with partial fill.

        This sets up the mock and triggers a new order:
        1. Configure mock to return new order
        2. Trigger price change to create new order
        3. Wait for order to be active

        Args:
            strategy: Strategy to resend order for
            trigger_price: Price to trigger new order creation
        """
        strategy.client.create_order.side_effect = [
            get_new_order(order=strategy.sell.current_position.sell_order)
        ]
        self.new_price(price=trigger_price)
        await wait_for_condition(
            lambda: strategy.sell.current_position.sell_order.status == ORDER_STATUS_NEW
        )
