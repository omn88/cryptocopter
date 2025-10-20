"""BuyDipPosition - State machine for Buy Dip position lifecycle.

States:
- WATCHING: Monitoring candles for rising pattern
- POTENTIAL_TOP: Order 1 pending (top detected, awaiting confirmation)
- ACTIVE: Position confirmed (Order 1 filled), sequential DCA in progress
- COMPLETED: Position closed, profit realized

Key Constraints:
- ONE pending buy order at a time (sequential, not concurrent)
- Order fill triggers next order placement
- Top invalidation cancels pending order and resets
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
from decimal import Decimal


class PositionState(Enum):
    """Buy Dip position states."""

    WATCHING = "WATCHING"
    POTENTIAL_TOP = "POTENTIAL_TOP"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


@dataclass
class OrderInfo:
    """Information about a buy order."""

    order_id: str
    price: Decimal
    quantity: Decimal
    dca_level: int  # 0=φ, 1=e, 2=π
    status: str  # NEW, FILLED, CANCELED, EXPIRED
    filled_quantity: Decimal = Decimal("0")
    filled_price: Optional[Decimal] = None


@dataclass
class BuyDipPosition:
    """
    Buy Dip position with state machine.

    Manages position lifecycle from rising detection through DCA fills to sell.
    Enforces ONE pending order at a time constraint.
    """

    # Identification
    position_id: str
    symbol: str

    # Configuration
    dca_distances_pct: List[float]  # [φ=1.618, e=2.718, π=3.142]
    order_size: Decimal

    # State
    state: PositionState = PositionState.WATCHING
    top_price: Optional[Decimal] = None
    confirmed_top: Optional[Decimal] = None

    # Orders tracking
    buy_orders: List[OrderInfo] = field(default_factory=list)
    pending_order: Optional[OrderInfo] = None  # CRITICAL: Only ONE at a time!
    sell_order: Optional[OrderInfo] = None

    # Position metrics
    total_invested: Decimal = Decimal("0")
    average_entry: Optional[Decimal] = None
    total_quantity: Decimal = Decimal("0")
    next_dca_level: int = 0  # Next DCA level to place (0, 1, 2)

    # Metadata
    created_at: float = 0.0
    updated_at: float = 0.0
    # Timestamp of last invalidation (ms) to avoid placing replacement order in same candle
    last_invalidation_ts: Optional[int] = None
    # Transient flag set when an invalidation just occurred in the current
    # processing cycle to avoid immediate replacement in the same candle.
    just_invalidated: bool = False
    # Cooldown timestamp (seconds) until which replacement orders should not be placed.
    cooldown_until: Optional[float] = None
    # Private field to store the delayed replacement task (for cancellation on re-invalidation)
    _invalidation_task: Optional[Any] = field(default=None, init=False, repr=False)

    def can_place_order(self) -> bool:
        """Check if we can place a new order.

        Returns:
            True if no pending order exists, False otherwise
        """
        return self.pending_order is None

    def place_buy_order(
        self,
        order_id: str,
        price: Decimal,
        quantity: Decimal,
        dca_level: int,
    ) -> None:
        """Place a buy order.

        Args:
            order_id: Exchange order ID
            price: Order price
            quantity: Order quantity
            dca_level: DCA level (0=φ, 1=e, 2=π)

        Raises:
            RuntimeError: If there's already a pending order
        """
        if not self.can_place_order():
            # Assert for type checker - we know pending_order is not None here
            assert self.pending_order is not None
            raise RuntimeError(
                f"Cannot place order: pending order {self.pending_order.order_id} exists"
            )

        order = OrderInfo(
            order_id=order_id,
            price=price,
            quantity=quantity,
            dca_level=dca_level,
            status="NEW",
        )
        self.pending_order = order
        self.buy_orders.append(order)

    def handle_order_fill(
        self,
        order_id: str,
        filled_price: Decimal,
        filled_quantity: Decimal,
    ) -> None:
        """Handle order fill execution.

        Args:
            order_id: Exchange order ID
            filled_price: Actual fill price
            filled_quantity: Actual fill quantity

        Raises:
            ValueError: If order not found
        """
        # Find and update order
        order = None
        for o in self.buy_orders:
            if o.order_id == order_id:
                order = o
                break

        if not order:
            raise ValueError(f"Order {order_id} not found in position")

        # Update order status
        order.status = "FILLED"
        order.filled_price = filled_price
        order.filled_quantity = filled_quantity

        # Update position metrics
        self.total_invested += filled_price * filled_quantity
        self.total_quantity += filled_quantity

        # Calculate new average entry
        if self.average_entry is None:
            self.average_entry = filled_price
        else:
            # Weighted average
            total_cost = self.total_invested
            self.average_entry = total_cost / self.total_quantity

        # Clear pending order
        if self.pending_order and self.pending_order.order_id == order_id:
            self.pending_order = None

        # Transition state on first fill
        if self.state == PositionState.POTENTIAL_TOP:
            self.state = PositionState.ACTIVE
            self.confirmed_top = self.top_price

        # Advance DCA level
        self.next_dca_level += 1

    def handle_order_cancel(self, order_id: str) -> None:
        """Handle order cancellation.

        Args:
            order_id: Exchange order ID

        Raises:
            ValueError: If order not found
        """
        # Find and update order
        order = None
        for o in self.buy_orders:
            if o.order_id == order_id:
                order = o
                break

        if not order:
            raise ValueError(f"Order {order_id} not found in position")

        order.status = "CANCELED"

        # Clear pending order
        if self.pending_order and self.pending_order.order_id == order_id:
            self.pending_order = None

    def invalidate_top(self) -> None:
        """Invalidate the current top (new high detected).

        Cancels pending order and resets to WATCHING state.
        """
        # Cancel pending order if exists
        if self.pending_order:
            self.pending_order.status = "CANCELED"
            self.pending_order = None
            self.state = PositionState.WATCHING
            self.top_price = None
            # Note invalidation timestamp will be set by strategy using the candle timestamp
        if self.state == PositionState.POTENTIAL_TOP:
            self.state = PositionState.WATCHING
            self.top_price = None

    def set_potential_top(self, top_price: Decimal) -> None:
        """Set potential top price (rising pattern detected).

        Args:
            top_price: Detected top price
        """
        self.top_price = top_price
        self.state = PositionState.POTENTIAL_TOP

    def place_sell_order(
        self,
        order_id: str,
        price: Decimal,
        quantity: Decimal,
    ) -> None:
        """Place sell order at top price.

        Args:
            order_id: Exchange order ID
            price: Sell price (top price)
            quantity: Sell quantity
        """
        self.sell_order = OrderInfo(
            order_id=order_id,
            price=price,
            quantity=quantity,
            dca_level=-1,  # Not a DCA order
            status="NEW",
        )

    def handle_sell_fill(
        self,
        order_id: str,
        filled_price: Decimal,
        filled_quantity: Decimal,
    ) -> None:
        """Handle sell order fill.

        Args:
            order_id: Exchange order ID
            filled_price: Actual fill price
            filled_quantity: Actual fill quantity

        Raises:
            ValueError: If sell order not found or doesn't match
        """
        if not self.sell_order or self.sell_order.order_id != order_id:
            raise ValueError(f"Sell order {order_id} not found or mismatch")

        self.sell_order.status = "FILLED"
        self.sell_order.filled_price = filled_price
        self.sell_order.filled_quantity = filled_quantity

        # Transition to completed
        self.state = PositionState.COMPLETED

    def get_profit(self) -> Optional[Decimal]:
        """Calculate position profit.

        Returns:
            Profit amount, or None if position not completed
        """
        if self.state != PositionState.COMPLETED:
            return None

        if not self.sell_order or not self.sell_order.filled_price:
            return None

        # Profit = (sell_price - avg_entry) * quantity
        sell_revenue = self.sell_order.filled_price * self.sell_order.filled_quantity
        return sell_revenue - self.total_invested

    def get_profit_percentage(self) -> Optional[Decimal]:
        """Calculate profit percentage.

        Returns:
            Profit percentage, or None if position not completed
        """
        profit = self.get_profit()
        if profit is None or self.total_invested == 0:
            return None

        return (profit / self.total_invested) * Decimal("100")

    def has_max_dca_reached(self) -> bool:
        """Check if maximum DCA level has been reached.

        Returns:
            True if all DCA levels filled, False otherwise
        """
        return self.next_dca_level >= len(self.dca_distances_pct)

    def to_dict(self) -> Dict[str, Any]:
        """Convert position to dictionary for serialization.

        Returns:
            Dictionary representation
        """
        return {
            "position_id": self.position_id,
            "symbol": self.symbol,
            "state": self.state.value,
            "top_price": str(self.top_price) if self.top_price else None,
            "confirmed_top": str(self.confirmed_top) if self.confirmed_top else None,
            "total_invested": str(self.total_invested),
            "average_entry": str(self.average_entry) if self.average_entry else None,
            "total_quantity": str(self.total_quantity),
            "next_dca_level": self.next_dca_level,
            "pending_order": (
                {
                    "order_id": self.pending_order.order_id,
                    "price": str(self.pending_order.price),
                    "quantity": str(self.pending_order.quantity),
                    "dca_level": self.pending_order.dca_level,
                    "status": self.pending_order.status,
                }
                if self.pending_order
                else None
            ),
            "buy_orders_count": len(self.buy_orders),
            "has_sell_order": self.sell_order is not None,
            "profit": str(self.get_profit()) if self.get_profit() else None,
            "profit_pct": (
                str(self.get_profit_percentage())
                if self.get_profit_percentage()
                else None
            ),
        }
