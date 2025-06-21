"""
Recovery service for restoring trading positions after system restart.

This module handles the complex task of restoring all active positions,
verifying their state with the exchange, and ensuring consistency.
"""

import logging
from typing import List, Dict, Optional, Tuple, Any

from src.identifiers import (
    BinanceClient,
    HPBuyConfig,
    HPBuyData,
    HPSellConfig,
    HPSellData,
    StateInfo,
    State,
    PositionSide,
    Order as TradingOrder,  # Alias to avoid collision
    Mode,
)
from src.common.symbol_info import SymbolInfo
from .trading_database import TradingDatabase
from .models import (
    Position,
    Order as DatabaseOrder,
    PositionType,
    PositionStatus,
    TradeType,
)  # Alias to avoid collision
from .exceptions import RecoveryError

logger = logging.getLogger("recovery_service")


class RecoveryService:
    """
    Service for recovering trading positions after system restart.

    The recovery process:
    1. Load all active positions from database
    2. Verify position states with exchange
    3. Reconstruct position objects for the trading system
    4. Handle any discrepancies or missing data
    """

    def __init__(
        self,
        database: TradingDatabase,
        client: BinanceClient,
        symbols_info: Dict[str, SymbolInfo],
    ):
        self.database = database
        self.client = client
        self.symbols_info = symbols_info

    async def recover_all_positions(self) -> Tuple[List[HPBuyData], List[HPSellData]]:
        """
        Recover all active positions from the database.

        Returns:
            Tuple of (buy_positions, sell_positions) ready for the trading system
        """
        logger.info("Starting position recovery process...")

        try:
            # Load all active positions from database
            active_positions = await self.database.get_active_positions()
            logger.info(f"Found {len(active_positions)} active positions in database")

            # Verify positions with exchange
            verified_positions = await self._verify_positions_with_exchange(
                active_positions
            )

            # Group positions by type
            buy_positions = []
            sell_positions = []

            for position in verified_positions:
                if position.position_type == PositionType.BUY:
                    buy_data = await self._convert_to_buy_data(position)
                    if buy_data:
                        buy_positions.append(buy_data)
                else:
                    sell_data = await self._convert_to_sell_data(position)
                    if sell_data:
                        sell_positions.append(sell_data)

            logger.info(
                f"Recovered {len(buy_positions)} buy positions and {len(sell_positions)} sell positions"
            )
            return buy_positions, sell_positions

        except Exception as e:
            raise RecoveryError(f"Failed to recover positions: {e}")

    async def _verify_positions_with_exchange(
        self, positions: List[Position]
    ) -> List[Position]:
        """
        Verify position states with the exchange and update if necessary.

        This is crucial for ensuring consistency after a system outage.
        """
        verified_positions = []

        for position in positions:
            try:
                # Get position orders from database
                orders = await self.database.get_position_orders(position.id)

                # Verify each order with exchange
                updated_orders = []
                for order in orders:
                    if order.exchange_order_id:
                        # Check order status with exchange
                        try:
                            exchange_order = await self.client.get_order(
                                symbol=order.symbol, orderId=order.exchange_order_id
                            )

                            # Update order status if changed
                            if exchange_order["status"] != order.status.value:
                                logger.info(
                                    f"Order {order.exchange_order_id} status changed from {order.status.value} to {exchange_order['status']}"
                                )
                                order.status = self._convert_exchange_status(
                                    exchange_order["status"]
                                )
                                order.realized_quantity = float(
                                    exchange_order["executedQty"]
                                )

                                # Save updated order
                                await self.database.save_order(order)

                            updated_orders.append(order)

                        except Exception as e:
                            logger.warning(
                                f"Could not verify order {order.exchange_order_id}: {e}"
                            )
                            updated_orders.append(order)
                    else:
                        updated_orders.append(order)

                # Update position based on order states
                updated_position = await self._update_position_from_orders(
                    position, updated_orders
                )
                verified_positions.append(updated_position)

            except Exception as e:
                logger.error(f"Failed to verify position {position.hp_id}: {e}")
                # Add position anyway for manual review
                verified_positions.append(position)

        return verified_positions

    async def _update_position_from_orders(
        self, position: Position, orders: List[DatabaseOrder]
    ) -> Position:
        """Update position status and quantities based on order states."""
        total_quantity = sum(order.quantity for order in orders)
        realized_quantity = sum(order.realized_quantity for order in orders)

        # Update quantities
        position.quantity = total_quantity
        position.realized_quantity = realized_quantity
        position.completeness = (
            realized_quantity / total_quantity if total_quantity > 0 else 0.0
        )  # Update status based on completeness
        if position.completeness == 0.0:
            if any(
                (order.status.value if hasattr(order.status, "value") else order.status)
                in ["NEW", "PARTIALLY_FILLED"]
                for order in orders
            ):
                position.status = PositionStatus.OPEN
            else:
                position.status = PositionStatus.NEW
        elif position.completeness == 1.0:
            position.status = PositionStatus.FILLED
        else:
            position.status = PositionStatus.PARTIALLY_FILLED

        # Save updated position
        await self.database.save_position(position)

        return position

    async def _convert_to_buy_data(self, position: Position) -> Optional[HPBuyData]:
        """Convert database Position to HPBuyData for the trading system."""
        try:
            symbol_info = self.symbols_info.get(position.symbol)
            if not symbol_info:
                logger.error(f"Symbol info not found for {position.symbol}")
                return None

            config = HPBuyConfig(
                symbol_info=symbol_info,
                coin=position.coin,
                hp_id=position.hp_id,
                price_low=position.price_low,
                price_high=position.price_high,
                order_trigger=position.order_trigger,
                budget=position.budget,
                mode=(
                    Mode(position.mode)
                    if position.mode in ["SINGLE", "DCA"]
                    else Mode.DCA
                ),
            )

            state_info = StateInfo(
                state=self._convert_to_state(position.status),
                open_time=position.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                side=PositionSide.LONG,
                completeness=position.completeness,
            )

            return HPBuyData(config=config, state_info=state_info)

        except Exception as e:
            logger.error(
                f"Failed to convert position {position.hp_id} to buy data: {e}"
            )
            return None

    async def _convert_to_sell_data(self, position: Position) -> Optional[HPSellData]:
        """Convert database Position to HPSellData for the trading system."""
        try:
            symbol_info = self.symbols_info.get(position.symbol)
            if not symbol_info:
                logger.error(f"Symbol info not found for {position.symbol}")
                return None

            config = HPSellConfig(
                symbol_info=symbol_info,
                hp_id=position.hp_id,
                coin=position.coin,
                quantity=position.quantity,
                buy_price=position.buy_price,
                sell_price=position.sell_price,
                end_currency=position.end_currency,
                is_child=position.parent_position_id is not None,
                parent_hp_id=position.parent_position_id,
            )

            state_info = StateInfo(
                state=self._convert_to_state(position.status),
                open_time=position.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                side=PositionSide.SHORT,
                completeness=position.completeness,
            )

            return HPSellData(config=config, state_info=state_info)

        except Exception as e:
            logger.error(
                f"Failed to convert position {position.hp_id} to sell data: {e}"
            )
            return None

    def _convert_to_state(self, status: PositionStatus) -> State:
        """Convert database PositionStatus to trading system State."""
        mapping = {
            PositionStatus.NEW: State.NEW,
            PositionStatus.OPEN: State.BUYING,  # or SELLING depending on context
            PositionStatus.PARTIALLY_FILLED: State.PARTIALLY_BOUGHT,  # or PARTIALLY_SOLD
            PositionStatus.FILLED: State.BOUGHT,  # or SOLD
            PositionStatus.CANCELED: State.CLOSED,
            PositionStatus.CLOSED: State.CLOSED,
            PositionStatus.WAITING_PARENT: State.WAITING_CHILD,
            PositionStatus.WAITING_CHILD: State.WAITING_CHILD,
        }
        return mapping.get(status, State.NEW)

    def _convert_exchange_status(self, exchange_status: str):
        """Convert exchange order status to our OrderStatus."""
        from .models import OrderStatus

        mapping = {
            "NEW": OrderStatus.NEW,
            "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
            "FILLED": OrderStatus.FILLED,
            "CANCELED": OrderStatus.CANCELED,
            "REJECTED": OrderStatus.REJECTED,
            "EXPIRED": OrderStatus.CANCELED,
        }
        return mapping.get(exchange_status, OrderStatus.NEW)

    async def recover_multihop_positions(self) -> Dict[str, List[Position]]:
        """
        Recover multihop positions with their complete hierarchies.

        Returns:
            Dict mapping parent hp_id to list of positions in the chain
        """
        try:
            active_positions = (
                await self.database.get_active_positions()
            )  # Group by parent positions
            multihop_chains: Dict[str, List[Position]] = {}

            for position in active_positions:
                if position.trade_type in [TradeType.TWOHOP, TradeType.CONVERT]:
                    # Find the root parent
                    root_hp_id = position.hp_id
                    if position.parent_position_id:
                        # This is a child, find the parent
                        parent_positions = [
                            p
                            for p in active_positions
                            if p.id == position.parent_position_id
                        ]
                        if parent_positions:
                            root_hp_id = parent_positions[0].hp_id

                    if root_hp_id not in multihop_chains:
                        multihop_chains[root_hp_id] = []

                    multihop_chains[root_hp_id].append(
                        position
                    )  # Sort each chain by hop sequence
            for hp_id in multihop_chains:
                multihop_chains[hp_id].sort(key=lambda p: p.hop_sequence)

            logger.info(f"Recovered {len(multihop_chains)} multihop position chains")
            return multihop_chains

        except Exception as e:
            raise RecoveryError(f"Failed to recover multihop positions: {e}")

    async def validate_recovery_integrity(self) -> Dict[str, Any]:
        """
        Validate the integrity of recovered positions.

        Returns a report of any issues found.
        """
        try:
            issues: Dict[str, List[str]] = {
                "missing_symbols": [],
                "orphaned_orders": [],
                "inconsistent_states": [],
                "broken_hierarchies": [],
            }

            positions = await self.database.get_active_positions()

            for position in positions:
                # Check if symbol info exists
                if position.symbol not in self.symbols_info:
                    issues["missing_symbols"].append(position.symbol)

                # Check for broken parent-child relationships
                if position.parent_position_id:
                    parents = [
                        p for p in positions if p.id == position.parent_position_id
                    ]
                    if not parents:
                        issues["broken_hierarchies"].append(
                            f"Position {position.hp_id} has missing parent {position.parent_position_id}"
                        )

                # Check orders
                orders = await self.database.get_position_orders(position.id)
                for order in orders:
                    if order.position_id != position.id:
                        issues["orphaned_orders"].append(order.id)

            return issues

        except Exception as e:
            logger.error(f"Failed to validate recovery integrity: {e}")
            return {"validation_error": str(e)}
