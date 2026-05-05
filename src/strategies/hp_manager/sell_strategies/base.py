"""Base sell strategy interface for HP Manager."""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Dict, List

from src.domain.orders import Order
from src.domain.positions import SellPosition
from src.common.symbol import Symbol


class BaseSellStrategy(ABC):
    """Abstract base class for sell strategies.

    Each strategy knows how to:
    1. Build appropriate SellPosition(s) for its sell type
    2. Handle position completion logic (events, transitions)
    3. Recalculate prices before execution (if needed)
    """

    def __init__(
        self,
        original_position: SellPosition,
        sell_path: List[Symbol],
        price_resolver,
    ):
        """Initialize base sell strategy.

        Args:
            original_position: Original sell position with config
            sell_path: List of symbols representing the sell path (from determine_sell_strategy)
            price_resolver: Price resolver for getting current market prices
        """
        self.original_position = original_position
        self.sell_path = sell_path
        self.price_resolver = price_resolver

    @abstractmethod
    def build_positions(self) -> List[SellPosition]:
        """Build list of sell positions for this strategy.

        Returns:
            List of SellPosition objects ready for execution
        """
        pass

    @abstractmethod
    def handle_completion(
        self,
        current_position: SellPosition,
        all_positions: List[SellPosition],
    ) -> Dict[str, Any]:
        """Handle position completion logic.

        Args:
            current_position: The position that just completed
            all_positions: All sell positions for this strategy

        Returns:
            Dict with:
                - next_position: SellPosition | None (for multihop leg1->leg2 transition)
                - needs_close: bool (whether to send HPClose event)
                - completion_events: List[dict] (portfolio events to send)
                - original_position: SellPosition | None (for UI update in multihop)
        """
        pass

    def should_use_convert(self) -> bool:
        """Check if this strategy uses Binance convert API (not limit orders).

        Returns:
            True if strategy uses convert API, False for limit orders
        """
        return False

    async def recalculate_prices(self, sell_positions: List[SellPosition]) -> None:
        """Recalculate prices before execution (multihop specific).

        Base implementation does nothing - only MultihopSellStrategy overrides.

        Args:
            sell_positions: List of sell positions to recalculate
        """
        pass

    def _generate_order(
        self, symbol: Symbol, price: Decimal, quantity: Decimal
    ) -> Order:
        """Helper to generate an Order with proper precision.

        Args:
            symbol: Symbol for the order
            price: Price for the order
            quantity: Quantity for the order

        Returns:
            Order object with adjusted price and quantity
        """
        return Order(
            quantity=symbol.adjust_quantity(quantity=quantity),
            price=symbol.adjust_price(price=price),
            precision=symbol.precision,
        )
