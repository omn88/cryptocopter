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
from typing import Callable, List, Dict, Optional, Any
from datetime import datetime, timedelta

from src.strategies.buy_dip.position import PositionState, BuyDipPosition
from src.strategies.buy_dip.strategy import BuyDipStrategy

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

    for i in range(num_candles):
        timestamp = start_time + timedelta(minutes=15 * i)
        # Calculate the high for this pullback candle
        # For HWM detector to confirm, high must be below top by at least threshold
        # We gradually move from top towards bottom
        progress = (i + 1) / num_candles
        current_high = top_price - (top_price - bottom_price) * progress
        current_close = bottom_price + (top_price - bottom_price) * (1 - progress) * 0.1

        candle = create_candle(
            open_price=top_price if i == 0 else current_close,
            high=current_high,
            low=bottom_price * 0.999,
            close=current_close,
            timestamp=timestamp,
        )
        candles.append(candle)

    return candles


# ============================================================================
# BUY DIP SIMULATOR
# ============================================================================


class BuyDipSimulator:
    """Simulator for Buy Dip strategy lifecycle testing."""

    def __init__(
        self,
        strategy: BuyDipStrategy,
    ) -> None:
        """
        Initialize simulator.

        Args:
            strategy: BuyDipStrategy instance
        """
        self.strategy: BuyDipStrategy = strategy
        self.candle_buffer: List[Dict] = []
        self.current_time = datetime.now()

    # ========================================================================
    # PROPERTIES FOR EASY ACCESS
    # ========================================================================

    @property
    def broker_adapter(self):
        """Access to broker adapter for order management."""
        return self.strategy.broker_adapter

    # ========================================================================
    # CANDLE INJECTION
    # ========================================================================

    async def send_candle(self, candle: Dict) -> None:
        """
        Send a single candle to the strategy.

        Args:
            candle: Candle dictionary (Binance kline format)
        """
        # Convert Binance kline format to strategy format
        strategy_candle = {
            "open": float(candle["o"]),
            "high": float(candle["h"]),
            "low": float(candle["l"]),
            "close": float(candle["c"]),
            "volume": float(candle["v"]),
            "timestamp": candle["t"] / 1000,  # Convert ms to seconds
        }

        # Process candle through strategy (async)
        await self.strategy.process_candle("BTCUSDC", strategy_candle)
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
        confirm_top: bool = True,
    ) -> Optional[float]:
        """
        Simulate rising pattern leading to potential top.

        Args:
            start_price: Starting price
            end_price: Top price
            num_candles: Number of candles
            confirm_top: If True, send pullback candle to confirm top (default: True)

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

        # Send pullback candle to confirm the top (default min_pullback_pct is 0.5%)
        if confirm_top:
            # Get the actual HWM from the detector (might be slightly higher than end_price)
            hwm_detector = self.strategy._hwm_detectors.get("BTCUSDC")
            actual_top = hwm_detector.get_hwm() if hwm_detector else end_price

            pullback_candles = create_pullback_pattern(
                top_price=actual_top if actual_top is not None else end_price,
                pullback_pct=0.6,  # Slightly more than min threshold
                num_candles=1,
                start_time=self.current_time,
            )
            await self.send_candles(pullback_candles)
            self.current_time += timedelta(minutes=15)

            # Return the actual HWM (confirmed top)
            if hwm_detector and hwm_detector.is_top_confirmed():
                return hwm_detector.get_confirmed_top()
            return None

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

        # Auto-fill sell orders if price reached their level
        for position in self.get_active_positions():
            logger.debug(
                f"Checking position {position.position_id} for sell order: {position.sell_order}"
            )
            if position.sell_order and position.sell_order.status == "NEW":
                sell_price = float(position.sell_order.price)
                logger.debug(f"Sell order at {sell_price}, recovery to {to_price}")
                # If recovery reached or exceeded sell price, fill it
                if to_price >= sell_price:
                    await self.fill_sell_order(position.sell_order.order_id, sell_price)
                else:
                    logger.debug(
                        f"Price {to_price} did not reach sell price {sell_price}"
                    )
            elif position.sell_order:
                logger.debug(
                    f"Sell order exists but status is: {position.sell_order.status}"
                )
            else:
                logger.debug(f"No sell order for position {position.position_id}")

        logger.info(f"Simulated recovery: {from_price} → {to_price}")

    # ========================================================================
    # ORDER SIMULATION (E2E through broker callbacks)
    # ========================================================================

    async def fill_order(self, order_id: str, fill_price: float) -> None:
        """
        Simulate order fill through broker adapter ExecutionReport path.

        This simulates the real flow:
        1. Order was placed through broker_adapter.place_order (already done by strategy)
        2. Exchange fills the order
        3. WebSocket user stream sends executionReport event
        4. Broker adapter processes event via handle_user_stream_update()
        5. Broker adapter triggers callback to strategy

        Args:
            order_id: Order ID to fill
            fill_price: Execution price
        """
        # Find which position this order belongs to
        position_id = self.strategy._order_to_position.get(order_id)
        if not position_id:
            logger.warning(f"Order {order_id} not found in order tracking")
            return

        position = self.strategy._positions.get(position_id)
        if not position:
            logger.warning(f"Position {position_id} not found")
            return

        # Determine fill quantity from pending order
        if position.pending_order and position.pending_order.order_id == order_id:
            fill_quantity = float(position.pending_order.quantity)
        else:
            logger.warning(f"Order {order_id} not pending for position {position_id}")
            return

        # Simulate executionReport event from WebSocket (if using broker_adapter)
        if self.strategy.broker_adapter:
            execution_report = {
                "e": "executionReport",  # Event type
                "s": "BTCUSDC",  # Symbol
                "c": order_id,  # Client order ID
                "S": "BUY",  # Side
                "o": "LIMIT",  # Order type
                "q": str(fill_quantity),  # Order quantity
                "p": str(fill_price),  # Price
                "X": "FILLED",  # Order status
                "l": str(fill_quantity),  # Last executed quantity (full fill)
                "L": str(fill_price),  # Last executed price
                "z": str(fill_quantity),  # Cumulative filled quantity
                "n": "0",  # Commission
                "N": "USDC",  # Commission asset
            }
            # Process through broker adapter (simulates WebSocket event)
            self.strategy.broker_adapter.handle_user_stream_update(execution_report)
        else:
            # Fallback: direct callback (for old-style tests)
            self.strategy.handle_order_fill(order_id, fill_price, fill_quantity)

        logger.info(f"Filled order {order_id} at {fill_price} qty {fill_quantity}")

    async def fill_sell_order(self, order_id: str, fill_price: float) -> None:
        """
        Simulate sell order fill through broker adapter ExecutionReport path.

        This simulates the real flow:
        1. Sell order was placed through broker_adapter.place_order
        2. Exchange fills the sell order
        3. WebSocket user stream sends executionReport event
        4. Broker adapter processes event
        5. Broker adapter triggers callback to strategy

        Args:
            order_id: Sell order ID to fill
            fill_price: Execution price
        """
        # Find position with this sell order
        position = None
        for pos in self.strategy._positions.values():
            if pos.sell_order and pos.sell_order.order_id == order_id:
                position = pos
                break

        if not position:
            logger.warning(f"Sell order {order_id} not found")
            return

        # Check if sell order exists
        if not position.sell_order:
            logger.warning(f"Position {position.position_id} has no sell order")
            return

        # Get sell quantity
        fill_quantity = float(position.sell_order.quantity)

        # Simulate executionReport event from WebSocket (if using broker_adapter)
        if self.strategy.broker_adapter:
            execution_report = {
                "e": "executionReport",  # Event type
                "s": "BTCUSDC",  # Symbol
                "c": order_id,  # Client order ID
                "S": "SELL",  # Side
                "o": "LIMIT",  # Order type
                "q": str(fill_quantity),  # Order quantity
                "p": str(fill_price),  # Price
                "X": "FILLED",  # Order status
                "l": str(fill_quantity),  # Last executed quantity (full fill)
                "L": str(fill_price),  # Last executed price
                "z": str(fill_quantity),  # Cumulative filled quantity
                "n": "0",  # Commission
                "N": "USDC",  # Commission asset
            }
            # Process through broker adapter (simulates WebSocket event)
            self.strategy.broker_adapter.handle_user_stream_update(execution_report)
        else:
            # Fallback: direct callback (for old-style tests)
            self.strategy.handle_sell_fill(order_id, fill_price)

        logger.info(f"Filled sell order {order_id} at {fill_price} qty {fill_quantity}")

    async def cancel_order(self, order_id: str) -> None:
        """
        Simulate order cancellation.

        Args:
            order_id: Order ID to cancel
        """
        # Create executionReport for cancellation
        execution_report = {
            "e": "executionReport",
            "s": (
                self.strategy.broker_adapter.symbol
                if self.strategy.broker_adapter
                else "BTCUSDC"
            ),
            "c": order_id,
            "S": "BUY",  # Side
            "o": "LIMIT",  # Order type
            "q": "0",  # Original quantity
            "p": "0",  # Price
            "X": "CANCELED",  # Order status
            "l": "0",  # Last executed quantity
            "L": "0",  # Last executed price
            "z": "0",  # Cumulative filled quantity
            "n": "0",  # Commission amount
            "N": "USDC",  # Commission asset
        }

        if self.strategy.broker_adapter:
            self.strategy.broker_adapter.handle_user_stream_update(execution_report)

        logger.info(f"Cancelled order {order_id}")

    # ========================================================================
    # POSITION QUERIES
    # ========================================================================

    def get_active_positions(self) -> List[BuyDipPosition]:
        """Get all active positions."""

        return [
            pos
            for pos in self.strategy._positions.values()
            if pos.state in [PositionState.POTENTIAL_TOP, PositionState.ACTIVE]
        ]

    def get_completed_positions(self) -> List[BuyDipPosition]:
        """Get all completed positions."""

        return [
            pos
            for pos in self.strategy._positions.values()
            if pos.state == PositionState.COMPLETED
        ]

    def get_pending_orders(self) -> List[Any]:
        """Get all pending orders across all positions."""
        orders = []
        for pos in self.strategy._positions.values():
            if pos.pending_order:
                orders.append(pos.pending_order)
        return orders

    def get_position_by_id(self, position_id: str) -> Optional[BuyDipPosition]:
        """Get position by ID."""
        return self.strategy._positions.get(position_id)

    # ========================================================================
    # STATE ASSERTIONS
    # ========================================================================

    async def wait_for_potential_top(self, timeout: float = 2.0) -> None:
        """Wait for a position to reach POTENTIAL_TOP state."""

        await wait_for_condition(
            lambda: any(
                pos.state == PositionState.POTENTIAL_TOP
                for pos in self.strategy._positions.values()
            ),
            timeout=timeout,
        )

    async def wait_for_active_position(self, timeout: float = 2.0) -> None:
        """Wait for a position to reach ACTIVE state."""

        await wait_for_condition(
            lambda: any(
                pos.state == PositionState.ACTIVE
                for pos in self.strategy._positions.values()
            ),
            timeout=timeout,
        )

    async def wait_for_order_placed(
        self, position_id: str, timeout: float = 2.0
    ) -> None:
        """Wait for an order to be placed for a position."""
        await wait_for_condition(
            lambda: (pos := self.get_position_by_id(position_id)) is not None
            and pos.pending_order is not None,
            timeout=timeout,
        )

    async def wait_for_position_closed(
        self, position_id: str, timeout: float = 2.0
    ) -> None:
        """Wait for a position to close."""

        await wait_for_condition(
            lambda: (pos := self.get_position_by_id(position_id)) is not None
            and pos.state == PositionState.COMPLETED,
            timeout=timeout,
        )

    async def wait_for_no_pending_orders(
        self, position_id: str, timeout: float = 2.0
    ) -> None:
        """Wait for all orders of a position to be cancelled/filled."""
        await wait_for_condition(
            lambda: (pos := self.get_position_by_id(position_id)) is not None
            and pos.pending_order is None,
            timeout=timeout,
        )

    # ========================================================================
    # BUDGET QUERIES
    # ========================================================================

    def get_available_budget(self) -> float:
        """Get current available budget."""
        return float(self.strategy._budget_manager.get_available_budget())

    def get_locked_budget(self) -> float:
        """Get total locked budget across all positions."""
        return float(self.strategy._budget_manager.get_locked_budget())

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
        assert position.pending_order is not None, "No pending order found"
        order_1 = position.pending_order
        await self.fill_order(order_1.order_id, top_price)
        await self.wait_for_active_position()

        # 3. Fill DCA orders sequentially
        for i in range(dca_levels):
            await self.wait_for_order_placed(position_id)
            pos = self.get_position_by_id(position_id)
            assert pos is not None, f"Position {position_id} not found"
            assert pos.pending_order is not None, "No pending order found"
            order = pos.pending_order
            await self.fill_order(order.order_id, float(order.price))

        # 4. Recovery and sell
        # Get the actual sell price from the position
        pos_for_sell = self.get_position_by_id(position_id)
        assert pos_for_sell is not None
        if pos_for_sell.sell_order:
            # Recover to at least the sell price to trigger fill
            recovery_target = max(float(pos_for_sell.sell_order.price), top_price)
        else:
            recovery_target = top_price

        await self.simulate_recovery(float(order.price), recovery_target)
        await self.wait_for_position_closed(position_id)

        final_pos = self.get_position_by_id(position_id)
        assert final_pos is not None, f"Position {position_id} not found"

        # Calculate realized PnL
        # Total invested = sum of all buy order fills
        # Total returned = sell order fill
        # PnL = returned - invested
        total_invested = float(final_pos.total_invested)
        total_quantity = float(final_pos.total_quantity)

        # Get sell price from sell order if it was filled
        if final_pos.sell_order and final_pos.sell_order.filled_price:
            sell_price = float(final_pos.sell_order.filled_price)
            total_returned = total_quantity * sell_price
            realized_pnl = total_returned - total_invested
        else:
            realized_pnl = 0.0

        return {
            "position_id": position_id,
            "realized_pnl": realized_pnl,
            "total_invested": total_invested,
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
        assert first_position.pending_order is not None, "No pending order found"
        first_order_id = first_position.pending_order.order_id

        # 2. New higher top (invalidation)
        await self.simulate_rising_to_top(first_top, second_top, num_candles=2)

        # 3. Verify first order cancelled, new order placed
        await self.wait_for_no_pending_orders(first_position.position_id)
        await self.wait_for_order_placed(first_position.position_id)

        updated_pos = self.get_position_by_id(first_position.position_id)
        assert (
            updated_pos is not None
        ), f"Position {first_position.position_id} not found"
        assert updated_pos.pending_order is not None, "No pending order found"
        new_order = updated_pos.pending_order

        return {
            "first_top": first_top,
            "second_top": second_top,
            "first_order_cancelled": first_order_id != new_order.order_id,
            "new_order_price": float(new_order.price),
        }
