"""
Position verifier for validating position states with the exchange.

Ensures consistency between database state and exchange state after
system restart, updating positions and orders as needed.
"""

import logging
from typing import List

from src.common.client import KrakenClient
from src.database.trading_database import Database
from src.database.models import (
    Position,
    PositionType,
    PositionStatus,
    Order as DatabaseOrder,
)
from .position_converter import PositionConverter

logger = logging.getLogger(__name__)


class PositionVerifier:
    """Verifies and updates position states with exchange."""

    def __init__(self, database: Database, converter: PositionConverter):
        self.db = database
        self.converter = converter

    async def verify_positions_with_exchange(
        self, client: KrakenClient, positions: List[Position]
    ) -> List[Position]:
        """
        Verify position states with the exchange and update if necessary.

        This is crucial for ensuring consistency after a system outage.
        """
        verified_positions = []

        for position in positions:
            try:
                # Get position orders from database
                orders = await self.db.get_position_orders(position.id)

                # Optimization: If all orders are FILLED, skip exchange verification
                if self._all_orders_filled(orders):
                    updated_position = await self._update_position_from_orders(
                        position, orders
                    )
                    verified_positions.append(updated_position)
                    continue

                # Verify each order with exchange
                updated_orders = await self._verify_orders_with_exchange(client, orders)

                # Update position based on verified orders
                if updated_orders:
                    updated_position = await self._update_position_from_orders(
                        position, updated_orders
                    )
                    verified_positions.append(updated_position)
                else:
                    # No orders, keep position as-is
                    verified_positions.append(position)

            except Exception as e:
                logger.exception("Failed to verify position %s: %s", position.hp_id, e)
                raise

        return verified_positions

    def _all_orders_filled(self, orders: List[DatabaseOrder]) -> bool:
        """Check if all orders in list are FILLED."""
        if not orders:
            return False

        return all(
            (order.status.value if hasattr(order.status, "value") else order.status)
            == "FILLED"
            for order in orders
        )

    async def _verify_orders_with_exchange(
        self, client: KrakenClient, orders: List[DatabaseOrder]
    ) -> List[DatabaseOrder]:
        """
        Verify each order with the exchange and update status/quantity if changed.
        """
        updated_orders = []

        for order in orders:
            if not order.exchange_order_id:
                updated_orders.append(order)
                continue

            try:
                # Check order status with exchange
                exchange_order = await client.get_order(
                    symbol=order.symbol, orderId=order.exchange_order_id
                )

                # Update order status if changed
                if exchange_order["status"] != order.status.value:
                    order.status = self.converter.convert_exchange_status(
                        exchange_order["status"]
                    )
                    order.realized_quantity = float(exchange_order["executedQty"])

                    # Save updated order
                    await self.db.save_order(order)

                updated_orders.append(order)

            except Exception as e:
                logger.exception(
                    "Could not verify order %s: %s",
                    order.exchange_order_id,
                    e,
                )
                raise

        return updated_orders

    async def _update_position_from_orders(
        self, position: Position, orders: List[DatabaseOrder]
    ) -> Position:
        """Update position status and quantities based on order states."""
        if not orders:
            return position

        total_quantity = sum(order.quantity for order in orders)
        realized_quantity = sum(order.realized_quantity for order in orders)

        # Update quantities
        position.quantity = total_quantity
        position.realized_quantity = realized_quantity
        position.completeness = (
            realized_quantity / total_quantity if total_quantity > 0 else 0.0
        )

        # Determine position status from orders
        all_canceled = self._all_orders_canceled(orders)
        any_partial = any(order.realized_quantity > 0 for order in orders)

        if all_canceled:
            if any_partial:
                position.status = PositionStatus.PARTIALLY_FILLED
                logger.info(
                    "All orders canceled but some partially filled for position %s: PARTIALLY_FILLED",
                    position.hp_id,
                )
            else:
                position.status = PositionStatus.NEW
                position.completeness = 0.0
        elif position.completeness == 0.0:
            if any(self._order_is_open(order) for order in orders):
                position.status = PositionStatus.OPEN
            else:
                position.status = PositionStatus.NEW
        elif position.completeness >= 1.0:
            position.status = PositionStatus.FILLED
        else:
            position.status = PositionStatus.PARTIALLY_FILLED

        # Check for PARTIALLY_SOLD state (fully bought but partially sold then canceled)
        await self._check_partially_sold_state(position)

        # Save updated position
        await self.db.save_position(position)
        return position

    def _all_orders_canceled(self, orders: List[DatabaseOrder]) -> bool:
        """Check if all orders are CANCELED and none are FILLED."""
        all_canceled = all(
            (order.status.value if hasattr(order.status, "value") else order.status)
            == "CANCELED"
            for order in orders
        )
        any_filled = any(
            (order.status.value if hasattr(order.status, "value") else order.status)
            == "FILLED"
            for order in orders
        )
        return all_canceled and not any_filled

    def _order_is_open(self, order: DatabaseOrder) -> bool:
        """Check if order status indicates it's still open."""
        status = order.status.value if hasattr(order.status, "value") else order.status
        return status in ["NEW", "PARTIALLY_FILLED"]

    async def _check_partially_sold_state(self, position: Position) -> None:
        """
        Check if position should be marked as PARTIALLY_SOLD.
        This happens when buy is fully filled but sell is partially filled then canceled.
        """
        try:
            if (
                position.position_type != PositionType.BUY
                or position.status != PositionStatus.FILLED
            ):
                return

            # Try to find related SELL position
            related_sell_positions = []
            if hasattr(self.db, "get_positions_by_hp_id"):
                related_sell_positions = await self.db.get_positions_by_hp_id(
                    position.hp_id, PositionType.SELL
                )
            elif hasattr(self.db, "get_active_positions"):
                all_positions = await self.db.get_active_positions()
                related_sell_positions = [
                    p
                    for p in all_positions
                    if getattr(p, "hp_id", None) == position.hp_id
                    and getattr(p, "position_type", None) == PositionType.SELL
                ]

            # Check if any sell order is CANCELED with realized_quantity > 0
            for sell_pos in related_sell_positions:
                if hasattr(self.db, "get_position_orders"):
                    sell_orders = await self.db.get_position_orders(sell_pos.id)
                    for so in sell_orders:
                        so_status = (
                            so.status.value
                            if hasattr(so.status, "value")
                            else so.status
                        )
                        if (
                            so_status == "CANCELED"
                            and getattr(so, "realized_quantity", 0.0) > 0.0
                        ):
                            logger.warning(
                                "Detected fully filled buy and partially filled/canceled sell for hp_id=%s: PARTIALLY_SOLD",
                                position.hp_id,
                            )
                            position.strategy_state = "PARTIALLY_SOLD"
                            return

        except Exception as e:
            logger.exception(
                "Error in PARTIALLY_SOLD check for hp_id=%s: %s",
                getattr(position, "hp_id", None),
                e,
            )
            raise
