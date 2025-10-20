"""
Buy Dip Strategy Orchestrator

Coordinates detection components and position lifecycle management.
Main entry point for processing market data and managing positions.
"""

from decimal import Decimal
from typing import Dict, Optional, List
from collections import defaultdict

from src.strategies.buy_dip.candle_buffer import CandleBuffer
from src.strategies.buy_dip.atr import ATR
from src.strategies.buy_dip.rising_detector import RisingCandleDetector
from src.strategies.buy_dip.hwm_detector import HighWatermarkDetector
from src.strategies.buy_dip.budget_manager import BudgetManager
from src.strategies.buy_dip.config import BuyDipConfig
from src.strategies.buy_dip.position import BuyDipPosition, PositionState, OrderInfo


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
        self, config: BuyDipConfig, total_budget: Decimal, order_budget_pct: Decimal
    ):
        """
        Initialize strategy with configuration.

        Args:
            config: Strategy configuration (DCA levels, detection params, etc.)
            total_budget: Total budget available for trading
            order_budget_pct: Percentage of total budget per order (e.g., 2.0 for 2%)
        """
        self.config = config
        self.total_budget = total_budget
        self.order_budget_pct = order_budget_pct

        # Detection components (per-symbol)
        self._candle_buffers: Dict[str, CandleBuffer] = {}
        self._atr_indicators: Dict[str, ATR] = {}
        self._rising_detectors: Dict[str, RisingCandleDetector] = {}
        self._hwm_detectors: Dict[str, HighWatermarkDetector] = {}

        # Budget manager (shared across all positions)
        self._budget_manager = BudgetManager(
            float(total_budget), float(order_budget_pct)
        )

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
        self._atr_indicators[symbol] = ATR(period=self.config.atr_period)
        self._rising_detectors[symbol] = RisingCandleDetector(
            min_consecutive=self.config.min_consecutive_rising,
            min_total_gain_pct=self.config.min_total_gain_pct,
        )
        self._hwm_detectors[symbol] = HighWatermarkDetector(
            atr_multiplier=self.config.atr_multiplier,
            min_pullback_pct=self.config.min_pullback_pct,
        )

    def process_candle(self, symbol: str, candle: Dict) -> None:
        """
        Process incoming candle through detection pipeline.

        Args:
            symbol: Symbol the candle is for
            candle: Candle data (open, high, low, close, volume, timestamp)
        """
        # Ensure symbol is tracked
        if symbol not in self._candle_buffers:
            self.add_symbol(symbol)

        # Add to buffer
        buffer = self._candle_buffers[symbol]
        buffer.add(candle)

        # Update indicators
        atr = self._atr_indicators[symbol]
        atr.add_candle(candle)

        # Update HWM detector with latest ATR (if available)
        atr_value = atr.get_atr()
        hwm_detector = self._hwm_detectors[symbol]
        if atr_value is not None:
            hwm_detector.update_atr(atr_value)

        rising_detector = self._rising_detectors[symbol]
        rising_detector.add_candle(candle)

        hwm_detector.add_candle(candle)

        # Check for top invalidation (new high invalidates previous potential tops)
        current_high = Decimal(str(candle["high"]))
        for pos_id in self._symbol_positions[symbol]:
            position = self._positions[pos_id]
            if (
                position.state == PositionState.POTENTIAL_TOP
                and position.top_price
                and current_high > position.top_price
            ):
                # New high detected - invalidate old top and update
                self._handle_top_invalidation(symbol, candle)
                break  # Only need to call once per symbol

        # Check for rising pattern detection
        if rising_detector.is_rising():
            self._handle_rising_pattern(symbol, candle)

        # Check for top confirmation (for positions in WATCHING state)
        if hwm_detector.is_top_confirmed():
            self._handle_top_confirmed(symbol, candle)

    def _handle_rising_pattern(self, symbol: str, candle: Dict) -> None:
        """
        Handle detection of rising pattern - create new position.

        Args:
            symbol: Symbol with rising pattern
            candle: Current candle
        """
        # Calculate order size
        order_size = self._budget_manager.calculate_order_size()
        if order_size is None:
            return  # No budget available

        # Check if we already have an active position in WATCHING state
        for pos_id in self._symbol_positions[symbol]:
            position = self._positions[pos_id]
            if position.state == PositionState.WATCHING:
                return  # Already tracking this symbol

        # Create new position
        position_id = f"{symbol}_{candle['timestamp']}"
        position = BuyDipPosition(
            position_id=position_id,
            symbol=symbol,
            dca_distances_pct=self.config.dca_distances_pct,
            order_size=Decimal(str(order_size)),
        )

        # Store position
        self._positions[position_id] = position
        self._symbol_positions[symbol].append(position_id)

    def _handle_top_confirmed(self, symbol: str, candle: Dict) -> None:
        """
        Handle top confirmation - set potential top for watching positions.

        Args:
            symbol: Symbol with confirmed top
            candle: Current candle
        """
        # Get the confirmed top from HWM detector (not the current candle's high)
        hwm_detector = self._hwm_detectors[symbol]
        confirmed_top = hwm_detector.get_confirmed_top()

        if confirmed_top is None:
            return  # No confirmed top yet

        top_price = Decimal(str(confirmed_top))

        # Update all WATCHING positions for this symbol
        for pos_id in self._symbol_positions[symbol]:
            position = self._positions[pos_id]
            if position.state == PositionState.WATCHING:
                position.set_potential_top(top_price)

                # Place first DCA order at the calculated level
                # DCA price is: top_price * (1 - dca_distance_pct / 100)
                if len(position.dca_distances_pct) > 0:
                    dca_distance = position.dca_distances_pct[0]  # First DCA level
                    dca_price = float(top_price) * (1 - dca_distance / 100)

                    # Generate order ID
                    order_id = f"{position.position_id}_dca_0"

                    # Place the order through the strategy
                    self.place_order(pos_id, dca_price, order_id)

    def _handle_top_invalidation(self, symbol: str, candle: Dict) -> None:
        """
        Handle top invalidation - cancel pending orders and update to new top.

        Args:
            symbol: Symbol with invalidated top
            candle: Current candle with new high
        """
        new_top_price = Decimal(str(candle["high"]))

        # Update all POTENTIAL_TOP positions for this symbol
        for pos_id in self._symbol_positions[symbol]:
            position = self._positions[pos_id]

            # Only invalidate if position has a top price and is in POTENTIAL_TOP state
            if position.state == PositionState.POTENTIAL_TOP and position.top_price:
                # Get pending order before invalidation
                pending_order = position.pending_order

                # Cancel pending order if exists
                if pending_order:
                    pending_order.status = "CANCELED"
                    position.pending_order = None

                    # Clear order tracking
                    if pending_order.order_id in self._order_to_position:
                        del self._order_to_position[pending_order.order_id]

                # Update to new top price (stay in POTENTIAL_TOP state)
                position.top_price = new_top_price

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
        position = self._positions.get(position_id)
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
        self._budget_manager.lock_funds(order_size)

        # Calculate quantity based on price
        quantity = Decimal(str(order_size)) / Decimal(str(price))

        # Place order on position
        position.place_buy_order(
            order_id, Decimal(str(price)), quantity, position.next_dca_level
        )

        # Track order
        self._order_to_position[order_id] = position_id

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

        # If position just became ACTIVE (first fill), place sell order
        if position.state == PositionState.ACTIVE and position.sell_order is None:
            sell_order_id = f"{position_id}_sell"
            self.place_sell_order(position_id, sell_order_id)

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

        # Calculate profit
        invested = float(position.total_quantity)
        proceeds = filled_price * float(position.total_quantity)
        profit = proceeds - invested

        # Update position with full quantity
        position.handle_sell_fill(
            order_id, Decimal(str(filled_price)), position.total_quantity
        )

        # Release all locked funds with profit
        self._budget_manager.release_funds(invested, profit)

        # Clear order tracking
        del self._order_to_position[order_id]

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
