import asyncio
from typing import List
from binance.enums import (
    FUTURE_ORDER_TYPE_LIMIT,
    TIME_IN_FORCE_GTC,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_NEW,
    FUTURE_ORDER_TYPE_MARKET,
)
from binance.exceptions import (
    BinanceAPIException,
    BinanceOrderException,
    BinanceRequestException,
)

from logging_config import StrategyLogger
from src.common.common import convert_time
from src.common.constants import DCA_SPAN, LEVERAGE
from src.common.identifiers import (
    BinanceClient,
    Order,
    PositionMode,
    PositionSide,
)
from src.gui.gui_handler import GuiHandler


class OrderHandler:
    MAX_RETRIES = 10

    def __init__(
        self,
        strategy_logger: StrategyLogger,
        client: BinanceClient,
        order_quantity_stable: float,
        gui_handler: GuiHandler,
    ):
        self.strategy_logger = strategy_logger
        self.client = client
        self.order_quantity_stable = order_quantity_stable
        self.gui_handler = gui_handler

    def prepare_orders(
        self,
        side: PositionSide,
        mode: PositionMode,
        entry_price: float,
        number_of_orders: int,
    ) -> List[Order]:
        self.strategy_logger.info("Entering prepare orders")

        orders = [
            Order(
                price=self.get_order_price(
                    side=side,
                    entry_price=entry_price,
                    order=order,
                ),
                quantity=self.get_order_quantity(
                    side=side,
                    mode=mode,
                    order_quantity=self.order_quantity_stable,
                    entry_price=entry_price,
                    order=order,
                    number_of_orders=number_of_orders,
                ),
                order_id=0,
                quantity_stable=self.order_quantity_stable,
            )
            for order in range(number_of_orders)
        ]

        self.strategy_logger.info("Exiting prepare orders")
        return orders

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
        tasks = []
        for order in orders:
            task = asyncio.create_task(
                self.create_order(side=side, order=order, symbol=symbol)
            )
            tasks.append(task)
        results = await asyncio.gather(*tasks)

        return list(results)

    def get_order_price(self, side: PositionSide, entry_price: float, order: int):
        if side == PositionSide.LONG:
            return round((entry_price - (DCA_SPAN * order * entry_price)), 1)

        if side == PositionSide.SHORT:
            return round((entry_price + (DCA_SPAN * order * entry_price)), 1)

    def get_order_quantity(
        self,
        side: PositionSide,
        mode: PositionMode,
        order_quantity: float,
        entry_price: float,
        number_of_orders: int,
        order: int,
    ):
        if side == PositionSide.LONG and mode == PositionMode.DCA:
            return round(
                LEVERAGE
                * order_quantity
                / (round((entry_price - (DCA_SPAN * order * entry_price)), 2)),
                3,
            )

        if side == PositionSide.LONG and mode == PositionMode.FULL:
            return round(
                LEVERAGE
                * order_quantity
                * number_of_orders
                / (round((entry_price - (DCA_SPAN * order * entry_price)), 2)),
                3,
            )

        if side == PositionSide.SHORT and mode == PositionMode.DCA:
            return round(
                LEVERAGE
                * order_quantity
                / (round((entry_price + (DCA_SPAN * order * entry_price)), 2)),
                3,
            )

        if side == PositionSide.SHORT and mode == PositionMode.FULL:
            return round(
                LEVERAGE
                * order_quantity
                * number_of_orders
                / (round((entry_price + (DCA_SPAN * order * entry_price)), 2)),
                3,
            )

    async def create_order(
        self,
        side: PositionSide,
        order: Order,
        symbol: str,
    ) -> Order:
        last_exception = None

        for _ in range(self.MAX_RETRIES):
            try:
                resp = await self.client.futures_create_order(
                    symbol=symbol,
                    price=round(order.price, 1),
                    quantity=round(abs(order.quantity), 3),
                    side=side.value,
                    type=FUTURE_ORDER_TYPE_LIMIT,
                    timeInForce=TIME_IN_FORCE_GTC,
                    timestamp=int(await self.client.get_adjusted_time() * 1000),
                )
            except (
                BinanceAPIException,
                BinanceOrderException,
                BinanceRequestException,
            ) as exception:
                last_exception = exception
                self.strategy_logger.error(
                    "Failed to create order due to %s: %s",
                    type(exception).__name__,
                    exception,
                )
                await asyncio.sleep(1)  # wait for a second before retrying
                continue
            else:
                self.strategy_logger.info("RESP: %s", resp)
                order.order_id = int(resp["orderId"])
                order.status = resp["status"]
                self.strategy_logger.info("New: %s", order)
                order.open_time = convert_time(resp["updateTime"])

                return order

        assert last_exception is not None
        raise last_exception

    async def cancel_order(
        self,
        order: Order,
        symbol: str,
    ) -> str:
        self.strategy_logger.info(
            "Enter cancel order: %s, symbol: %s", order.order_id, symbol
        )
        last_exception = None

        for _ in range(self.MAX_RETRIES):
            try:
                resp = await self.client.futures_cancel_order(
                    symbol=symbol,
                    orderId=order.order_id,
                    timestamp=int(await self.client.get_adjusted_time() * 1000),
                )
                order.status = resp["status"]
                # await ui_queue.put(
                #     OrderData(
                #         order_id=order.order_id,
                #         open_time=order.open_time,
                #         symbol=symbol,
                #         order_type=order.order_type,
                #         side=side,
                #         price=order.price,
                #         quantity=order.quantity,
                #         realized_quantity=order.realized_quantity,
                #         status=order.status,
                #     )
                # )
            except (
                BinanceAPIException,
                BinanceOrderException,
                BinanceRequestException,
            ) as exception:
                last_exception = exception
                self.strategy_logger.error(
                    "Failed to cancel order order due to %s: %s",
                    type(exception).__name__,
                    exception,
                )
                await asyncio.sleep(1)  # wait for a second before retrying
            else:
                self.strategy_logger.info("Exit cancel order")
                return resp["status"]

        # if we've exhausted all retries and still have an exception, raise it
        if last_exception is not None:
            raise last_exception
        return ""

    async def create_market_order(
        self, side: str, symbol: str, quantity: float
    ) -> Order:
        order_type = FUTURE_ORDER_TYPE_MARKET
        quantity = abs(quantity)

        last_exception = None

        for _ in range(self.MAX_RETRIES):
            try:
                resp = await self.client.futures_create_order(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    type=order_type,
                    timestamp=int(await self.client.get_adjusted_time() * 1000),
                )
            except (
                BinanceAPIException,
                BinanceOrderException,
                BinanceRequestException,
            ) as exception:
                last_exception = exception
                self.strategy_logger.error(
                    "Failed to send market order due to %s: %s",
                    type(exception).__name__,
                    exception,
                )
                await asyncio.sleep(1)  # wait for a second before retrying
                continue
            else:
                market_order = Order(
                    order_type=order_type,
                    order_id=int(resp["orderId"]),
                    price=0,
                    quantity=quantity,
                )
                self.strategy_logger.info(
                    "%s order, type: %s send: %s",
                    side,
                    order_type,
                    resp,
                )

            return market_order

        assert last_exception is not None
        raise last_exception

    async def cancel_remaining_limit_orders(
        self, orders: List[Order], symbol: str
    ) -> List[Order]:
        self.strategy_logger.info("Cancelling remaining limit orders")
        assert orders
        for order in orders:
            if order.status == ORDER_STATUS_PARTIALLY_FILLED:
                order.status = await self.cancel_order(order=order, symbol=symbol)
                self.strategy_logger.info(
                    "Cancelled partially filled order_id: %s", order.order_id
                )
            elif order.status == ORDER_STATUS_NEW:
                order.status = await self.cancel_order(order=order, symbol=symbol)
                self.strategy_logger.info("Cancelled new order_id: %s", order.order_id)

        return orders

    def target_price_calculate(self, side: PositionSide, price: float) -> float:
        self.strategy_logger.info("Entering target price calculate")
        if side == PositionSide.LONG:
            target_price = round((1 + (100 / LEVERAGE / 100)) * price, 1)
        elif side == PositionSide.SHORT:
            target_price = round((1 - (100 / LEVERAGE / 100)) * price, 1)
        else:
            raise AssertionError(f"Wrong position side: {side}")

        self.strategy_logger.info("position side: %s, target: %s", side, target_price)
        return target_price

    # async def update_order(self, symbol, order_id, new_quantity=None, new_price=None):
    #     # Binance does not support modifying an existing order. You must cancel and create a new order.
    #     try:
    #         await self.cancel_order(symbol, order_id)
    #         response = await self.create_order(
    #             symbol, "LIMIT", "BUY", new_quantity, new_price
    #         )  # Example for a limit buy order
    #         self.strategy_logger.info(f"Order updated: {response}")
    #         return response
    #     except Exception as e:
    #         self.strategy_logger.error(f"Error updating order: {e}")
    #         raise

    # # Add additional methods as needed for querying orders, etc.
