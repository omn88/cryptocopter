import asyncio
from logging_config import StrategyLogger

from src.common.identifiers.spot import Position
from src.gui.identifiers.spot import PositionData


class GuiHandler:
    def __init__(
        self,
        ui_queue: asyncio.Queue,
        main_ui_queue: asyncio.Queue,
        logger: StrategyLogger,
    ):
        self.ui_queue = ui_queue
        self.main_ui_queue = main_ui_queue
        self.logger = logger

    async def update_position(self, position: Position):
        position_data = self.prepare_position_data(position=position)
        await self.ui_queue.put(position_data)
        self.logger.info("PositionData added to UI queue: %s", position_data)

    def prepare_position_data(self, position: Position) -> PositionData:
        return PositionData(
            system_id=position.id,
            symbol=position.symbol,
            status=position.status,
        )

    # async def update_position(self, position: Position):
    #     position_data = self._prepare_position_data(position=position)
    #     await self.ui_queue.put(position_data)
    #     self.logger.info("PositionData added to UI queue: %s", position_data)

    # async def update_strategy(self, position: Position, strategy_name: str):
    #     strategy_data = self._prepare_strategy_data(
    #         position_data=self._prepare_position_data(position=position),
    #         strategy_name=strategy_name,
    #     )
    #     await self.main_ui_queue.put(strategy_data)
    #     self.logger.info("StrategyData added to UI queue: %s", strategy_data)

    # async def create_orders(self, orders: List[Order], symbol: str, side: PositionSide):
    #     for order in orders:
    #         await self.update_order(order=order, symbol=symbol, side=side)

    # def _prepare_order_data(
    #     self, order: Order, symbol: str, side: PositionSide
    # ) -> OrderData:
    #     return OrderData(
    #         order_id=order.order_id,
    #         open_time=order.open_time,
    #         symbol=symbol,
    #         order_type=order.order_type,
    #         side=side.value,
    #         price=order.price,
    #         quantity=order.quantity,
    #         realized_quantity=order.realized_quantity,
    #         status=order.status,
    #     )

    # def _prepare_strategy_data(self, position_data: PositionData, strategy_name: str):
    #     return StrategyData(strategy_name=strategy_name, position_data=position_data)
