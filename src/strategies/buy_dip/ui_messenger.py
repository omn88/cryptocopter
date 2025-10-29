"""UIMessenger - Handles UI update messaging for Buy Dip strategy.

Extracted from BuyDipExecutor to follow Single Responsibility Principle.
Manages:
- Budget status updates to UI
- Position detail updates to UI
- Batch position updates (e.g., on startup)
"""

import logging
from typing import TYPE_CHECKING, Any, Dict
from queue import Queue

if TYPE_CHECKING:
    from src.strategies.buy_dip.strategy import BuyDipStrategy

logger = logging.getLogger(__name__)


class UIMessenger:
    """Handles sending updates to UI queue for budget and position states."""

    def __init__(self, strategy: "BuyDipStrategy", ui_queue: Queue):
        """Initialize UI messenger.

        Args:
            strategy: Reference to main strategy instance
            ui_queue: Queue for sending UI updates
        """
        self.strategy = strategy
        self.ui_queue = ui_queue

    def send_budget_update(self) -> None:
        """
        Send budget status to UI.
        """
        available = self.strategy._budget_manager.get_available_budget()
        locked = self.strategy._budget_manager.get_locked_budget()
        total = available + locked

        self.ui_queue.put(
            {
                "type": "budget",
                "total": total,
                "available": available,
                "locked": locked,
            }
        )

    def send_position_update(
        self, position_id: str, update_type: str = "position_updated"
    ) -> None:
        """
        Send position details to UI.

        Args:
            position_id: Position to send update for
            update_type: Type of update (position_created, position_updated, position_completed)
        """
        position = self.strategy._positions.get(position_id)
        if not position:
            logger.warning(f"Position {position_id} not found for UI update")
            return

        # Build position data for UI
        position_data: Dict[str, Any] = {
            "type": update_type,
            "position_id": position_id,
            "symbol": position.symbol,
            "state": position.state.name,
            "top_price": float(position.top_price) if position.top_price else 0,
            "current_dca_level": position.next_dca_level,  # next_dca_level = how many filled so far
            "total_dca_levels": len(self.strategy.config.dca_distances_pct),
            "avg_entry_price": (
                float(position.average_entry) if position.average_entry else 0
            ),
            "total_invested": float(position.total_invested),
            "pending_order": None,
            "sell_order": None,
            "pnl": 0,
        }

        # Pending buy order
        if position.pending_order:
            position_data["pending_order"] = {
                "order_id": position.pending_order.order_id,
                "price": float(position.pending_order.price),
                "quantity": float(position.pending_order.quantity),
            }

        # Sell order
        if position.sell_order:
            position_data["sell_order"] = {
                "order_id": position.sell_order.order_id,
                "price": float(position.sell_order.price),
                "quantity": float(position.sell_order.quantity),
            }

        # PnL calculation (placeholder - need current price for accurate PnL)
        # For now, just set to 0 unless position is completed
        # position_data["pnl"] already set above

        self.ui_queue.put(position_data)
        logger.debug(f"Sent {update_type} for position {position_id}")

    def send_all_positions_update(self) -> None:
        """
        Send updates for all positions to UI (e.g., on startup).
        """
        for position_id in self.strategy._positions.keys():
            self.send_position_update(position_id, "position_updated")
