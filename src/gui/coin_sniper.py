import asyncio
from typing import List, Tuple

from binance.enums import (
    ORDER_STATUS_FILLED,
    ORDER_STATUS_EXPIRED,
    ORDER_STATUS_CANCELED,
)
from kivy.properties import (
    ListProperty,
    NumericProperty,
    StringProperty,
    ObjectProperty,
)
from kivy.uix.boxlayout import BoxLayout
from logging_config import StrategyLogger
from src.common.identifiers import EventName, Event, Position, State
from src.gui.gui_handler import GuiHandlerSpot
from src.gui.identifiers import (
    AccountData,
    PositionData,
    OrderData,
    PriceData,
    PositionStatus,
)

from src.trading_system import TradingSystem


class CoinSniperTab(BoxLayout):
    strategy_name = StringProperty("")
    symbol = StringProperty("")
    price_label = StringProperty("0")
    open_positions = ListProperty([])
    open_orders = ListProperty([])
    closed_orders = ListProperty([])
    closed_positions = ListProperty([])

    order_count = NumericProperty(0)
    position_count = NumericProperty(0)

    log_display = ObjectProperty(None)

    def __init__(
        self,
        trading_system: TradingSystem,
        gui_handler: GuiHandlerSpot,
        strategy_logger: StrategyLogger,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.trading_system: TradingSystem = trading_system
        self.gui_handler: GuiHandlerSpot = gui_handler
        self.strategy_logger: StrategyLogger = strategy_logger
        asyncio.create_task(self.update_ui())

    async def update_ui(self):
        while True:
            self.strategy_logger.debug(
                "Events in UI queue: %s", self.gui_handler.ui_queue.qsize()
            )
            if self.gui_handler.ui_queue.qsize() == 0:
                self.strategy_logger.debug("Awaiting new Event")
            data = await self.gui_handler.ui_queue.get()
            # Update the UI based on data
            if isinstance(data, Event):
                if data.name == EventName.SENTINEL:
                    self.strategy_logger.info("SENTINEL -> Exiting UI updates.")
                    await asyncio.sleep(3)
                    return
            if isinstance(data, AccountData):
                self.strategy_logger.info("PANU  DYS IS update account")
                # self.balance_label = f"{str(data.balance)} USDT"
            if isinstance(data, PositionData):
                self.update_position(data=data)

            if isinstance(data, OrderData):
                self.open_orders, self.closed_orders = self.update_order(
                    data=data,
                    open_orders=self.open_orders,
                    closed_orders=self.closed_orders,
                )

            if isinstance(data, PriceData):
                self.price_label = str(data.mark_price)
                for position in self.open_positions:
                    if (
                        position["symbol"] == data.symbol
                        and position["status"] != PositionStatus.CLOSED.value
                    ):
                        self.open_positions = self.update_price_data(data=data)
