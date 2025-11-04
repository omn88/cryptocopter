"""Direct sell strategy - simple sell to quote currency."""

from typing import List

from src.common.identifiers import SellPosition, SellType, StateInfo, PositionSide
from src.common.symbol import Symbol
from .base import BaseSellStrategy


class DirectSellStrategy(BaseSellStrategy):
    """Direct sell strategy for selling to quote currency.

    Example: BTC → USDC (direct pair BTCUSDC)

    Creates a single sell position with:
    - Original quantity and price
    - DIRECT sell type
    - No HP ID modifications
    """

    def build_positions(self) -> List[SellPosition]:
        """Build a single direct sell position.

        Returns:
            List with one SellPosition for direct sell
        """
        symbol = self.sell_strategy[0]

        sell_position = SellPosition(
            config=self.original_position.config,
            state_info=self.original_position.state_info,
            sell_order=self._generate_order(
                symbol,
                quantity=self.original_position.config.quantity,
                price=self.original_position.config.sell_price,
            ),
            sell_type=SellType.DIRECT,
        )

        return [sell_position]
