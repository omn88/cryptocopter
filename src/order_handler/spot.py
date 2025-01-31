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

from logging_config import StrategyLogger
from src.common.identifiers.common import BinanceClient, Mode, PositionSide
from src.common.identifiers.spot import Event, EventName, HPConfig, Order
from src.common.symbol_info import SymbolInfo


logger = logging.getLogger("order_handler")


class OrderHandler:
    MAX_RETRIES = 10

    def __init__(
        self,
        strategy_logger: StrategyLogger,
        client: BinanceClient,
    ):
        self.strategy_logger = strategy_logger
        self.client = client

    def prepare_buy_orders(self, config: HPConfig) -> List[Order]:
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
        return orders

    def prepare_sell_orders(
        self, config: HPConfig, buy_orders: List[Order], sell_orders: List[Order]
    ) -> List[Order]:
        orders = []
        quantity = sum(order.realized_quantity for order in buy_orders) - sum(
            order.realized_quantity for order in sell_orders
        )
        quantity_stable = round(quantity * config.price_low, 2)

        if config.mode == Mode.SINGLE:
            orders.append(
                Order(
                    quantity=config.symbol_info.adjust_quantity(quantity),
                    price=config.symbol_info.adjust_price(config.price_low),
                    quantity_stable=quantity_stable,
                    precision=config.symbol_info.precision,
                    price_precision=config.symbol_info.price_precision,
                )
            )

        if config.mode == Mode.DCA:
            num_orders = 3

            min_budget_for_max_orders = num_orders * config.symbol_info.min_notional

            if quantity_stable >= min_budget_for_max_orders:
                order_quantity_stable = quantity_stable / num_orders
            else:
                order_quantity_stable = config.symbol_info.min_notional
                num_orders = int(quantity_stable / config.symbol_info.min_notional)
                num_orders = num_orders if num_orders % 2 == 1 else num_orders - 1

            if num_orders == 1:
                orders.append(
                    Order(
                        quantity=config.symbol_info.adjust_quantity(quantity),
                        price=config.symbol_info.adjust_price(config.price_low),
                        quantity_stable=quantity_stable,
                        precision=config.symbol_info.precision,
                        price_precision=config.symbol_info.price_precision,
                    )
                )
            else:
                price_increment = (config.price_high - config.price_low) / (
                    num_orders - 1
                )

                for i in range(num_orders):
                    order_price = config.price_low + i * price_increment

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
            "Sell orders prepared:\n%s\n for position: %s",
            pprint.pformat(list(orders)),
            config.symbol_info.symbol,
        )
        return orders

    async def create_order(
        self, side: PositionSide, order: Order, symbol_info: SymbolInfo
    ) -> Order:
        last_exception = None
        for _ in range(self.MAX_RETRIES):
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
            logger.info(
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

    async def cancel_remaining_limit_orders(
        self, orders: List[Order], symbol: str
    ) -> List[Order]:
        logger.info("Cancelling remaining limit orders: %s", orders)
        assert orders
        for order in orders:
            if order.status == ORDER_STATUS_PARTIALLY_FILLED and order.order_id:
                await self.cancel_order(order_id=order.order_id, symbol=symbol)
                order.status = ORDER_STATUS_CANCELED

                logger.info(
                    "Cancelled partially filled order with id: %s", order.order_id
                )
            elif order.status == ORDER_STATUS_NEW and order.order_id:
                await self.cancel_order(order_id=order.order_id, symbol=symbol)
                order.status = ORDER_STATUS_CANCELED
                logger.info("Cancelled new order with id: %s", order.order_id)

        return orders
