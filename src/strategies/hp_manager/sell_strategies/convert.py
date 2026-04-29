"""Convert sell strategy - uses Binance convert API instead of limit orders."""

import logging
from typing import Any, Dict, List

from src.domain.enums import PositionSide, SellType
from src.domain.orders import Order
from src.domain.positions import HPSellConfig, SellPosition, StateInfo
from .base import BaseSellStrategy


logger = logging.getLogger("convert_sell_strategy")


class ConvertSellStrategy(BaseSellStrategy):
    """Convert sell strategy for conversion operations.

    Example: BTC -> USDT (using convert API, not limit order)

    Creates one sell position marked for conversion via Binance convert API.
    The actual conversion happens in hp_manager.convert_position().
    """

    def build_positions(self) -> List[SellPosition]:
        """Build convert sell position.

        Returns:
            List with single SellPosition marked for conversion
        """
        symbol = self.sell_path[0]

        # For convert operations, use the symbol's current price
        # The actual conversion will happen at market rate
        sell_price = symbol.adjust_price(self.original_position.config.sell_price)
        quantity = symbol.adjust_quantity(self.original_position.config.quantity)

        logger.info(
            "[CONVERT] === Building convert position for %s ===",
            self.original_position.config.coin,
        )
        logger.info("[CONVERT] Symbol: %s (convert-only)", symbol.name)
        logger.info("[CONVERT] Quantity: %.8f", quantity)
        logger.info("[CONVERT] Price: %.8f", sell_price)
        logger.info(
            "[CONVERT] Expected value: %.8f %s",
            quantity * sell_price,
            self.original_position.config.end_currency,
        )

        # Get current market price to check spread
        current_price = self.price_resolver.latest_prices.get(symbol.name)
        if current_price:
            spread_pct = (
                ((sell_price - current_price) / current_price * 100)
                if current_price
                else 0
            )
            logger.info(
                "[CONVERT] Current market price: %.8f (spread: %.2f%%)",
                current_price,
                spread_pct,
            )
            if spread_pct < -5:
                logger.warning(
                    "[CONVERT] WARNING: Large negative spread detected! "
                    "Price may be too low: target=%.8f market=%.8f (%.2f%%)",
                    sell_price,
                    current_price,
                    spread_pct,
                )
        else:
            logger.warning(
                "[CONVERT] WARNING: No current market price available for %s",
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
            sell_order=Order(
                quantity=quantity,
                price=sell_price,
                precision=symbol.precision,
            ),
            sell_type=SellType.CONVERT,
        )

        logger.info(
            "[CONVERT] Created position: %s for %s (convert operation)",
            position.config.hp_id,
            symbol.name,
        )

        return [position]

    def should_use_convert(self) -> bool:
        """Convert strategy uses Binance convert API.

        Returns:
            True - this strategy always uses convert API
        """
        return True

    def handle_completion(
        self,
        current_position: SellPosition,
        all_positions: List[SellPosition],
    ) -> Dict[str, Any]:
        """Handle convert operation completion.

        For convert operations:
        - DON'T send completion event (already sent in convert_position)
        - Send HPClose to complete the position lifecycle

        Returns:
            Dict with empty completion_events and needs_close=True
        """
        logger.info(
            "Convert operation completed for %s, skipping duplicate event",
            current_position.config.hp_id,
        )

        return {
            "next_position": None,
            "needs_close": True,  # Send HPClose
            "completion_events": [],  # No event - already sent in convert_position
        }
