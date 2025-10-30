"""Direct sell strategy - Simple coin → stable sell.

Handles the straightforward sell scenario where the coin can be directly
sold to the target stable currency (e.g., BTC/USDC → sell BTC for USDC).
"""

import logging
import queue
from typing import TYPE_CHECKING

from binance.enums import (
    ORDER_STATUS_FILLED,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_TYPE_LIMIT,
    TIME_IN_FORCE_GTC,
)

from src.broker import BrokerSpot
from src.common.client import BinanceClient
from src.common.identifiers import (
    ExecutionReport,
    HPSellPositionCompleted,
    TickerUpdate,
)
from src.common.symbol import Symbol
from src.database import Database
from src.strategies.hp_manager_v2.sell_strategies.base import SellExecutionStrategy
from src.common.identifiers import (
    ExecutionReport,
    HPSellConfig,
    PositionLifecycleState,
)

if TYPE_CHECKING:
    from src.strategies.hp_manager_v2.position_buy_v2 import HPPositionBuyV2

logger = logging.getLogger("direct_sell")

# Hardcoded sell trigger constants (see SELL_STRATEGY_REFACTORING_DESIGN.md)
SELL_TRIGGER_PERCENTAGE = 0.96  # Send sell order when price drops to 96% of target
SELL_CANCEL_PERCENTAGE = 0.92  # Cancel sell order when price drops to 92% of target


class DirectSellStrategy(SellExecutionStrategy):
    """Simple direct sell: coin → stable (e.g., BTC/USDC).

    This is the most common sell scenario where the trading pair directly
    exists between the coin and target stable currency.

    Example: Selling BTC for USDC using BTC/USDC pair.
    """

    def __init__(
        self,
        client: BinanceClient,
        symbol: Symbol,
        coin: str,
        quantity: float,
        target_price: float,
        buy_price: float,
        db: Database,
        hp_id: str,
        worker_queue: queue.Queue,
        broker: BrokerSpot,
        buy_position: "HPPositionBuyV2",
    ):
        """Initialize direct sell strategy.

        Args:
            client: Binance API client
            symbol: Trading symbol (e.g., BTC/USDC)
            coin: Coin being sold (e.g., "BTC")
            quantity: Amount to sell
            target_price: Target sell price
            buy_price: Original buy price (for profit calculation)
            db: Database for persistence
            hp_id: High price position identifier
            worker_queue: Queue for portfolio events
            broker: Broker for order execution
            buy_position: Buy position data
        """
        super().__init__(
            client=client,
            symbol=symbol,
            coin=coin,
            quantity=quantity,
            target_price=target_price,
            db=db,
            hp_id=hp_id,
            worker_queue=worker_queue,
            buy_position=buy_position,
        )
        self.buy_price = buy_price
        self.broker = broker

    def should_send_sell(self, ticker_price: float) -> bool:
        """Send sell when price drops to 96% of target."""
        return ticker_price <= self.target_price * SELL_TRIGGER_PERCENTAGE

    def should_cancel_sell(self, ticker_price: float) -> bool:
        """Cancel sell when price drops below 92% of target."""
        return ticker_price <= self.target_price * SELL_CANCEL_PERCENTAGE

    async def execute_sell(self) -> None:
        """Send sell limit order to exchange."""
        logger.info(
            f"[{self.hp_id}] Executing direct sell: {self.quantity} {self.coin} "
            f"@ {self.target_price} on {self.symbol.name}"
        )

        # Adjust for symbol precision
        adjusted_quantity = self.symbol.adjust_quantity(self.quantity)
        adjusted_price = self.symbol.adjust_price(self.target_price)

        try:
            # Send sell order
            order_response = await self.client.create_order(
                symbol=self.symbol.name,
                side="SELL",
                order_type=ORDER_TYPE_LIMIT,
                time_in_force=TIME_IN_FORCE_GTC,
                quantity=adjusted_quantity,
                price=adjusted_price,
            )

            self.order_id = order_response.get("orderId")
            logger.info(f"[{self.hp_id}] Sell order placed: {self.order_id}")

            # Update database with SELLING state
            await self.db.upsert_buy_price_level(
                data=self.buy_position.data,
                strategy_state=PositionLifecycleState.SELLING,
            )

        except Exception as e:
            logger.error(f"[{self.hp_id}] Failed to execute sell: {e}")
            raise

    async def handle_execution_report(self, report: ExecutionReport) -> None:
        """Process fill reports and trigger portfolio events."""
        if report.order_id != self.order_id:
            return

        logger.info(f"[{self.hp_id}] Execution report: {report.current_order_status}")

        if report.current_order_status == ORDER_STATUS_PARTIALLY_FILLED:
            # Track partial fill
            fill_increment = report.last_executed_quantity
            self.filled_quantity = report.cumulative_filled_quantity

            logger.info(
                f"[{self.hp_id}] Partial fill: {fill_increment} "
                f"(total: {self.filled_quantity}/{self.quantity})"
            )

            # Update database (still SELLING)
            await self.db.upsert_buy_price_level(
                data=self.buy_position.data,
                strategy_state=PositionLifecycleState.SELLING,
            )

        elif report.current_order_status == ORDER_STATUS_FILLED:
            # Complete fill
            self.filled_quantity = report.cumulative_filled_quantity

            logger.info(
                f"[{self.hp_id}] Sell complete: {self.filled_quantity} {self.coin}"
            )

            # Get quote currency for the event
            quote_currency = self._get_quote_currency(self.symbol)

            # Trigger portfolio event
            self.worker_queue.put(
                HPSellPositionCompleted(
                    hp_id=self.hp_id,
                    coin=self.coin,
                    quantity_sold=self.filled_quantity,
                    buy_price=self.buy_price,
                    sell_price=self.target_price,
                    end_currency=quote_currency,
                )
            )

            # Update database to CLOSED
            await self.db.upsert_buy_price_level(
                data=self.buy_position.data,
                strategy_state=PositionLifecycleState.CLOSED,
            )

    async def handle_ticker_update(self, ticker: TickerUpdate) -> None:
        """Update tracked ticker price."""
        if ticker.symbol == self.symbol.name:
            self.ticker_price = ticker.last_price

    async def cancel_sell(self) -> None:
        """Cancel active sell order."""
        if not self.order_id:
            logger.warning(f"[{self.hp_id}] No order to cancel")
            return

        logger.info(f"[{self.hp_id}] Cancelling sell order: {self.order_id}")

        try:
            await self.client.cancel_order(
                symbol=self.symbol.name, order_id=self.order_id
            )

            # Update database back to BOUGHT
            await self.db.upsert_buy_price_level(
                data=self.buy_position.data,
                strategy_state=PositionLifecycleState.BOUGHT,
            )

            self.order_id = None

        except Exception as e:
            logger.error(f"[{self.hp_id}] Failed to cancel sell: {e}")
            raise

    def is_complete(self) -> bool:
        """Check if sell is fully complete."""
        return self.filled_quantity >= self.quantity

    def get_required_symbols(self) -> list[Symbol]:
        """Direct sell only needs one symbol."""
        return [self.symbol]
