import asyncio
import logging
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

from logging_config import StrategyLogger
from src.identifiers.common import BinanceClient, PositionSide
from src.common.symbol_info import SymbolInfo

from src.database import Database
from src.identifiers.spot import (
    ExecutionReport,
    HPSellData,
    Order,
    UiState,
)


logger = logging.getLogger("pos_handler")


class HPPositionSell:
    def __init__(
        self,
        client: BinanceClient,
        strategy_logger: StrategyLogger,
        data: HPSellData,
        db: Database,
    ):
        self.client = client
        self.data = data
        self.strategy_logger = strategy_logger
        self.db = db
        self.sell_order: Order = Order(quantity=0, precision=0, price_precision=0)

    def prepare_sell_order(self, buy_realized_quantity: float) -> None:
        config = self.data.config
        quantity = buy_realized_quantity - self.sell_order.realized_quantity
        quantity_stable = round(quantity * config.sell_price, 2)

        self.sell_order = Order(
            quantity=config.symbol_info.adjust_quantity(quantity),
            price=config.symbol_info.adjust_price(config.sell_price),
            quantity_stable=quantity_stable,
            precision=config.symbol_info.precision,
            price_precision=config.symbol_info.price_precision,
        )

        logger.info(
            "Sell order prepared:\n%s\n for position: %s",
            self.sell_order,
            config.symbol_info.symbol,
        )

    async def open_position(self) -> None:
        """Send a list of orders concurrently.

        Args:
            client: A `BinanceClient` object.
            side: The side of the orders (either `PositionSide.BUY` or `PositionSide.SELL`).
            orders: A list of `Order` objects to send.

        Returns:
            A list of `Order` objects with updated order IDs and statuses.
        """
        if self.sell_order.status != ORDER_STATUS_FILLED:
            self.sell_order = await self._create_order(
                side=self.data.state_info.side,
                order=self.sell_order,
                symbol_info=self.data.config.symbol_info,
            )
            logger.info(
                "New %s order send for %s at price: %s and quantity: %s [id: %s]",
                self.data.state_info.side.value,
                self.data.config.symbol_info.symbol,
                self.sell_order.price,
                self.sell_order.quantity_stable,
                self.sell_order.order_id,
            )

    async def cancel_position(self) -> None:
        assert isinstance(self.data, HPSellData)
        logger.info(
            "Start canceling position: %s %s, hp id: %s",
            self.data.config.symbol_info.symbol,
            self.data.state_info.side,
            self.data.config.hp_id,
        )
        self.data.state_info.stagnation_counter = 0

        await self.cancel_remaining_order()
        if self.sell_order.status == ORDER_STATUS_CANCELED:
            self.db.upsert_order(
                order=self.sell_order,
                hp_id=self.data.config.hp_id,
                side=self.data.state_info.side,
            )

        self.data.state_info.completeness = round(
            self.sell_order.realized_quantity / self.sell_order.quantity, 2
        )
        self.data.state_info.ui_state = UiState.STAGNATED

        self.db.upsert_sell_price_level(data=self.data)

    async def handle_order_partially_filled(
        self, execution_report: ExecutionReport
    ) -> None:
        if execution_report.order_id == self.sell_order.order_id:
            self.sell_order.status = execution_report.current_order_status
            self.sell_order.realized_quantity = (
                execution_report.cumulative_filled_quantity
            )
            self.sell_order.quantity_stable -= (
                execution_report.last_executed_price
                * execution_report.last_executed_quantity
            )
            self.sell_order.price = execution_report.last_executed_price

            self.db.upsert_order(
                order=self.sell_order,
                hp_id=self.data.config.hp_id,
                side=self.data.state_info.side,
            )
            logger.info("Order: %s partially filled", self.sell_order.order_id)

        logger.info("Stagnation counter reset for system: %s", self.data.config.hp_id)
        self.data.state_info.stagnation_counter = 0
        self.data.state_info.generate_next_monitor_time()
        self.data.state_info.completeness = round(
            self.sell_order.realized_quantity / self.sell_order.quantity, 2
        )
        self.data.state_info.ui_state = UiState.OPEN

    async def handle_order_filled(self, execution_report: ExecutionReport) -> None:
        if execution_report.order_id == self.sell_order.order_id:
            self.sell_order.status = execution_report.current_order_status
            self.sell_order.price = execution_report.last_executed_price
            self.sell_order.realized_quantity = (
                execution_report.cumulative_filled_quantity
            )
            logger.info(
                "Order: %s filled, symbol: %s, price: %s, status: %s",
                self.sell_order.order_id,
                execution_report.symbol,
                self.sell_order.price,
                self.sell_order.status,
            )

            self.db.upsert_order(
                order=self.sell_order,
                hp_id=self.data.config.hp_id,
                side=self.data.state_info.side,
            )

        self.data.state_info.ui_state = UiState.OPEN
        self.data.state_info.stagnation_counter = 0
        self.data.state_info.generate_next_monitor_time()

        self.data.state_info.completeness = round(
            self.sell_order.realized_quantity / self.sell_order.quantity, 2
        )

        logger.info("Completeness: %s", self.data.state_info.completeness)
        logger.info("Stagnation counter reset for system: %s", self.data.config.hp_id)

    async def cancel_remaining_order(self) -> None:
        if (
            self.sell_order.status == ORDER_STATUS_PARTIALLY_FILLED
            and self.sell_order.order_id
        ):
            await self._cancel_order(
                order_id=self.sell_order.order_id,
                symbol=self.data.config.symbol_info.symbol,
            )
            self.sell_order.status = ORDER_STATUS_CANCELED

            logger.info(
                "Cancelled partially filled order with id: %s", self.sell_order.order_id
            )
        elif self.sell_order.status == ORDER_STATUS_NEW and self.sell_order.order_id:
            await self._cancel_order(
                order_id=self.sell_order.order_id,
                symbol=self.data.config.symbol_info.symbol,
            )
            self.sell_order.status = ORDER_STATUS_CANCELED
            logger.info("Cancelled new order with id: %s", self.sell_order.order_id)

    async def _create_order(
        self, side: PositionSide, order: Order, symbol_info: SymbolInfo
    ) -> Order:
        max_retries = 10
        last_exception = None
        for _ in range(max_retries):
            try:
                price = symbol_info.adjust_price(order.price)
                quantity = symbol_info.adjust_quantity(
                    order.quantity - order.realized_quantity
                )
                symbol_info.validate_order(price=price, quantity=quantity)
                resp = await self.client.create_order(
                    symbol=symbol_info.symbol,
                    price=price,
                    quantity=quantity,
                    side=side.value,
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
                    order,
                    type(exception).__name__,
                    exception,
                )
                await asyncio.sleep(1)  # wait for a second before retrying
                continue
            else:
                order.order_id = int(resp["orderId"])
                # order.price = resp["price"]
                order.status = resp["status"]
                return order

        assert last_exception is not None
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
