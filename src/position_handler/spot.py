import datetime
from typing import List
from logging_config import StrategyLogger
from src.common.identifiers.common import (
    BinanceClient,
    Order,
    OrderUpdate,
    PositionSide,
    PositionStatus,
)
from src.common.identifiers.spot import State, StrategyConfig
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
        self.strategy_logger = strategy_logger
        self.gui_handler = gui_handler
        self.order_handler = OrderHandler(
            client=client,
            strategy_logger=strategy_logger,
            gui_handler=gui_handler,
        )
        self.orders: List[Order] = self.order_handler.prepare_orders(
            budget=config.budget,
            price_low=config.price_low,
            price_high=config.price_high,
            min_notional=config.min_notional,
        )

        self.stagnation_counter: int = 0
        self.prev_orders: List[Order] = []
        self.next_monitor_position_time: datetime.datetime = datetime.datetime.now()

        self.state: State = State.NEW
        self.side: PositionSide = PositionSide.FLAT
        self.status: PositionStatus = PositionStatus.NEW
        self.opened: bool = False

    async def open_position(
        self,
        side: PositionSide,
        symbol: str,
    ) -> None:
        self.orders = await self.order_handler.create_orders(
            side=side, orders=self.orders, symbol=symbol
        )
        self.next_monitor_position_time = datetime.datetime.now() + datetime.timedelta(
            hours=1
        )

        self.state = State.OPEN

        # Update GUI
        # await self.gui_handler.update_price_level(
        #     strategy_name=self.config.name, position=self.position
        # )
        self.status = PositionStatus.OPEN
        self.strategy_logger.info("Position opened successfully: %s", self)

    async def cancel_position(self) -> None:
        self.strategy_logger.info("Enter cancel position")

        self.orders = await self.order_handler.cancel_remaining_limit_orders(
            symbol=self.config.symbol,
            orders=self.orders,
            side=self.side,
        )

        # await self.gui_handler.update_position(position=self.position)
        # await self.gui_handler.update_strategy(
        #     strategy_name=self.config.name,
        #     position=self.position,
        # )
        self.status = PositionStatus.STAGNATED

    async def handle_order_partially_filled(self, order_update: OrderUpdate) -> None:
        for order in self.orders:
            if order_update.order_id == order.order_id:
                order.status = order_update.status
                order.price = order_update.price
                order.quantity = order_update.quantity
                order.realized_quantity = order_update.realized_quantity
                self.strategy_logger.info("Order: %s partially filled", order.order_id)

        #         await self.gui_handler.update_order(
        #             order=order,
        #             symbol=self.position.symbol,
        #             side=self.position.side,
        #         )
        # await self.gui_handler.update_position(position=self.position)
        # await self.gui_handler.update_strategy(
        #     strategy_name=self.config.name, position=self.position
        # )

    async def handle_order_filled(self, order_update: OrderUpdate) -> None:
        for order in self.orders:
            if order_update.order_id == order.order_id:
                order.status = order_update.status
                order.price = order_update.price
                order.quantity = order_update.quantity
                order.realized_quantity = order_update.realized_quantity
                self.strategy_logger.info("Order: %s filled", order.order_id)

        #         await self.gui_handler.update_order(
        #             order=order,
        #             symbol=self.position.symbol,
        #             side=self.position.side,
        #         )
        # await self.gui_handler.update_position(position=self.position)
        # await self.gui_handler.update_strategy(
        #     strategy_name=self.config.name, position=self.position
        # )
