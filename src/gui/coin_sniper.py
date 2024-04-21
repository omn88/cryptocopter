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


class CoinSniperTab(BoxLayout):
    trading_systems = ListProperty([])
    active_strategies = ListProperty([])
    closed_strategies = ListProperty([])
    open_positions = ListProperty([])
    open_orders = ListProperty([])
    closed_orders = ListProperty([])
    closed_positions = ListProperty([])

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
        self.gui_handler: GuiHandlerSpot = gui_handler
        self.strategy_logger: StrategyLogger = strategy_logger
        asyncio.create_task(self.update_ui())

    def strategy_config_retrieve(self) -> CoinSniperConfig:
        strategy_name: str = self.root.ids.strategy_spinner.text
        symbol: str = self.root.ids.symbol_spinner.text

        widgets = self.dynamic_spinners.get(strategy_name, {})

        return CoinSniperConfig(
            name=strategy_name,
            symbol=symbol,
            number_of_orders=int(widgets.get("orders_spinner").text),
            dca_span=float(widgets.get("dca_span_spinner").text),
            leverage=int(widgets.get("leverage_spinner").text),
            budget=20.0,
        )

    async def on_start_strategy(self) -> None:
        """Creates and starts a new trading strategy."""

        # CHECK THAT ALL MANDATORY FIELDS ARE SET
        config = self.strategy_config_retrieve()

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
        # await trading_system.start_trading()

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
