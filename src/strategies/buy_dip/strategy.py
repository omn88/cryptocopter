"""
Buy Dip Strategy Orchestrator

Coordinates detection components and position lifecycle management.
Main entry point for processing market data and managing positions.
"""

import asyncio
import logging
import time
from collections import defaultdict
from decimal import Decimal
from typing import Dict, Optional, List

from src.strategies.buy_dip.budget_manager import BudgetManager
from src.strategies.buy_dip.candle_buffer import CandleBuffer
from src.strategies.buy_dip.config import BuyDipConfig
from src.strategies.buy_dip.invalidation_handler import TopInvalidationHandler
from src.strategies.buy_dip.position import BuyDipPosition, PositionState
from src.strategies.buy_dip.rising_detector import RisingCandleDetector

logger = logging.getLogger(__name__)


class BuyDipStrategy:
    """
    Main strategy orchestrator for Buy Dip trading.

    Responsibilities:
    - Process incoming candles through detection pipeline
    - Create positions on rising pattern detection
    - Manage position lifecycle (top confirmation, DCA progression)
    - Handle order fills, cancellations, and expirations
    - Enforce ONE pending order at a time per position
    - Manage budget allocation across positions
    """

    def __init__(
        self,
        config: BuyDipConfig,
        total_budget: Decimal,
        order_budget_pct: Decimal,
        broker=None,
        broker_adapter=None,
        on_position_update=None,
    ):
        """
        Initialize strategy with configuration.

        Args:
            config: Strategy configuration (DCA levels, detection params, etc.)
            total_budget: Total budget available for trading
            order_budget_pct: Percentage of total budget per order (e.g., 2.0 for 2%)
            broker: Optional broker instance for order placement (for E2E testing)
            broker_adapter: Optional broker adapter for production use
            on_position_update: Optional callback for position updates (position_id, event_type)
        """
        self.config = config
        self.total_budget = total_budget
        self.order_budget_pct = order_budget_pct
        self.broker = broker
        self.broker_adapter = broker_adapter
        self.on_position_update = on_position_update  # Callback for UI updates

        # Detection components (per-symbol)
        self._candle_buffers: Dict[str, CandleBuffer] = {}
        self._rising_detectors: Dict[str, RisingCandleDetector] = {}

        # Budget manager (shared across all positions)
        self._budget_manager = BudgetManager(
            float(total_budget), float(order_budget_pct)
        )

        # Invalidation handler (manages top invalidation logic)
        self._invalidation_handler = TopInvalidationHandler(self)

        # Position tracking
        self._positions: Dict[str, BuyDipPosition] = {}  # position_id -> BuyDipPosition
        self._symbol_positions: Dict[str, List[str]] = defaultdict(
            list
        )  # symbol -> [position_ids]
        self._order_to_position: Dict[str, str] = {}  # order_id -> position_id

    def add_symbol(self, symbol: str) -> None:
        """
        Add a symbol to track for trading opportunities.

        Args:
            symbol: Symbol to track (e.g., "BTCUSDC")
        """
        if symbol in self._candle_buffers:
            return  # Already tracking

        self._candle_buffers[symbol] = CandleBuffer(maxlen=50)
        self._rising_detectors[symbol] = RisingCandleDetector(
            min_consecutive=self.config.min_consecutive_rising,
            min_total_gain_pct=self.config.min_total_gain_pct,
        )

    def _create_placeholder_watching_position(self, symbol: str) -> None:
        """
        Create a placeholder WATCHING position for UI visibility.

        This shows the user that the strategy is actively watching this symbol
        even before any rising patterns are detected.

        Args:
            symbol: Symbol to create placeholder for
        """
        # Check if WATCHING position already exists
        if self._get_watching_position(symbol):
            return

        # Calculate order size for display
        order_size = self._budget_manager.calculate_order_size()
        if order_size is None:
            order_size = 0  # No budget available, but still create for visibility

        # Generate unique position ID (with timestamp if base ID exists)
        position_id = f"{symbol}_watching"
        if position_id in self._positions:
            position_id = f"{symbol}_watching_{int(time.time() * 1000)}"

        position = BuyDipPosition(
            position_id=position_id,
            symbol=symbol,
            dca_distances_pct=self.config.dca_distances_pct,
            order_size=Decimal(str(order_size)),
        )

        # Store and register position
        self._positions[position_id] = position
        self._symbol_positions[symbol].append(position_id)

        logger.info(
            f"Created WATCHING position {position_id} ({len(self._positions)} total)"
        )

        # Notify UI callback if registered
        if self.on_position_update:
            self.on_position_update(position_id, "position_created")

    async def process_candle(self, symbol: str, candle: Dict) -> None:
        """
        Process incoming candle through detection pipeline.

        Args:
            symbol: Symbol the candle is for
            candle: Candle data (open, high, low, close, volume, timestamp)
        """
        # Ensure symbol is tracked
        if symbol not in self._candle_buffers:
            self.add_symbol(symbol)

        # Add candle to buffer
        candle_buffer = self._candle_buffers[symbol]
        candle_buffer.add(candle)

        # Update rising detector
        rising_detector = self._rising_detectors[symbol]
        rising_detector.add_candle(candle)

        # Check for top invalidation (new high invalidates previous potential tops)
        current_high = Decimal(str(candle["high"]))
        for position in self._get_potential_top_positions(symbol):
            if position.top_price and current_high > position.top_price:
                # New high detected - invalidate old top and update
                await self._handle_top_invalidation(symbol, candle)
                break  # Only need to call once per symbol

        # Check for rising pattern detection
        if rising_detector.is_rising():
            self._handle_rising_pattern(symbol, candle)

        # For positions that are in POTENTIAL_TOP but have no pending order (eg. after
        # an invalidation), place a replacement order using the updated top_price.
        # This is intentionally done per incoming candle to avoid tight inner loops
        # while still reacting promptly to new highs. We respect last_invalidation_ts
        # and a short realtime cooldown to ensure tests can observe cancellations
        # before replacement.
        for position in self._get_potential_top_positions(symbol):
            # Only place replacement for first DCA order (before any fills)
            if (
                position.top_price
                and position.pending_order is None
                and position.next_dca_level == 0
            ):
                last_inv = getattr(position, "last_invalidation_ts", None)
                candle_ts: Optional[int] = None
                try:
                    ts_value = candle.get("timestamp")
                    if ts_value is not None:
                        candle_ts = int(ts_value)
                except Exception:
                    candle_ts = None

                # If the invalidation happened in the same candle or a realtime
                # cooldown is active, skip replacement for now.
                if (
                    last_inv is not None
                    and candle_ts is not None
                    and candle_ts <= last_inv
                ):
                    continue
                if getattr(position, "just_invalidated", False):
                    continue
                cooldown_until = getattr(position, "cooldown_until", None)
                if cooldown_until is not None and time.time() < cooldown_until:
                    logger.debug(
                        "Skipping replacement for %s due to cooldown until %s",
                        position.position_id,
                        cooldown_until,
                    )
                    continue

                # Place the first DCA level order from the updated top
                if len(position.dca_distances_pct) > 0:
                    dca_distance = position.dca_distances_pct[0]
                    dca_price = float(position.top_price) * (1 - dca_distance / 100)
                    order_id = f"{position.position_id}_dca_{position.next_dca_level}"
                    pos_id = position.position_id  # Define pos_id before using it
                    logger.debug(
                        "Scheduling replacement order %s at price %s for pos %s (next tick)",
                        order_id,
                        dca_price,
                        pos_id,
                    )
                    try:
                        loop = asyncio.get_event_loop()

                        # Use a small wrapper so we can log when the scheduled callback runs
                        def _execute_scheduled_placement(
                            p_id=pos_id, p_price=dca_price, p_oid=order_id
                        ):
                            logger.debug(
                                "Executing scheduled placement for %s (pos=%s price=%s)",
                                p_oid,
                                p_id,
                                p_price,
                            )
                            try:
                                # Re-check state: position must still exist and have no pending order
                                pos = self._positions.get(p_id)
                                if not pos:
                                    logger.debug(
                                        "Scheduled placement aborted: position %s not found",
                                        p_id,
                                    )
                                    return
                                if pos.pending_order is not None:
                                    logger.debug(
                                        "Scheduled placement aborted: pending already exists for %s",
                                        p_id,
                                    )
                                    return
                                # Respect realtime cooldown if set
                                if (
                                    getattr(pos, "cooldown_until", None)
                                    and time.time() < pos.cooldown_until
                                ):
                                    logger.debug(
                                        "Scheduled placement delayed: cooldown active until %s for %s",
                                        pos.cooldown_until,
                                        p_id,
                                    )
                                    return

                                self.place_order(p_id, p_price, p_oid)
                            except Exception:
                                logger.exception(
                                    "Scheduled placement failed for %s", p_oid
                                )

                        # Schedule placement by creating an asyncio task that sleeps for
                        # the configured cooldown, then re-checks state and places the order.
                        async def _delayed_place():
                            try:
                                await asyncio.sleep(
                                    float(
                                        self.config.invalidation_cooldown_seconds or 0
                                    )
                                )
                                _execute_scheduled_placement()
                            except Exception:
                                logger.exception(
                                    "Delayed placement task failed for %s", order_id
                                )

                        try:
                            loop.create_task(_delayed_place())
                        except Exception:
                            # Fallback to call_later if task creation fails
                            delay = float(
                                self.config.invalidation_cooldown_seconds or 0
                            )
                            loop.call_later(delay, _execute_scheduled_placement)
                    except Exception:
                        # If no running loop, fallback to immediate placement
                        logger.debug(
                            "No running event loop; placing replacement immediately %s",
                            order_id,
                        )
                        try:
                            self.place_order(pos_id, dca_price, order_id)
                        except Exception:
                            logger.exception(
                                "Immediate replacement placement failed %s", order_id
                            )

        # Clear transient invalidation flags after handling this candle so that
        # subsequent candles may place replacements normally.
        for pos_id in self._symbol_positions[symbol]:
            position = self._positions[pos_id]
            if getattr(position, "just_invalidated", False):
                position.just_invalidated = False

    def _handle_rising_pattern(self, symbol: str, candle: Dict) -> None:
        """
        Handle detection of rising pattern - create POTENTIAL_TOP position and place order.

        When rising pattern is detected, we immediately:
        1. Create position in POTENTIAL_TOP state with current high as top
        2. Place first DCA buy order
        3. Order fill will confirm the top and transition to ACTIVE

        Args:
            symbol: Symbol with rising pattern
            candle: Current candle
        """
        # Calculate order size
        order_size = self._budget_manager.calculate_order_size()
        if order_size is None:
            return  # No budget available

        # Check if there's a WATCHING position that should transition to POTENTIAL_TOP
        watching_pos = self._get_watching_position(symbol)
        if watching_pos:
            # Transition WATCHING → POTENTIAL_TOP with new top
            current_high = Decimal(str(candle["high"]))
            watching_pos.set_potential_top(current_high)

            # Place first DCA order
            if len(watching_pos.dca_distances_pct) > 0:
                dca_distance = watching_pos.dca_distances_pct[0]
                dca_price = float(current_high) * (1 - dca_distance / 100)
                order_id = f"{watching_pos.position_id}_dca_0"
                logger.info(
                    f"WATCHING position {watching_pos.position_id} detected rising pattern! "
                    f"Transitioning to POTENTIAL_TOP, placing first order @ ${dca_price:.2f} "
                    f"({dca_distance}% below ${float(current_high):.2f})"
                )
                self.place_order(watching_pos.position_id, dca_price, order_id)
            return

        # Also check for existing POTENTIAL_TOP positions waiting for first fill
        for pos in self._get_potential_top_positions(symbol):
            if pos.next_dca_level == 0:  # First order not filled yet
                return  # Wait for this one to fill first

        # Get current high as the potential top
        current_high = Decimal(str(candle["high"]))

        # Create new position in POTENTIAL_TOP state (not WATCHING!)
        position_id = f"{symbol}_{candle['timestamp']}"
        position = BuyDipPosition(
            position_id=position_id,
            symbol=symbol,
            dca_distances_pct=self.config.dca_distances_pct,
            order_size=Decimal(str(order_size)),
        )

        # Set as potential top immediately
        position.set_potential_top(current_high)

        # Store position
        self._positions[position_id] = position
        self._symbol_positions[symbol].append(position_id)

        # Notify UI of new position
        if self.on_position_update:
            self.on_position_update(position_id, "position_created")

        # Place first DCA order immediately
        if len(position.dca_distances_pct) > 0:
            dca_distance = position.dca_distances_pct[0]
            dca_price = float(current_high) * (1 - dca_distance / 100)
            order_id = f"{position_id}_dca_0"
            logger.info(
                f"Rising pattern detected! Created POTENTIAL_TOP position {position_id}, "
                f"placing first order @ ${dca_price:.2f} ({dca_distance}% below ${float(current_high):.2f})"
            )
            self.place_order(position_id, dca_price, order_id)

    def check_for_invalidation(self, symbol: str, current_price: float) -> None:
        """
        Check if current price invalidates any POTENTIAL_TOP positions.
        Called every 5 seconds with real-time price.

        Args:
            symbol: Symbol to check
            current_price: Current market price
        """
        # Check all POTENTIAL_TOP positions for invalidation
        for position in self._get_potential_top_positions(symbol):
            # Check if price exceeded the confirmed top
            if position.confirmed_top and current_price > float(position.confirmed_top):
                logger.info(
                    f"Position {position.position_id} invalidated: "
                    f"price ${current_price:.2f} > top ${float(position.confirmed_top):.2f}"
                )

                # Cancel pending buy order if exists
                if position.pending_order and self.broker_adapter:
                    try:
                        asyncio.create_task(
                            self.broker_adapter.cancel_order(
                                position.pending_order.order_id
                            )
                        )
                    except Exception as e:
                        logger.error(f"Error cancelling order: {e}")

                # Mark as invalidated
                position.state = PositionState.INVALIDATED

                # Notify UI
                if self.on_position_update:
                    self.on_position_update(position.position_id, "position_updated")

    async def _handle_top_invalidation(self, symbol: str, candle: Dict) -> None:
        """
        Handle top invalidation - delegate to invalidation handler.

        Args:
            symbol: Symbol with invalidated top
            candle: Current candle with new high
        """
        await self._invalidation_handler.handle_invalidation(symbol, candle)

    def place_order(self, position_id: str, price: float, order_id: str) -> bool:
        """
        Attempt to place an order for a position.

        Args:
            position_id: Position to place order for
            price: Price to place order at
            order_id: Unique order identifier

        Returns:
            True if order was placed, False if not allowed
        """
        logger.debug(
            "Attempting to place order %s for pos %s at price %s",
            order_id,
            position_id,
            price,
        )
        position = self._positions.get(position_id)
        if position is None:
            logger.debug("Place order failed: position %s not found", position_id)
            return False
        if not position:
            return False

        # Check if position can place order (ONE pending order constraint)
        if not position.can_place_order():
            return False

        # Calculate order size for this order
        order_size = self._budget_manager.calculate_order_size()
        if order_size is None:
            return False  # Insufficient budget

        # Lock the funds
        try:
            self._budget_manager.lock_funds(order_size)
            logger.debug("Locked funds %s for order %s", order_size, order_id)
        except Exception:
            logger.exception("Failed to lock funds for order %s", order_id)
            return False

        # Calculate quantity based on price
        quantity = Decimal(str(order_size)) / Decimal(str(price))

        # Place order on position (internal state)
        position.place_buy_order(
            order_id, Decimal(str(price)), quantity, position.next_dca_level
        )

        # Track order
        self._order_to_position[order_id] = position_id

        # Place order through broker (E2E flow - for testing)
        if self.broker:
            try:
                self.broker.place_order(
                    order_id=order_id,
                    symbol=position.symbol,
                    side="BUY",
                    price=float(price),
                    quantity=float(quantity),
                )
            except Exception:
                logger.exception("Broker order placement failed for %s", order_id)

        # Place order through broker adapter (production flow)
        if self.broker_adapter:
            try:
                # Schedule async order placement
                loop = asyncio.get_event_loop()
                asyncio.ensure_future(
                    self.broker_adapter.place_order(
                        order_id=order_id,
                        side="BUY",
                        price=Decimal(str(price)),
                        quantity=quantity,
                    ),
                    loop=loop,
                )
            except Exception:
                logger.exception(
                    "Broker adapter order placement failed for %s", order_id
                )

        return True

    def handle_order_fill(
        self, order_id: str, filled_price: float, filled_quantity: float
    ) -> None:
        """
        Handle order fill event from exchange.

        Args:
            order_id: Order that was filled
            filled_price: Actual fill price
            filled_quantity: Actual fill quantity
        """
        # Find position for this order
        position_id = self._order_to_position.get(order_id)
        if not position_id:
            return  # Unknown order

        position = self._positions[position_id]

        # Update position with fill
        position.handle_order_fill(
            order_id, Decimal(str(filled_price)), Decimal(str(filled_quantity))
        )

        # Clear order tracking
        del self._order_to_position[order_id]

        # Notify UI of position update
        if self.on_position_update:
            self.on_position_update(position_id, "position_updated")

        # If position just became ACTIVE (first fill), place sell order and create new WATCHING placeholder
        if position.state == PositionState.ACTIVE and position.sell_order is None:
            sell_order_id = f"{position_id}_sell"
            self.place_sell_order(position_id, sell_order_id)

            # Create new WATCHING placeholder for next opportunity
            # This allows tracking multiple positions simultaneously
            symbol = position.symbol
            logger.info(
                f"Position {position_id} became ACTIVE, creating new WATCHING placeholder for {symbol}"
            )
            self._create_placeholder_watching_position(symbol)

        # Check if position wants to place next DCA order
        if position.state == PositionState.ACTIVE and position.can_place_order():
            # Check if we've reached max DCA level
            if position.next_dca_level >= len(position.dca_distances_pct):
                return  # Max DCA reached, no more orders to place

            # Calculate next DCA price from confirmed top
            if position.confirmed_top is not None:
                reference_price = (
                    position.confirmed_top
                )  # Use confirmed top as reference
                dca_pct = position.dca_distances_pct[position.next_dca_level]
                next_price = float(
                    reference_price
                    * (Decimal("1") - Decimal(str(dca_pct)) / Decimal("100"))
                )

                # Generate order ID and attempt to place
                next_order_id = f"{position_id}_dca_{position.next_dca_level}"
                self.place_order(position_id, next_price, next_order_id)

    def handle_order_cancel(self, order_id: str) -> None:
        """
        Handle order cancellation event from exchange.

        Args:
            order_id: Order that was cancelled
        """
        # Find position for this order
        position_id = self._order_to_position.get(order_id)
        if not position_id:
            return  # Unknown order

        position = self._positions[position_id]

        # Get order amount to release
        if position.pending_order and position.pending_order.order_id == order_id:
            order_amount = float(
                position.pending_order.price * position.pending_order.quantity
            )

            # Update position
            position.handle_order_cancel(order_id)

            # Release locked funds
            self._budget_manager.release_funds(order_amount)

            # Clear order tracking
            del self._order_to_position[order_id]

    def handle_order_expire(self, order_id: str) -> None:
        """
        Handle order expiration event.

        Args:
            order_id: Order that expired
        """
        # Find position for this order
        position_id = self._order_to_position.get(order_id)
        if not position_id:
            return  # Unknown order

        position = self._positions[position_id]

        # Get order amount to release
        if position.pending_order and position.pending_order.order_id == order_id:
            order_amount = float(
                position.pending_order.price * position.pending_order.quantity
            )

            # Update position (treat expiration same as cancellation)
            position.handle_order_cancel(order_id)

            # Release locked funds
            self._budget_manager.release_funds(order_amount)

            # Clear order tracking
            del self._order_to_position[order_id]

    def place_sell_order(self, position_id: str, order_id: str) -> bool:
        """
        Place sell order to close position.

        Args:
            position_id: Position to sell
            order_id: Unique order identifier

        Returns:
            True if order was placed, False otherwise
        """
        position = self._positions.get(position_id)
        if not position:
            return False

        # Check if position is ready to sell
        if position.state != PositionState.ACTIVE:
            return False

        if position.total_quantity <= 0:
            return False

        # Calculate sell price (use confirmed top or current market price estimate)
        sell_price = (
            position.confirmed_top if position.confirmed_top else position.average_entry
        )
        if sell_price is None:
            return False

        # Place sell order
        position.place_sell_order(order_id, sell_price, position.total_quantity)

        # Track order
        self._order_to_position[order_id] = position_id

        # Place order through broker adapter (production flow)
        if self.broker_adapter:
            try:
                loop = asyncio.get_event_loop()
                asyncio.ensure_future(
                    self.broker_adapter.place_order(
                        order_id=order_id,
                        side="SELL",
                        price=sell_price,
                        quantity=position.total_quantity,
                    ),
                    loop=loop,
                )
            except Exception:
                logger.exception(
                    "Broker adapter sell order placement failed for %s", order_id
                )

        return True

    def handle_sell_fill(self, order_id: str, filled_price: float) -> None:
        """
        Handle sell order fill event.

        Args:
            order_id: Sell order that was filled
            filled_price: Actual fill price
        """
        # Find position for this order
        position_id = self._order_to_position.get(order_id)
        if not position_id:
            return  # Unknown order

        position = self._positions[position_id]

        # Cancel any remaining pending buy orders before closing position
        if position.pending_order:
            pending_order_id = position.pending_order.order_id
            order_amount = float(
                position.pending_order.price * position.pending_order.quantity
            )

            # Mark as canceled
            position.pending_order.status = "CANCELED"

            # Release locked funds
            self._budget_manager.release_funds(order_amount)

            # Clear pending order on position
            position.pending_order = None

            # Clear order tracking
            if pending_order_id in self._order_to_position:
                del self._order_to_position[pending_order_id]

            logger.debug(
                "Cancelled remaining pending order %s for position %s on sell fill",
                pending_order_id,
                position_id,
            )

        # Calculate profit
        invested = float(position.total_invested)
        proceeds = float(filled_price) * float(position.total_quantity)
        profit = proceeds - invested

        # Update position with full quantity
        position.handle_sell_fill(
            order_id, Decimal(str(filled_price)), position.total_quantity
        )

        # Release all locked funds with profit
        self._budget_manager.release_funds(invested, profit)

        # Clear order tracking
        del self._order_to_position[order_id]

        # Notify UI of position completion
        if self.on_position_update:
            self.on_position_update(position_id, "position_completed")

    def get_position(self, position_id: str) -> Optional[BuyDipPosition]:
        """Get position by ID."""
        return self._positions.get(position_id)

    def get_positions_for_symbol(self, symbol: str) -> List[BuyDipPosition]:
        """Get all positions for a symbol."""
        return [self._positions[pid] for pid in self._symbol_positions[symbol]]

    def get_all_positions(self) -> List[BuyDipPosition]:
        """Get all positions."""
        return list(self._positions.values())

    def get_budget_info(self) -> Dict:
        """Get current budget information."""
        return {
            "available": self._budget_manager.get_available_budget(),
            "locked": self._budget_manager.get_locked_budget(),
            "total": self._budget_manager.get_available_budget()
            + self._budget_manager.get_locked_budget(),
            "order_size": self._budget_manager.calculate_order_size(),
        }

    # === Helper Methods for Cleaner Position Filtering ===

    def _get_watching_position(self, symbol: str) -> Optional[BuyDipPosition]:
        """Get the WATCHING position for a symbol, if any."""
        for pos_id in self._symbol_positions.get(symbol, []):
            position = self._positions.get(pos_id)
            if position and position.state == PositionState.WATCHING:
                return position
        return None

    def _get_potential_top_positions(self, symbol: str) -> List[BuyDipPosition]:
        """Get all POTENTIAL_TOP positions for a symbol."""
        positions = []
        for pos_id in self._symbol_positions.get(symbol, []):
            position = self._positions.get(pos_id)
            if position and position.state == PositionState.POTENTIAL_TOP:
                positions.append(position)
        return positions

    def _get_positions_by_state(
        self, symbol: str, state: PositionState
    ) -> List[BuyDipPosition]:
        """Get all positions for a symbol in a specific state."""
        positions = []
        for pos_id in self._symbol_positions.get(symbol, []):
            position = self._positions.get(pos_id)
            if position and position.state == state:
                positions.append(position)
        return positions
