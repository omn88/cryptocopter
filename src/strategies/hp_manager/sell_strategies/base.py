"""Base sell strategy interface for HP Manager."""

from abc import ABC, abstractmethod
from typing import List

from src.common.identifiers import SellPosition
from src.common.symbol import Symbol


class BaseSellStrategy(ABC):
    """Abstract base class for sell strategies.

    Each strategy is responsible for:
    1. Building the appropriate SellPosition(s) based on the sell path
    2. Calculating prices, quantities, and order details
    3. Setting correct sell_type (DIRECT, CONVERT, TWOHOPS)
    """

    def __init__(
        self,
        original_position: SellPosition,
        sell_strategy: List[Symbol],
        price_resolver,
    ):
        """Initialize base sell strategy.

        Args:
            original_position: Original sell position with config
            sell_strategy: List of symbols representing the sell path
            price_resolver: Price resolver for getting current market prices
        """
        self.original_position = original_position
        self.sell_strategy = sell_strategy
        self.price_resolver = price_resolver

    @abstractmethod
    def build_positions(self) -> List[SellPosition]:
        """Build list of sell positions for this strategy.

        Returns:
            List of SellPosition objects ready for execution
        """
        pass

    def _generate_order(self, symbol: Symbol, price: float, quantity: float):
        """Helper to generate order with proper precision."""
        from src.common.identifiers import Order

        return Order(
            quantity=symbol.adjust_quantity(quantity=quantity),
            price=symbol.adjust_price(price=price),
            precision=symbol.precision,
            price_precision=symbol.price_precision,
            quantity_stable=symbol.adjust_price(price * quantity),
        )
