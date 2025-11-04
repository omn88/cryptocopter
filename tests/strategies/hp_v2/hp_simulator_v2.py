"""HP Manager V2 Simulator - Test utilities for V2 end-to-end tests.

This module provides testing utilities for HP Manager V2, adapted from the V1 hp_simulator.py.
The key difference is working with HpExecutorV2 (single executor per position) instead of
StrategyExecutor (multiple strategies in a dict).
"""

import asyncio
import logging
import time
from typing import Callable

from binance.enums import ORDER_STATUS_NEW

from src.common.identifiers import (
    Event,
    EventName,
    HPBuyConfig,
    HPSellConfig,
    PositionLifecycleState,
    TickerUpdate,
)
from src.common.symbol import Symbol
from src.gui.hp_manager.hpfront import HpFront
from src.strategies.hp_manager_v2.executor_v2 import HpExecutorV2
from tests.helpers import get_new_order

logger = logging.getLogger("hp_v2_simulator")


class HPSimulatorV2:
    """Simulator for HP Manager V2 end-to-end tests.

    Simplified version of HPSimulator that works with HpExecutorV2 instead of StrategyExecutor.

    Key architectural differences from V1:
    - V1: Uses StrategyExecutor.strategies dict with multiple HpStrategy instances
    - V2: Uses single HpExecutorV2 per position with embedded HpStrategyV2

    Example usage:
        sim = HPSimulatorV2(front=hp_gui, back=hp_v2_executor)
        sim.simulate_buy_position(symbol="BTCUSDC")
        await sim.assert_default_buy_position()
        sim.new_price(49500.0)  # Trigger buy
    """

    def __init__(self, front: HpFront, back: HpExecutorV2):
        """Initialize V2 simulator.

        Args:
            front: HpFront GUI instance
            back: HpExecutorV2 backend instance
        """
        self.front = front
        self.back = back

    @staticmethod
    def create_buy_config(
        hp_id: str,
        symbol: Symbol,
        budget: float = 1000.0,
        buy_price: float = 1400.0,
        order_trigger: float | None = None,
    ) -> HPBuyConfig:
        """Create HP V2 buy configuration.

        Args:
            hp_id: HP position ID
            symbol: Trading symbol
            budget: Budget for buy order
            buy_price: Buy trigger price
            order_trigger: Percentage offset for trigger (e.g., 0.01 = 1%, defaults to 0.01)

        Returns:
            HPBuyConfig instance
        """
        if order_trigger is None:
            order_trigger = 0.01  # Default 1% above buy_price

        return HPBuyConfig(
            hp_id=hp_id,
            symbol=symbol,
            coin=symbol.extract_coin_from_symbol(symbol.name),
            budget=budget,
            buy_price=buy_price,
            order_trigger=order_trigger,
        )

    @staticmethod
    def create_sell_config(
        hp_id: str,
        symbol: Symbol,
        sell_price: float = 4200.0,
        quantity: float = 0.0,
        buy_price: float = 1400.0,
        end_currency: str = "USDC",
    ) -> HPSellConfig:
        """Create HP V2 sell configuration.

        Args:
            hp_id: HP position ID
            symbol: Trading symbol
            sell_price: Sell target price
            quantity: Quantity to sell (0.0 if not yet bought)
            buy_price: Original buy price (for P&L calculation)
            end_currency: Target currency for selling

        Returns:
            HPSellConfig instance
        """
        return HPSellConfig(
            hp_id=hp_id,
            symbol=symbol,
            coin=symbol.extract_coin_from_symbol(symbol.name),
            sell_price=sell_price,
            quantity=quantity,
            buy_price=buy_price,
            end_currency=end_currency,
        )

    async def wait_for_condition(
        self, condition_func: Callable, timeout: float = 2.0, interval: float = 0.05
    ):
        """Wait for a condition function to return True.

        Args:
            condition_func: Callable (sync or async) that returns True when condition is met
            timeout: Maximum time to wait in seconds
            interval: Time between condition checks in seconds

        Raises:
            AssertionError: If condition not met within timeout
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            if asyncio.iscoroutinefunction(condition_func):
                result = await condition_func()
            else:
                result = condition_func()

            if result:
                return  # Condition met
            await asyncio.sleep(interval)

        raise AssertionError(f"Condition not met within {timeout} seconds")

    def new_price(self, price: float, symbol: str = "BTCUSDC"):
        """Send ticker price update to V2 executor.

        This simulates market price updates that drive state machine transitions.

        Args:
            price: New market price
            symbol: Trading symbol (default: BTCUSDC)
        """
        ticker_event = Event(
            name=EventName.TICKER,
            content=TickerUpdate(last_price=price, symbol=symbol),
        )

        # Update price resolver (shared state)
        self.back.price_resolver.update_price(symbol, price)

        # Send to V2 executor's worker queue
        # Note: In V1 this went to strategy.worker_queue, in V2 it goes to executor.worker_queue
        self.back.worker_queue.put_nowait(ticker_event)

        logger.info(
            "Put ticker event to V2 executor worker queue: price=%s, symbol=%s",
            price,
            symbol,
        )

    def setup_order_mocking(self):
        """Setup mock for unlimited order creation with unique IDs.

        This is useful for tests that need to create multiple orders (e.g., cancel/resend scenarios).
        Each call to create_order will return a new order with a unique ID.

        The mock tracks used IDs internally and generates unique order responses.

        Example usage:
            sim.setup_order_mocking()
            # Now create_order will return unique orders each time
            order1 = await strategy.client.create_order(...)
            order2 = await strategy.client.create_order(...)
            # order1.orderId != order2.orderId
        """
        used_ids = set()

        async def mock_create_order(*args, **kwargs):
            # Generate unique order ID
            # Use price and quantity from kwargs to create deterministic ID
            price = kwargs.get("price", 1000.0)
            quantity = kwargs.get("quantity", 1.0)
            base_id = int(abs(hash((price, quantity)))) % 1_000_000_000
            candidate_id = base_id
            while candidate_id in used_ids:
                candidate_id += 1
            used_ids.add(candidate_id)

            # Return order response dict
            return {
                "orderId": candidate_id,
                "price": price,
                "quantity": quantity,
                "status": "NEW",
                "updateTime": 1566818724722,
            }

        self.back.strategy.client.create_order.side_effect = mock_create_order
        logger.info("Setup order mocking with unique ID tracking")

    def simulate_buy_position(
        self,
        symbol: str = "BTCUSDC",
        budget: float = 1000.0,
        buy_price: float = 1400.0,
        order_trigger: float = 0.01,
        hp_id: str = "1000",
        coin: str | None = None,
        sell_price: float | None = None,
    ):
        """Simulate creating a buy position from the frontend.

        This creates buy config and initializes the V2 executor strategy.
        Sell config is optional - if not provided, a placeholder is created.

        Args:
            symbol: Trading symbol (e.g., "BTCUSDC")
            budget: Budget in USDC
            buy_price: Target buy price
            order_trigger: Order execution price (defaults to buy_price * 0.99)
            hp_id: HP position ID
            coin: Base coin (auto-extracted from symbol if None)
            sell_price: Sell target price (optional, defaults to None = placeholder)
        """
        # Get symbol object
        symbol_obj = self.back.symbols.get(symbol)
        if not symbol_obj:
            raise ValueError(f"Symbol {symbol} not found in executor symbols dict")

        # Create buy config
        buy_config = self.create_buy_config(
            hp_id=hp_id,
            symbol=symbol_obj,
            budget=budget,
            buy_price=buy_price,
            order_trigger=order_trigger,
        )

        # Create sell config if sell_price provided
        sell_config = None
        if sell_price is not None:
            # Extract base coin from symbol name if not provided
            # For "BTCUSDC", base_coin is "BTC"
            if not coin:
                coin = symbol_obj.name.replace("USDC", "").replace("USDT", "")

            sell_config = HPSellConfig(
                hp_id=hp_id,
                symbol=symbol_obj,
                sell_price=sell_price,
                coin=coin,
            )

        # Initialize executor with configs
        self.back.set_configs(buy_config, sell_config)

        # Start executor if not already running (mimic V1 behavior)
        # V1's StrategyExecutor auto-starts in __init__, V2 requires explicit start()
        if not self.back.thread.is_alive():
            self.back.start()
            logger.info("V2 executor started (mimicking V1 auto-start behavior)")

        logger.info(
            f"Simulated buy position: HP {hp_id}, symbol: {symbol}, "
            f"buy_price: {buy_price}, budget: {budget}"
        )

    async def simulate_bought_position(
        self,
        symbol: str = "BTCUSDC",
        budget: float = 1000.0,
        buy_price: float = 1400.0,
        sell_price: float = 4200.0,
        hp_id: str = "1000",
    ):
        """Simulate a fully bought position (BOUGHT state).

        This creates a position, sends buy order, and fills it completely.
        The position will be in BOUGHT state with sell config ready.

        Steps:
        1. Create buy position with buy/sell configs
        2. Send buy order (IDLE → BUYING)
        3. Fill buy order completely (BUYING → BOUGHT)

        Args:
            symbol: Trading symbol
            budget: Budget in USDC
            buy_price: Target buy price
            sell_price: Target sell price
            hp_id: HP position ID

        Returns:
            The strategy instance in BOUGHT state
        """
        from binance.enums import ORDER_STATUS_FILLED
        from src.common.identifiers import ExecutionReport

        # Step 1: Create position with both buy and sell configs
        self.simulate_buy_position(
            symbol=symbol,
            budget=budget,
            buy_price=buy_price,
            sell_price=sell_price,
            hp_id=hp_id,
        )
        await self.assert_default_buy_position()

        strategy = self.back.strategy
        assert strategy is not None, "Strategy should be initialized"

        # Step 2: Setup order mocking and send buy order
        self.setup_order_mocking()

        trigger_price = strategy.buy.trigger_price
        self.new_price(price=trigger_price)
        await self.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

        assert strategy.lifecycle_state == PositionLifecycleState.BUYING

        # Give time for order to be fully created
        await asyncio.sleep(0.1)

        assert strategy.buy.buy_order is not None, "Buy order should exist"
        order_id = strategy.buy.buy_order.order_id
        quantity = strategy.buy.buy_order.quantity

        logger.info(f"Buy order sent: order_id={order_id}, quantity={quantity}")

        # Step 3: Fill buy order completely
        # CRITICAL: order_id must match the buy_order.order_id exactly
        exec_report = ExecutionReport(
            order_type="LIMIT",
            current_order_status=ORDER_STATUS_FILLED,
            order_id=order_id,  # Must be int, not string
            last_executed_quantity=quantity,
            last_executed_price=buy_price,
            cumulative_filled_quantity=quantity,
            price=buy_price,
        )

        self.back.worker_queue.put_nowait(
            Event(name=EventName.EXECUTION_REPORT, content=exec_report)
        )

        logger.info(f"Sent execution report for buy order fill")

        # Wait for order status to update and state transition
        await self.wait_for_condition(
            lambda: (
                strategy.buy.buy_order is not None
                and strategy.buy.buy_order.status == ORDER_STATUS_FILLED
            ),
            timeout=2.0,
        )

        # Wait for state transition to BOUGHT
        await self.wait_for_state(PositionLifecycleState.IDLE, timeout=2.0)

        assert strategy.lifecycle_state == PositionLifecycleState.IDLE
        assert strategy.buy.buy_order is not None, "Buy order should exist"
        assert strategy.buy.buy_order.status == ORDER_STATUS_FILLED
        assert strategy.buy.buy_order.realized_quantity == quantity

        logger.info(
            f"✓ Position fully bought: {quantity} {strategy.buy_config.coin} @ {buy_price}"
        )

        return strategy

    async def assert_default_buy_position(self):
        """Assert that default buy position was created with correct initial state.

        Verifies:
        - V2 executor strategy was initialized
        - Executor is in IDLE lifecycle state
        - Buy config was set correctly
        - Buy order was prepared (not sent yet)

        Note: Does NOT validate sell config (may be placeholder at this stage)
        """
        # Verify strategy was created
        assert self.back.strategy is not None, "Strategy should be initialized"
        logger.info("V2 executor has strategy instance")

        # V2 should start in IDLE state (clean state machine)
        assert (
            self.back.strategy.lifecycle_state == PositionLifecycleState.IDLE
        ), f"Expected IDLE, got {self.back.strategy.lifecycle_state}"
        logger.info(f"Initial lifecycle state: {self.back.strategy.lifecycle_state}")

        # Verify buy config was set correctly
        assert self.back.buy_config is not None
        assert self.back.buy_config.hp_id == "1000"
        assert self.back.buy_config.symbol.name == "BTCUSDC"
        logger.info(
            f"Buy config: HP {self.back.buy_config.hp_id}, "
            f"symbol: {self.back.buy_config.symbol.name}, "
            f"buy_price: {self.back.buy_config.buy_price}, "
            f"budget: {self.back.buy_config.budget}"
        )

        # Verify buy order was prepared (not sent yet)
        assert self.back.strategy.buy.buy_order is not None
        logger.info("Buy order prepared (not sent yet)")

        logger.info("Default buy position assertion PASSED")

    async def move_to_position_active_buy(self):
        """Move position from IDLE to BUYING by triggering buy order.

        Simulates:
        1. Mock create_order to return NEW order
        2. Send price trigger to initiate buy
        3. Wait for BUYING state transition
        4. Verify order was sent

        V2 State: IDLE → BUYING
        """

        strategy = self.back.strategy

        # Mock order creation to return NEW order
        strategy.client.create_order.side_effect = [
            get_new_order(order=strategy.buy.buy_order)
        ]

        # Trigger buy by sending price at or below trigger_price
        # With buy_price=50000 and order_trigger=0.01 (1%), trigger_price=50500
        # Send price at 50500 to trigger the buy
        trigger_price = strategy.buy.trigger_price
        self.new_price(price=trigger_price, symbol="BTCUSDC")
        logger.info(
            f"Sent price={trigger_price} to trigger buy (trigger_price={trigger_price})"
        )

        # Give time for worker loop to process the event
        await asyncio.sleep(0.5)

        # Debug: Check conditions manually
        logger.info(f"Current state: {strategy.lifecycle_state}")
        logger.info(f"Ticker price: {strategy.ticker_price}")
        logger.info(f"Trigger price: {strategy.buy.trigger_price}")
        logger.info(
            f"Balance: {strategy.balance}, Budget: {strategy.buy_config.budget}"
        )
        logger.info(
            f"can_start_buying would return: {strategy.ticker_price is not None and strategy.ticker_price <= strategy.buy.trigger_price and strategy.balance >= strategy.buy_config.budget}"
        )

        # Wait for BUYING state transition
        await self.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)

        # Verify order was sent
        assert strategy.buy.buy_order.order_id is not None
        assert strategy.buy.buy_order.status == ORDER_STATUS_NEW

        logger.info(
            f"Position moved to BUYING: order_id={strategy.buy.buy_order.order_id}, "
            f"status={strategy.buy.buy_order.status}"
        )

    async def wait_for_state(
        self,
        expected_state: PositionLifecycleState,
        timeout: float = 2.0,
    ):
        """Wait for V2 strategy to reach expected lifecycle state.

        Args:
            expected_state: Expected PositionLifecycleState
            timeout: Maximum wait time in seconds

        Raises:
            AssertionError: If state not reached within timeout
        """
        await self.wait_for_condition(
            lambda: self.back.strategy is not None
            and self.back.strategy.lifecycle_state == expected_state,
            timeout=timeout,
        )
        logger.info(f"✓ Strategy reached state: {expected_state}")

    def get_current_state(self) -> PositionLifecycleState:
        """Get current lifecycle state of V2 strategy.

        Returns:
            Current PositionLifecycleState
        """
        if self.back.strategy:
            return self.back.strategy.lifecycle_state
        return PositionLifecycleState.IDLE

    def assert_state(self, expected_state: PositionLifecycleState):
        """Assert current state matches expected state.

        Args:
            expected_state: Expected PositionLifecycleState

        Raises:
            AssertionError: If state doesn't match
        """
        current_state = self.get_current_state()
        assert (
            current_state == expected_state
        ), f"Expected state {expected_state}, got {current_state}"
        logger.info(f"✓ State assertion passed: {expected_state}")
