"""Convert sell strategy - convert-only operations (e.g., BTC → USDT)."""

from typing import List

from src.common.identifiers import SellPosition, SellType
from .base import BaseSellStrategy


class ConvertSellStrategy(BaseSellStrategy):
    """Convert-only sell strategy.
    
    Example: BTC → USDT (convert operation, symbol ends with USDT)
    
    Creates a single sell position with:
    - Original quantity and price
    - CONVERT sell type
    - HP ID appended with _CONVERT suffix
    """

    def build_positions(self) -> List[SellPosition]:
        """Build a single convert sell position.
        
        Returns:
            List with one SellPosition for convert operation
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
            sell_type=SellType.CONVERT,
        )
        
        # Add _CONVERT suffix only if not already present (to handle recovery cases)
        original_hp_id = str(self.original_position.config.hp_id)
        if not original_hp_id.endswith("_CONVERT"):
            sell_position.config.hp_id = f"{original_hp_id}_CONVERT"
        else:
            sell_position.config.hp_id = original_hp_id
            
        return [sell_position]
