"""
Portfolio Event Helper Module

Centralizes all portfolio event creation and sending logic for:
- Buy position creation, completion, and cancellation
- Sell position creation, completion, and cancellation

This reduces code duplication and keeps event handling consistent across the application.
"""

import logging
from src.common.identifiers import (
    EventName,
    HPBuyPositionCreated,
    HPSellPositionCreated,
    HPSellPositionCompleted,
    HPPositionCancelled,
    State,
)
from src.gui.identifiers import HPClose
from src.strategies.hp_manager.hp_manager import HpStrategy

logger = logging.getLogger(__name__)


class PortfolioEventHelper:
    """Helper class for sending portfolio events."""

    @staticmethod
    def send_buy_creation_event(
        strategy: HpStrategy,
        hp_id: str,
        coin: str,
        budget: float,
        price_low: float,
        price_high: float,
    ) -> None:
        """Send HP buy position created event to portfolio."""
        hp_buy_created = HPBuyPositionCreated(
            hp_id=hp_id,
            coin=coin,
            budget=budget,
            price_low=price_low,
            price_high=price_high,
            end_currency="USDC",
        )
        strategy._send_portfolio_event(
            EventName.HP_BUY_POSITION_CREATED, hp_buy_created
        )
        logger.info("Sent HP buy creation event for position: %s", hp_id)

    @staticmethod
    def send_sell_creation_event(
        strategy: HpStrategy,
        hp_id: str,
        coin: str,
        quantity: float,
        buy_price: float,
        sell_price: float,
        end_currency: str,
    ) -> None:
        """Send HP sell position created event to portfolio."""
        hp_sell_created = HPSellPositionCreated(
            hp_id=hp_id,
            coin=coin,
            quantity=quantity,
            buy_price=buy_price,
            sell_price=sell_price,
            end_currency=end_currency,
        )
        strategy._send_portfolio_event(
            EventName.HP_SELL_POSITION_CREATED, hp_sell_created
        )
        logger.info(
            "Sent HP_SELL_POSITION_CREATED event for position %s to lock %s %s",
            hp_id,
            quantity,
            coin,
        )

    @staticmethod
    def send_sell_completion_event(
        strategy: HpStrategy,
        hp_id: str,
        coin: str,
        quantity_sold: float,
        buy_price: float,
        sell_price: float,
        end_currency: str,
    ) -> None:
        """Send HP sell position completed event to portfolio."""
        hp_completed = HPSellPositionCompleted(
            hp_id=hp_id,
            coin=coin,
            quantity_sold=quantity_sold,
            buy_price=buy_price,
            sell_price=sell_price,
            end_currency=end_currency,
        )
        strategy._send_portfolio_event(
            EventName.HP_SELL_POSITION_COMPLETED, hp_completed
        )
        logger.info("Sent HP sell completion event for position: %s", hp_id)

    @staticmethod
    def send_cancellation_event(
        strategy: HpStrategy,
        hp_id: str,
        coin: str,
        quantity: float,
        position_type: str,
    ) -> None:
        """Send HP position cancelled event to portfolio."""
        hp_cancelled = HPPositionCancelled(
            hp_id=hp_id,
            coin=coin,
            quantity=quantity,
            position_type=position_type,
        )
        strategy._send_portfolio_event(EventName.HP_POSITION_CANCELLED, hp_cancelled)
        logger.info(
            "Sent manual HP cancellation event for %s position: %s",
            position_type,
            hp_id,
        )

    @staticmethod
    def handle_sell_completion(strategy: HpStrategy, close_data: HPClose) -> None:
        """Handle successful sell position completion event."""
        PortfolioEventHelper.send_sell_completion_event(
            strategy=strategy,
            hp_id=close_data.config.hp_id,
            coin=close_data.config.coin,
            quantity_sold=close_data.config.quantity,
            buy_price=close_data.config.buy_price,
            sell_price=close_data.config.sell_price,
            end_currency=close_data.config.end_currency,
        )

    @staticmethod
    def handle_sell_cancellation(strategy: HpStrategy, close_data: HPClose) -> None:
        """Handle sell position cancellation event."""
        PortfolioEventHelper.send_cancellation_event(
            strategy=strategy,
            hp_id=close_data.config.hp_id,
            coin=close_data.config.coin,
            quantity=strategy.sell.current_position.sell_order.quantity,
            position_type="SELL",
        )

    @staticmethod
    def handle_buy_cancellation(strategy: HpStrategy, close_data: HPClose) -> None:
        """Handle buy position cancellation event."""
        if strategy.state != State.NEW:
            budget_amount = strategy.get_remaining_quantity_buy()
            PortfolioEventHelper.send_cancellation_event(
                strategy=strategy,
                hp_id=close_data.config.hp_id,
                coin="USDC",
                quantity=budget_amount,
                position_type="BUY",
            )
        else:
            logger.info(
                "Skipped budget unlock for buy position %s - orders never sent to exchange",
                close_data.config.hp_id,
            )
