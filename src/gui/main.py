import asyncio
import logging

from kivy.uix.boxlayout import BoxLayout

from src.trading_system import TradingSystem


logger = logging.getLogger("gui_main")


class MainWindow(BoxLayout):
    def __init__(self, **kwargs):
        super(MainWindow, self).__init__(**kwargs)
        self.update_queue = asyncio.Queue()
        self.trading_system = TradingSystem("RSI_Extended", self.update_queue)
        asyncio.create_task(self.process_updates())

    @classmethod
    async def create(cls, **kwargs):
        self = MainWindow(**kwargs)
        await self.post_init()
        return self

    async def post_init(self):
        await self.trading_system.initialize()

    async def process_updates(self):
        while True:
            update = await self.update_queue.get()
            logger.info("Update: %s", update)
            # Update the UI according to `update`
