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
    ObjectProperty,
)
from kivy.uix.boxlayout import BoxLayout
from logging_config import StrategyLogger
from src.common.identifiers import BinanceClient, CoinSniperConfig, EventName, Event
from src.gui.gui_handler import GuiHandlerSpot
from src.gui.identifiers import (
    AccountData,
    PositionData,
    OrderData,
    PriceData,
    PositionStatus,
)
from src.trading_system import TradingSystemSpot


class CoinSniper(BoxLayout):
    trading_systems = ListProperty([])
    active_strategies = ListProperty([])
    closed_strategies = ListProperty([])
    open_positions = ListProperty([])
    open_orders = ListProperty([])
    closed_orders = ListProperty([])
    closed_positions = ListProperty([])
    active_records = ListProperty([])
    closed_records = ListProperty([])

    order_count = NumericProperty(0)
    position_count = NumericProperty(0)

    log_display = ObjectProperty(None)

    def __init__(
        self,
        client: BinanceClient,
        gui_handler: GuiHandlerSpot,
        strategy_logger: StrategyLogger,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.client = client
        self.gui_handler = gui_handler
        self.strategy_logger = strategy_logger
        asyncio.create_task(self.update_ui())

    def trigger_add_record(self, *args):
        asyncio.create_task(self.add_record(*args))

    async def add_record(
        self,
        symbol: str,
        side: str,
        price_low: str,
        price_high: str,
        budget: str,
        order_trigger_buffer: str,
        mode: str,
    ) -> None:
        """Creates and starts a new trading strategy."""

        self.strategy_logger.info(
            "Symbol: %s, side: %s, price_low: %s, price_high: %s, budget: %s, order trigger buffer: %s, mode: %s",
            symbol,
            side,
            price_low,
            price_high,
            budget,
            order_trigger_buffer,
            mode,
        )

        config = CoinSniperConfig(
            symbol=symbol,
            side=side,
            price_low=price_low,
            price_high=price_high,
            budget=budget,
            order_trigger_buffer=order_trigger_buffer,
            mode=mode,
        )

        trading_system = TradingSystemSpot(
            client=self.client,
            gui_handler=self.gui_handler,
            strategy_logger=self.strategy_logger,
            config=config,
        )
        await trading_system.initialize()
        self.trading_systems.append(trading_system)

        self.strategy_logger.info(
            "Strategy prepared, starting to initialize, total trading systems: %s",
            len(self.trading_systems),
        )
        self.strategy_logger.info(
            "So we are the point where trading will start, config: %s", config
        )
        await trading_system.start_trading()

    async def delete_record(self):
        pass

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
