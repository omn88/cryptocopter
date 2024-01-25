from typing import List, Tuple
from binance.enums import SIDE_BUY, SIDE_SELL, ORDER_STATUS_FILLED
from logging_config import StrategyLogger
from src.common.common import generate_position_id, signal_to_state
from src.common.constants import LEVERAGE
from src.common.identifiers import (
    BinanceClient,
    Order,
    OrderUpdate,
    Position,
    PositionMode,
    PositionSide,
    PositionStatus,
    SignalUpdate,
    State,
)
from src.gui.identifiers import OrderData, PositionData
from src.order_handler import OrderHandler


class PositionHandler:
    def __init__(
        self,
        client: BinanceClient,
        strategy_logger: StrategyLogger,
        budget: float,
        number_of_orders: int,
    ):
        self.client = client
        self.budget = budget
        self.number_of_orders = number_of_orders
        self.position: Position = Position()
        self.closed_positions: List[Position] = []
        self.order_handler = OrderHandler(
            client=client,
            strategy_logger=strategy_logger,
            order_quantity_stable=(self.budget / (2 * self.number_of_orders)),
        )
        self.strategy_logger = strategy_logger

    async def open_position(
        self,
        side: PositionSide,
        signal_update: SignalUpdate,
        number_of_orders: int,
        symbol: str,
        mode: PositionMode,
        strategy_name: str,
    ) -> None:
        self.position = Position(
            id=generate_position_id(strategy_name=strategy_name),
            symbol=symbol,
            side=side,
            entry_price=signal_update.price,
        )

        self.position.orders = self.order_handler.prepare_orders(
            side=side,
            mode=mode,
            entry_price=signal_update.price,
            number_of_orders=number_of_orders,
        )

        self.position.orders = await self.order_handler.create_orders(
            side=side, orders=self.position.orders, symbol=symbol
        )

        self.position.state = signal_to_state(signal_update.signal)

    async def close_position(self) -> PositionData:
        self.strategy_logger.info(
            "Enter close position, quant: %s", self.position.quantity
        )
        if self.position.quantity:
            self.position.status = PositionStatus.CLOSING
            close_side = SIDE_BUY if self.position.quantity < 0 else SIDE_SELL
            self.strategy_logger.info(
                "Entering position close, trying to market %s", close_side
            )
            self.position.market_order = await self.order_handler.create_market_order(
                quantity=self.position.quantity,
                side=close_side,
                symbol=self.position.symbol,
            )

            self.position.take_profit_order.status = (
                await self.order_handler.cancel_order(
                    order=self.position.take_profit_order,
                    symbol=self.position.symbol,
                )
            )
            self.strategy_logger.info("Cancelled take profit order")

        self.position.orders = await self.order_handler.cancel_remaining_limit_orders(
            symbol=self.position.symbol, orders=self.position.orders
        )

        position_data = PositionData(
            symbol=self.position.symbol,
            quantity=self.position.quantity,
            entry_price=self.position.entry_price,
            mark_price=0,
            liquidation_price=self.position.liquidation_price,
            pnl=0,
            state=self.position.state,
            status=self.position.status,
        )

        self.closed_positions.append(self.position)

        self.strategy_logger.debug(
            "Number of closed positions: %s", len(self.closed_positions)
        )
        self.position = Position()

        return position_data

    async def update_take_profit_order(self) -> OrderData:
        take_profit_side = (
            PositionSide.LONG
            if self.position.side == PositionSide.SHORT
            else PositionSide.SHORT
        )
        if self.position.take_profit_order.order_id != 0:
            self.strategy_logger.info(
                "Enter update take profit order: %s, side: %s",
                self.position.take_profit_order.order_id,
                take_profit_side,
            )
            self.position.take_profit_order.status = (
                await self.order_handler.cancel_order(
                    order=self.position.take_profit_order,
                    symbol=self.position.symbol,
                )
            )

        self.position.take_profit_order = await self.order_handler.create_order(
            side=take_profit_side,
            order=Order(
                price=self.order_handler.target_price_calculate(
                    side=self.position.side,
                    price=self.position.entry_price,
                ),
                quantity=self.position.quantity,
                quantity_stable=round(
                    (
                        abs(self.position.quantity)
                        * self.position.entry_price
                        / LEVERAGE
                    ),
                    2,
                ),
            ),
            symbol=self.position.symbol,
        )

        take_profit_order = self.position.take_profit_order

        assert isinstance(take_profit_order, Order)
        self.strategy_logger.info(
            "New take profit buy order send, price: %s, quantity: %s realized QUANT: %s",
            take_profit_order.price,
            take_profit_order.quantity,
            take_profit_order.realized_quantity,
        )

        return OrderData(
            open_time=take_profit_order.open_time,
            order_id=take_profit_order.order_id,
            symbol=self.position.symbol,
            order_type=take_profit_order.order_type,
            side=self.position.side.value,
            price=take_profit_order.price,
            quantity=take_profit_order.quantity,
            realized_quantity=take_profit_order.realized_quantity,
            status=take_profit_order.status,
        )

    async def position_liquidation(
        self,
        balance: float,
    ) -> Tuple[float, PositionData]:
        self.strategy_logger.info("Position liquidation")

        self.position.status = PositionStatus.CLOSING

        loss = 0.0
        assert self.position.orders is not None
        for order in self.position.orders:
            self.strategy_logger.info(
                "quantity: %s, price: %s", order.quantity, order.price
            )
            loss += order.quantity_stable

        balance -= round(loss, 2)

        self.closed_positions.append(self.position)

        position_data = PositionData(
            symbol=self.position.symbol,
            quantity=self.position.quantity,
            entry_price=self.position.entry_price,
            mark_price=0,
            liquidation_price=self.position.liquidation_price,
            pnl=0,
            state=self.position.state,
            status=self.position.status,
        )

        # IS THE CANCEL TAKE PROFIT REMOVED AUTOMATICALLY?

        # take_profit_order_data = OrderData(
        #     open_time=self.position.take_profit_order.open_time,
        #     order_id=self.position.take_profit_order.order_id,
        #     symbol=self.position.symbol,
        #     order_type=self.position.take_profit_order.order_type,
        #     side=self.position.side,
        #     price=self.position.take_profit_order.price,
        #     quantity=self.position.take_profit_order.quantity,
        #     realized_quantity=self.position.take_profit_order.realized_quantity,
        #     status=self.position.take_profit_order.status,
        # )

        self.position = Position()

        return balance, position_data

    async def partial_position_liquidation(
        self,
        order_update: OrderUpdate,
    ) -> None:
        self.strategy_logger.info(
            "Position liquidation in progress, order status: %s!",
            order_update.status,
        )

    async def target_partially_reached(
        self,
        order_update: OrderUpdate,
        balance: float,
    ) -> Tuple[float, PositionData, OrderData]:
        self.strategy_logger.info("Take profit order filled partially")

        assert isinstance(self.position.take_profit_order, Order)

        self.position.take_profit_order.status = order_update.status
        self.position.take_profit_order.quantity -= order_update.last_filled_quantity
        self.position.take_profit_order.realized_quantity += (
            order_update.last_filled_quantity
        )
        self.position.quantity -= order_update.last_filled_quantity

        self.strategy_logger.info(
            "Original quantity: %s, last filled quantity: %s, realized quantity: %s, remaining quantity: %s",
            order_update.quantity,
            order_update.last_filled_quantity,
            order_update.realized_quantity,
            self.position.take_profit_order.quantity,
        )

        realized_position = round(
            abs(
                order_update.last_filled_quantity
                * (self.position.take_profit_order.price - self.position.entry_price)
            ),
            2,
        )

        balance += realized_position

        self.strategy_logger.info("Earned: %s", round(realized_position, 2))

        position_data = PositionData(
            symbol=self.position.symbol,
            quantity=self.position.quantity,
            entry_price=self.position.entry_price,
            mark_price=0,
            liquidation_price=self.position.liquidation_price,
            pnl=0,
            state=self.position.state,
            status=self.position.status,
        )

        take_profit_order_data = OrderData(
            open_time=self.position.take_profit_order.open_time,
            order_id=self.position.take_profit_order.order_id,
            symbol=self.position.symbol,
            order_type=self.position.take_profit_order.order_type,
            side=self.position.side.value,
            price=self.position.take_profit_order.price,
            quantity=self.position.take_profit_order.quantity,
            realized_quantity=self.position.take_profit_order.realized_quantity,
            status=self.position.take_profit_order.status,
        )

        return balance, position_data, take_profit_order_data

    async def target_reached(
        self, order_update: OrderUpdate, balance: float
    ) -> Tuple[float, PositionData, OrderData]:
        self.strategy_logger.info("Take profit order filled")

        self.position.status = PositionStatus.CLOSING

        assert isinstance(self.position.take_profit_order, Order)

        self.position.take_profit_order.quantity -= order_update.last_filled_quantity
        self.position.take_profit_order.realized_quantity += (
            order_update.last_filled_quantity
        )
        self.position.quantity -= order_update.last_filled_quantity

        self.strategy_logger.info(
            "Original quantity: %s, last filled quantity: %s, realized quantity: %s, remaining quantity: %s",
            order_update.quantity,
            order_update.last_filled_quantity,
            order_update.realized_quantity,
            self.position.take_profit_order.quantity,
        )

        realized_position = round(
            abs(
                order_update.last_filled_quantity
                * (self.position.take_profit_order.price - self.position.entry_price)
            ),
            2,
        )

        balance += realized_position

        self.strategy_logger.info("Earned: %s", round(realized_position, 2))

        self.position.orders = await self.order_handler.cancel_remaining_limit_orders(
            orders=self.position.orders, symbol=self.position.symbol
        )

        self.closed_positions.append(self.position)

        position_data = PositionData(
            symbol=self.position.symbol,
            quantity=self.position.quantity,
            entry_price=self.position.entry_price,
            mark_price=0,
            liquidation_price=self.position.liquidation_price,
            pnl=0,
            state=self.position.state,
            status=self.position.status,
        )

        take_profit_order_data = OrderData(
            open_time=self.position.take_profit_order.open_time,
            order_id=self.position.take_profit_order.order_id,
            symbol=self.position.symbol,
            order_type=self.position.take_profit_order.order_type,
            side=self.position.side.value,
            price=self.position.take_profit_order.price,
            quantity=self.position.take_profit_order.quantity,
            realized_quantity=self.position.take_profit_order.realized_quantity,
            status=self.position.take_profit_order.status,
        )

        self.position = Position()

        return balance, position_data, take_profit_order_data

    async def handle_order_partially_filled(
        self, order_update: OrderUpdate
    ) -> Tuple[OrderData, OrderData, PositionData]:
        self.strategy_logger.info("Enter order update handle")

        for order in self.position.orders:
            if order_update.order_id == order.order_id:
                order.status = order_update.status
                order.price = order_update.price
                order.quantity = order_update.quantity
                order.realized_quantity = order_update.realized_quantity
                self.strategy_logger.info("Order: %s partially filled", order.order_id)

                part_filled_order_data = OrderData(
                    open_time=order.open_time,
                    order_id=order.order_id,
                    symbol=self.position.symbol,
                    order_type=order.order_type,
                    side=self.position.side.value,
                    price=order.price,
                    quantity=order.quantity,
                    realized_quantity=order.realized_quantity,
                    status=order.status,
                )

                (
                    self.position.liquidation_price,
                    self.position.entry_price,
                    self.position.quantity,
                ) = await self.futures_get_position_info()

                take_profit_order_data: OrderData = (
                    await self.update_take_profit_order()
                )
                self.strategy_logger.info("Exiting update position")

        self.strategy_logger.info("Exit order update handle")

        position_data = PositionData(
            symbol=self.position.symbol,
            quantity=self.position.quantity,
            entry_price=self.position.entry_price,
            mark_price=0,
            liquidation_price=self.position.liquidation_price,
            pnl=0,
            state=self.position.state,
            status=self.position.status,
        )

        return part_filled_order_data, take_profit_order_data, position_data

    async def futures_get_position_info(self) -> Tuple[float, float, float]:
        self.strategy_logger.info("Enter position information")

        resp = await self.client.futures_position_information(
            symbol=self.position.symbol
        )
        self.strategy_logger.info("RESP: %s", resp)
        liquidation_price = round(float(resp[0]["liquidationPrice"]), 1)
        entry_price = round(float(resp[0]["entryPrice"]), 1)
        position_amt = float(resp[0]["positionAmt"])

        self.strategy_logger.info("Exit position information")

        return liquidation_price, entry_price, position_amt

    async def handle_order_filled(
        self, order_update: OrderUpdate
    ) -> Tuple[OrderData, OrderData, PositionData]:
        self.strategy_logger.info("Enter order update handle")
        for order in self.position.orders:
            if order_update.order_id == order.order_id:
                if order.status == ORDER_STATUS_FILLED:
                    self.strategy_logger.info(
                        "Order: %s already filled", order.order_id
                    )
                else:
                    order.status = order_update.status
                    order.price = order_update.price
                    order.quantity = order_update.quantity
                    order.realized_quantity = order_update.realized_quantity
                    self.strategy_logger.info("Order: %s filled", order.order_id)

                    filled_order_data = OrderData(
                        open_time=order.open_time,
                        order_id=order.order_id,
                        symbol=self.position.symbol,
                        order_type=order.order_type,
                        side=self.position.side.value,
                        price=order.price,
                        quantity=order.quantity,
                        realized_quantity=order.realized_quantity,
                        status=order.status,
                    )

                (
                    self.position.liquidation_price,
                    self.position.entry_price,
                    self.position.quantity,
                ) = await self.futures_get_position_info()

                take_profit_order_data = await self.update_take_profit_order()
                self.strategy_logger.info(
                    "Exiting update position: %s", self.position.quantity
                )
        position_data = PositionData(
            symbol=self.position.symbol,
            quantity=self.position.quantity,
            entry_price=self.position.entry_price,
            mark_price=0,
            liquidation_price=self.position.liquidation_price,
            pnl=0,
            state=self.position.state,
            status=self.position.status,
        )

        self.strategy_logger.info("Exit order update handle")
        return filled_order_data, take_profit_order_data, position_data

        # async def update_position(self, position_id, update_info):

    async def market_order_filled(self, order_update: OrderUpdate):
        self.strategy_logger.info("MARKET order filled!")
        assert self.position.market_order is not None

        self.position.market_order.status = order_update.status
        self.position.market_order.price = order_update.price
        self.position.market_order.quantity = order_update.quantity
        self.position.market_order.realized_quantity = order_update.realized_quantity

    async def market_order_filled_partially(self, order_update: OrderUpdate):
        self.position.market_order = Order(
            price=order_update.price,
            quantity=order_update.quantity,
            order_id=order_update.order_id,
            realized_quantity=order_update.realized_quantity,
            status=order_update.status,
        )
        self.strategy_logger.info(
            "Market order realization in progress: %s!",
            self.position.market_order,
        )

    # async def confirm_position(self, position_id):
    #     # Logic to confirm that all actions related to the old position are completed
    #     position = self.positions.get(position_id)
    #     if position:
    #         position.status = PositionStatus.CONFIRMED
    #         # Perform any additional logic needed after confirmation
    #         self.strategy_logger.info(f"Position {position_id} confirmed.")

    # def archive_position(self, position_id):
    #     if position_id in self.positions:
    #         position = self.positions.pop(position_id)
    #         self.archived_positions[position_id] = position
    #         self.strategy_logger.info(f"Position {position_id} archived.")
