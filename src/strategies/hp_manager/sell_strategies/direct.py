"""Direct sell strategy - single-hop sell to USDC."""

import logging
from typing import Any, Dict, List

from src.domain.enums import PositionSide, SellType
from src.domain.positions import HPSellConfig, SellPosition, StateInfo
from .base import BaseSellStrategy


logger = logging.getLogger(__name__)


class DirectSellStrategy(BaseSellStrategy):
    """Direct sell strategy for single-hop sells to end currency.

    Example: BTC -> USDC (BTCUSDC)

    Creates one sell position that directly sells to the target currency.
    """

    def build_positions(self) -> List[SellPosition]:
        """Build direct sell position.

        Returns:
            List with single SellPosition for direct sell
        """
        symbol = self.sell_path[0]

        # Use configured sell price and quantity
        sell_price = symbol.adjust_price(self.original_position.config.sell_price)
        quantity = symbol.adjust_quantity(self.original_position.config.quantity)

        logger.info(
            "[DIRECT] === Building direct sell position for %s ===",
            self.original_position.config.coin,
        )
        logger.info("[DIRECT] Symbol: %s", symbol.name)
        logger.info("[DIRECT] Quantity: %.8f", quantity)
        logger.info("[DIRECT] Sell price: %.8f", sell_price)
        logger.info(
            "[DIRECT] Expected value: %.8f %s",
            quantity * sell_price,
            self.original_position.config.end_currency,
        )

        # Check current market price
        current_price = self.price_resolver.latest_prices.get(symbol.name)
        if current_price:
            spread_pct = (
                ((sell_price - current_price) / current_price * 100)
                if current_price
                else 0
            )
            logger.info(
                "[DIRECT] Current market price: %.8f (spread: %.2f%%)",
                current_price,
                spread_pct,
            )
            if spread_pct < -5:
                logger.warning(
                    "[DIRECT] WARNING: Large negative spread! May fill immediately or be rejected"
                )
        else:
            logger.warning(
                "[DIRECT] WARNING: No current market price available for %s",
                symbol.name,
            )

        position = SellPosition(
            config=HPSellConfig(
                hp_id=self.original_position.config.hp_id,
                symbol=symbol,
                quantity=quantity,
                sell_price=sell_price,
                coin=self.original_position.config.coin,
                buy_price=self.original_position.config.buy_price,
                end_currency=self.original_position.config.end_currency,
                is_child=self.original_position.config.is_child,
                parent_hp_id=self.original_position.config.parent_hp_id,
            ),
            state_info=StateInfo(side=PositionSide.SHORT),
            sell_order=self._generate_order(
                symbol=symbol,
                quantity=quantity,
                price=sell_price,
            ),
            sell_type=SellType.DIRECT,
        )

        logger.info(
            "[DIRECT] Created position: %s for %s",
            position.config.hp_id,
            symbol.name,
        )

        return [position]

    def handle_completion(
        self,
        current_position: SellPosition,
        all_positions: List[SellPosition],
    ) -> Dict[str, Any]:
        """Handle direct sell completion.

        For direct sells:
        - Send 1 completion event
        - Send HPClose to complete the position lifecycle

        Returns:
            Dict with completion_events and needs_close=True
        """
        logger.info("Direct sell completed for %s", current_position.config.hp_id)

        completion_event = {
            "hp_id": current_position.config.hp_id,
            "coin": current_position.config.coin,
            "quantity_sold": current_position.sell_order.realized_quantity,
            "buy_price": current_position.config.buy_price,
            "sell_price": current_position.config.sell_price,
            "end_currency": current_position.config.end_currency,
        }

        return {
            "next_position": None,
            "needs_close": True,  # Send HPClose for direct sells
            "completion_events": [completion_event],
        }
