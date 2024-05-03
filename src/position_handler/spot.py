import datetime
from typing import List
from logging_config import StrategyLogger
from src.common.common import generate_position_id
from src.common.identifiers.common import (
    BinanceClient,
    Order,
    OrderUpdate,
    PositionSide,
    PositionStatus,
)
from src.common.identifiers.spot import Position, State, StrategyConfig
from src.gui.gui_handler.spot import GuiHandler
from src.order_handler.spot import OrderHandler


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
        self.order_handler = OrderHandler(
            client=client,
            strategy_logger=strategy_logger,
            gui_handler=gui_handler,
        )
        self.strategy_logger = strategy_logger
        self.gui_handler: GuiHandler = gui_handler
        self.stagnation_counter: int = 0
        self.prev_orders: List[Order] = []
        self.next_monitor_position_time: datetime.datetime

    async def open_position(
        self,
        side: PositionSide,
        symbol: str,
        name: str,
        budget: float,
        price_low: float,
        price_high: float,
        min_notional: float,
    ) -> None:
        self.position = Position(
            id=generate_position_id(strategy_name=name),
            symbol=symbol,
            side=side,
        )
        self.strategy_logger.info("Position created: %s", self.position)
        self.position.orders = self.order_handler.prepare_orders(
            symbol=symbol,
            side=side,
            budget=budget,
            price_low=price_low,
            price_high=price_high,
            min_notional=min_notional,
        )
        self.position.orders = await self.order_handler.create_orders(
            side=side, orders=self.position.orders, symbol=symbol
        )
        self.next_monitor_position_time = datetime.datetime.now() + datetime.timedelta(
            hours=1
        )

        self.position.state = State.OPEN

        # Update GUI
        await self.gui_handler.update_strategy(
            strategy_name=self.config.name, position=self.position
        )

        self.position.status = PositionStatus.OPEN
        self.strategy_logger.info("Position opened successfully.")

    async def close_position(self) -> None:
        self.strategy_logger.info(
            "Enter close position, quant: %s", self.position.quantity
        )

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
        self.position.status = PositionStatus.CLOSING

    async def handle_order_partially_filled(self, order_update: OrderUpdate) -> None:
        for order in self.position.orders:
            if order_update.order_id == order.order_id:
                order.status = order_update.status
                order.price = order_update.price
                order.quantity = order_update.quantity
                order.realized_quantity = order_update.realized_quantity
                self.strategy_logger.info("Order: %s partially filled", order.order_id)

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

    async def handle_order_filled(self, order_update: OrderUpdate) -> None:
        for order in self.position.orders:
            if order_update.order_id == order.order_id:
                order.status = order_update.status
                order.price = order_update.price
                order.quantity = order_update.quantity
                order.realized_quantity = order_update.realized_quantity
                self.strategy_logger.info("Order: %s filled", order.order_id)

        await self.gui_handler.update_order(
            order=order,
            symbol=self.position.symbol,
            side=self.position.side,
        )
        await self.gui_handler.update_position(position=self.position)
        await self.gui_handler.update_strategy(
            strategy_name=self.config.name, position=self.position
        )
