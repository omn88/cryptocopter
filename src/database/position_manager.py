"""
Position manager for integrating the new database with the trading system.
This module handles the conversion between trading system objects and database models.
"""

import logging
from typing import List, Optional, Dict
from datetime import datetime

from src.identifiers import (
    HPBuyData,
    HPSellData,
    Order as TradingOrder,
    ExecutionReport,
    State,
    PositionSide,
    SellPosition,
)

from .trading_database import TradingDatabase
from .models import (
    Position,
    Order,
    PositionType,
    PositionStatus,
    TradeType,
    OrderStatus,
)
from .exceptions import DatabaseError

logger = logging.getLogger("position_manager")


class PositionManager:
    """
    Manages the integration between trading positions and database persistence.

    This class handles:
    - Converting trading system objects to database models
    - Persisting position updates in real-time
    - Managing multihop position relationships
    - Providing a clean interface for the trading system
    """

    def __init__(self, database: TradingDatabase):
        self.database = database

    async def save_buy_position(self, buy_data: HPBuyData) -> str:
        """
        Save a buy position to the database.

        Args:
            buy_data: HPBuyData from the trading system

        Returns:
            Position ID
        """
        try:
            position = Position(
                hp_id=buy_data.config.hp_id,
                position_type=PositionType.BUY,
                status=self._convert_state_to_status(buy_data.state_info.state),
                symbol=buy_data.config.symbol_info.symbol,
                coin=buy_data.config.coin,
                budget=buy_data.config.budget,
                price_low=buy_data.config.price_low,
                price_high=buy_data.config.price_high,
                order_trigger=buy_data.config.order_trigger,
                mode=buy_data.config.mode.value,
                completeness=buy_data.state_info.completeness,
                trade_type=TradeType.DIRECT,
                created_at=(
                    datetime.strptime(
                        buy_data.state_info.open_time, "%Y-%m-%d %H:%M:%S"
                    )
                    if buy_data.state_info.open_time
                    else datetime.now()
                ),
            )

            position_id = await self.database.save_position(position)
            logger.info("Saved buy position %s", buy_data.config.hp_id)
            return position_id

        except Exception as e:
            raise DatabaseError(
                f"Failed to save buy position {buy_data.config.hp_id}: {e}"
            ) from e

    async def save_sell_position(
        self, sell_data: HPSellData, parent_hp_id: Optional[str] = None
    ) -> str:
        """
        Save a sell position to the database.

        Args:
            sell_data: HPSellData from the trading system
            parent_hp_id: Parent position ID for multihop trades

        Returns:
            Position ID
        """
        try:
            position = Position(
                hp_id=sell_data.config.hp_id,
                position_type=PositionType.SELL,
                status=self._convert_state_to_status(sell_data.state_info.state),
                symbol=sell_data.config.symbol_info.symbol,
                coin=sell_data.config.coin,
                quantity=sell_data.config.quantity,
                buy_price=sell_data.config.buy_price,
                sell_price=sell_data.config.sell_price,
                end_currency=sell_data.config.end_currency,
                parent_position_id=parent_hp_id,
                trade_type=TradeType.DIRECT,  # Will be updated for multihop
                completeness=sell_data.state_info.completeness,
                created_at=(
                    datetime.strptime(
                        sell_data.state_info.open_time, "%Y-%m-%d %H:%M:%S"
                    )
                    if sell_data.state_info.open_time
                    else datetime.now()
                ),
            )

            position_id = await self.database.save_position(position)
            logger.info("Saved sell position %s", sell_data.config.hp_id)
            return position_id

        except Exception as e:
            raise DatabaseError(
                f"Failed to save sell position {sell_data.config.hp_id}: {e}"
            ) from e

    async def save_multihop_sell_positions(
        self, sell_positions: List[SellPosition], parent_hp_id: str
    ) -> List[str]:
        """
        Save a multihop sell position chain to the database.

        Args:
            sell_positions: List of SellPosition objects from HPPositionSell
            parent_hp_id: The original position ID

        Returns:
            List of position IDs
        """
        try:
            position_ids = []

            for i, sell_pos in enumerate(sell_positions):
                trade_type = (
                    TradeType.TWOHOP if len(sell_positions) > 1 else TradeType.DIRECT
                )
                if sell_pos.config.symbol_info.is_convert_only:
                    trade_type = TradeType.CONVERT

                position = Position(
                    hp_id=sell_pos.config.hp_id,
                    position_type=PositionType.SELL,
                    status=self._convert_state_to_status(sell_pos.state_info.state),
                    symbol=sell_pos.config.symbol_info.symbol,
                    coin=sell_pos.config.coin,
                    quantity=sell_pos.config.quantity,
                    buy_price=sell_pos.config.buy_price,
                    sell_price=sell_pos.config.sell_price,
                    end_currency=sell_pos.config.end_currency,
                    parent_position_id=(
                        parent_hp_id if sell_pos.config.is_child else None
                    ),
                    trade_type=trade_type,
                    hop_sequence=i,
                    completeness=sell_pos.state_info.completeness,
                )

                position_id = await self.database.save_position(position)
                position_ids.append(position_id)

                # Update parent with child IDs
                if i == 0 and len(sell_positions) > 1:
                    # This is a multihop trade, we'll need to update relationships
                    pass

            # Update parent position with child relationships
            if len(position_ids) > 1:
                await self._update_parent_child_relationships(
                    parent_hp_id, position_ids
                )

            logger.info(
                "Saved %s multihop sell positions for parent %s",
                len(sell_positions),
                parent_hp_id,
            )
            return position_ids

        except Exception as e:
            raise DatabaseError(f"Failed to save multihop sell positions: {e}") from e

    async def save_order(
        self, order: TradingOrder, position_id: str, side: PositionSide
    ) -> str:
        """
        Save a trading order to the database.

        Args:
            order: Trading system Order object
            position_id: Position ID this order belongs to
            side: BUY or SELL

        Returns:
            Order ID
        """
        try:
            db_order = Order(
                position_id=position_id,
                exchange_order_id=order.order_id if order.order_id > 0 else None,
                symbol="",  # Will be filled from position
                side=side.value,
                status=self._convert_order_status(order.status),
                price=order.price,
                quantity=order.quantity,
                quantity_stable=order.quantity_stable,
                realized_quantity=order.realized_quantity,
                time_in_force=order.time_in_force,
                order_type=order.order_type,
            )

            order_id = await self.database.save_order(db_order)
            logger.debug("Saved order %s for position %s", order.order_id, position_id)
            return order_id

        except Exception as e:
            raise DatabaseError(f"Failed to save order: {e}") from e

    async def update_position_from_execution(
        self, hp_id: str, execution_report: ExecutionReport
    ) -> None:
        """
        Update position based on execution report.

        Args:
            hp_id: Position HP ID
            execution_report: ExecutionReport from the exchange
        """
        try:
            # Get the position
            positions = await self.database.get_active_positions()
            position = next((p for p in positions if p.hp_id == hp_id), None)

            if not position:
                logger.warning("Position %s not found for execution update", hp_id)
                return

            # Update position quantities and status
            position.realized_quantity = execution_report.cumulative_filled_quantity

            # Calculate completeness
            if position.quantity > 0:
                position.completeness = position.realized_quantity / position.quantity

            # Update status based on execution
            if execution_report.current_order_status == "FILLED":
                position.status = PositionStatus.FILLED
            elif execution_report.current_order_status == "PARTIALLY_FILLED":
                position.status = PositionStatus.PARTIALLY_FILLED
            elif execution_report.current_order_status == "CANCELED":
                position.status = PositionStatus.CANCELED

            # Save updated position
            await self.database.save_position(position)

            logger.info("Updated position %s from execution report", hp_id)

        except Exception as e:
            logger.error("Failed to update position from execution: %s", e)

    async def close_position(self, hp_id: str) -> None:
        """
        Mark a position as closed.

        Args:
            hp_id: Position HP ID to close
        """
        try:
            positions = await self.database.get_active_positions()
            position = next((p for p in positions if p.hp_id == hp_id), None)

            if position:
                position.status = PositionStatus.CLOSED
                await self.database.save_position(position)
                logger.info("Closed position %s", hp_id)

        except Exception as e:
            raise DatabaseError(f"Failed to close position {hp_id}: {e}") from e

    async def get_position_status(self, hp_id: str) -> Optional[Dict]:
        """
        Get current position status for monitoring.

        Args:
            hp_id: Position HP ID

        Returns:
            Dict with position status information
        """
        try:
            positions = await self.database.get_active_positions()
            position = next((p for p in positions if p.hp_id == hp_id), None)

            if not position:
                return None

            orders = await self.database.get_position_orders(position.id)

            return {
                "hp_id": position.hp_id,
                "status": position.status.value,
                "symbol": position.symbol,
                "completeness": position.completeness,
                "trade_type": position.trade_type.value,
                "orders_count": len(orders),
                "created_at": position.created_at.isoformat(),
                "updated_at": position.updated_at.isoformat(),
            }

        except Exception as e:
            logger.error("Failed to get position status for %s: %s", hp_id, e)
            return None

    def _convert_state_to_status(self, state: State) -> PositionStatus:
        """Convert trading system State to database PositionStatus."""
        mapping = {
            State.NEW: PositionStatus.NEW,
            State.BUYING: PositionStatus.OPEN,
            State.SELLING: PositionStatus.OPEN,
            State.PARTIALLY_BOUGHT: PositionStatus.PARTIALLY_FILLED,
            State.PARTIALLY_SOLD: PositionStatus.PARTIALLY_FILLED,
            State.BOUGHT: PositionStatus.FILLED,
            State.SOLD: PositionStatus.FILLED,
            State.CLOSED: PositionStatus.CLOSED,
            State.WAITING_CHILD: PositionStatus.WAITING_CHILD,
        }
        return mapping.get(state, PositionStatus.NEW)

    def _convert_order_status(self, status: str) -> OrderStatus:
        """Convert trading system order status to database OrderStatus."""
        mapping = {
            "NEW": OrderStatus.NEW,
            "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
            "FILLED": OrderStatus.FILLED,
            "CANCELED": OrderStatus.CANCELED,
            "REJECTED": OrderStatus.REJECTED,
        }
        return mapping.get(status, OrderStatus.NEW)

    async def _update_parent_child_relationships(
        self, parent_hp_id: str, child_position_ids: List[str]
    ) -> None:
        """Update parent-child relationships for multihop trades."""
        try:
            positions = await self.database.get_active_positions()
            parent = next((p for p in positions if p.hp_id == parent_hp_id), None)

            if parent:
                parent.child_position_ids = child_position_ids
                await self.database.save_position(parent)

        except Exception as e:
            logger.error("Failed to update parent-child relationships: %s", e)
