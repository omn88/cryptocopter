"""Buy Dip Strategy Simulator for E2E Testing.

This simulator provides lifecycle methods for testing Buy Dip strategy,
similar to HPSimulator for HP Manager.

Supports:
- Single position lifecycle (rising → top → DCA → sell)
- Multiple concurrent positions
- Budget tracking
- Order sequencing
- Top invalidation scenarios
"""

import asyncio
import logging
import time
from typing import Callable, List, Dict, Optional, Tuple, Any
from datetime import datetime, timedelta

logger = logging.getLogger("buy_dip_simulator")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


async def wait_for_condition(
    condition_func: Callable, timeout: float = 2.0, interval: float = 0.05
) -> None:
    """
    Wait for a condition function to return True, otherwise raise AssertionError.

    Args:
        condition_func: Callable (sync or async) that returns True when condition is met
        timeout: Maximum time to wait (seconds)
        interval: Time between checks (seconds)

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


# ============================================================================
# CANDLE DATA HELPERS
# ============================================================================


def create_candle(
    open_price: float,
    high: float,
    low: float,
    close: float,
    timestamp: datetime,
    volume: float = 100.0,
) -> Dict:
    """Create a candle dictionary matching Binance kline format."""
    return {
        "t": int(timestamp.timestamp() * 1000),  # Open time
        "o": str(open_price),
        "h": str(high),
        "l": str(low),
        "c": str(close),
        "v": str(volume),
        "T": int((timestamp + timedelta(minutes=15)).timestamp() * 1000),  # Close time
        "q": str(volume * close),  # Quote asset volume
        "n": 1000,  # Number of trades
        "V": str(volume * 0.5),  # Taker buy base volume
        "Q": str(volume * close * 0.5),  # Taker buy quote volume
        "x": True,  # Is closed
    }


def create_rising_pattern(
    start_price: float,
    num_candles: int,
    gain_per_candle: float,
    start_time: Optional[datetime] = None,
) -> List[Dict]:
    """
    Create a rising candle pattern.

    Args:
        start_price: Starting price
        num_candles: Number of candles
        gain_per_candle: Percentage gain per candle (e.g., 0.1 for 0.1%)
        start_time: Starting timestamp (defaults to now)

    Returns:
        List of candle dictionaries with consecutive higher highs
    """
    if start_time is None:
        start_time = datetime.now()

    candles = []
    current_price = start_price

    for i in range(num_candles):
        timestamp = start_time + timedelta(minutes=15 * i)
        next_price = current_price * (1 + gain_per_candle / 100)

        candle = create_candle(
            open_price=current_price,
            high=next_price,
            low=current_price * 0.999,  # Small wick down
            close=next_price * 0.9995,  # Close near high
            timestamp=timestamp,
        )
        candles.append(candle)
        current_price = next_price

    return candles


def create_pullback_pattern(
    top_price: float,
    pullback_pct: float,
    num_candles: int = 2,
    start_time: Optional[datetime] = None,
) -> List[Dict]:
    """
    Create a pullback pattern from a top.

    Args:
        top_price: The high watermark price
        pullback_pct: Pullback percentage (e.g., 0.5 for 0.5% drop)
        num_candles: Number of candles in pullback
        start_time: Starting timestamp

    Returns:
        List of candle dictionaries showing price decline
    """
    if start_time is None:
        start_time = datetime.now()

    candles = []
    bottom_price = top_price * (1 - pullback_pct / 100)
    price_step = (top_price - bottom_price) / num_candles

    current_price = top_price
    for i in range(num_candles):
        timestamp = start_time + timedelta(minutes=15 * i)
        next_price = current_price - price_step

        candle = create_candle(
            open_price=current_price,
            high=current_price,
            low=next_price * 0.999,
            close=next_price,
            timestamp=timestamp,
        )
        candles.append(candle)
        current_price = next_price

    return candles


# ============================================================================
# BUY DIP SIMULATOR
# ============================================================================


class BuyDipSimulator:
    """Simulator for Buy Dip strategy lifecycle testing."""

    def __init__(
        self,
        strategy,  # BuyDipStrategy instance
        broker,  # Mock broker
    ):
        """
        Initialize simulator.

        Args:
            strategy: BuyDipStrategy instance
            broker: Mock broker for order execution
        """
        self.strategy = strategy
        self.broker = broker
        self.candle_buffer = []
        self.current_time = datetime.now()

    # ========================================================================
    # CANDLE INJECTION
    # ========================================================================

    async def send_candle(self, candle: Dict) -> None:
        """
        Send a single candle to the strategy.

        Args:
            candle: Candle dictionary
        """
        await self.strategy.on_candle(candle)
        self.candle_buffer.append(candle)
        logger.info(f"Sent candle: H={candle['h']}, L={candle['l']}, C={candle['c']}")

    async def send_candles(self, candles: List[Dict]) -> None:
        """
        Send multiple candles sequentially.

        Args:
            candles: List of candle dictionaries
        """
        for candle in candles:
            await self.send_candle(candle)
            await asyncio.sleep(0.01)  # Small delay for processing

    # ========================================================================
    # PATTERN SIMULATION
    # ========================================================================

    async def simulate_rising_to_top(
        self,
        start_price: float = 67000,
        end_price: float = 67890,
        num_candles: int = 3,
    ) -> float:
        """
        Simulate rising pattern leading to potential top.

        Args:
            start_price: Starting price
            end_price: Top price
            num_candles: Number of candles

        Returns:
            The top price reached
        """
        total_gain = ((end_price - start_price) / start_price) * 100
        gain_per_candle = total_gain / num_candles

        candles = create_rising_pattern(
            start_price=start_price,
            num_candles=num_candles,
            gain_per_candle=gain_per_candle,
            start_time=self.current_time,
        )

        await self.send_candles(candles)
        self.current_time += timedelta(minutes=15 * num_candles)

        logger.info(f"Simulated rising pattern: {start_price} → {end_price}")
        return end_price

    async def simulate_pullback(
        self,
        from_price: float,
        pullback_pct: float = 0.5,
        num_candles: int = 2,
    ) -> float:
        """
        Simulate pullback from top.

        Args:
            from_price: Starting price (top)
            pullback_pct: Pullback percentage
            num_candles: Number of candles

        Returns:
            Bottom price reached
        """
        candles = create_pullback_pattern(
            top_price=from_price,
            pullback_pct=pullback_pct,
            num_candles=num_candles,
            start_time=self.current_time,
        )

        await self.send_candles(candles)
        self.current_time += timedelta(minutes=15 * num_candles)

        bottom_price = from_price * (1 - pullback_pct / 100)
        logger.info(f"Simulated pullback: {from_price} → {bottom_price}")
        return bottom_price

    async def simulate_recovery(
        self,
        from_price: float,
        to_price: float,
        num_candles: int = 2,
    ) -> None:
        """
        Simulate price recovery back to top.

        Args:
            from_price: Current price (bottom)
            to_price: Target price (top)
            num_candles: Number of candles
        """
        total_gain = ((to_price - from_price) / from_price) * 100
        gain_per_candle = total_gain / num_candles

        candles = create_rising_pattern(
            start_price=from_price,
            num_candles=num_candles,
            gain_per_candle=gain_per_candle,
            start_time=self.current_time,
        )

        await self.send_candles(candles)
        self.current_time += timedelta(minutes=15 * num_candles)

        logger.info(f"Simulated recovery: {from_price} → {to_price}")

    # ========================================================================
    # ORDER SIMULATION
    # ========================================================================

    async def fill_order(self, order_id: str, fill_price: float) -> None:
        """
        Simulate order fill.

        Args:
            order_id: Order ID to fill
            fill_price: Execution price
        """
        await self.broker.simulate_fill(order_id, fill_price)
        logger.info(f"Filled order {order_id} at {fill_price}")

    async def cancel_order(self, order_id: str) -> None:
        """
        Simulate order cancellation.

        Args:
            order_id: Order ID to cancel
        """
        await self.broker.simulate_cancel(order_id)
        logger.info(f"Cancelled order {order_id}")

    # ========================================================================
    # POSITION QUERIES
    # ========================================================================

    def get_active_positions(self) -> List[Any]:
        """Get all active positions."""
        return [
            pos
            for pos in self.strategy.positions.values()
            if pos.state in ["POTENTIAL_TOP", "ACTIVE"]
        ]

    def get_completed_positions(self) -> List[Any]:
        """Get all completed positions."""
        return [
            pos for pos in self.strategy.positions.values() if pos.state == "COMPLETED"
        ]

    def get_pending_orders(self) -> List[Any]:
        """Get all pending orders across all positions."""
        orders = []
        for pos in self.strategy.positions.values():
            orders.extend(pos.get_pending_orders())
        return orders

    def get_position_by_id(self, position_id: str) -> Optional[Any]:
        """Get position by ID."""
        return self.strategy.positions.get(position_id)

    # ========================================================================
    # STATE ASSERTIONS
    # ========================================================================

    async def wait_for_potential_top(self, timeout: float = 2.0) -> None:
        """Wait for a position to reach POTENTIAL_TOP state."""
        await wait_for_condition(
            lambda: any(
                pos.state == "POTENTIAL_TOP" for pos in self.strategy.positions.values()
            ),
            timeout=timeout,
        )

    async def wait_for_active_position(self, timeout: float = 2.0) -> None:
        """Wait for a position to reach ACTIVE state."""
        await wait_for_condition(
            lambda: any(
                pos.state == "ACTIVE" for pos in self.strategy.positions.values()
            ),
            timeout=timeout,
        )

    async def wait_for_order_placed(
        self, position_id: str, timeout: float = 2.0
    ) -> None:
        """Wait for an order to be placed for a position."""
        await wait_for_condition(
            lambda: (pos := self.get_position_by_id(position_id)) is not None
            and len(pos.pending_orders) > 0,
            timeout=timeout,
        )

    async def wait_for_position_closed(
        self, position_id: str, timeout: float = 2.0
    ) -> None:
        """Wait for a position to close."""
        await wait_for_condition(
            lambda: (pos := self.get_position_by_id(position_id)) is not None
            and pos.state == "COMPLETED",
            timeout=timeout,
        )

    async def wait_for_no_pending_orders(
        self, position_id: str, timeout: float = 2.0
    ) -> None:
        """Wait for all orders of a position to be cancelled/filled."""
        await wait_for_condition(
            lambda: (pos := self.get_position_by_id(position_id)) is not None
            and len(pos.pending_orders) == 0,
            timeout=timeout,
        )

    # ========================================================================
    # BUDGET QUERIES
    # ========================================================================

    def get_available_budget(self) -> float:
        """Get current available budget."""
        return self.strategy.budget_manager.available_budget

    def get_locked_budget(self) -> float:
        """Get total locked budget across all positions."""
        return self.strategy.budget_manager.locked_budget

    def get_total_budget(self) -> float:
        """Get total budget (available + locked)."""
        return self.get_available_budget() + self.get_locked_budget()

    # ========================================================================
    # COMPLETE LIFECYCLE SCENARIOS
    # ========================================================================

    async def simulate_perfect_position(
        self,
        start_price: float = 67000,
        top_price: float = 67890,
        dca_levels: int = 2,
    ) -> Dict:
        """
        Simulate a complete position lifecycle with perfect fills.

        Args:
            start_price: Starting price
            top_price: Top price
            dca_levels: Number of DCA orders to fill

        Returns:
            Position result dictionary
        """
        # 1. Rising to top
        await self.simulate_rising_to_top(start_price, top_price)
        await self.wait_for_potential_top()

        positions = self.get_active_positions()
        assert len(positions) > 0, "No active positions found"
        position = positions[0]
        position_id = position.position_id

        # 2. Fill first order (confirmation)
        assert len(position.pending_orders) > 0, "No pending orders found"
        order_1 = position.pending_orders[0]
        await self.fill_order(order_1.order_id, top_price)
        await self.wait_for_active_position()

        # 3. Fill DCA orders sequentially
        for i in range(dca_levels):
            await self.wait_for_order_placed(position_id)
            pos = self.get_position_by_id(position_id)
            assert pos is not None, f"Position {position_id} not found"
            assert len(pos.pending_orders) > 0, "No pending orders found"
            order = pos.pending_orders[0]
            await self.fill_order(order.order_id, float(order.price))

        # 4. Recovery and sell
        await self.simulate_recovery(float(order.price), top_price)
        await self.wait_for_position_closed(position_id)

        final_pos = self.get_position_by_id(position_id)
        assert final_pos is not None, f"Position {position_id} not found"

        return {
            "position_id": position_id,
            "realized_pnl": final_pos.realized_pnl,
            "total_invested": final_pos.total_invested,
        }

    async def simulate_top_invalidation(
        self,
        first_top: float = 67890,
        second_top: float = 68100,
    ) -> Dict:
        """
        Simulate top invalidation scenario.

        Args:
            first_top: Initial top price
            second_top: New higher top price

        Returns:
            Result dictionary
        """
        # 1. First top
        await self.simulate_rising_to_top(67000, first_top)
        await self.wait_for_potential_top()

        positions = self.get_active_positions()
        assert len(positions) > 0, "No active positions found"
        first_position = positions[0]
        assert len(first_position.pending_orders) > 0, "No pending orders found"
        first_order_id = first_position.pending_orders[0].order_id

        # 2. New higher top (invalidation)
        await self.simulate_rising_to_top(first_top, second_top, num_candles=2)

        # 3. Verify first order cancelled, new order placed
        await self.wait_for_no_pending_orders(first_position.position_id)
        await self.wait_for_order_placed(first_position.position_id)

        updated_pos = self.get_position_by_id(first_position.position_id)
        assert (
            updated_pos is not None
        ), f"Position {first_position.position_id} not found"
        assert len(updated_pos.pending_orders) > 0, "No pending orders found"
        new_order = updated_pos.pending_orders[0]

        return {
            "first_top": first_top,
            "second_top": second_top,
            "first_order_cancelled": first_order_id
            not in [o.order_id for o in updated_pos.pending_orders],
            "new_order_price": float(new_order.price),
        }
