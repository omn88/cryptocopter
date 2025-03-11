from typing import List
import uuid
from binance.enums import SIDE_BUY, SIDE_SELL, ORDER_STATUS_FILLED
from logging_config import StrategyLogger
from src.common.common import signal_to_state
from src.identifiers.common import (
    BinanceClient,
    PositionSide,
)
from src.identifiers.futures import (
    OrderUpdate,
    Position,
    PositionMode,
    PositionStatus,
    StrategyConfig,
    SignalUpdate,
    Order,
)
from src.gui.gui_handler.futures import GuiHandler
from src.futures.order_handler.futures import OrderHandler


class PositionHandler:
    def __init__(
        self,
        client: BinanceClient,
        strategy_logger: StrategyLogger,
        config: StrategyConfig,
        gui_handler: GuiHandler,
    ):
        self.config = config
        self.position: Position = Position()
        self.closed_positions: List[Position] = []
        self.order_handler = OrderHandler(
            client=client,
            strategy_logger=strategy_logger,
            order_quantity_stable=(
                self.config.budget / (2 * self.config.number_of_orders)
            ),
            gui_handler=gui_handler,
        )
        self.strategy_logger = strategy_logger
        self.gui_handler: GuiHandler = gui_handler

    async def open_position(
        self,
        side: PositionSide,
        signal_update: SignalUpdate,
        mode: PositionMode,
        config: StrategyConfig,
    ) -> None:
        self.position = Position(
            id=str(uuid.uuid4()),
            symbol=config.symbol,
            side=side,
            entry_price=signal_update.price,
            leverage=config.leverage,
        )
        self.strategy_logger.info("Position created: %s", self.position)
        self.position.orders = self.order_handler.prepare_orders(
            side=side,
            mode=mode,
            entry_price=signal_update.price,
            number_of_orders=config.number_of_orders,
            dca_span=self.config.dca_span,
            leverage=self.config.leverage,
        )
        self.position.entry_price = signal_update.price
        self.position.orders = await self.order_handler.create_orders(
            side=side, orders=self.position.orders, symbol=config.symbol
        )
        self.position.state = signal_to_state(signal_update.signal)

        # Update GUI
        await self.gui_handler.update_strategy(
            strategy_name=self.config.name, position=self.position
        )
        self.strategy_logger.info("Position opened successfully.")

    async def close_position(self) -> None:
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

            self.position.take_profit_order = await self.order_handler.cancel_order(
                order=self.position.take_profit_order,
                symbol=self.position.symbol,
            )
            await self.gui_handler.update_order(
                order=self.position.take_profit_order,
                side=self.position.side,
                symbol=self.position.symbol,
            )
            self.strategy_logger.info("Cancelled take profit order")

        self.position.orders = await self.order_handler.cancel_remaining_limit_orders(
            symbol=self.position.symbol,
            orders=self.position.orders,
            side=self.position.side,
        )

        await self.gui_handler.update_position(position=self.position)
        await self.gui_handler.update_strategy(
            strategy_name=self.config.name,
            position=self.position,
        )

        self.closed_positions.append(self.position)

        self.strategy_logger.debug(
            "Number of closed positions: %s", len(self.closed_positions)
        )
        self.position = Position()

    async def position_liquidation(
        self,
        balance: float,
    ) -> float:
        self.strategy_logger.info("Position liquidation")

        self.position.status = PositionStatus.CLOSED

        loss = 0.0
        assert self.position.orders is not None
        for order in self.position.orders:
            self.strategy_logger.info(
                "quantity: %s, price: %s", order.quantity, order.price
            )
            loss += order.quantity_stable

        balance -= round(loss, 2)

        await self.gui_handler.update_position(position=self.position)
        await self.gui_handler.update_strategy(
            strategy_name=self.config.name,
            position=self.position,
        )

        self.closed_positions.append(self.position)

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

        return balance

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
    ) -> float:
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

        await self.gui_handler.update_order(
            order=self.position.take_profit_order,
            symbol=self.position.symbol,
            side=self.position.side,
        )
        await self.gui_handler.update_position(position=self.position)
        await self.gui_handler.update_strategy(
            position=self.position, strategy_name=self.config.name
        )

        return balance

    async def target_reached(self, order_update: OrderUpdate, balance: float) -> float:
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
            orders=self.position.orders,
            symbol=self.position.symbol,
            side=self.position.side,
        )

        self.position.status = PositionStatus.CLOSED
        await self.gui_handler.update_order(
            order=self.position.take_profit_order,
            side=self.position.side,
            symbol=self.position.symbol,
        )

        await self.gui_handler.update_position(position=self.position)
        await self.gui_handler.update_strategy(
            position=self.position, strategy_name=self.config.name
        )

        self.closed_positions.append(self.position)

        self.position = Position()

        return balance

    async def handle_order_partially_filled(self, order_update: OrderUpdate) -> None:
        await self.get_position_info()

        # cancel take profit if exists
        if self.position.take_profit_order.order_id:
            self.position.take_profit_order = await self.order_handler.cancel_order(
                order=self.position.take_profit_order,
                symbol=self.config.symbol,
            )
            await self.gui_handler.update_order(
                order=self.position.take_profit_order,
                symbol=self.position.symbol,
                side=self.position.side,
            )
            self.strategy_logger.info(
                "Cancelled take profit order with id: %s",
                self.position.take_profit_order.order_id,
            )

        # create new take profit order
        self.position.take_profit_order = (
            await self.order_handler.create_take_profit_order(
                position=self.position,
                leverage=self.config.leverage,
            )
        )

        for order in self.position.orders:
            if order_update.order_id == order.order_id:
                order.status = order_update.status
                order.price = order_update.price
                order.quantity = order_update.quantity
                order.realized_quantity = order_update.realized_quantity
                self.strategy_logger.info("Order: %s partially filled", order.order_id)
                self.position.margin += round(
                    (
                        order_update.last_filled_quantity
                        * order_update.price
                        / self.config.leverage
                    ),
                    2,
                )

                part_filled_ord = order

        await self.gui_handler.update_order(
            order=part_filled_ord,
            symbol=self.position.symbol,
            side=self.position.side,
        )
        await self.gui_handler.update_position(position=self.position)
        await self.gui_handler.update_strategy(
            strategy_name=self.config.name, position=self.position
        )

    async def get_position_info(self) -> None:
        resp = await self.order_handler.client.futures_position_information(
            symbol=self.position.symbol
        )
        self.position.liquidation_price = round(float(resp[0]["liquidationPrice"]), 1)
        self.position.entry_price = round(float(resp[0]["entryPrice"]), 1)
        self.position.quantity = float(resp[0]["positionAmt"])

        self.strategy_logger.info("Position update: %s", resp)

    async def handle_order_filled(self, order_update: OrderUpdate) -> None:
        await self.get_position_info()

        # cancel take profit if exists
        if self.position.take_profit_order.order_id:
            self.position.take_profit_order = await self.order_handler.cancel_order(
                order=self.position.take_profit_order,
                symbol=self.position.symbol,
            )
            self.strategy_logger.info(
                "Cancelled take profit order with id: %s",
                self.position.take_profit_order.order_id,
            )
            await self.gui_handler.update_order(
                order=self.position.take_profit_order,
                side=PositionSide.SHORT
                if self.position.side == PositionSide.LONG
                else PositionSide.LONG,
                symbol=self.position.symbol,
            )
            self.strategy_logger.info("GUI order updated")

        # create new take profit
        self.position.take_profit_order = (
            await self.order_handler.create_take_profit_order(
                position=self.position,
                leverage=self.config.leverage,
            )
        )

        # update order status
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
                    self.position.margin += round(
                        (
                            order_update.last_filled_quantity
                            * order_update.price
                            / self.config.leverage
                        ),
                        2,
                    )

                filled_order = order

        self.strategy_logger.info("Order: %s filled", filled_order.order_id)

        await self.gui_handler.update_order(
            order=filled_order,
            symbol=self.position.symbol,
            side=self.position.side,
        )
        await self.gui_handler.update_position(position=self.position)
        await self.gui_handler.update_strategy(
            strategy_name=self.config.name, position=self.position
        )
