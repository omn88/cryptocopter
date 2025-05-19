import asyncio
import logging
import queue
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

from src.broker import BrokerSpot
from src.identifiers.common import BinanceClient, PositionSide
from src.common.symbol_info import SymbolInfo

from src.database import Database
from src.identifiers.spot import (
    ExecutionReport,
    HPSellConfig,
    Order,
    SellPosition,
    SellType,
    State,
    StateInfo,
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
    UiState,
)
from src.portfolio.usd_price_resolver import UsdPriceResolver


logger = logging.getLogger("pos_handler")


class HPPositionSell:
    def __init__(
        self,
        client: BinanceClient,
        original_position: SellPosition,
        sell_strategy: List[SymbolInfo],
        db: Database,
        price_resolver: UsdPriceResolver,
        broker: BrokerSpot,
        worker_queue: queue.Queue,
    ):
        self.client = client
        self.original_position = original_position
        self.db = db
        self.sell_strategy = sell_strategy
        self.broker = broker
        self.price_resolver = price_resolver
        self.worker_queue = worker_queue

        self.sell_positions: List[SellPosition] = []
        self.current_position: SellPosition = SellPosition(
            Order(quantity=0),
            config=HPSellConfig(symbol_info=SymbolInfo()),
            state_info=StateInfo(side=PositionSide.SHORT),
            sell_type=SellType.DIRECT,
        )

        self._initialize_positions()

    def _initialize_positions(self) -> None:
        """Initializes sell positions and sets the current active position."""

        self._build_sell_positions()

        if self.sell_positions:
            self.current_position = self.sell_positions[0]

        if len(self.sell_positions) == 2:
            for position in self.sell_positions:
                self.broker.subscribe(
                    system_id=self.original_position.config.hp_id,
                    subscription_info=SubscriptionInfo(
                        data_type=SubscriptionType.PRICE,
                        symbol=position.config.symbol_info.symbol,
                        target=SubscriptionTarget.BACKEND,
                        queue=self.worker_queue,
                    ),
                )
                self.broker.subscribe(
                    system_id=self.original_position.config.hp_id,
                    subscription_info=SubscriptionInfo(
                        data_type=SubscriptionType.USER,
                        symbol=position.config.symbol_info.symbol,
                        target=SubscriptionTarget.BACKEND,
                        queue=self.worker_queue,
                    ),
                )
        self.broker.subscribe(
            system_id=self.original_position.config.hp_id,
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol=self.original_position.config.symbol_info.symbol,
                target=SubscriptionTarget.BACKEND,
                queue=self.worker_queue,
            ),
        )

    def _build_sell_positions(self) -> None:
        if not self.sell_strategy:
            self.sell_positions = []

        assert len(self.sell_strategy) <= 2, "Only 1 or 2-hop strategies are supported."

        if len(self.sell_strategy) == 1:
            self.sell_positions = self._build_1hop_position(self.sell_strategy[0])
        if len(self.sell_strategy) == 2:
            self.sell_positions = self._build_2hop_positions(self.sell_strategy)

    def _build_1hop_position(self, symbol_info: SymbolInfo) -> List[SellPosition]:
        if not symbol_info.symbol.endswith("USDT"):
            sell_position = SellPosition(
                config=self.original_position.config,
                state_info=self.original_position.state_info,
                sell_order=self._generate_order(
                    symbol_info,
                    quantity=self.original_position.config.quantity,
                    price=self.original_position.config.sell_price,
                ),
                sell_type=SellType.DIRECT,
            )
            return [sell_position]

        sell_position = SellPosition(
            config=self.original_position.config,
            state_info=self.original_position.state_info,
            sell_order=self._generate_order(
                symbol_info,
                quantity=self.original_position.config.quantity,
                price=self.original_position.config.sell_price,
            ),
            sell_type=SellType.CONVERT,
        )
        return [sell_position]

    def _build_2hop_positions(
        self, sell_strategy: List[SymbolInfo]
    ) -> List[SellPosition]:
        original = self.original_position
        sell_price = original.config.sell_price
        quantity = original.config.quantity

        leg1_info = sell_strategy[0]
        leg2_info = sell_strategy[1]

        leg2_price = self.price_resolver.latest_prices.get(leg2_info.symbol)
        if not leg2_price:
            raise ValueError(f"{leg2_info.symbol} price is missing from feed")

        # Convert target sell_price in USDC to quote token of leg1 (e.g. BTC)
        price_in_quote = sell_price / leg2_info.adjust_price(leg2_price)

        leg1_price = leg1_info.adjust_price(price_in_quote)
        leg1_quantity = leg1_info.adjust_quantity(quantity)
        leg1_quantity_stable = round(leg1_quantity * leg1_price, 8)

        leg2_price_adjusted = leg2_info.adjust_price(
            self.price_resolver.latest_prices[leg2_info.symbol]
        )
        leg2_quantity = leg2_info.adjust_quantity(leg1_quantity_stable)

        logger.info("Original sell data: %s", original)
        logger.info("Sell price: %s", sell_price)
        logger.info("Leg2 price: %s", leg2_price)
        logger.info("price in quote: %s", price_in_quote)

        logger.info("leg1_price: %s", leg1_price)
        logger.info("leg1_quantity: %s", leg1_quantity)
        logger.info("leg2_quantity: %s", leg2_quantity)

        sell_positions = [
            SellPosition(
                config=HPSellConfig(
                    hp_id=f"{self.original_position.config.hp_id}a",
                    is_child=True,
                    parent_hp_id=self.original_position.config.hp_id,
                    symbol_info=leg1_info,
                    quantity=leg1_quantity,
                    sell_price=leg1_price,
                    coin=self.original_position.config.coin,
                    buy_price=self.original_position.config.buy_price / leg2_price,
                ),
                state_info=StateInfo(side=PositionSide.SHORT),
                sell_order=self._generate_order(
                    symbol_info=leg1_info,
                    quantity=leg1_quantity,
                    price=leg1_price,
                ),
                sell_type=SellType.TWOHOPS,
            ),
            SellPosition(
                config=HPSellConfig(
                    hp_id=f"{self.original_position.config.hp_id}b",
                    is_child=True,
                    parent_hp_id=self.original_position.config.hp_id,
                    symbol_info=leg2_info,
                    quantity=leg2_quantity,
                    sell_price=leg2_price,
                    coin=leg2_info.extract_coin_from_symbol(leg2_info.symbol),
                    buy_price=leg2_price,
                ),
                state_info=StateInfo(
                    side=PositionSide.SHORT, state=State.WAITING_CHILD
                ),
                sell_order=self._generate_order(
                    symbol_info=leg2_info,
                    quantity=leg2_info.adjust_quantity(leg1_quantity_stable),
                    price=leg2_price_adjusted,
                ),
                sell_type=SellType.TWOHOPS,
            ),
        ]
        return sell_positions

    def _generate_order(
        self, symbol_info: SymbolInfo, price: float, quantity: float
    ) -> Order:
        return Order(
            quantity=symbol_info.adjust_quantity(quantity=quantity),
            price=symbol_info.adjust_price(price=price),
            precision=symbol_info.precision,
            price_precision=symbol_info.price_precision,
            quantity_stable=symbol_info.adjust_price(price * quantity),
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
        try:
            if self.current_position.sell_order.status != ORDER_STATUS_FILLED:
                logger.info(
                    "Trying to send sell order: %s, side: %s, symbol info: %s",
                    self.current_position.sell_order,
                    self.current_position.state_info.side,
                    self.current_position.config.symbol_info,
                )
                self.current_position.sell_order = await self._create_order(
                    side=self.current_position.state_info.side,
                    order=self.current_position.sell_order,
                    symbol_info=self.current_position.config.symbol_info,
                )
                logger.info(
                    "New %s order send for %s at price: %s, quantity: %s and status: %s [id: %s]",
                    self.current_position.state_info.side.value,
                    self.current_position.config.symbol_info.symbol,
                    self.current_position.sell_order.price,
                    self.current_position.sell_order.quantity_stable,
                    self.current_position.sell_order.status,
                    self.current_position.sell_order.order_id,
                )
        except AssertionError as error:
            logger.error("Error: %s", error)

    async def cancel_position(self) -> None:
        assert isinstance(self.current_position, SellPosition)
        logger.info(
            "Start canceling position: %s %s, hp id: %s",
            self.current_position.config.symbol_info.symbol,
            self.current_position.state_info.side,
            self.current_position.config.hp_id,
        )
        self.current_position.state_info.stagnation_counter = 0

        await self.cancel_remaining_order()
        # if self.current_position.sell_order.status == ORDER_STATUS_CANCELED:
        #     self.db.upsert_order(
        #         order=self.current_position.sell_order,
        #         hp_id=self.current_position.config.hp_id,
        #         side=self.current_position.state_info.side,
        #     )

        self.current_position.state_info.completeness = round(
            self.current_position.sell_order.realized_quantity
            / self.current_position.sell_order.quantity,
            2,
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

            # self.db.upsert_order(
            #     order=self.current_position.sell_order,
            #     hp_id=self.current_position.config.hp_id,
            #     side=self.current_position.state_info.side,
            # )
            logger.info(
                "Order: %s partially filled", self.current_position.sell_order.order_id
            )

        logger.info(
            "Stagnation counter reset for system: %s, realized sell quantity: %s",
            self.current_position.config.hp_id,
            self.current_position.sell_order.realized_quantity,
        )
        self.current_position.state_info.stagnation_counter = 0
        self.current_position.state_info.generate_next_monitor_time()
        self.current_position.state_info.completeness = round(
            self.current_position.sell_order.realized_quantity
            / self.current_position.sell_order.quantity,
            2,
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

            # self.db.upsert_order(
            #     order=self.current_position.sell_order,
            #     hp_id=self.current_position.config.hp_id,
            #     side=self.current_position.state_info.side,
            # )

        self.current_position.state_info.ui_state = UiState.OPEN
        self.current_position.state_info.stagnation_counter = 0
        self.current_position.state_info.generate_next_monitor_time()

        self.current_position.state_info.completeness = round(
            self.current_position.sell_order.realized_quantity
            / self.current_position.sell_order.quantity,
            2,
        )

        logger.info("Completeness: %s", self.current_position.state_info.completeness)
        logger.info(
            "Stagnation counter reset for system: %s",
            self.current_position.config.hp_id,
        )

    async def cancel_remaining_order(self) -> None:
        if (
            self.current_position.sell_order.status == ORDER_STATUS_PARTIALLY_FILLED
            and self.current_position.sell_order.order_id
        ):
            await self._cancel_order(
                order_id=self.current_position.sell_order.order_id,
                symbol=self.current_position.config.symbol_info.symbol,
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
                symbol=self.current_position.config.symbol_info.symbol,
            )
            self.current_position.sell_order.status = ORDER_STATUS_CANCELED
            logger.info(
                "Cancelled new order with id: %s",
                self.current_position.sell_order.order_id,
            )

    async def _create_order(
        self, side: PositionSide, order: Order, symbol_info: SymbolInfo
    ) -> Order:
        max_retries = 10
        last_exception = None
        for _ in range(max_retries):
            try:
                price = symbol_info.format_price(order.price)

                quantity = symbol_info.adjust_quantity(
                    order.quantity - order.realized_quantity
                )
                symbol_info.validate_order(price=float(price), quantity=quantity)

                logger.info(
                    "Before actual order sending(%s): %s", symbol_info.symbol, order
                )

                resp = await self.client.create_order(
                    symbol=symbol_info.symbol,
                    price=price,
                    quantity=quantity,
                    side=side.value,
                    type=ORDER_TYPE_LIMIT,
                    timeInForce=TIME_IN_FORCE_GTC,
                )
                logger.info("After sending(%s): %s", symbol_info.symbol, order)
                logger.info("Response: %s", resp)
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
