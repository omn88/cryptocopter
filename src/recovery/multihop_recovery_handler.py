"""
Multihop recovery handler for restoring complex multi-leg sell positions.

Handles the restoration of two-hop sell positions where the first leg
must complete before the second leg activates.
"""

import logging
from binance.enums import ORDER_STATUS_FILLED, ORDER_STATUS_NEW

from src.identifiers import PositionSide
from src.strategies.hp_manager.hp_manager import HpStrategy
from src.database.trading_database import Database


logger = logging.getLogger("MultihopRecoveryHandler")


class MultihopRecoveryHandler:
    """Handles recovery of multihop (two-leg) sell positions."""

    def __init__(self, database: Database):
        self.db = database

    def restore_current_sell_position_for_multihop(self, strategy: HpStrategy) -> None:
        """
        If this is a two-hop sell and the first leg is FILLED,
        advance current_position to the second leg.
        """
        sell_positions = strategy.sell.sell_positions
        if not sell_positions or len(sell_positions) != 2:
            return

        first_leg = sell_positions[0]
        second_leg = sell_positions[1]

        if first_leg.sell_order.status == ORDER_STATUS_FILLED:
            strategy.sell.current_position = second_leg
            logger.info(
                "Advanced current_position to second leg after first leg FILLED: %s",
                second_leg.config.hp_id,
            )

    async def restore_all_child_sell_positions_for_multihop(
        self, strategy: HpStrategy
    ) -> None:
        """
        For two-hop sells, restore both child sell positions from DB.
        Set their orders and state, and determine which leg should be current_position.
        """
        sell_positions = strategy.sell.sell_positions
        if not sell_positions or len(sell_positions) != 2:
            return

        # Restore each child sell position's order from DB
        for pos in sell_positions:
            await self._restore_child_position_order(pos)

        # Set current_position based on child leg order status
        self._set_current_position_based_on_status(strategy, sell_positions)

    async def _restore_child_position_order(self, position) -> None:
        """Restore order data from database for a child position."""
        orders = await self.db.fetch_orders_for_price_level(
            hp_id=position.config.hp_id, side=PositionSide.SHORT.value
        )

        if not orders:
            return

        order_dict = orders[0]
        position.sell_order.order_id = order_dict["order_id"]
        position.sell_order.quantity = order_dict["quantity"]
        position.sell_order.precision = position.config.symbol.precision
        position.sell_order.price_precision = position.config.symbol.price_precision
        position.sell_order.price = order_dict["price"]
        position.sell_order.quantity_stable = order_dict["quantity_stable"]
        position.sell_order.realized_quantity = order_dict["realized_quantity"]
        position.sell_order.status = order_dict["status"]

    def _set_current_position_based_on_status(
        self, strategy: HpStrategy, sell_positions: list
    ) -> None:
        """
        Determine which leg should be the current_position based on order statuses.

        Logic:
        - If first leg is FILLED, use second leg
        - If first leg is open (NEW/PARTIALLY_FILLED), use first leg
        - If second leg is open, use second leg
        - Fallback: use leg ending with 'b'
        """
        first_leg = sell_positions[0]
        second_leg = sell_positions[1]
        first_status = first_leg.sell_order.status
        second_status = second_leg.sell_order.status

        if first_status == ORDER_STATUS_FILLED:
            strategy.sell.current_position = second_leg
            logger.info(
                "Set current_position to second leg after first leg FILLED: %s",
                second_leg.config.hp_id,
            )
        elif first_status in [ORDER_STATUS_NEW, "PARTIALLY_FILLED", "SUBMITTED"]:
            strategy.sell.current_position = first_leg
            logger.info(
                "Set current_position to first leg (open): %s",
                first_leg.config.hp_id,
            )
        elif second_status in [ORDER_STATUS_NEW, "PARTIALLY_FILLED", "SUBMITTED"]:
            strategy.sell.current_position = second_leg
            logger.info(
                "Set current_position to second leg (open): %s",
                second_leg.config.hp_id,
            )
        else:
            # Fallback: set to 'b' leg if present
            for pos in sell_positions:
                if pos.config.hp_id.endswith("b"):
                    strategy.sell.current_position = pos
                    logger.info(
                        "Fallback: Set current_position to child leg 'b': %s",
                        pos.config.hp_id,
                    )
                    break
