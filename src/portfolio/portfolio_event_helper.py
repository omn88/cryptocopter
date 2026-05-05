"""
Portfolio Event Helper Module

Centralizes all portfolio event creation and sending logic for:
- Buy position creation, completion, and cancellation
- Sell position creation, completion, and cancellation

This reduces code duplication and keeps event handling consistent across the application.
"""

import logging
from decimal import Decimal
from typing import Callable, Optional, Any
from src.domain.enums import EventName, State
from src.domain.events import (
    HPBuyOrdersPlaced,
    HPBuyPositionCreated,
    HPBuyPositionFilled,
    HPBuyPositionPartiallyFilled,
    HPPositionCancelled,
    HPSellPositionCompleted,
    HPSellPositionCreated,
    HPSellPositionPartiallyFilled,
)
from src.gui.identifiers import HPClose

logger = logging.getLogger(__name__)


class PortfolioEventHelper:
    """Helper class for sending portfolio events."""

    def __init__(
        self,
        portfolio_event_callback: Optional[Callable[[EventName, Any], None]] = None,
    ) -> None:
        """Initialize the portfolio event helper with a callback function.

        Args:
            portfolio_event_callback: Optional callback function to send portfolio events.
                                     Takes event_name and event_data as parameters.
        """
        self._callback = portfolio_event_callback

    def _send_portfolio_event(self, event_name: EventName, event_data: Any) -> None:
        """Send HP events to portfolio via callback.

        Args:
            event_name: The name/type of the event to send.
            event_data: The event data payload.

        Raises:
            RuntimeError: If callback fails to process the event.
        """
        if self._callback:
            try:
                self._callback(event_name, event_data)
            except (TypeError, ValueError, AttributeError) as exc:
                # Catch specific exceptions related to invalid event data or callback issues
                logger.error(
                    "Failed to send portfolio event %s: %s",
                    event_name,
                    exc,
                    exc_info=True,
                )
                raise RuntimeError(
                    f"Portfolio event {event_name} delivery failed"
                ) from exc
            except Exception:
                # Unexpected exceptions - log with full traceback and re-raise
                logger.exception(
                    "Unexpected error sending portfolio event %s", event_name
                )
                raise

    def send_buy_creation_event(
        self,
        hp_id: str,
        coin: str,
        budget: Decimal,
        buy_price: Decimal,
    ) -> None:
        """Send HP buy position created event to portfolio."""
        hp_buy_created = HPBuyPositionCreated(
            hp_id=hp_id,
            coin=coin,
            budget=float(budget),
            buy_price=float(buy_price),
            end_currency="USDC",
        )
        self._send_portfolio_event(EventName.HP_BUY_POSITION_CREATED, hp_buy_created)
        logger.info("Sent HP buy creation event for position: %s", hp_id)

    def send_buy_orders_placed_event(
        self,
        hp_id: str,
        coin: str,
        budget_amount: Decimal,
        end_currency: str = "USDC",
    ) -> None:
        """Send HP buy orders placed event to portfolio."""
        hp_orders_placed = HPBuyOrdersPlaced(
            hp_id=hp_id,
            coin=coin,
            budget_amount=float(budget_amount),
            end_currency=end_currency,
        )
        self._send_portfolio_event(EventName.HP_BUY_ORDERS_PLACED, hp_orders_placed)
        logger.info(
            "Sent HP buy orders placed event to lock %s %s budget for position %s",
            budget_amount,
            end_currency,
            hp_id,
        )

    def send_buy_position_filled_event(
        self,
        hp_id: str,
        coin: str,
        symbol: str,
        quantity_bought: Decimal,
        buy_price: Decimal,
        total_cost: Decimal,
    ) -> None:
        """Send HP buy position filled event to portfolio."""
        hp_buy_filled = HPBuyPositionFilled(
            hp_id=hp_id,
            coin=coin,
            symbol=symbol,
            quantity_bought=float(quantity_bought),
            buy_price=float(buy_price),
            total_cost=float(total_cost),
        )
        self._send_portfolio_event(EventName.HP_BUY_POSITION_FILLED, hp_buy_filled)
        logger.info("Sent HP buy position filled event for position: %s", hp_id)

    def send_buy_position_partially_filled_event(
        self,
        hp_id: str,
        coin: str,
        filled_quantity: float,
        total_filled: float,
        buy_price: float,
        partial_cost: float,
    ) -> None:
        """Send HP buy position partially filled event to portfolio."""
        hp_buy_partial = HPBuyPositionPartiallyFilled(
            hp_id=hp_id,
            coin=coin,
            filled_quantity=filled_quantity,
            total_filled=total_filled,
            buy_price=buy_price,
            partial_cost=partial_cost,
        )
        self._send_portfolio_event(
            EventName.HP_BUY_POSITION_PARTIALLY_FILLED, hp_buy_partial
        )
        logger.info(
            "Sent HP buy position partially filled event for position: %s", hp_id
        )

    def send_sell_creation_event(
        self,
        hp_id: str,
        coin: str,
        quantity: Decimal,
        buy_price: Decimal,
        sell_price: Decimal,
        end_currency: str,
    ) -> None:
        """Send HP sell position created event to portfolio."""
        hp_sell_created = HPSellPositionCreated(
            hp_id=hp_id,
            coin=coin,
            quantity=float(quantity),
            buy_price=float(buy_price),
            sell_price=float(sell_price),
            end_currency=end_currency,
        )
        self._send_portfolio_event(EventName.HP_SELL_POSITION_CREATED, hp_sell_created)
        logger.info(
            "Sent HP_SELL_POSITION_CREATED event for position %s to lock %s %s",
            hp_id,
            quantity,
            coin,
        )

    def send_sell_completion_event(
        self,
        hp_id: str,
        coin: str,
        quantity_sold: Decimal,
        buy_price: Decimal,
        sell_price: Decimal,
        end_currency: str,
    ) -> None:
        """Send HP sell position completed event to portfolio."""
        hp_completed = HPSellPositionCompleted(
            hp_id=hp_id,
            coin=coin,
            quantity_sold=float(quantity_sold),
            buy_price=float(buy_price),
            sell_price=float(sell_price),
            end_currency=end_currency,
        )
        self._send_portfolio_event(EventName.HP_SELL_POSITION_COMPLETED, hp_completed)
        logger.info("Sent HP sell completion event for position: %s", hp_id)

    def send_sell_position_partially_filled_event(
        self,
        hp_id: str,
        coin: str,
        filled_quantity: float,
        total_filled: float,
    ) -> None:
        """Send HP sell position partially filled event to portfolio."""
        hp_sell_partial = HPSellPositionPartiallyFilled(
            hp_id=hp_id,
            coin=coin,
            filled_quantity=filled_quantity,
            total_filled=total_filled,
        )
        self._send_portfolio_event(
            EventName.HP_SELL_POSITION_PARTIALLY_FILLED, hp_sell_partial
        )
        logger.info(
            "Sent HP sell position partially filled event for position: %s", hp_id
        )

    def send_cancellation_event(
        self,
        hp_id: str,
        coin: str,
        quantity: Decimal,
        position_type: str,
    ) -> None:
        """Send HP position cancelled event to portfolio."""
        hp_cancelled = HPPositionCancelled(
            hp_id=hp_id,
            coin=coin,
            quantity=float(quantity),
            position_type=position_type,
        )
        self._send_portfolio_event(EventName.HP_POSITION_CANCELLED, hp_cancelled)
        logger.info(
            "Sent manual HP cancellation event for %s position: %s",
            position_type,
            hp_id,
        )

    def handle_sell_completion(self, close_data: HPClose) -> None:
        """Handle successful sell position completion event."""
        self.send_sell_completion_event(
            hp_id=close_data.config.hp_id,
            coin=close_data.config.coin,
            quantity_sold=close_data.config.quantity,
            buy_price=close_data.config.buy_price,
            sell_price=close_data.config.sell_price,
            end_currency=close_data.config.end_currency,
        )

    def handle_sell_cancellation(
        self, close_data: HPClose, sell_quantity: Decimal
    ) -> None:
        """Handle sell position cancellation event.

        Args:
            close_data: The close data containing position information.
            sell_quantity: The quantity of the sell order to be cancelled.
        """
        self.send_cancellation_event(
            hp_id=close_data.config.hp_id,
            coin=close_data.config.coin,
            quantity=sell_quantity,
            position_type="SELL",
        )

    def handle_buy_cancellation(
        self, close_data: HPClose, current_state: State, remaining_budget: Decimal
    ) -> None:
        """Handle buy position cancellation event.

        Args:
            close_data: The close data containing position information.
            current_state: The current state of the strategy.
            remaining_budget: The remaining budget amount to be unlocked.
        """
        if current_state != State.NEW:
            self.send_cancellation_event(
                hp_id=close_data.config.hp_id,
                coin="USDC",
                quantity=remaining_budget,
                position_type="BUY",
            )
        else:
            logger.info(
                "Skipped budget unlock for buy position %s - orders never sent to exchange",
                close_data.config.hp_id,
            )
