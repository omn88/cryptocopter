"""Multihop sell strategy - two-hop sell through intermediate pair."""

import logging
from typing import Any, Dict, List

from binance.enums import ORDER_STATUS_FILLED

from src.common.identifiers import (
    HPSellConfig,
    PositionSide,
    SellPosition,
    SellType,
    State,
    StateInfo,
)
from .base import BaseSellStrategy


logger = logging.getLogger(__name__)


class MultihopSellStrategy(BaseSellStrategy):
    """Two-hop sell strategy for selling through intermediate pair.

    Example: AXL -> BTC -> USDC
    - Leg 1: Sell AXL for BTC (AXLBTC)
    - Leg 2: Sell BTC for USDC (BTCUSDC)

    Creates two sell positions:
    - Leg 1 (child 'a'): Sells base coin for intermediate coin
    - Leg 2 (child 'b'): Sells intermediate coin for end currency

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
        sell_price = self.original_position.config.sell_price
        quantity = self.original_position.config.quantity

        leg1 = self.sell_path[0]
        leg2 = self.sell_path[1]

        # Get current market price for leg2 (intermediate -> end)
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
        leg2_price_adjusted = leg2.adjust_price(leg2_price)
        leg2_quantity = leg2.adjust_quantity(leg1_quantity_stable)

        # Log calculated values for debugging
        logger.info(
            "[MULTIHOP] === Building 2-hop position for %s (qty: %.8f) ===",
            self.original_position.config.coin,
            leg1_quantity,
        )
        logger.info("[MULTIHOP] Path: %s -> %s", leg1.name, leg2.name)
        logger.info("[MULTIHOP] Original sell price: %.8f", sell_price)
        logger.info("[MULTIHOP] Leg2 current price: %.8f", leg2_price)
        logger.info("[MULTIHOP] Calculated leg1 price in quote: %.8f", price_in_quote)
        logger.info(
            "[MULTIHOP] Leg1: %s @ %.8f x %.8f = %.8f %s",
            leg1.name,
            leg1_price,
            leg1_quantity,
            leg1_price * leg1_quantity,
            leg2.extract_coin_from_symbol(leg2.name),
        )
        logger.info(
            "[MULTIHOP] Leg2: %s @ %.8f x %.8f = %.8f %s",
            leg2.name,
            leg2_price_adjusted,
            leg2_quantity,
            leg2_price_adjusted * leg2_quantity,
            self.original_position.config.end_currency,
        )

        # Build first leg position (base -> intermediate)
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

        # Build second leg position (intermediate -> end)
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
                quantity=leg2_quantity,
                price=leg2_price_adjusted,
            ),
            sell_type=SellType.TWOHOPS,
        )

        logger.info(
            "[MULTIHOP] Created 2-hop positions: %s -> %s",
            leg1_position.config.hp_id,
            leg2_position.config.hp_id,
        )

        return [leg1_position, leg2_position]

    async def recalculate_prices(self, sell_positions: List[SellPosition]) -> None:
        """Recalculate leg prices using current market data before execution.

        This ensures both legs use fresh market prices at execution time
        rather than stale prices from position creation time.

        Args:
            sell_positions: List containing leg1 and leg2 positions
        """
        if len(sell_positions) != 2:
            logger.debug("Not a multihop trade, skipping price recalculation")
            return

        leg1_position = sell_positions[0]
        leg2_position = sell_positions[1]
        leg1 = leg1_position.config.symbol
        leg2 = leg2_position.config.symbol

        logger.info("[MULTIHOP RECALC] === Recalculating prices before execution ===")
        logger.info("[MULTIHOP RECALC] HP ID: %s", self.original_position.config.hp_id)
        logger.info("[MULTIHOP RECALC] Coin: %s", self.original_position.config.coin)
        logger.info("[MULTIHOP RECALC] Path: %s -> %s", leg1.name, leg2.name)

        # Get current market price for leg2
        current_leg2_price = self.price_resolver.latest_prices.get(leg2.name)
        if not current_leg2_price:
            logger.warning(
                "[MULTIHOP RECALC] WARNING: Missing current price for %s, skipping recalculation",
                leg2.name,
            )
            return

        # Store old prices for logging
        old_leg1_price = leg1_position.sell_order.price
        old_leg2_price = leg2_position.sell_order.price

        logger.info(
            "[MULTIHOP RECALC] Old prices: Leg1=%.8f, Leg2=%.8f",
            old_leg1_price,
            old_leg2_price,
        )
        logger.info(
            "[MULTIHOP RECALC] Current leg2 market price: %.8f", current_leg2_price
        )

        # Recalculate leg1 price based on current leg2 price
        sell_price = self.original_position.config.sell_price
        current_price_in_quote = sell_price / leg2.adjust_price(current_leg2_price)
        current_leg1_price = leg1.adjust_price(current_price_in_quote)

        # Calculate leg1 quantity and stable amount
        leg1_quantity = leg1.adjust_quantity(self.original_position.config.quantity)
        leg1_quantity_stable = round(leg1_quantity * current_leg1_price, 8)

        # Recalculate leg2 price and quantity
        current_leg2_price_adjusted = leg2.adjust_price(current_leg2_price)
        leg2_quantity = leg2.adjust_quantity(leg1_quantity_stable)

        # Update leg1 position with fresh prices
        leg1_position.sell_order.price = current_leg1_price
        leg1_position.sell_order.quantity_stable = leg1_quantity_stable
        leg1_position.config.sell_price = current_leg1_price
        leg1_position.config.buy_price = (
            self.original_position.config.buy_price / current_leg2_price
        )

        # Update leg2 position with fresh prices
        leg2_position.sell_order.price = current_leg2_price_adjusted
        leg2_position.sell_order.quantity = leg2_quantity
        leg2_position.config.sell_price = current_leg2_price
        leg2_position.config.buy_price = current_leg2_price

        logger.info(
            "[MULTIHOP RECALC] > New prices: Leg1=%.8f (Delta %.8f%%), Leg2=%.8f (Delta %.8f%%)",
            current_leg1_price,
            (
                ((current_leg1_price - old_leg1_price) / old_leg1_price * 100)
                if old_leg1_price
                else 0
            ),
            current_leg2_price_adjusted,
            (
                ((current_leg2_price_adjusted - old_leg2_price) / old_leg2_price * 100)
                if old_leg2_price
                else 0
            ),
        )
        logger.info(
            "[MULTIHOP RECALC] > New quantities: Leg1=%.8f (stable: %.8f), Leg2=%.8f",
            leg1_quantity,
            leg1_quantity_stable,
            leg2_quantity,
        )
        logger.info(
            "[MULTIHOP RECALC] > Expected total value: %.8f %s",
            leg2_quantity * current_leg2_price_adjusted,
            self.original_position.config.end_currency,
        )

    def handle_completion(
        self,
        current_position: SellPosition,
        all_positions: List[SellPosition],
    ) -> Dict[str, Any]:
        """Handle completion of multihop sell position.

        For multihop sells:
        - If leg1 completes: transition to leg2, send leg1 completion (handled by caller)
        - If leg2 completes: send leg2 + parent completion, no HPClose

        Args:
            current_position: The position that just completed (leg1 or leg2)
            all_positions: Both positions [leg1, leg2]

        Returns:
            Dict with appropriate next_position, events, and flags
        """
        # Determine which leg completed
        is_leg1 = current_position is all_positions[0]
        is_leg2 = current_position is all_positions[1]

        if is_leg2:
            # Second leg completed - multihop trade finished
            logger.info("Multihop leg2 completed, sending completion events")

            # Update original position state for UI
            original_position = SellPosition(
                sell_order=self.original_position.sell_order,
                config=self.original_position.config,
                state_info=self.original_position.state_info,
            )
            original_position.state_info.state = State.SOLD
            original_position.sell_order.status = ORDER_STATUS_FILLED
            original_position.state_info.completeness = 1.0

            # Send completion events for leg2 AND parent
            completion_events = [
                {
                    "hp_id": current_position.config.hp_id,
                    "coin": current_position.config.coin,
                    "quantity_sold": current_position.sell_order.realized_quantity,
                    "buy_price": current_position.config.buy_price,
                    "sell_price": current_position.config.sell_price,
                    "end_currency": current_position.config.end_currency,
                },
                {
                    "hp_id": original_position.config.hp_id,
                    "coin": original_position.config.coin,
                    "quantity_sold": original_position.config.quantity,
                    "buy_price": original_position.config.buy_price,
                    "sell_price": original_position.config.sell_price,
                    "end_currency": original_position.config.end_currency,
                },
            ]

            return {
                "next_position": None,
                "needs_close": False,  # DON'T send HPClose for multihop
                "completion_events": completion_events,
                "original_position": original_position,  # For UI update
            }

        elif is_leg1:
            # First leg completed - transition to leg2
            logger.info("Multihop leg1 completed, transitioning to leg2")

            leg2_position = all_positions[1]
            leg2_position.state_info.state = State.SELLING

            return {
                "next_position": leg2_position,
                "needs_close": False,
                "completion_events": [],  # Wait for leg2 to complete before sending events
            }

        # Should never reach here
        logger.error("Unexpected completion state in multihop strategy")
        return {
            "next_position": None,
            "needs_close": False,
            "completion_events": [],
        }
