"""
Recovery service for restoring trading positions after system restart.

This module handles the complex task of restoring all active positions,
verifying their state with the exchange, and ensuring consistency.
"""

import logging
from typing import List, Dict, Optional, Tuple, Any

from src.database.trading_database import TradingDatabase
from src.identifiers import (
    BinanceClient,
    HPBuyConfig,
    HPBuyData,
    HPSellConfig,
    HPSellData,
    StateInfo,
    State,
    PositionSide,
    Mode,
)
from src.common.symbol import Symbol
from .models import (
    Position,
    Order as DatabaseOrder,
    PositionType,
    PositionStatus,
    TradeType,
    OrderStatus,
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
        symbols: Dict[str, Symbol],
        database: TradingDatabase,
        client: BinanceClient,
    ):
        self.database = database
        self.client = client
        self.symbols = symbols

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
            logger.info("Found %d active positions in database", len(active_positions))

            logger.info("Active positions: %s", active_positions)

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
                "Recovered %d buy positions and %d sell positions",
                len(buy_positions),
                len(sell_positions),
            )

            return buy_positions, sell_positions

        except Exception as e:
            raise RecoveryError(f"Failed to recover positions: {e}") from e

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

                # Optimization: If all orders are FILLED, skip exchange verification
                all_filled = all(
                    (
                        order.status.value
                        if hasattr(order.status, "value")
                        else order.status
                    )
                    == "FILLED"
                    for order in orders
                )
                if all_filled and len(orders) > 0:
                    # Just update position from orders, do not query exchange
                    updated_position = await self._update_position_from_orders(
                        position, orders
                    )
                    verified_positions.append(updated_position)
                    continue

                # Otherwise, verify each order with exchange
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
                                    "Order %s status changed from %s to %s",
                                    order.exchange_order_id,
                                    order.status.value,
                                    exchange_order["status"],
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
                                "Could not verify order %s: %s",
                                order.exchange_order_id,
                                e,
                            )
                            updated_orders.append(order)
                    else:
                        updated_orders.append(
                            order
                        )  # Update position based on order states only if there are orders
                if updated_orders:
                    updated_position = await self._update_position_from_orders(
                        position, updated_orders
                    )
                    verified_positions.append(updated_position)
                else:
                    # No orders, keep position as-is
                    verified_positions.append(position)

            except Exception as e:
                logger.error("Failed to verify position %s: %s", position.hp_id, e)
                # Add position anyway for manual review
                verified_positions.append(position)

        return verified_positions

    async def _update_position_from_orders(
        self, position: Position, orders: List[DatabaseOrder]
    ) -> Position:
        """Update position status and quantities based on order states."""
        if not orders:
            # No orders, return position unchanged
            return position

        total_quantity = sum(order.quantity for order in orders)
        realized_quantity = sum(order.realized_quantity for order in orders)

        # Update quantities
        position.quantity = total_quantity
        position.realized_quantity = realized_quantity
        position.completeness = (
            realized_quantity / total_quantity if total_quantity > 0 else 0.0
        )

        # Explicitly check for all orders canceled
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
        any_partial = any(
            (order.realized_quantity if hasattr(order, "realized_quantity") else 0.0)
            > 0.0
            for order in orders
        )
        if all_canceled and not any_filled:
            if any_partial:
                position.status = PositionStatus.PARTIALLY_FILLED
                logger.info(
                    "[Recovery] All buy orders canceled but some partially filled for position %s: setting status to PARTIALLY_FILLED",
                    position.hp_id,
                )
            else:
                position.status = PositionStatus.NEW
                position.completeness = 0.0
                logger.info(
                    "[Recovery] All buy orders canceled and none filled for position %s: setting status to NEW and completeness to 0.0",
                    position.hp_id,
                )
        elif position.completeness == 0.0:
            if any(
                (order.status.value if hasattr(order.status, "value") else order.status)
                in ["NEW", "PARTIALLY_FILLED"]
                for order in orders
            ):
                position.status = PositionStatus.OPEN
            else:
                position.status = PositionStatus.NEW
        elif (
            position.completeness >= 1.0
        ):  # Use >= instead of == for floating point safety
            position.status = PositionStatus.FILLED
        else:
            position.status = PositionStatus.PARTIALLY_FILLED

        # Save updated position

        # --- PATCH: Check for PARTIALLY_SOLD after full buy and partial/canceled sell ---
        try:
            # Only run this for BUY positions
            if (
                position.position_type == PositionType.BUY
                and position.status == PositionStatus.FILLED
            ):
                # Try to find a related SELL position (same hp_id, type SELL)
                related_sell_positions = []
                if hasattr(self.database, "get_positions_by_hp_id"):
                    related_sell_positions = await self.database.get_positions_by_hp_id(
                        position.hp_id, PositionType.SELL
                    )
                # Fallback: try to get all positions and filter
                elif hasattr(self.database, "get_active_positions"):
                    all_positions = await self.database.get_active_positions()
                    related_sell_positions = [
                        p
                        for p in all_positions
                        if getattr(p, "hp_id", None) == position.hp_id
                        and getattr(p, "position_type", None) == PositionType.SELL
                    ]
                for sell_pos in related_sell_positions:
                    # Get all orders for the sell position
                    sell_orders = []
                    if hasattr(self.database, "get_position_orders"):
                        sell_orders = await self.database.get_position_orders(
                            sell_pos.id
                        )
                    # If any sell order is CANCELED and realized_quantity > 0, set PARTIALLY_SOLD
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
                                "[Recovery] Detected fully filled buy and partially filled/canceled sell for hp_id=%s: setting strategy_state to PARTIALLY_SOLD",
                                position.hp_id,
                            )
                            position.strategy_state = "PARTIALLY_SOLD"
                            break

        except Exception as e:
            logger.error(
                "[Recovery] Error in PARTIALLY_SOLD patch logic for hp_id=%s: %s",
                getattr(position, "hp_id", None),
                e,
            )

        await self.database.save_position(position)
        return position

    def _convert_to_state_info_state(
        self, status: PositionStatus, completeness: float, side: PositionSide
    ) -> State:
        """
        Convert database PositionStatus and side to the nested state_info.state for HPBuyData/HPSellData.
        This state should never be BUYING or SELLING, only terminal/summary states.
        Handles both buy and sell sides, and complex/edge states.
        For OPEN status, return BUYING/SELLING for the nested state to match the main strategy state.
        """
        # Handle fully filled (or completeness >= 1.0, even if status is PARTIALLY_FILLED)
        if completeness >= 1.0:
            logger.debug(
                "[Recovery] Mapping to state: completeness >= 1.0, status=%s, side=%s -> BOUGHT/SOLD",
                status,
                side,
            )
            return State.BOUGHT if side == PositionSide.LONG else State.SOLD
        # Handle fully filled by status (legacy safety)
        if status == PositionStatus.FILLED:
            logger.debug(
                "[Recovery] Mapping to state: status == FILLED, completeness=%s, side=%s -> BOUGHT/SOLD",
                completeness,
                side,
            )
            return State.BOUGHT if side == PositionSide.LONG else State.SOLD
        # Handle partially filled
        if status == PositionStatus.PARTIALLY_FILLED or (0.0 < completeness < 1.0):
            logger.debug(
                "[Recovery] Mapping to state: PARTIALLY_FILLED, status=%s, completeness=%s, side=%s",
                status,
                completeness,
                side,
            )
            if side == PositionSide.LONG:
                return State.PARTIALLY_BOUGHT
            elif side == PositionSide.SHORT:
                return State.PARTIALLY_SOLD
        # Handle open (orders sent, not filled)
        if status == PositionStatus.OPEN:
            logger.debug("[Recovery] Mapping to state: OPEN, side=%s", side)
            if side == PositionSide.LONG:
                return State.BUYING
            elif side == PositionSide.SHORT:
                return State.SELLING
        # New
        if status == PositionStatus.NEW:
            logger.debug("[Recovery] Mapping to state: NEW, side=%s", side)
            return State.NEW
        # Closed/canceled
        if status == PositionStatus.CANCELED or status == PositionStatus.CLOSED:
            logger.debug("[Recovery] Mapping to state: CANCELED/CLOSED, side=%s", side)
            return State.CLOSED
        # Waiting
        if (
            status == PositionStatus.WAITING_PARENT
            or status == PositionStatus.WAITING_CHILD
        ):
            logger.debug("[Recovery] Mapping to state: WAITING, side=%s", side)
            return State.WAITING_CHILD
        # Fallback
        logger.warning(
            "[Recovery] Mapping to state: FALLBACK to NEW, status=%s, completeness=%s, side=%s",
            status,
            completeness,
            side,
        )
        return State.NEW

    async def _convert_to_buy_data(self, position: Position) -> Optional[HPBuyData]:
        """Convert database Position to HPBuyData for the trading system."""
        try:
            symbol = self.symbols.get(position.symbol)
            if not symbol:
                logger.error("Symbol info not found for %s", position.symbol)
                return None

            # Ensure that if all buy orders are filled, completeness is correct
            if position.status == PositionStatus.FILLED and position.completeness < 1.0:
                position.completeness = 1.0

            # Always enforce: if completeness >= 1.0, buy state must be BOUGHT (never PARTIALLY_SOLD), regardless of any strategy state
            state_info_state = self._convert_to_state_info_state(
                position.status, position.completeness, PositionSide.LONG
            )

            # Special case: if database status is NEW but strategy_state is BUYING/SELLING,
            # it means orders were sent but no fills yet, so state should reflect the active trading state
            logger.debug(
                "[Recovery] Checking special case: status=%s, strategy_state=%s, condition=%s",
                position.status,
                position.strategy_state,
                (
                    position.status == PositionStatus.NEW
                    and position.strategy_state
                    and position.strategy_state in ["BUYING", "SELLING"]
                ),
            )
            if (
                position.status == PositionStatus.NEW
                and position.strategy_state
                and position.strategy_state in ["BUYING", "SELLING"]
            ):
                logger.info(
                    "[Recovery] Position status=NEW but strategy_state=%s, using strategy state for state_info",
                    position.strategy_state,
                )
                if position.strategy_state == "BUYING":
                    state_info_state = State.BUYING
                elif position.strategy_state == "SELLING":
                    state_info_state = State.SELLING

            if position.completeness >= 1.0:
                if state_info_state != State.BOUGHT:
                    logger.warning(
                        "[Recovery] For hp_id=%s, completeness=%.3f, forcibly setting buy state to BOUGHT (was %s)",
                        position.hp_id,
                        position.completeness,
                        state_info_state,
                    )
                # Explicitly set buy state to BOUGHT if all buy orders are filled
                state_info_state = State.BOUGHT
            else:
                # If for any reason the mapping returns PARTIALLY_SOLD for a buy, force to PARTIALLY_BOUGHT
                if state_info_state == State.PARTIALLY_SOLD:
                    logger.error(
                        "[Recovery] Invalid buy state PARTIALLY_SOLD detected for hp_id=%s, forcing to PARTIALLY_BOUGHT",
                        position.hp_id,
                    )
                    state_info_state = State.PARTIALLY_BOUGHT
                else:
                    logger.info(
                        "[Recovery] For hp_id=%s, completeness=%.3f, buy state mapped to %s",
                        position.hp_id,
                        position.completeness,
                        state_info_state,
                    )

            config = HPBuyConfig(
                symbol=symbol,
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
                state=state_info_state,
                open_time=position.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                side=PositionSide.LONG,
                completeness=position.completeness,
            )

            logger.debug(
                "[Recovery] Creating HPBuyData with state=%s for hp_id=%s",
                state_info_state,
                position.hp_id,
            )

            return HPBuyData(config=config, state_info=state_info)

        except Exception as e:
            logger.error(
                "Failed to convert position %s to buy data: %s", position.hp_id, e
            )
            return None

    async def _convert_to_sell_data(self, position: Position) -> Optional[HPSellData]:
        """Convert database Position to HPSellData for the trading system."""
        try:
            symbol = self.symbols.get(position.symbol)
            if not symbol:
                logger.error("Symbol info not found for %s", position.symbol)
                return None

            config = HPSellConfig(
                symbol=symbol,
                hp_id=position.hp_id,
                coin=position.coin,
                quantity=position.quantity,
                buy_price=position.buy_price,
                sell_price=position.sell_price,
                end_currency=position.end_currency,
                is_child=position.parent_position_id is not None,
                parent_hp_id=position.parent_position_id,
            )

            # Nested state_info.state (never BUYING/SELLING), pass side explicitly
            state_info_state = self._convert_to_state_info_state(
                position.status, position.completeness, PositionSide.SHORT
            )

            state_info = StateInfo(
                state=state_info_state,
                open_time=position.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                side=PositionSide.SHORT,
                completeness=position.completeness,
            )

            return HPSellData(config=config, state_info=state_info)

        except Exception as e:
            logger.error(
                "Failed to convert position %s to sell data: %s", position.hp_id, e
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
                    multihop_chains[root_hp_id].append(position)

            # Sort each chain by hop sequence
            for _, chain in multihop_chains.items():
                chain.sort(key=lambda p: p.hop_sequence)

            logger.info("Recovered %d multihop position chains", len(multihop_chains))
            return multihop_chains

        except Exception as e:
            raise RecoveryError(f"Failed to recover multihop positions: {e}") from e

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
                if position.symbol not in self.symbols:
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
            logger.error("Failed to validate recovery integrity: %s", e)
            return {"validation_error": str(e)}
