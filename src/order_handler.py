import asyncio
from typing import List, Union
from binance.enums import (
    FUTURE_ORDER_TYPE_LIMIT,
    TIME_IN_FORCE_GTC,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_NEW,
    ORDER_TYPE_LIMIT,
    ORDER_TYPE_MARKET,
    FUTURE_ORDER_TYPE_MARKET,
)
from binance.exceptions import (
    BinanceAPIException,
    BinanceOrderException,
    BinanceRequestException,
)

from logging_config import StrategyLogger
from src.common.common import convert_time
from src.common.identifiers import (
    BinanceClient,
    Order,
    Position,
    PositionMode,
    PositionSide,
)
from src.gui.gui_handler import GuiHandlerFutures, GuiHandlerSpot


class OrderHandlerFutures:
    MAX_RETRIES = 10

    def __init__(
        self,
        strategy_logger: StrategyLogger,
        client: BinanceClient,
        order_quantity_stable: float,
        gui_handler: GuiHandlerFutures,
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
        dca_span: float,
        leverage: int,
    ) -> List[Order]:
        orders = [
            Order(
                price=self.get_order_price(
                    side=side,
                    entry_price=entry_price,
                    order=order,
                    dca_span=dca_span,
                ),
                quantity=self.get_order_quantity(
                    side=side,
                    mode=mode,
                    order_quantity=self.order_quantity_stable,
                    entry_price=entry_price,
                    order=order,
                    number_of_orders=number_of_orders,
                    dca_span=dca_span,
                    leverage=leverage,
                ),
                order_id=0,
                quantity_stable=self.order_quantity_stable,
            )
            for order in range(number_of_orders)
        ]

        self.strategy_logger.info("Prepared orders: %s", orders)
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
        results = await asyncio.gather(
            *[
                self.create_order(side=side, order=order, symbol=symbol)
                for order in orders
            ]
        )
        self.strategy_logger.info(
            "Orders created, ids: %s", [order.order_id for order in orders]
        )

        await self.gui_handler.create_orders(
            orders=results,
            symbol=symbol,
            side=side,
        )

        return results

    def get_order_price(
        self, side: PositionSide, entry_price: float, order: int, dca_span: float
    ):
        if side == PositionSide.LONG:
            return round((entry_price - (dca_span * order * entry_price)), 1)

        if side == PositionSide.SHORT:
            return round((entry_price + (dca_span * order * entry_price)), 1)

    def get_order_quantity(
        self,
        side: PositionSide,
        mode: PositionMode,
        order_quantity: float,
        entry_price: float,
        number_of_orders: int,
        dca_span: float,
        leverage: int,
        order: int,
    ):
        if side == PositionSide.LONG and mode == PositionMode.DCA:
            return round(
                leverage
                * order_quantity
                / (round((entry_price - (dca_span * order * entry_price)), 2)),
                3,
            )

        if side == PositionSide.LONG and mode == PositionMode.FULL:
            return round(
                leverage
                * order_quantity
                * number_of_orders
                / (round((entry_price - (dca_span * order * entry_price)), 2)),
                3,
            )

        if side == PositionSide.SHORT and mode == PositionMode.DCA:
            return round(
                leverage
                * order_quantity
                / (round((entry_price + (dca_span * order * entry_price)), 2)),
                3,
            )

        if side == PositionSide.SHORT and mode == PositionMode.FULL:
            return round(
                leverage
                * order_quantity
                * number_of_orders
                / (round((entry_price + (dca_span * order * entry_price)), 2)),
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
    ) -> Order:
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
                return order

        # if we've exhausted all retries and still have an exception, raise it
        if last_exception is not None:
            raise last_exception
        return Order(price=0, quantity=0)

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
        self, orders: List[Order], symbol: str, side: PositionSide
    ) -> List[Order]:
        self.strategy_logger.info("Cancelling remaining limit orders")
        assert orders
        for order in orders:
            if order.status == ORDER_STATUS_PARTIALLY_FILLED:
                order = await self.cancel_order(order=order, symbol=symbol)
                await self.gui_handler.update_order(
                    order=order, symbol=symbol, side=side
                )

                self.strategy_logger.info(
                    "Cancelled partially filled order_id: %s", order.order_id
                )
            elif order.status == ORDER_STATUS_NEW:
                order = await self.cancel_order(order=order, symbol=symbol)
                self.strategy_logger.info("Cancelled new order_id: %s", order.order_id)

        return orders

    def target_price_calculate(
        self, side: PositionSide, price: float, leverage: int
    ) -> float:
        if side == PositionSide.LONG:
            target_price = round((1 + (100 / leverage / 100)) * price, 1)
        elif side == PositionSide.SHORT:
            target_price = round((1 - (100 / leverage / 100)) * price, 1)
        else:
            raise AssertionError(f"Wrong position side: {side}")

        return target_price

    async def create_take_profit_order(
        self, position: Position, leverage: int
    ) -> Order:
        side = (
            PositionSide.LONG
            if position.side == PositionSide.SHORT
            else PositionSide.SHORT
        )
        order = await self.create_order(
            side=side,
            order=Order(
                price=self.target_price_calculate(
                    side=position.side, price=position.entry_price, leverage=leverage
                ),
                quantity=position.quantity,
                quantity_stable=round(
                    (abs(position.quantity) * position.entry_price / leverage),
                    2,
                ),
            ),
            symbol=position.symbol,
        )

        await self.gui_handler.update_order(
            order=order, side=side, symbol=position.symbol
        )

        return order


class OrderHandlerSpot:
    MAX_RETRIES = 10

    def __init__(
        self,
        strategy_logger: StrategyLogger,
        client: BinanceClient,
        gui_handler: GuiHandlerSpot,
    ):
        self.strategy_logger = strategy_logger
        self.client = client
        self.gui_handler = gui_handler

    def prepare_orders(
        self,
        side: PositionSide,
        mode: PositionMode,
        entry_price: float,
        number_of_orders: int,
        dca_span: float,
        leverage: int,
    ) -> List[Order]:
        orders = [
            Order(
                price=self.get_order_price(
                    side=side,
                    entry_price=entry_price,
                    order=order,
                    dca_span=dca_span,
                ),
                quantity=self.get_order_quantity(
                    side=side,
                    mode=mode,
                    order_quantity=self.order_quantity_stable,
                    entry_price=entry_price,
                    order=order,
                    number_of_orders=number_of_orders,
                    dca_span=dca_span,
                    leverage=leverage,
                ),
                order_id=0,
                quantity_stable=self.order_quantity_stable,
            )
            for order in range(number_of_orders)
        ]

        self.strategy_logger.info("Prepared orders: %s", orders)
        return orders

    def get_order_price(
        self, side: PositionSide, entry_price: float, order: int, dca_span: float
    ):
        if side == PositionSide.LONG:
            return round((entry_price - (dca_span * order * entry_price)), 1)

        if side == PositionSide.SHORT:
            return round((entry_price + (dca_span * order * entry_price)), 1)

    def get_order_quantity(
        self,
        side: PositionSide,
        mode: PositionMode,
        order_quantity: float,
        entry_price: float,
        number_of_orders: int,
        dca_span: float,
        leverage: int,
        order: int,
    ):
        if side == PositionSide.LONG and mode == PositionMode.DCA:
            return round(
                leverage
                * order_quantity
                / (round((entry_price - (dca_span * order * entry_price)), 2)),
                3,
            )

        if side == PositionSide.LONG and mode == PositionMode.FULL:
            return round(
                leverage
                * order_quantity
                * number_of_orders
                / (round((entry_price - (dca_span * order * entry_price)), 2)),
                3,
            )

        if side == PositionSide.SHORT and mode == PositionMode.DCA:
            return round(
                leverage
                * order_quantity
                / (round((entry_price + (dca_span * order * entry_price)), 2)),
                3,
            )

        if side == PositionSide.SHORT and mode == PositionMode.FULL:
            return round(
                leverage
                * order_quantity
                * number_of_orders
                / (round((entry_price + (dca_span * order * entry_price)), 2)),
                3,
            )

    def target_price_calculate(
        self, side: PositionSide, price: float, leverage: int
    ) -> float:
        if side == PositionSide.LONG:
            target_price = round((1 + (100 / leverage / 100)) * price, 1)
        elif side == PositionSide.SHORT:
            target_price = round((1 - (100 / leverage / 100)) * price, 1)
        else:
            raise AssertionError(f"Wrong position side: {side}")

        return target_price

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
            "Orders created, ids: %s", [order.order_id for order in orders]
        )

        await self.gui_handler.create_orders(
            orders=results,
            symbol=symbol,
            side=side,
        )

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

    async def create_market_order(
        self, side: PositionSide, symbol: str, quantity: float
    ) -> Order:
        try:
            resp = await self.client.create_order(
                symbol=symbol,
                side=side.value,
                quantity=round(abs(quantity), 3),
                type=ORDER_TYPE_MARKET,
            )
            market_order = Order(
                order_type=ORDER_TYPE_MARKET,
                order_id=int(resp["orderId"]),
                quantity=quantity,
            )
            return market_order
        except (
            BinanceAPIException,
            BinanceOrderException,
            BinanceRequestException,
        ) as exception:
            self.strategy_logger.error(
                "Failed to send market order due to %s: %s",
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
                order = await self.cancel_order(order_id=order.order_id, symbol=symbol)
                await self.gui_handler.update_order(
                    order=order, symbol=symbol, side=side
                )

                self.strategy_logger.info(
                    "Cancelled partially filled order_id: %s", order.order_id
                )
            elif order.status == ORDER_STATUS_NEW:
                order = await self.cancel_order(order_id=order.order_id, symbol=symbol)
                self.strategy_logger.info("Cancelled new order_id: %s", order.order_id)

        return orders

    async def handle_order_updates(self, orders: List[Order], symbol: str) -> None:
        try:
            # In actual implementation, handle real-time updates
            # This is a placeholder for the implementation of update handling
            self.strategy_logger.info(f"Handling order updates for {symbol}")
        except Exception as exception:
            self.strategy_logger.error(
                "Failed to handle order updates due to %s", exception
            )
            raise exception
