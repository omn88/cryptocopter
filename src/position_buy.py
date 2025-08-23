import asyncio
import logging
import pprint
from typing import List
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


from src.database import TradingDatabase
from src.identifiers import (
    ExecutionReport,
    HPBuyData,
    Order,
    UiState,
    BinanceClient,
    Mode,
    State,
)


logger = logging.getLogger("buy_handler")


class HPPositionBuy:
    def __init__(
        self,
        client: BinanceClient,
        data: HPBuyData,
        db: TradingDatabase,
    ):
        self.client = client
        self.data = data
        self.db = db
        self.orders: List[Order] = []
        self.orders_cancel_price: float = 0

    async def open_position(self) -> List[Order]:
        """Send a list of orders concurrently.

        Returns:
            A list of `Order` objects with updated order IDs and statuses.
        """
        logger.debug("Entered open position")
        self.orders_cancel_price = self.calculate_trigger_cancel_orders_price()
        logger.info(
            "Orders cancel price set to: %s for position: %s",
            self.orders_cancel_price,
            self.data.config.symbol_info.symbol,
        )
        logger.info("Orders: %s", self.orders)
        for order in self.orders:
            if order.status != ORDER_STATUS_FILLED:
                order.status = ORDER_STATUS_NEW
                order.order_id = 0

        logger.info("Orders after update: %s", self.orders)

        results = await asyncio.gather(
            *[
                self._create_order(order=order)
                for order in self.orders
                if order.status != ORDER_STATUS_FILLED
            ]
        )
        for order in results:
            logger.info(
                "New %s order send for %s at price: %s and quantity: %s [id: %s]",
                self.data.state_info.side.value,
                self.data.config.symbol_info.symbol,
                order.price,
                order.quantity_stable,
                order.order_id,
            )
        logger.info("Exited open position")
        return results

    async def cancel_position(self) -> None:
        logger.info(
            "Start canceling position: %s %s, hp id: %s",
            self.data.config.symbol_info.symbol,
            self.data.state_info.side,
            self.data.config.hp_id,
        )

        self.orders = await self.cancel_remaining_limit_orders(
            symbol=self.data.config.symbol_info.symbol,
            orders=self.orders,
        )
        for order in self.orders:
            if order.status == ORDER_STATUS_CANCELED:
                await self.db.upsert_order(
                    order=order,
                    hp_id=self.data.config.hp_id,
                    side=self.data.state_info.side,
                )

        all_canceled = all(
            order.status == ORDER_STATUS_CANCELED for order in self.orders
        )
        any_filled = any(order.status == ORDER_STATUS_FILLED for order in self.orders)
        any_partially_filled = any(
            order.status == ORDER_STATUS_PARTIALLY_FILLED or order.realized_quantity > 0
            for order in self.orders
        )

        # If all orders are canceled and none are filled or partially filled, set state to NEW
        if all_canceled and not any_filled and not any_partially_filled:
            self.data.state_info.state = State.NEW
            self.data.state_info.completeness = 0.0
            logger.info(
                "All buy orders canceled and none filled: setting state to NEW and completeness to 0.0"
            )
        # If any order is filled or partially filled, set state to PARTIALLY_BOUGHT, unless all are filled
        elif any_filled or any_partially_filled:
            self.data.state_info.get_completeness(orders=self.orders)
            if all(order.status == ORDER_STATUS_FILLED for order in self.orders):
                self.data.state_info.state = State.BOUGHT
                logger.info(
                    "All buy orders filled: setting state to BOUGHT (completeness=%.4f)",
                    self.data.state_info.completeness,
                )
            else:
                self.data.state_info.state = State.PARTIALLY_BOUGHT
                logger.info(
                    "Some buy orders filled or partially filled: setting state to PARTIALLY_BOUGHT (completeness=%.4f)",
                    self.data.state_info.completeness,
                )
        else:
            self.data.state_info.get_completeness(orders=self.orders)

        self.data.state_info.ui_state = UiState.STAGNATED

        await self.db.upsert_buy_price_level(data=self.data)

    async def handle_order_partially_filled(
        self, execution_report: ExecutionReport
    ) -> None:
        for order in self.orders:
            if execution_report.order_id == order.order_id:
                order.status = execution_report.current_order_status
                order.realized_quantity = execution_report.cumulative_filled_quantity
                order.quantity_stable -= (
                    execution_report.last_executed_price
                    * execution_report.last_executed_quantity
                )
                order.price = execution_report.last_executed_price

                await self.db.upsert_order(
                    order=order,
                    hp_id=self.data.config.hp_id,
                    side=self.data.state_info.side,
                )
                logger.info("Order: %s partially filled", order.order_id)

        self.data.state_info.get_completeness(self.orders)
        self.data.state_info.ui_state = UiState.OPEN

    async def handle_order_filled(self, execution_report: ExecutionReport) -> None:
        for order in self.orders:
            if execution_report.order_id == order.order_id:
                order.status = execution_report.current_order_status
                order.price = execution_report.last_executed_price
                order.realized_quantity = execution_report.cumulative_filled_quantity
                logger.info(
                    "Order: %s filled, symbol: %s, price: %s, status: %s",
                    order.order_id,
                    execution_report.symbol,
                    order.price,
                    order.status,
                )

                await self.db.upsert_order(
                    order=order,
                    hp_id=self.data.config.hp_id,
                    side=self.data.state_info.side,
                )

        self.data.state_info.ui_state = UiState.OPEN

        self.data.state_info.get_completeness(self.orders)
        logger.info("Completeness: %s", self.data.state_info.completeness)

    def prepare_orders(self) -> None:
        config = self.data.config

        def prepare_single_buy_order():
            orders.append(
                Order(
                    quantity=config.symbol_info.adjust_quantity(
                        config.budget / config.price_high
                    ),
                    price=config.symbol_info.adjust_price(config.price_high),
                    quantity_stable=config.budget,
                    precision=config.symbol_info.precision,
                    price_precision=config.symbol_info.price_precision,
                )
            )

        orders = []

        if config.mode == Mode.SINGLE:
            prepare_single_buy_order()

        if config.mode == Mode.DCA:
            num_orders = 3

            min_budget_for_max_orders = num_orders * config.symbol_info.min_notional

            if config.budget >= min_budget_for_max_orders:
                order_quantity_stable = config.budget / num_orders
            else:
                order_quantity_stable = config.symbol_info.min_notional
                num_orders = int(config.budget / config.symbol_info.min_notional)
                num_orders = num_orders if num_orders % 2 == 1 else num_orders - 1

            if num_orders == 1:
                prepare_single_buy_order()
            else:
                price_increment = (config.price_high - config.price_low) / (
                    num_orders - 1
                )

                for i in range(num_orders):
                    order_price = config.price_high - i * price_increment

                    orders.append(
                        Order(
                            quantity=config.symbol_info.adjust_quantity(
                                order_quantity_stable / order_price
                            ),
                            price=config.symbol_info.adjust_price(order_price),
                            quantity_stable=round(order_quantity_stable, 2),
                            precision=config.symbol_info.precision,
                            price_precision=config.symbol_info.price_precision,
                        )
                    )
        logger.info(
            "Buy orders prepared:\n%s\n for position: %s",
            pprint.pformat(list(orders)),
            config.symbol_info.symbol,
        )
        self.orders = orders

    def calculate_trigger_cancel_orders_price(self):
        return self.data.config.symbol_info.adjust_price(
            max(
                order.price
                for order in self.orders
                if order.status != ORDER_STATUS_FILLED
            )
            * (1 + (2 * self.data.config.order_trigger / 100))
        )

    async def cancel_remaining_limit_orders(
        self, orders: List[Order], symbol: str
    ) -> List[Order]:
        logger.info("Cancelling remaining limit orders: %s", orders)
        assert orders
        for order in orders:
            if order.status == ORDER_STATUS_PARTIALLY_FILLED and order.order_id:
                await self._cancel_order(order_id=order.order_id, symbol=symbol)
                order.status = ORDER_STATUS_CANCELED
                logger.info(
                    "Cancelled partially filled order with id: %s", order.order_id
                )
            elif order.status == ORDER_STATUS_NEW and order.order_id:
                await self._cancel_order(order_id=order.order_id, symbol=symbol)
                order.status = ORDER_STATUS_CANCELED
                logger.info("Cancelled new order with id: %s", order.order_id)
            # No new Order object is created; status is updated in-place
        return orders

    def calculate_avg_buy_price(self) -> float:
        """
        Calculates the weighted average buy price based on realized quantities.

        Args:
            orders (List[Dict]): Each dict has 'price', 'realized_quantity', and 'total_quantity'

        Returns:
            float: Weighted average buy price or 0.0 if no realized quantity
        """
        total_realized_quantity = 0.0
        total_cost = 0.0

        for order in self.orders:
            total_realized_quantity += order.realized_quantity
            total_cost += order.realized_quantity * order.price

        if total_realized_quantity == 0:
            return 0.0  # Avoid division by zero

        return self.data.config.symbol_info.adjust_price(
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
        total_realized_quantity = 0.0

        for order in self.orders:
            total_realized_quantity += order.realized_quantity

        if total_realized_quantity == 0:
            return 0.0  # Avoid division by zero

        return self.data.config.symbol_info.adjust_quantity(total_realized_quantity)

    async def _create_order(self, order: Order) -> Order:
        max_retries = 10
        last_exception = None
        for _ in range(max_retries):
            try:
                symbol_info = self.data.config.symbol_info
                price = symbol_info.format_price(order.price)
                quantity = symbol_info.adjust_quantity(
                    order.quantity - order.realized_quantity
                )
                symbol_info.validate_order(price=float(price), quantity=quantity)
                resp = await self.client.create_order(
                    symbol=symbol_info.symbol,
                    price=price,
                    quantity=quantity,
                    side=self.data.state_info.side.value,
                    type=ORDER_TYPE_LIMIT,
                    timeInForce=TIME_IN_FORCE_GTC,
                )
                logger.debug("Order create response: %s", resp)
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
