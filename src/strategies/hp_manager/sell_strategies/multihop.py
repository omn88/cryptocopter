"""Multihop sell strategy - two-hop sell through intermediate pair."""

import logging
from typing import List

from src.common.identifiers import (
    HPSellConfig,
    PositionSide,
    SellPosition,
    SellType,
    State,
    StateInfo,
)
from .base import BaseSellStrategy


logger = logging.getLogger("multihop_strategy")


class MultihopSellStrategy(BaseSellStrategy):
    """Two-hop sell strategy for selling through intermediate pair.

    Example: AXL → BTC → USDC
    - Leg 1: Sell AXL for BTC (AXLBTC)
    - Leg 2: Sell BTC for USDC (BTCUSDC)

    Creates two sell positions:
    - Leg 1 (child 'a'): Sells base coin for intermediate coin
    - Leg 2 (child 'b'): Sells intermediate coin for end currency (USDC)

    Both legs are marked as TWOHOPS sell type.
    Leg 2 starts in WAITING_CHILD state until leg 1 completes.
    """

    def build_positions(self) -> List[SellPosition]:
        """Build two-hop sell positions (leg1 + leg2).

        Returns:
            List with two SellPosition objects for multihop trade

        Raises:
            ValueError: If leg2 price is not available in price feed
        """
        original = self.original_position
        sell_price = original.config.sell_price
        quantity = original.config.quantity

        leg1 = self.sell_strategy[0]
        leg2 = self.sell_strategy[1]

        # Get current market price for leg2 (intermediate → end)
        leg2_price = self.price_resolver.latest_prices.get(leg2.name)
        if not leg2_price:
            raise ValueError(f"{leg2.name} price is missing from feed")

        # Calculate leg1 price: Convert target sell_price in USDC to quote token (e.g., BTC)
        price_in_quote = sell_price / leg2.adjust_price(leg2_price)
        leg1_price = leg1.adjust_price(price_in_quote)

        # Calculate leg1 quantity and stable amount
        leg1_quantity = leg1.adjust_quantity(quantity)
        leg1_quantity_stable = round(leg1_quantity * leg1_price, 8)

        # Calculate leg2 price and quantity
        leg2_price_adjusted = leg2.adjust_price(
            self.price_resolver.latest_prices[leg2.name]
        )
        leg2_quantity = leg2.adjust_quantity(leg1_quantity_stable)

        # Log calculated values for debugging
        logger.info("Original sell data: %s", original)
        logger.info("Sell price: %s", sell_price)
        logger.info("Leg2 price: %s", leg2_price)
        logger.info("Price in quote: %s", price_in_quote)
        logger.info("Leg1 price: %s, quantity: %s", leg1_price, leg1_quantity)
        logger.info("Leg2 quantity: %s", leg2_quantity)

        # Build first leg position (base → intermediate)
        leg1_position = SellPosition(
            config=HPSellConfig(
                hp_id=f"{self.original_position.config.hp_id}a",
                is_child=True,
                parent_hp_id=self.original_position.config.hp_id,
                symbol=leg1,
                quantity=leg1_quantity,
                sell_price=leg1_price,
                coin=self.original_position.config.coin,
                buy_price=self.original_position.config.buy_price / leg2_price,
                end_currency=self.original_position.config.end_currency,
            ),
            state_info=StateInfo(side=PositionSide.SHORT),
            sell_order=self._generate_order(
                symbol=leg1,
                quantity=leg1_quantity,
                price=leg1_price,
            ),
            sell_type=SellType.TWOHOPS,
        )

        # Build second leg position (intermediate → end)
        leg2_position = SellPosition(
            config=HPSellConfig(
                hp_id=f"{self.original_position.config.hp_id}b",
                is_child=True,
                parent_hp_id=self.original_position.config.hp_id,
                symbol=leg2,
                quantity=leg2_quantity,
                sell_price=leg2_price,
                coin=leg2.extract_coin_from_symbol(leg2.name),
                buy_price=leg2_price,
                end_currency=self.original_position.config.end_currency,
            ),
            state_info=StateInfo(side=PositionSide.SHORT, state=State.WAITING_CHILD),
            sell_order=self._generate_order(
                symbol=leg2,
                quantity=leg2.adjust_quantity(leg1_quantity_stable),
                price=leg2_price_adjusted,
            ),
            sell_type=SellType.TWOHOPS,
        )

        sell_positions = [leg1_position, leg2_position]

        logger.info(
            "[MULTIHOP] Created 2-hop positions: %s",
            [pos.config.hp_id for pos in sell_positions],
        )

        return sell_positions
