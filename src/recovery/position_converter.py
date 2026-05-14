"""
Position converter for transforming database models to trading system models.

Handles conversion between database Position objects and HPBuy/HPSell
data structures used by the trading system.
"""

import logging
from typing import Optional, Dict

from src.domain.enums import PositionSide, State
from src.domain.positions import HPBuy, HPBuyConfig, HPSell, HPSellConfig, StateInfo
from src.common.symbol import Symbol
from src.database.models import Position, PositionStatus, OrderStatus


logger = logging.getLogger(__name__)


class PositionConverter:
    """Converts database positions to trading system data structures."""

    def __init__(self, symbols: Dict[str, Symbol]):
        self.symbols = symbols

    def convert_to_state_info_state(
        self, status: PositionStatus, completeness: float, side: PositionSide
    ) -> State:
        """
        Convert database PositionStatus and side to state_info.state for HPBuy/HPSell.
        This state should reflect the actual order state (NEW, BUYING, PARTIALLY_BOUGHT, etc.).
        """
        # Handle fully filled
        if completeness >= 1.0 or status == PositionStatus.FILLED:
            return State.BOUGHT if side == PositionSide.LONG else State.SOLD

        # Handle partially filled
        if status == PositionStatus.PARTIALLY_FILLED or (0.0 < completeness < 1.0):
            return (
                State.PARTIALLY_BOUGHT
                if side == PositionSide.LONG
                else State.PARTIALLY_SOLD
            )

        # Handle open (orders sent, not filled)
        if status == PositionStatus.OPEN:
            return State.BUYING if side == PositionSide.LONG else State.SELLING

        # New
        if status == PositionStatus.NEW:
            return State.NEW

        # Closed/canceled
        if status in [PositionStatus.CANCELED, PositionStatus.CLOSED]:
            return State.CLOSED

        # Waiting
        if status in [PositionStatus.WAITING_PARENT, PositionStatus.WAITING_CHILD]:
            return State.WAITING_CHILD

        # Fallback
        logger.warning(
            "Mapping to state: FALLBACK to NEW, status=%s, completeness=%s, side=%s",
            status,
            completeness,
            side,
        )
        return State.NEW

    async def convert_to_buy_data(self, position: Position) -> Optional[HPBuy]:
        """Convert database Position to HPBuy for the trading system."""
        try:
            symbol = self.symbols.get(position.symbol)
            if not symbol:
                logger.error("Symbol info not found for %s", position.symbol)
                return None

            # Ensure that if all buy orders are filled, completeness is correct
            if position.status == PositionStatus.FILLED and position.completeness < 1.0:
                position.completeness = 1.0

            # Get base state from status and completeness
            state_info_state = self.convert_to_state_info_state(
                position.status, position.completeness, PositionSide.LONG
            )

            # Special case: if database status is NEW but strategy_state is BUYING/SELLING,
            # it means orders were sent but no fills yet
            if (
                position.status == PositionStatus.NEW
                and position.strategy_state
                and position.strategy_state in ["BUYING", "SELLING"]
            ):
                if position.strategy_state == "BUYING":
                    state_info_state = State.BUYING
                elif position.strategy_state == "SELLING":
                    state_info_state = State.SELLING

            # Enforce: if completeness >= 1.0, buy state must be BOUGHT
            if position.completeness >= 1.0:
                if state_info_state != State.BOUGHT:
                    logger.warning(
                        "For hp_id=%s, completeness=%.3f, forcibly setting buy state to BOUGHT (was %s)",
                        position.hp_id,
                        position.completeness,
                        state_info_state,
                    )
                state_info_state = State.BOUGHT
            else:
                # If for any reason the mapping returns PARTIALLY_SOLD for a buy, force to PARTIALLY_BOUGHT
                if state_info_state == State.PARTIALLY_SOLD:
                    logger.error(
                        "Invalid buy state PARTIALLY_SOLD detected for hp_id=%s, forcing to PARTIALLY_BOUGHT",
                        position.hp_id,
                    )
                    state_info_state = State.PARTIALLY_BOUGHT

            config = HPBuyConfig(
                symbol=symbol,
                coin=position.coin,
                hp_id=position.hp_id,
                buy_price=position.buy_price,
                order_trigger=position.order_trigger,
                budget=position.budget,
            )

            state_info = StateInfo(
                state=state_info_state,
                open_time=position.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                side=PositionSide.LONG,
                completeness=position.completeness,
            )

            return HPBuy(config=config, state_info=state_info)

        except Exception as e:
            logger.exception(
                "Failed to convert position %s to buy data: %s", position.hp_id, e
            )
            raise

    async def convert_to_sell_data(self, position: Position) -> Optional[HPSell]:
        """Convert database Position to HPSell for the trading system."""
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

            # Get state from status and completeness
            state_info_state = self.convert_to_state_info_state(
                position.status, position.completeness, PositionSide.SHORT
            )

            state_info = StateInfo(
                state=state_info_state,
                open_time=position.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                side=PositionSide.SHORT,
                completeness=position.completeness,
            )

            return HPSell(config=config, state_info=state_info)

        except Exception as e:
            logger.exception(
                "Failed to convert position %s to sell data: %s", position.hp_id, e
            )
            raise

    def convert_to_state(self, status: PositionStatus) -> State:
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

    def convert_exchange_status(self, exchange_status: str) -> OrderStatus:
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
