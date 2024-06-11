import asyncio
import pprint
from typing import List
from binance.enums import (
    TIME_IN_FORCE_GTC,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_NEW,
    ORDER_TYPE_LIMIT,
)
from binance.exceptions import (
    BinanceAPIException,
    BinanceOrderException,
    BinanceRequestException,
)

from logging_config import StrategyLogger
from src.gui.gui_handler.spot import GuiHandler
from src.common.identifiers.common import BinanceClient, Order, PositionSide


class OrderHandler:
    MAX_RETRIES = 10

    def __init__(
        self,
        strategy_logger: StrategyLogger,
        client: BinanceClient,
        gui_handler: GuiHandler,
    ):
        self.strategy_logger = strategy_logger
        self.client = client
        self.gui_handler = gui_handler

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

        self.strategy_logger.info(
            "Orders created, ids:\n%s", pprint.pformat([order for order in orders])
        )
        return orders

    async def create_order(
        self, side: PositionSide, order: Order, symbol: str
    ) -> Order:
        last_exception = None
        for _ in range(self.MAX_RETRIES):
            try:
                resp = await self.client.create_order(
                    symbol=symbol,
                    price=round(order.price, 2),
                    quantity=round(abs(order.quantity), 3),
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
        symbol: str,
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
                self.create_order(side=side, order=order, symbol=symbol)
                for order in orders
            ]
        )
        self.strategy_logger.info(
            "Orders created, ids:\n%s", pprint.pformat(list(results))
        )
        # await self.gui_handler.create_orders(
        #     orders=results,
        #     symbol=symbol,
        #     side=side,
        # )

        return results

    async def cancel_order(self, order_id: int, symbol: str) -> None:
        try:
            resp = await self.client.cancel_order(symbol=symbol, orderId=order_id)
            self.strategy_logger.info(f"Cancelled order {order_id}: {resp}")
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
        self, orders: List[Order], symbol: str, side: PositionSide
    ) -> List[Order]:
        self.strategy_logger.info("Cancelling remaining limit orders")
        assert orders
        for order in orders:
            if order.status == ORDER_STATUS_PARTIALLY_FILLED:
                await self.cancel_order(order_id=order.order_id, symbol=symbol)
                # await self.gui_handler.update_order(
                #     order=order, symbol=symbol, side=side
                # )

                self.strategy_logger.info(
                    "Cancelled partially filled order_id: %s", order.order_id
                )
            elif order.status == ORDER_STATUS_NEW:
                await self.cancel_order(order_id=order.order_id, symbol=symbol)
                self.strategy_logger.info("Cancelled new order_id: %s", order.order_id)

        return orders
