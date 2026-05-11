import asyncio
import logging
import pprint
from typing import List, Optional
from binance.enums import (
    TIME_IN_FORCE_GTC,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_NEW,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_CANCELED,
)
from binance.exceptions import (
    BinanceAPIException,
    BinanceOrderException,
    BinanceRequestException,
)


from src.database import Database
from src.common.client import BinanceClient
from src.domain.enums import Mode, State, UiState
from src.domain.orders import ExecutionReport, Order
from src.domain.positions import HPBuy


logger = logging.getLogger(__name__)


class HPPositionBuy:
    def __init__(
        self,
        client: BinanceClient,
        data: HPBuy,
        db: Database,
    ):
        self.client = client
        self.data = data
        self.db = db
        self.buy_order: Optional[Order] = None
        self.order_cancel_price: float = 0

    async def open_position(self) -> None:
        """Send a list of orders concurrently.

        Returns:
            A list of `Order` objects with updated order IDs and statuses.
        """
        if self.buy_order is None:
            raise RuntimeError("Buy order not prepared")
        self.order_cancel_price = self.calculate_trigger_cancel_order_price()
        logger.info(
            "Order cancel price set to: %s for position: %s",
            self.order_cancel_price,
            self.data.config.symbol.name,
        )
        logger.info("Order: %s", self.buy_order)
        if self.buy_order.status != ORDER_STATUS_FILLED:
            await self._create_order()

        logger.info(
            "New %s order send for %s at price: %s and quantity: %s [id: %s]",
            self.data.state_info.side.value,
            self.data.config.symbol.name,
            self.buy_order.price,
            self.buy_order.quantity_stable,
            self.buy_order.order_id,
        )

    async def cancel_position(self) -> None:
        if self.buy_order is None:
            raise RuntimeError("Buy order not prepared")
        logger.info(
            "Start canceling position: %s %s, hp id: %s",
            self.data.config.symbol.name,
            self.data.state_info.side,
            self.data.config.hp_id,
        )

        if (
            self.buy_order.status == ORDER_STATUS_PARTIALLY_FILLED
            and self.buy_order.order_id
        ):
            await self._cancel_order(
                order_id=self.buy_order.order_id, symbol=self.data.config.symbol.name
            )
            self.buy_order.status = ORDER_STATUS_CANCELED
            logger.info(
                "Cancelled partially filled order with id: %s", self.buy_order.order_id
            )
        elif self.buy_order.status == ORDER_STATUS_NEW and self.buy_order.order_id:
            await self._cancel_order(
                order_id=self.buy_order.order_id, symbol=self.data.config.symbol.name
            )
            self.buy_order.status = ORDER_STATUS_CANCELED
            logger.info("Cancelled new order with id: %s", self.buy_order.order_id)
        # No new Order object is created; status is updated in-place
        if self.buy_order.status == ORDER_STATUS_CANCELED:
            await self.db.upsert_order(
                order=self.buy_order,
                hp_id=self.data.config.hp_id,
                side=self.data.state_info.side,
            )

        # If order is canceled and has realized quantity, it was partially filled before cancel
        if (
            self.buy_order.status == ORDER_STATUS_CANCELED
            and self.buy_order.realized_quantity > 0
        ):
            self.data.state_info.state = State.PARTIALLY_BOUGHT
            logger.info(
                "Order canceled with partial fill (realized_quantity=%.5f): state remains PARTIALLY_BOUGHT",
                self.buy_order.realized_quantity,
            )
        # If order is canceled and has no realized quantity, it was never filled
        elif self.buy_order.status == ORDER_STATUS_CANCELED:
            self.data.state_info.state = State.NEW
            self.data.state_info.completeness = 0.0
            logger.info(
                "Order canceled with no fill: setting state to NEW and completeness to 0.0"
            )
        # If order is filled, set state to BOUGHT
        elif self.buy_order.status == ORDER_STATUS_FILLED:

            self.data.state_info.state = State.BOUGHT
            logger.info(
                "All buy orders filled: setting state to BOUGHT (completeness=%.4f)",
                self.data.state_info.completeness,
            )
        if self.buy_order.status == ORDER_STATUS_PARTIALLY_FILLED:
            self.data.state_info.state = State.PARTIALLY_BOUGHT
            logger.info(
                "Some buy orders filled or partially filled: setting state to PARTIALLY_BOUGHT (completeness=%.4f)",
                self.data.state_info.completeness,
            )
        self.data.state_info.get_completeness(order=self.buy_order)
        self.data.state_info.ui_state = UiState.STAGNATED

        await self.db.upsert_buy_price_level(data=self.data)

    async def handle_order_partially_filled(
        self, execution_report: ExecutionReport
    ) -> None:
        if self.buy_order is None:
            raise RuntimeError("Buy order not prepared")
        if execution_report.order_id == self.buy_order.order_id:
            self.buy_order.status = execution_report.current_order_status
            self.buy_order.realized_quantity = (
                execution_report.cumulative_filled_quantity
            )
            self.buy_order.quantity_stable -= (
                execution_report.last_executed_price
                * execution_report.last_executed_quantity
            )
            self.buy_order.price = execution_report.last_executed_price

            await self.db.upsert_order(
                order=self.buy_order,
                hp_id=self.data.config.hp_id,
                side=self.data.state_info.side,
            )
            logger.info("Order: %s partially filled", self.buy_order.order_id)

        self.data.state_info.get_completeness(self.buy_order)
        self.data.state_info.ui_state = UiState.OPEN

    async def handle_order_filled(self, execution_report: ExecutionReport) -> None:
        if self.buy_order is None:
            raise RuntimeError("Buy order not prepared")
        if execution_report.order_id == self.buy_order.order_id:
            self.buy_order.status = execution_report.current_order_status
            self.buy_order.price = execution_report.last_executed_price
            self.buy_order.realized_quantity = (
                execution_report.cumulative_filled_quantity
            )
            logger.info(
                "Order: %s filled, symbol: %s, price: %s, status: %s",
                self.buy_order.order_id,
                execution_report.symbol,
                self.buy_order.price,
                self.buy_order.status,
            )

            await self.db.upsert_order(
                order=self.buy_order,
                hp_id=self.data.config.hp_id,
                side=self.data.state_info.side,
            )

        self.data.state_info.ui_state = UiState.OPEN

        self.data.state_info.get_completeness(self.buy_order)
        logger.info("Completeness: %s", self.data.state_info.completeness)

    def prepare_order(self) -> None:
        config = self.data.config

        # buy_price should already be set in the config
        if config.buy_price <= 0:
            raise ValueError("buy_price must be set before calling prepare_order")

        order = Order(
            quantity=config.symbol.adjust_quantity(config.budget / config.buy_price),
            price=config.symbol.adjust_price(config.buy_price),
            quantity_stable=config.budget,
            precision=config.symbol.precision,
            price_precision=config.symbol.price_precision,
        )

        logger.info(
            "Buy orders prepared:\n%s\n for position: %s",
            pprint.pformat(order),
            config.symbol.name,
        )
        self.buy_order = order

    def calculate_trigger_cancel_order_price(self) -> float:
        if self.buy_order is None:
            raise RuntimeError("Buy order not prepared")
        if self.buy_order.status == ORDER_STATUS_FILLED:
            return 0.0
        return self.data.config.symbol.adjust_price(
            self.buy_order.price * (1 + (2 * self.data.config.order_trigger / 100))
        )

    def calculate_avg_buy_price(self) -> float:
        """
        Calculates the weighted average buy price based on realized quantities.

        Args:
            orders (List[Dict]): Each dict has 'price', 'realized_quantity', and 'total_quantity'

        Returns:
            float: Weighted average buy price or 0.0 if no realized quantity
        """
        if self.buy_order is None:
            raise RuntimeError("Buy order not prepared")
        total_realized_quantity = self.buy_order.realized_quantity
        total_cost = self.buy_order.realized_quantity * self.buy_order.price

        if total_realized_quantity == 0:
            return 0.0  # Avoid division by zero

        return self.data.config.symbol.adjust_price(
            total_cost / total_realized_quantity
        )

    def calculate_realized_quantity(self) -> float:
        """
        Calculates the weighted average buy price based on realized quantities.

        Args:
            orders (List[Dict]): Each dict has 'price', 'realized_quantity', and 'total_quantity'

        Returns:
            float: Weighted average buy price or 0.0 if no realized quantity
        """
        if self.buy_order is None:
            raise RuntimeError("Buy order not prepared")
        total_realized_quantity = self.buy_order.realized_quantity

        if total_realized_quantity == 0:
            return 0.0  # Avoid division by zero

        return self.data.config.symbol.adjust_quantity(total_realized_quantity)

    async def _create_order(self) -> Order:
        if self.buy_order is None:
            raise RuntimeError("Buy order not prepared")
        max_retries = 10
        last_exception = None
        for _ in range(max_retries):
            try:
                symbol = self.data.config.symbol
                price = symbol.format_price(self.buy_order.price)
                quantity = symbol.adjust_quantity(
                    self.buy_order.quantity - self.buy_order.realized_quantity
                )
                symbol.validate_order(price=float(price), quantity=quantity)
                resp = await self.client.create_order(
                    symbol=symbol.name,
                    price=price,
                    quantity=quantity,
                    side=self.data.state_info.side.value,
                    type=ORDER_TYPE_LIMIT,
                    timeInForce=TIME_IN_FORCE_GTC,
                )
            except (
                BinanceAPIException,
                BinanceOrderException,
                BinanceRequestException,
            ) as exception:
                last_exception = exception
                logger.error(
                    "Failed to create spot order: %s due to %s: %s",
                    self.buy_order,
                    type(exception).__name__,
                    exception,
                )
                await asyncio.sleep(1)  # wait for a second before retrying
                continue
            else:
                self.buy_order.order_id = int(resp["orderId"])
                # self.buy_order.price = resp["price"]
                self.buy_order.status = resp["status"]
                return self.buy_order

        if last_exception is None:
            raise RuntimeError("Retry loop exhausted without capturing an exception")
        raise last_exception

    async def _cancel_order(self, order_id: int, symbol: str) -> None:
        try:
            resp = await self.client.cancel_order(symbol=symbol, orderId=order_id)
            logger.info("Cancelled order %s: %s", order_id, resp)
        except (
            BinanceAPIException,
            BinanceOrderException,
            BinanceRequestException,
        ) as exception:
            logger.error(
                "Failed to cancel order due to %s: %s",
                type(exception).__name__,
                exception,
            )
            raise exception
