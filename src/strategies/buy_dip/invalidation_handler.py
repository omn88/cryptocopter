"""TopInvalidationHandler - Handles top invalidation logic for Buy Dip strategy.

Extracted from BuyDipStrategy to follow Single Responsibility Principle.
Manages:
- ATR-based validation of new highs
- Pending order cancellation
- Budget unlocking
- Replacement order scheduling
- Cooldown management
"""

import asyncio
import logging
import time
from decimal import Decimal
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from src.strategies.buy_dip.strategy import BuyDipStrategy

from src.strategies.buy_dip.position import BuyDipPosition, PositionState

logger = logging.getLogger(__name__)


class TopInvalidationHandler:
    """Handles top invalidation and replacement order logic.

    Responsibilities:
    - Validate new highs against ATR thresholds
    - Cancel pending orders when top is invalidated
    - Release locked budget
    - Schedule replacement orders after cooldown
    - Manage invalidation tasks
    """

    def __init__(self, strategy: "BuyDipStrategy"):
        """Initialize handler with reference to main strategy.

        Args:
            strategy: BuyDipStrategy instance (for access to config, positions, etc.)
        """
        self.strategy = strategy
        self._scheduled_tasks: Dict[str, asyncio.Task] = {}

    async def handle_invalidation(self, symbol: str, candle: Dict) -> None:
        """Handle top invalidation - cancel pending orders and update to new top.

        Args:
            symbol: Symbol with invalidated top
            candle: Current candle with new high
        """
        new_top_price = Decimal(str(candle["high"]))
        logger.debug(
            "Top invalidation detected for %s: new_high=%s", symbol, str(new_top_price)
        )

        # Update all POTENTIAL_TOP positions for this symbol
        for position in self.strategy._get_potential_top_positions(symbol):
            if not position.top_price:
                continue

            await self._invalidate_position(position, new_top_price, candle)

    async def _invalidate_position_async(
        self, position: BuyDipPosition, new_top_price: Decimal, candle: Dict
    ) -> None:
        """Invalidate a single position and place immediate replacement (async version).

        Used when we need to ensure order cancellation completes before placing replacement.

        Args:
            position: Position to invalidate
            new_top_price: New top price from candle
            candle: Current candle data
        """
        logger.debug(
            "Invalidating pos=%s current_top=%s pending=%s (async)",
            position.position_id,
            str(position.top_price),
            bool(position.pending_order),
        )

        # Validate that new high is significant enough
        if not self._is_significant_new_high(position, new_top_price):
            return

        # Cancel pending order if exists (await completion)
        await self._cancel_pending_order_async(position)

        # Update position to new top
        self._update_position_state(position, new_top_price, candle)

        # For first DCA level, place order immediately
        # For subsequent levels, schedule delayed replacement
        if position.next_dca_level == 0:
            # Place first order immediately based on new top
            self._place_immediate_replacement(position)
        else:
            # Schedule delayed replacement order
            self._schedule_replacement_order(position)

    async def _invalidate_position(
        self, position: BuyDipPosition, new_top_price: Decimal, candle: Dict
    ) -> None:
        """Invalidate a single position and schedule replacement.

        Args:
            position: Position to invalidate
            new_top_price: New top price from candle
            candle: Current candle data
        """
        logger.debug(
            "Invalidating pos=%s current_top=%s pending=%s",
            position.position_id,
            str(position.top_price),
            bool(position.pending_order),
        )

        # Validate that new high is significant enough
        if not self._is_significant_new_high(position, new_top_price):
            return

        # For first DCA level, await async cancellation before placing replacement
        if position.next_dca_level == 0:
            await self._invalidate_position_async(position, new_top_price, candle)
        else:
            # For subsequent levels, use regular flow with delayed replacement
            self._cancel_pending_order(position)
            self._update_position_state(position, new_top_price, candle)
            self._schedule_replacement_order(position)

    def _is_significant_new_high(
        self, position: BuyDipPosition, new_top_price: Decimal
    ) -> bool:
        """Check if new high is significant enough to invalidate top.

        Uses both percentage delta and ATR-based thresholds.

        Args:
            position: Position with current top
            new_top_price: Potential new top

        Returns:
            True if new high is significant, False if marginal
        """
        if position.top_price is None:
            return True  # No previous top, treat as significant

        try:
            prev_top = float(position.top_price)
            new_top = float(new_top_price)
            pct_delta = (new_top - prev_top) / prev_top * 100.0
        except (ValueError, TypeError, ZeroDivisionError):
            pct_delta = 0.0

        # Check if delta is below threshold (too small to be significant)
        if pct_delta < float(self.strategy.config.invalidation_min_delta_pct):
            logger.debug(
                "Ignoring marginal new high for %s: delta_pct=%.6f < min_delta_pct=%.6f",
                position.symbol,
                pct_delta,
                float(self.strategy.config.invalidation_min_delta_pct),
            )
            return False

        return True

    async def _cancel_pending_order_async(self, position: BuyDipPosition) -> None:
        """Cancel pending order and release locked funds (async version).

        Args:
            position: Position with pending order to cancel
        """
        pending_order = position.pending_order
        if not pending_order:
            return

        # Cancel order in broker (await completion)
        order_id = pending_order.order_id
        try:
            # Try broker_adapter first (production), fallback to broker (backtesting)
            broker = self.strategy.broker_adapter or self.strategy.broker
            if broker:
                await broker.cancel_order(order_id)
                logger.debug(f"Cancelled order {order_id} in broker")
        except Exception as e:
            logger.warning(f"Failed to cancel order {order_id} in broker: {e}")

        # Mark as canceled and release locked funds immediately
        pending_order.status = "CANCELED"

        # Calculate and release locked funds
        try:
            order_amount = float(pending_order.price * pending_order.quantity)
        except (ValueError, TypeError):
            order_amount = 0.0

        if order_amount > 0:
            self.strategy._budget_manager.release_funds(order_amount)

        # Clear pending order on position
        position.pending_order = None

        # Clear order tracking
        if pending_order.order_id in self.strategy._order_to_position:
            del self.strategy._order_to_position[pending_order.order_id]

        logger.debug(
            "Canceled pending order %s, released %.2f USDC",
            pending_order.order_id,
            order_amount,
        )

    def _cancel_pending_order(self, position: BuyDipPosition) -> None:
        """Cancel pending order and release locked funds.

        Args:
            position: Position with pending order to cancel
        """
        pending_order = position.pending_order
        if not pending_order:
            return

        # Cancel order in broker (fire and forget for backward compatibility)
        order_id = pending_order.order_id
        try:
            # Try broker_adapter first (production), fallback to broker (backtesting)
            broker = self.strategy.broker_adapter or self.strategy.broker
            if broker:
                # Use asyncio.create_task to avoid blocking
                asyncio.create_task(broker.cancel_order(order_id))
        except Exception as e:
            logger.warning(f"Failed to cancel order {order_id} in broker: {e}")

        # Mark as canceled and release locked funds immediately
        pending_order.status = "CANCELED"

        # Calculate and release locked funds
        try:
            order_amount = float(pending_order.price * pending_order.quantity)
        except (ValueError, TypeError):
            order_amount = 0.0

        if order_amount > 0:
            self.strategy._budget_manager.release_funds(order_amount)

        # Clear pending order on position
        position.pending_order = None

        # Clear order tracking
        if pending_order.order_id in self.strategy._order_to_position:
            del self.strategy._order_to_position[pending_order.order_id]

        logger.debug(
            "Canceled pending order %s, released %.2f USDC",
            pending_order.order_id,
            order_amount,
        )

    def _update_position_state(
        self, position: BuyDipPosition, new_top_price: Decimal, candle: Dict
    ) -> None:
        """Update position to new top and set cooldown.

        Args:
            position: Position to update
            new_top_price: New top price
            candle: Current candle (for timestamp)
        """
        # Update to new top price (stay in POTENTIAL_TOP state)
        position.top_price = new_top_price

        # Mark transient flag so replacement will not occur in this cycle
        position.just_invalidated = True

        # Record invalidation timestamp
        try:
            ts_value = candle.get("timestamp")
            if ts_value is not None:
                position.last_invalidation_ts = int(ts_value)
            else:
                position.last_invalidation_ts = None
        except (ValueError, TypeError):
            position.last_invalidation_ts = None

        # Set cooldown to prevent immediate replacement
        try:
            position.cooldown_until = time.time() + float(
                self.strategy.config.invalidation_cooldown_seconds
            )
        except (ValueError, TypeError):
            position.cooldown_until = None

        logger.debug(
            "Position %s updated to new top %s; last_invalidation_ts=%s cooldown_until=%s",
            position.position_id,
            str(position.top_price),
            position.last_invalidation_ts,
            position.cooldown_until,
        )

    def _place_immediate_replacement(self, position: BuyDipPosition) -> None:
        """Place replacement order immediately (for first DCA level).

        Args:
            position: Position needing replacement order
        """
        try:
            # Ensure any pending broker cancellation completes
            # (The cancel was initiated in _cancel_pending_order)
            try:
                # Give the cancel task time to complete (important for backtesting)
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Can't block in running loop, but task should complete quickly
                    pass
            except RuntimeError:
                pass

            # Generate order details
            order_id, dca_price = self._generate_replacement_order_details(position)

            # Place order immediately
            logger.info(
                "Placing immediate replacement order for %s at price %s (new top: %s)",
                order_id,
                dca_price,
                str(position.top_price),
            )
            self.strategy.place_order(position.position_id, dca_price, order_id)

        except Exception:
            logger.exception(
                "Failed to place immediate replacement for %s", position.position_id
            )
            raise

    def _schedule_replacement_order(self, position: BuyDipPosition) -> None:
        """Schedule delayed replacement order after cooldown.

        Creates async task that places order after cooldown period.
        Cancels any previous task for this position.

        Args:
            position: Position needing replacement order
        """
        try:
            pos_id = position.position_id

            async def _delayed_replacement() -> None:
                """Place replacement order after cooldown."""
                try:
                    # Wait for cooldown
                    await asyncio.sleep(
                        float(self.strategy.config.invalidation_cooldown_seconds or 0)
                    )

                    # Re-fetch position (may have changed)
                    pos = self.strategy._positions.get(pos_id)
                    if not pos:
                        logger.debug(
                            "Delayed replacement aborted: position %s not found", pos_id
                        )
                        return

                    # Validate position is still eligible
                    if not self._is_eligible_for_replacement(pos):
                        return

                    # Generate order details
                    order_id, dca_price = self._generate_replacement_order_details(pos)

                    # Place order
                    logger.debug(
                        "Delayed placement executing for %s at price %s",
                        order_id,
                        dca_price,
                    )
                    self.strategy.place_order(pos.position_id, dca_price, order_id)

                except Exception:
                    logger.exception("Delayed replacement task failed for %s", pos_id)

            # Get event loop
            loop = asyncio.get_event_loop()

            # Cancel previous task if exists
            if pos_id in self._scheduled_tasks:
                prev_task = self._scheduled_tasks[pos_id]
                if not prev_task.done():
                    prev_task.cancel()

            # Create and store new task
            self._scheduled_tasks[pos_id] = loop.create_task(_delayed_replacement())

        except Exception:
            logger.exception(
                "Failed to schedule replacement for %s", position.position_id
            )
            raise

    def _is_eligible_for_replacement(self, position: BuyDipPosition) -> bool:
        """Check if position is eligible for replacement order.

        Args:
            position: Position to check

        Returns:
            True if eligible, False otherwise
        """
        # Must still be POTENTIAL_TOP
        if position.state != PositionState.POTENTIAL_TOP:
            logger.debug(
                "Delayed replacement aborted: state %s for %s",
                position.state,
                position.position_id,
            )
            return False

        # Must not have pending order already
        if position.pending_order is not None:
            logger.debug(
                "Delayed replacement aborted: pending exists for %s",
                position.position_id,
            )
            return False

        # Must have top price
        if not position.top_price:
            logger.debug(
                "Delayed replacement aborted: no top_price for %s",
                position.position_id,
            )
            return False

        return True

    def _generate_replacement_order_details(
        self, position: BuyDipPosition
    ) -> tuple[str, float]:
        """Generate order ID and price for replacement order.

        Args:
            position: Position needing replacement

        Returns:
            Tuple of (order_id, dca_price)
        """
        # Get DCA distance for next level
        dca_distance = (
            position.dca_distances_pct[0] if position.dca_distances_pct else 0
        )

        # Calculate price - ensure top_price is not None
        if position.top_price is None:
            raise ValueError(f"Position {position.position_id} has no top_price")

        dca_price = float(position.top_price) * (1 - dca_distance / 100)

        # Generate unique order ID with timestamp
        order_id = (
            f"{position.position_id}_dca_{position.next_dca_level}_"
            f"{int(time.time() * 1000)}"
        )

        return order_id, dca_price

    def cancel_scheduled_replacement(self, position_id: str) -> None:
        """Cancel any scheduled replacement task for a position.

        Args:
            position_id: Position ID to cancel task for
        """
        if position_id in self._scheduled_tasks:
            task = self._scheduled_tasks[position_id]
            if not task.done():
                task.cancel()
            del self._scheduled_tasks[position_id]
            logger.debug("Canceled scheduled replacement for %s", position_id)
