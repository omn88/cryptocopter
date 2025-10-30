"""Convert sell strategy - Sell via stable conversion.

Handles the scenario where we need to convert to a different stable currency
before selling. Example: BTC/USDT → sell to USDT, then USDT/USDC → convert to USDC.

This happens when the direct pair (BTC/USDC) doesn't exist or has poor liquidity.
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

logger = logging.getLogger("convert_sell")

# Hardcoded sell trigger constants
SELL_TRIGGER_PERCENTAGE = 0.96
SELL_CANCEL_PERCENTAGE = 0.92
CONVERT_MAX_SPREAD = 0.01  # Max 1% spread for convert orders


class ConvertSellStrategy(SellExecutionStrategy):
    """Convert sell: coin → stable1, then stable1 → stable2.

    Two-phase sell when we need to convert between stable currencies.

    Example:
    1. Sell BTC/USDT: BTC → USDT (sell phase)
    2. Convert USDT/USDC: USDT → USDC (convert phase)

    The convert phase uses tighter spread limits since it's stable→stable.
    """

    def __init__(
        self,
        client: BinanceClient,
        sell_symbol: Symbol,
        convert_symbol: Symbol,
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
        """Initialize convert sell strategy.

        Args:
            client: Binance API client
            sell_symbol: First trade symbol (e.g., BTC/USDT)
            convert_symbol: Second trade symbol (e.g., USDT/USDC)
            coin: Coin being sold (e.g., "BTC")
            quantity: Amount to sell
            target_price: Target sell price in final currency
            buy_price: Original buy price
            db: Database for persistence
            hp_id: High price position identifier
            worker_queue: Queue for portfolio events
            broker: Broker for order execution
            buy_position: Buy position data
        """
        super().__init__(
            client=client,
            symbol=sell_symbol,  # Primary symbol for base class
            coin=coin,
            quantity=quantity,
            target_price=target_price,
            db=db,
            hp_id=hp_id,
            worker_queue=worker_queue,
            buy_position=buy_position,
        )
        self.sell_symbol = sell_symbol
        self.convert_symbol = convert_symbol
        self.buy_price = buy_price
        self.broker = broker

        # Track both phases
        self.sell_order_id: int | None = None
        self.convert_order_id: int | None = None
        self.sell_filled_quantity: float = 0.0
        self.convert_filled_quantity: float = 0.0
        self.intermediate_currency_received: float = 0.0

        # Ticker prices for both symbols
        self.sell_ticker_price: float | None = None
        self.convert_ticker_price: float | None = None

    def should_send_sell(self, ticker_price: float) -> bool:
        """Send sell when sell phase price drops to 96% of target."""
        return ticker_price <= self.target_price * SELL_TRIGGER_PERCENTAGE

    def should_cancel_sell(self, ticker_price: float) -> bool:
        """Cancel sell when price drops below 92% of target."""
        return ticker_price <= self.target_price * SELL_CANCEL_PERCENTAGE

    async def execute_sell(self) -> None:
        """Execute first phase: sell coin to intermediate stable."""
        logger.info(
            f"[{self.hp_id}] Executing convert sell phase 1: {self.quantity} {self.coin} "
            f"@ {self.target_price} on {self.sell_symbol.name}"
        )

        # Adjust for symbol precision
        adjusted_quantity = self.sell_symbol.adjust_quantity(self.quantity)
        adjusted_price = self.sell_symbol.adjust_price(self.target_price)

        try:
            # Send sell order (phase 1)
            order_response = await self.client.create_order(
                symbol=self.sell_symbol.name,
                side="SELL",
                order_type=ORDER_TYPE_LIMIT,
                time_in_force=TIME_IN_FORCE_GTC,
                quantity=adjusted_quantity,
                price=adjusted_price,
            )

            self.sell_order_id = order_response.get("orderId")
            logger.info(
                f"[{self.hp_id}] Convert sell phase 1 order placed: {self.sell_order_id}"
            )

            # Update database to SELLING
            await self.db.upsert_buy_price_level(
                data=self.buy_position.data,
                strategy_state=PositionLifecycleState.SELLING,
            )

        except Exception as e:
            logger.error(f"[{self.hp_id}] Failed to execute sell phase 1: {e}")
            raise

    async def _execute_convert_phase(self) -> None:
        """Execute second phase: convert intermediate stable to target stable."""
        sell_quote = self._get_quote_currency(self.sell_symbol)
        convert_quote = self._get_quote_currency(self.convert_symbol)

        logger.info(
            f"[{self.hp_id}] Executing convert sell phase 2: convert "
            f"{self.intermediate_currency_received} {sell_quote} "
            f"to {convert_quote}"
        )

        # Use market price with small spread for convert
        if not self.convert_ticker_price:
            logger.error(f"[{self.hp_id}] No ticker price for convert phase")
            return

        # Convert orders use tight spread (stable→stable should be 1:1 ish)
        convert_price = self.convert_ticker_price * (1 - CONVERT_MAX_SPREAD)

        # Adjust for symbol precision
        adjusted_quantity = self.convert_symbol.adjust_quantity(
            self.intermediate_currency_received
        )
        adjusted_price = self.convert_symbol.adjust_price(convert_price)

        try:
            # Send convert order (phase 2)
            order_response = await self.client.create_order(
                symbol=self.convert_symbol.name,
                side="SELL",
                order_type=ORDER_TYPE_LIMIT,
                time_in_force=TIME_IN_FORCE_GTC,
                quantity=adjusted_quantity,
                price=adjusted_price,
            )

            self.convert_order_id = order_response.get("orderId")
            logger.info(
                f"[{self.hp_id}] Convert sell phase 2 order placed: {self.convert_order_id}"
            )

        except Exception as e:
            logger.error(f"[{self.hp_id}] Failed to execute convert phase 2: {e}")
            raise

    async def handle_execution_report(self, report: ExecutionReport) -> None:
        """Process fill reports for both sell and convert phases."""
        # Phase 1: Sell coin to intermediate stable
        if report.order_id == self.sell_order_id:
            await self._handle_sell_phase_report(report)

        # Phase 2: Convert intermediate to target stable
        elif report.order_id == self.convert_order_id:
            await self._handle_convert_phase_report(report)

    async def _handle_sell_phase_report(self, report: ExecutionReport) -> None:
        """Handle execution reports for sell phase."""
        logger.info(
            f"[{self.hp_id}] Sell phase execution: {report.current_order_status}"
        )

        if report.current_order_status == ORDER_STATUS_PARTIALLY_FILLED:
            self.sell_filled_quantity = report.cumulative_filled_quantity
            logger.info(
                f"[{self.hp_id}] Sell phase partial fill: "
                f"{self.sell_filled_quantity}/{self.quantity}"
            )

        elif report.current_order_status == ORDER_STATUS_FILLED:
            self.sell_filled_quantity = report.cumulative_filled_quantity
            self.intermediate_currency_received = (
                self.sell_filled_quantity * report.last_executed_price
            )

            sell_quote = self._get_quote_currency(self.sell_symbol)
            logger.info(
                f"[{self.hp_id}] Sell phase complete: received "
                f"{self.intermediate_currency_received} {sell_quote}"
            )

            # Trigger phase 2: convert
            await self._execute_convert_phase()

    async def _handle_convert_phase_report(self, report: ExecutionReport) -> None:
        """Handle execution reports for convert phase."""
        logger.info(
            f"[{self.hp_id}] Convert phase execution: {report.current_order_status}"
        )

        if report.current_order_status == ORDER_STATUS_PARTIALLY_FILLED:
            self.convert_filled_quantity = report.cumulative_filled_quantity
            logger.info(
                f"[{self.hp_id}] Convert phase partial fill: "
                f"{self.convert_filled_quantity}/{self.intermediate_currency_received}"
            )

        elif report.current_order_status == ORDER_STATUS_FILLED:
            self.convert_filled_quantity = report.cumulative_filled_quantity

            convert_quote = self._get_quote_currency(self.convert_symbol)
            logger.info(
                f"[{self.hp_id}] Convert sell complete: {self.coin} → "
                f"{convert_quote}"
            )

            # Get quote currency for final convert symbol
            end_currency = self._get_quote_currency(self.convert_symbol)

            # Trigger portfolio event (entire sell flow complete)
            self.worker_queue.put(
                HPSellPositionCompleted(
                    hp_id=self.hp_id,
                    coin=self.coin,
                    quantity_sold=self.sell_filled_quantity,
                    buy_price=self.buy_price,
                    sell_price=self.target_price,
                    end_currency=end_currency,
                )
            )

            # Update database to CLOSED
            await self.db.upsert_buy_price_level(
                data=self.buy_position.data,
                strategy_state=PositionLifecycleState.CLOSED,
            )

    async def handle_ticker_update(self, ticker: TickerUpdate) -> None:
        """Update tracked ticker prices for both symbols."""
        if ticker.symbol == self.sell_symbol.name:
            self.sell_ticker_price = ticker.last_price
        elif ticker.symbol == self.convert_symbol.name:
            self.convert_ticker_price = ticker.last_price

    async def cancel_sell(self) -> None:
        """Cancel active orders (both phases if needed)."""
        cancelled_any = False

        # Cancel sell phase if active
        if self.sell_order_id:
            logger.info(
                f"[{self.hp_id}] Cancelling sell phase order: {self.sell_order_id}"
            )
            try:
                await self.client.cancel_order(
                    symbol=self.sell_symbol.name, order_id=self.sell_order_id
                )
                self.sell_order_id = None
                cancelled_any = True
            except Exception as e:
                logger.error(f"[{self.hp_id}] Failed to cancel sell phase: {e}")

        # Cancel convert phase if active
        if self.convert_order_id:
            logger.info(
                f"[{self.hp_id}] Cancelling convert phase order: {self.convert_order_id}"
            )
            try:
                await self.client.cancel_order(
                    symbol=self.convert_symbol.name, order_id=self.convert_order_id
                )
                self.convert_order_id = None
                cancelled_any = True
            except Exception as e:
                logger.error(f"[{self.hp_id}] Failed to cancel convert phase: {e}")

        if cancelled_any:
            # Update database back to BOUGHT
            await self.db.upsert_buy_price_level(
                data=self.buy_position.data,
                strategy_state=PositionLifecycleState.BOUGHT,
            )

    def is_complete(self) -> bool:
        """Check if both phases complete."""
        sell_complete = self.sell_filled_quantity >= self.quantity
        convert_complete = (
            self.convert_filled_quantity >= self.intermediate_currency_received
            if self.intermediate_currency_received > 0
            else False
        )
        return sell_complete and convert_complete

    def get_required_symbols(self) -> list[Symbol]:
        """Convert sell needs both symbols."""
        return [self.sell_symbol, self.convert_symbol]
