import asyncio
import logging
import queue
from typing import List, Optional
from src.domain.constants import (
    TIME_IN_FORCE_GTC,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_NEW,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_CANCELED,
)
from src.broker import BrokerSpot
from src.common.symbol import Symbol

from src.database import Database
from src.common.client import KrakenClient
from src.domain.enums import (
    PositionSide,
    SellType,
    SubscriptionTarget,
    SubscriptionType,
    UiState,
)
from src.domain.orders import ExecutionReport, Order
from src.domain.positions import HPSellConfig, SellPosition, StateInfo
from src.domain.subscriptions import SubscriptionInfo
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.strategies.hp_manager.sell_strategies.base import BaseSellStrategy

logger = logging.getLogger(__name__)


class HPPositionSell:
    def __init__(
        self,
        client: KrakenClient,
        original_position: SellPosition,
        sell_strategy: Optional[BaseSellStrategy],
        db: Database,
        price_resolver: UsdPriceResolver,
        broker: BrokerSpot,
        worker_queue: queue.Queue,
        is_restoration: bool = False,
    ):
        self.client = client
        self.original_position = original_position
        self.db = db
        self.sell_strategy = sell_strategy
        self.broker = broker
        self.price_resolver = price_resolver
        self.worker_queue = worker_queue
        self.is_restoration = is_restoration

        self.sell_positions: List[SellPosition] = []
        self.current_position: SellPosition = SellPosition(
            Order(quantity=0),
            config=HPSellConfig(),
            state_info=StateInfo(side=PositionSide.SHORT),
            sell_type=SellType.DIRECT,
        )

        # Only initialize positions (and subscribe to tickers) if not restoration
        # This avoids waste of resources for historical positions
        if not self.is_restoration:
            self.initialize_positions()
        else:
            # For restoration, build positions but skip ticker subscriptions
            self._build_sell_positions()
            if self.sell_positions:
                self.current_position = self.sell_positions[0]
            else:
                # Fallback: use original position if no sell positions were built
                self.current_position = self.original_position

    def initialize_positions(self) -> None:
        """Initializes sell positions and sets the current active position."""

        self._build_sell_positions()

        if self.sell_positions:
            self.current_position = self.sell_positions[0]

        # Subscribe to tickers for price updates
        self._subscribe_to_tickers()

    def _subscribe_to_tickers(self) -> None:
        """Subscribe to ticker updates for price monitoring."""

        if len(self.sell_positions) == 2:
            for position in self.sell_positions:
                self.broker.subscribe(
                    system_id=self.original_position.config.hp_id,
                    subscription_info=SubscriptionInfo(
                        data_type=SubscriptionType.PRICE,
                        symbol=position.config.symbol.name,
                        target=SubscriptionTarget.BACKEND,
                        queue=self.worker_queue,
                    ),
                )
                self.broker.subscribe(
                    system_id=self.original_position.config.hp_id,
                    subscription_info=SubscriptionInfo(
                        data_type=SubscriptionType.USER,
                        symbol=position.config.symbol.name,
                        target=SubscriptionTarget.BACKEND,
                        queue=self.worker_queue,
                    ),
                )
        self.broker.subscribe(
            system_id=self.original_position.config.hp_id,
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol=self.original_position.config.symbol.name,
                target=SubscriptionTarget.BACKEND,
                queue=self.worker_queue,
            ),
        )

    def _build_sell_positions(self) -> None:
        """Build sell positions using the strategy object."""
        if not self.sell_strategy:
            self.sell_positions = []
            return

        self.sell_positions = self.sell_strategy.build_positions()

    async def open_position(self) -> None:
        """Send a list of orders concurrently.

        Args:
            client: A `KrakenClient` object.
            side: The side of the orders (either `PositionSide.BUY` or `PositionSide.SELL`).
            orders: A list of `Order` objects to send.

        Returns:
            A list of `Order` objects with updated order IDs and statuses.
        """
        try:
            if self.current_position.sell_order.status != ORDER_STATUS_FILLED:
                logger.info(
                    "Trying to send sell order: %s, side: %s, symbol info: %s",
                    self.current_position.sell_order,
                    self.current_position.state_info.side,
                    self.current_position.config.symbol,
                )

                self.current_position.sell_order = await self._create_order(
                    side=self.current_position.state_info.side,
                    order=self.current_position.sell_order,
                    symbol=self.current_position.config.symbol,
                )

                logger.info(
                    "New %s order send for %s at price: %s, quantity: %s and status: %s [id: %s]",
                    self.current_position.state_info.side.value,
                    self.current_position.config.symbol.name,
                    self.current_position.sell_order.price,
                    self.current_position.sell_order.quantity_stable,
                    self.current_position.sell_order.status,
                    self.current_position.sell_order.order_id,
                )
        except AssertionError as error:
            logger.error("Error: %s", error)

    async def recalculate_multihop_prices(self) -> None:
        """Recalculate leg prices using current market data before execution.

        Delegates to the strategy object which handles the recalculation logic.
        """
        if not self.sell_strategy:
            return

        await self.sell_strategy.recalculate_prices(self.sell_positions)

    async def cancel_position(self) -> None:
        if not isinstance(self.current_position, SellPosition):
            raise TypeError(
                f"Expected SellPosition, got {type(self.current_position).__name__}"
            )

        logger.info(
            "Start canceling position: %s %s, hp id: %s",
            self.current_position.config.symbol.name,
            self.current_position.state_info.side,
            self.current_position.config.hp_id,
        )

        await self.cancel_remaining_order()
        # if self.current_position.sell_order.status == ORDER_STATUS_CANCELED:
        await self.db.upsert_order(
            order=self.current_position.sell_order,
            hp_id=self.current_position.config.hp_id,
            side=self.current_position.state_info.side,
        )

        self.current_position.state_info.get_completeness(
            self.current_position.sell_order
        )
        self.current_position.state_info.ui_state = UiState.STAGNATED

        # self.db.upsert_sell_price_level(data=self.current_position)

    async def handle_order_partially_filled(
        self, execution_report: ExecutionReport
    ) -> None:
        if execution_report.order_id == self.current_position.sell_order.order_id:
            self.current_position.sell_order.status = (
                execution_report.current_order_status
            )
            self.current_position.sell_order.realized_quantity = (
                execution_report.cumulative_filled_quantity
            )
            self.current_position.sell_order.quantity_stable = (
                execution_report.last_executed_price
                * execution_report.last_executed_quantity
            )
            self.current_position.sell_order.price = (
                execution_report.last_executed_price
            )
            # Persist the updated sell order to the database
            await self.db.upsert_order(
                order=self.current_position.sell_order,
                hp_id=self.current_position.config.hp_id,
                side=self.current_position.state_info.side,
            )
            logger.info(
                "Order: %s partially filled", self.current_position.sell_order.order_id
            )
        self.current_position.state_info.get_completeness(
            self.current_position.sell_order
        )
        self.current_position.state_info.ui_state = UiState.OPEN

    async def handle_order_filled(self, execution_report: ExecutionReport) -> None:
        if execution_report.order_id == self.current_position.sell_order.order_id:
            self.current_position.sell_order.status = (
                execution_report.current_order_status
            )
            self.current_position.sell_order.price = (
                execution_report.last_executed_price
            )
            self.current_position.sell_order.realized_quantity = (
                execution_report.cumulative_filled_quantity
            )
            logger.info(
                "Order: %s filled, symbol: %s, price: %s, status: %s",
                self.current_position.sell_order.order_id,
                execution_report.symbol,
                self.current_position.sell_order.price,
                self.current_position.sell_order.status,
            )

            await self.db.upsert_order(
                order=self.current_position.sell_order,
                hp_id=self.current_position.config.hp_id,
                side=self.current_position.state_info.side,
            )
        self.current_position.state_info.ui_state = UiState.OPEN

        self.current_position.state_info.get_completeness(
            self.current_position.sell_order
        )

        logger.info("Completeness: %s", self.current_position.state_info.completeness)

    async def cancel_remaining_order(self) -> None:
        if (
            self.current_position.sell_order.status == ORDER_STATUS_PARTIALLY_FILLED
            and self.current_position.sell_order.order_id
        ):
            await self._cancel_order(
                order_id=self.current_position.sell_order.order_id,
                symbol=self.current_position.config.symbol.name,
            )
            self.current_position.sell_order.status = ORDER_STATUS_CANCELED

            logger.info(
                "Cancelled partially filled order with id: %s",
                self.current_position.sell_order.order_id,
            )
        elif (
            self.current_position.sell_order.status == ORDER_STATUS_NEW
            and self.current_position.sell_order.order_id
        ):
            await self._cancel_order(
                order_id=self.current_position.sell_order.order_id,
                symbol=self.current_position.config.symbol.name,
            )
            self.current_position.sell_order.status = ORDER_STATUS_CANCELED
            logger.info(
                "Cancelled new order with id: %s",
                self.current_position.sell_order.order_id,
            )

    async def _create_order(
        self, side: PositionSide, order: Order, symbol: Symbol
    ) -> Order:
        max_retries = 10
        last_exception = None
        for _ in range(max_retries):
            try:
                price = symbol.format_price(order.price)

                quantity = symbol.adjust_quantity(
                    order.quantity - order.realized_quantity
                )
                symbol.validate_order(price=float(price), quantity=quantity)

                logger.info("Before actual order sending(%s): %s", symbol.name, order)

                resp = await self.client.create_order(
                    symbol=symbol.name,
                    price=price,
                    quantity=quantity,
                    side=side.value,
                    type=ORDER_TYPE_LIMIT,
                    timeInForce=TIME_IN_FORCE_GTC,
                )
                logger.info("After sending(%s): %s", symbol.name, order)
                logger.info("Response: %s", resp)
            except Exception as exception:
                # kraken.exceptions exposes ~50 flat error classes with no shared
                # base, plus network failures surface as requests exceptions;
                # retry on any of them the same way the old Binance tuple did.
                last_exception = exception
                logger.error(
                    "Failed to create spot order: %s due to %s: %s",
                    order,
                    type(exception).__name__,
                    exception,
                )
                await asyncio.sleep(1)  # wait for a second before retrying
                continue
            else:
                order.order_id = str(resp["orderId"])
                # order.price = resp["price"]
                order.status = resp["status"]

                return order

        if last_exception is None:
            raise RuntimeError("Retry loop exhausted without capturing an exception")
        raise last_exception

    async def _cancel_order(self, order_id: str, symbol: str) -> None:
        try:
            resp = await self.client.cancel_order(symbol=symbol, orderId=order_id)
            logger.info("Cancelled order %s: %s", order_id, resp)
        except Exception as exception:
            logger.error(
                "Failed to cancel order due to %s: %s",
                type(exception).__name__,
                exception,
            )
            raise exception
