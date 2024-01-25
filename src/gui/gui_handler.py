import asyncio

from src.gui.identifiers import OrderData, PositionData, StrategyData


class GuiHandler:
    def __init__(self, ui_queue: asyncio.Queue, main_ui_queue: asyncio.Queue):
        self.ui_queue = ui_queue
        self.main_ui_queue = main_ui_queue

    async def update_order(self, order_data: OrderData):
        await self.ui_queue.put(order_data)

    async def update_position(self, position_data: PositionData):
        await self.ui_queue.put(position_data)

    async def update_strategy(self, strategy_data: StrategyData):
        await self.main_ui_queue.put(strategy_data)
