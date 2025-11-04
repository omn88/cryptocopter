"""Multihop sell strategy - Two-hop routing for non-standard pairs.

Handles complex routing when neither direct nor convert paths work.
Example: Selling a coin that only has BTC pairs → coin/BTC, then BTC/USDC.

THIS STRATEGY WILL BE DELETED when EU exchange law changes and we can
use direct USDC pairs. For now, it's isolated here for easy removal.
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
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.strategies.hp_manager_v2.sell_strategies.base import SellExecutionStrategy
from src.common.identifiers import (
    ExecutionReport,
    HPSellConfig,
    PositionLifecycleState,
)

if TYPE_CHECKING:
    from src.strategies.hp_manager_v2.position_buy_v2 import HPPositionBuyV2

logger = logging.getLogger("multihop_sell")

# Hardcoded sell trigger constants
SELL_TRIGGER_PERCENTAGE = 0.96
SELL_CANCEL_PERCENTAGE = 0.92


class MultihopSellStrategy(SellExecutionStrategy):
    """Multihop sell: coin → intermediate → stable.

    Two-hop routing for coins that don't have direct stable pairs.

    Example:
    1. Sell ALTCOIN/BTC: ALTCOIN → BTC (leg1)
    2. Sell BTC/USDC: BTC → USDC (leg2)

    The first leg completes before the second leg starts (sequential execution).

    NOTE: This complexity exists due to EU exchange regulations. When direct
    USDC pairs become available, DELETE THIS ENTIRE FILE and remove from factory.
    """

    def __init__(
        self,
        client: BinanceClient,
        leg1_symbol: Symbol,
        leg2_symbol: Symbol,
        coin: str,
        quantity: float,
        target_price: float,
        buy_price: float,
        db: Database,
        hp_id: str,
        worker_queue: queue.Queue,
        broker: BrokerSpot,
        price_resolver: UsdPriceResolver,
        buy_position: "HPPositionBuyV2",
    ):
        """Initialize multihop sell strategy.

        Args:
            client: Binance API client
            leg1_symbol: First hop symbol (e.g., ALTCOIN/BTC)
            leg2_symbol: Second hop symbol (e.g., BTC/USDC)
            coin: Coin being sold (e.g., "ALTCOIN")
            quantity: Amount to sell
            target_price: Target sell price in final currency (USDC)
            buy_price: Original buy price
            db: Database for persistence
            hp_id: High price position identifier
            worker_queue: Queue for portfolio events
            broker: Broker for order execution
            price_resolver: Price resolver for cross-rate calculations
            buy_position: Buy position data
        """
        super().__init__(
            client=client,
            symbol=leg1_symbol,  # Primary symbol for base class
            coin=coin,
            quantity=quantity,
            target_price=target_price,
            db=db,
            hp_id=hp_id,
            worker_queue=worker_queue,
            buy_position=buy_position,
        )
        self.leg1_symbol = leg1_symbol
        self.leg2_symbol = leg2_symbol
        self.buy_price = buy_price
        self.broker = broker
        self.price_resolver = price_resolver

        # Track both legs
        self.leg1_order_id: int | None = None
        self.leg2_order_id: int | None = None
        self.leg1_filled_quantity: float = 0.0
        self.leg2_filled_quantity: float = 0.0
        self.intermediate_currency_received: float = 0.0

        # Ticker prices for both symbols
        self.leg1_ticker_price: float | None = None
        self.leg2_ticker_price: float | None = None

        # Calculate leg1 target price (convert USDC price to intermediate currency)
        self._calculate_leg1_price()

    def _calculate_leg1_price(self) -> None:
        """Calculate leg1 target price by converting from final USDC price."""
        # Get leg2 price (e.g., BTC/USDC price)
        leg2_price = self.price_resolver.latest_prices.get(self.leg2_symbol.name)
        if not leg2_price:
            logger.warning(
                f"[{self.hp_id}] Missing leg2 price for {self.leg2_symbol.name}, "
                f"using default calculation"
            )
            # Fallback: use target_price directly for leg1
            self.leg1_target_price = self.target_price
            return

        # Convert target USDC price to intermediate currency (BTC)
        # Example: if target is 50 USDC and BTC is 50000 USDC, leg1 target = 50/50000 = 0.001 BTC
        self.leg1_target_price = self.target_price / self.leg2_symbol.adjust_price(
            leg2_price
        )

        leg1_quote = self._get_quote_currency(self.leg1_symbol)
        logger.info(
            f"[{self.hp_id}] Calculated leg1 price: {self.leg1_target_price} "
            f"{leg1_quote} (leg2 price: {leg2_price})"
        )

    def should_send_sell(self, ticker_price: float) -> bool:
        """Send sell when leg1 price RISES to 96% of target (profit trigger)."""
        return ticker_price >= self.leg1_target_price * SELL_TRIGGER_PERCENTAGE

    def should_cancel_sell(self, ticker_price: float) -> bool:
        """Cancel sell when price drops below 92% of target (stop loss)."""
        return ticker_price <= self.leg1_target_price * SELL_CANCEL_PERCENTAGE

    async def execute_sell(self) -> None:
        """Execute first leg: sell coin to intermediate currency."""
        logger.info(
            f"[{self.hp_id}] Executing multihop leg1: {self.quantity} {self.coin} "
            f"@ {self.leg1_target_price} on {self.leg1_symbol.name}"
        )

        # Adjust for symbol precision
        adjusted_quantity = self.leg1_symbol.adjust_quantity(self.quantity)
        adjusted_price = self.leg1_symbol.adjust_price(self.leg1_target_price)

        try:
            # Send leg1 sell order
            order_response = await self.client.create_order(
                symbol=self.leg1_symbol.name,
                side="SELL",
                order_type=ORDER_TYPE_LIMIT,
                time_in_force=TIME_IN_FORCE_GTC,
                quantity=adjusted_quantity,
                price=adjusted_price,
            )

            self.leg1_order_id = order_response.get("orderId")
            logger.info(
                f"[{self.hp_id}] Multihop leg1 order placed: {self.leg1_order_id}"
            )

            # Update database to SELLING state
            await self.db.upsert_buy_price_level(
                data=self.buy_position.data,
                strategy_state=PositionLifecycleState.SELLING,
            )

        except Exception as e:
            logger.error(f"[{self.hp_id}] Failed to execute multihop leg1: {e}")
            raise

    async def _execute_leg2(self) -> None:
        """Execute second leg: sell intermediate currency to final stable."""
        leg1_quote = self._get_quote_currency(self.leg1_symbol)
        logger.info(
            f"[{self.hp_id}] Executing multihop leg2: {self.intermediate_currency_received} "
            f"{leg1_quote} on {self.leg2_symbol.name}"
        )

        # Use current market price for leg2
        if not self.leg2_ticker_price:
            logger.error(f"[{self.hp_id}] No ticker price for leg2")
            return

        leg2_price = self.leg2_ticker_price * SELL_TRIGGER_PERCENTAGE

        # Adjust for symbol precision
        adjusted_quantity = self.leg2_symbol.adjust_quantity(
            self.intermediate_currency_received
        )
        adjusted_price = self.leg2_symbol.adjust_price(leg2_price)

        try:
            # Send leg2 sell order
            order_response = await self.client.create_order(
                symbol=self.leg2_symbol.name,
                side="SELL",
                order_type=ORDER_TYPE_LIMIT,
                time_in_force=TIME_IN_FORCE_GTC,
                quantity=adjusted_quantity,
                price=adjusted_price,
            )

            self.leg2_order_id = order_response.get("orderId")
            logger.info(
                f"[{self.hp_id}] Multihop leg2 order placed: {self.leg2_order_id}"
            )

            # Update database (still SELLING for leg2)
            await self.db.upsert_buy_price_level(
                data=self.buy_position.data,
                strategy_state=PositionLifecycleState.SELLING,
            )

        except Exception as e:
            logger.error(f"[{self.hp_id}] Failed to execute multihop leg2: {e}")
            raise

    async def handle_execution_report(self, report: ExecutionReport) -> None:
        """Process fill reports for both legs."""
        # Leg 1: Sell coin to intermediate
        if report.order_id == self.leg1_order_id:
            await self._handle_leg1_report(report)

        # Leg 2: Sell intermediate to final stable
        elif report.order_id == self.leg2_order_id:
            await self._handle_leg2_report(report)

    async def _handle_leg1_report(self, report: ExecutionReport) -> None:
        """Handle execution reports for leg1."""
        logger.info(f"[{self.hp_id}] Leg1 execution: {report.current_order_status}")

        if report.current_order_status == ORDER_STATUS_PARTIALLY_FILLED:
            self.leg1_filled_quantity = report.cumulative_filled_quantity
            logger.info(
                f"[{self.hp_id}] Leg1 partial fill: "
                f"{self.leg1_filled_quantity}/{self.quantity}"
            )

        elif report.current_order_status == ORDER_STATUS_FILLED:
            self.leg1_filled_quantity = report.cumulative_filled_quantity
            self.intermediate_currency_received = (
                self.leg1_filled_quantity * report.last_executed_price
            )

            logger.info(
                f"[{self.hp_id}] Leg1 complete: received "
                f"{self.intermediate_currency_received} {self._get_quote_currency(self.leg1_symbol)}"
            )

            # Update leg1 to complete (still SELLING overall until leg2 completes)
            await self.db.upsert_buy_price_level(
                data=self.buy_position.data,
                strategy_state=PositionLifecycleState.SELLING,
            )

            # Trigger leg2
            await self._execute_leg2()

    async def _handle_leg2_report(self, report: ExecutionReport) -> None:
        """Handle execution reports for leg2."""
        logger.info(f"[{self.hp_id}] Leg2 execution: {report.current_order_status}")

        if report.current_order_status == ORDER_STATUS_PARTIALLY_FILLED:
            self.leg2_filled_quantity = report.cumulative_filled_quantity
            logger.info(
                f"[{self.hp_id}] Leg2 partial fill: "
                f"{self.leg2_filled_quantity}/{self.intermediate_currency_received}"
            )

        elif report.current_order_status == ORDER_STATUS_FILLED:
            self.leg2_filled_quantity = report.cumulative_filled_quantity

            leg2_quote = self._get_quote_currency(self.leg2_symbol)
            logger.info(
                f"[{self.hp_id}] Multihop sell complete: {self.coin} → " f"{leg2_quote}"
            )

            # Trigger portfolio event (entire multihop flow complete)
            self.worker_queue.put(
                HPSellPositionCompleted(
                    hp_id=self.hp_id,
                    coin=self.coin,
                    quantity_sold=self.leg1_filled_quantity,
                    buy_price=self.buy_price,
                    sell_price=self.target_price,
                    end_currency=self._get_quote_currency(self.leg2_symbol),
                )
            )

            # Update database to CLOSED (entire multihop complete)
            await self.db.upsert_buy_price_level(
                data=self.buy_position.data,
                strategy_state=PositionLifecycleState.CLOSED,
            )

    async def handle_ticker_update(self, ticker: TickerUpdate) -> None:
        """Update tracked ticker prices for both legs."""
        if ticker.symbol == self.leg1_symbol.name:
            self.leg1_ticker_price = ticker.last_price
        elif ticker.symbol == self.leg2_symbol.name:
            self.leg2_ticker_price = ticker.last_price

    async def cancel_sell(self) -> None:
        """Cancel active orders (both legs if needed)."""
        cancelled_any = False

        # Cancel leg1 if active
        if self.leg1_order_id:
            logger.info(f"[{self.hp_id}] Cancelling leg1 order: {self.leg1_order_id}")
            try:
                await self.client.cancel_order(
                    symbol=self.leg1_symbol.name, order_id=self.leg1_order_id
                )
                self.leg1_order_id = None
                cancelled_any = True
            except Exception as e:
                logger.error(f"[{self.hp_id}] Failed to cancel leg1: {e}")

        # Cancel leg2 if active
        if self.leg2_order_id:
            logger.info(f"[{self.hp_id}] Cancelling leg2 order: {self.leg2_order_id}")
            try:
                await self.client.cancel_order(
                    symbol=self.leg2_symbol.name, order_id=self.leg2_order_id
                )
                self.leg2_order_id = None
                cancelled_any = True
            except Exception as e:
                logger.error(f"[{self.hp_id}] Failed to cancel leg2: {e}")

        if cancelled_any:
            # Update position back to IDLE (4-state model: cancelled sell returns to IDLE)
            await self.db.upsert_buy_price_level(
                data=self.buy_position.data,
                strategy_state=PositionLifecycleState.IDLE,
            )

    def is_complete(self) -> bool:
        """Check if both legs complete."""
        leg1_complete = self.leg1_filled_quantity >= self.quantity
        leg2_complete = (
            self.leg2_filled_quantity >= self.intermediate_currency_received
            if self.intermediate_currency_received > 0
            else False
        )
        return leg1_complete and leg2_complete

    def is_partially_filled(self) -> bool:
        """Check if either leg has partial fills."""
        leg1_partial = self.leg1_filled_quantity > 0
        leg2_partial = self.leg2_filled_quantity > 0
        return (leg1_partial or leg2_partial) and not self.is_complete()

    def get_required_symbols(self) -> list[Symbol]:
        """Multihop needs both leg symbols."""
        return [self.leg1_symbol, self.leg2_symbol]
