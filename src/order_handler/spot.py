import asyncio
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

from logging_config import StrategyLogger
from src.common.identifiers.common import BinanceClient, Order, PositionSide
from src.common.symbol_info import SymbolInfo


class OrderHandler:
    MAX_RETRIES = 10

    def __init__(
        self,
        strategy_logger: StrategyLogger,
        client: BinanceClient,
    ):
        self.strategy_logger = strategy_logger
        self.client = client

    def round_quantity(self, quantity: float) -> float:
        if quantity >= 1:
            return round(quantity, 2)

        # Count the number of leading zeros after the decimal point
        str_quantity = f"{quantity:.10f}"
        zeros_after_decimal = len(str_quantity.split(".")[1]) - len(
            str_quantity.split(".")[1].lstrip("0")
        )
        return round(quantity, zeros_after_decimal + 4)

    def prepare_orders(
        self,
        price_low: float,
        price_high: float,
        budget: float,
        min_notional: float,
    ) -> List[Order]:
        orders = []

        # Define the number of orders
        max_num_orders = 3  # Number of desired orders
        min_budget_for_max_orders = max_num_orders * min_notional

        if budget >= min_budget_for_max_orders:
            number_of_orders = 3
            order_quantity_stable = budget / max_num_orders
        else:
            order_quantity_stable = min_notional
            number_of_orders = int(budget / min_notional)
            number_of_orders = (
                number_of_orders if number_of_orders % 2 == 1 else number_of_orders - 1
            )

        price_increment = (price_high - price_low) / (number_of_orders - 1)

        for i in range(number_of_orders):
            order_price = price_low + i * price_increment

            orders.append(
                Order(
                    quantity=self.round_quantity(order_quantity_stable / order_price),
                    price=order_price,
                    quantity_stable=self.round_quantity(order_quantity_stable),
                )
            )

        self.strategy_logger.debug("Orders prepared:\n%s", pprint.pformat(list(orders)))
        return orders

    async def create_order(
        self, side: PositionSide, order: Order, symbol_info: SymbolInfo
    ) -> Order:
        last_exception = None
        for _ in range(self.MAX_RETRIES):
            try:
                quantity = symbol_info.adjust_quantity(order.quantity)
                symbol_info.validate_order(price=order.price, quantity=quantity)
                resp = await self.client.create_order(
                    symbol=symbol_info.symbol,
                    price=round(order.price, 2),
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
                self.strategy_logger.error(
                    "Failed to create spot order due to %s: %s",
                    type(exception).__name__,
                    exception,
                )
                await asyncio.sleep(1)  # wait for a second before retrying
                continue
            else:
                order.order_id = int(resp["orderId"])
                order.status = resp["status"]
                return order

        assert last_exception is not None
        raise last_exception

    async def create_orders(
        self,
        side: PositionSide,
        orders: List[Order],
        symbol_info: SymbolInfo,
    ) -> List[Order]:
        """Send a list of orders concurrently.

        Args:
            client: A `BinanceClient` object.
            side: The side of the orders (either `PositionSide.BUY` or `PositionSide.SELL`).
            orders: A list of `Order` objects to send.

        Returns:
            A list of `Order` objects with updated order IDs and statuses.
        """
        results = await asyncio.gather(
            *[
                self.create_order(side=side, order=order, symbol_info=symbol_info)
                for order in orders
                if order.status != ORDER_STATUS_FILLED
            ]
        )
        for order in results:
            self.strategy_logger.info(
                "New %s order send for %s at price: %s and quantity: %s [id: %s]",
                side.value,
                symbol_info.symbol,
                order.price,
                order.quantity_stable,
                order.order_id,
            )
        return results

    async def cancel_order(self, order_id: int, symbol: str) -> None:
        try:
            resp = await self.client.cancel_order(symbol=symbol, orderId=order_id)
            self.strategy_logger.debug(f"Cancelled order {order_id}: {resp}")
        except (
            BinanceAPIException,
            BinanceOrderException,
            BinanceRequestException,
        ) as exception:
            self.strategy_logger.error(
                "Failed to cancel order due to %s: %s",
                type(exception).__name__,
                exception,
            )
            raise exception

    async def cancel_remaining_limit_orders(
        self, orders: List[Order], symbol: str
    ) -> List[Order]:
        self.strategy_logger.debug("Cancelling remaining limit orders")
        assert orders
        for order in orders:
            if order.status == ORDER_STATUS_PARTIALLY_FILLED:
                await self.cancel_order(order_id=order.order_id, symbol=symbol)
                order.status = ORDER_STATUS_CANCELED

                self.strategy_logger.debug(
                    "Cancelled partially filled order_id: %s", order.order_id
                )
            elif order.status == ORDER_STATUS_NEW:
                await self.cancel_order(order_id=order.order_id, symbol=symbol)
                order.status = ORDER_STATUS_CANCELED
                self.strategy_logger.debug("Cancelled new order_id: %s", order.order_id)

        return orders
