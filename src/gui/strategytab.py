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
from src.common.constants import LEVERAGE
from src.common.identifiers import EventName, Event, Position, State
from src.gui.gui_handler import GuiHandler
from src.gui.identifiers import (
    AccountData,
    PositionData,
    OrderData,
    PriceData,
    PositionStatus,
)

from src.trading_system import TradingSystem


class StrategyTab(BoxLayout):
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
        gui_handler: GuiHandler,
        strategy_logger: StrategyLogger,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.trading_system: TradingSystem = trading_system
        self.gui_handler: GuiHandler = gui_handler
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

    @staticmethod
    def calculate_pnl(quantity: float, index_price: float, entry_price: float) -> float:
        pnl = 0.0

        if quantity > 0:
            pnl = round((index_price / entry_price - 1) * 100 * LEVERAGE, 2)
        if quantity == 0:
            pnl = 0
        if quantity < 0:
            pnl = round((entry_price / index_price - 1) * 100 * LEVERAGE, 2)

        return pnl

    def update_price_data(self, data: PriceData) -> List:
        new_positions = [pos.copy() for pos in self.open_positions]

        if len(new_positions) != 0:
            for position in new_positions:
                if position["symbol"] == data.symbol:
                    position["quantity"] = str(position["quantity"])
                    position["entry_price"] = str(position["entry_price"])
                    position["mark_price"] = str(data.mark_price)
                    position["liquidation_price"] = str(position["liquidation_price"])
                    position["pnl"] = str(
                        round(
                            self.calculate_pnl(
                                quantity=round(float(position["quantity"]), 3),
                                index_price=float(data.mark_price),
                                entry_price=float(position["entry_price"]),
                            ),
                            3,
                        )
                    )
                    position["state"] = str(position["state"])
                    position["status"] = str(position["status"])

        return new_positions

    def add_new_position(self, symbol, data):
        self.strategy_logger.info("Creating a new position: %s", symbol)
        # If the position does not exist, create it
        self.position_count += 1
        self.open_positions.append(
            {
                "symbol": symbol,
                "quantity": str(data.quantity),
                "entry_price": str(data.entry_price),
                "mark_price": str(data.mark_price),
                "liquidation_price": str(data.liquidation_price),
                "pnl": str(data.pnl),
                "state": str(data.state.value),
                "status": str(data.status),
            }
        )

        self.strategy_logger.info(
            "Open Positions after adding position: %s", self.open_positions
        )

    def update_existing_position(self, data):
        for position in self.open_positions:
            if position["symbol"] == data.symbol:
                # If it exists, update the values
                position["quantity"] = str(data.quantity)
                position["entry_price"] = str(data.entry_price)
                position["mark_price"] = str(data.mark_price)
                position["liquidation_price"] = str(data.liquidation_price)
                position["pnl"] = str(data.pnl)
                position["state"] = str(data.state.value)
                position["status"] = str(data.status)

                if position["status"] == PositionStatus.CLOSED:
                    self.strategy_logger.info("Position status: %s", data.status)
                    self.strategy_logger.info(
                        "Length of open positions: %s", len(self.open_positions)
                    )
                    self.strategy_logger.info(
                        "Length of closed positions: %s",
                        len(self.closed_positions),
                    )
                    self.closed_positions.append(position)
                    self.open_positions.remove(position)
                    self.strategy_logger.info(
                        "Length of open positions after removal: %s",
                        len(self.open_positions),
                    )
                    self.strategy_logger.info(
                        "Length of closed positions after appending: %s",
                        len(self.closed_positions),
                    )
                    self.position_count -= 1

                self.strategy_logger.info("Updated positions: %s", self.open_positions)

    def add_new_order(self, open_orders, data):
        self.order_count += 1
        open_orders.append(
            {
                "order_id": str(data.order_id),
                "open_time": str(data.open_time),
                "symbol": data.symbol,
                "order_type": data.order_type,
                "side": data.side,
                "price": str(data.price),
                "quantity": str(data.quantity),
                "realized_quantity": str(data.realized_quantity),
                "status": data.status,
            }
        )
        self.strategy_logger.info("Open Orders after adding order: %s", open_orders)

        return open_orders

    def update_existing_order(self, open_orders, data, closed_orders):
        for order in open_orders:
            if order["order_id"] == str(data.order_id):
                # If it exists, update the values
                order["open_time"] = str(data.open_time)
                order["symbol"] = data.symbol
                order["order_type"] = data.order_type
                order["side"] = data.side
                order["price"] = str(data.price)
                order["quantity"] = str(data.quantity)
                order["realized_quantity"] = str(data.realized_quantity)
                order["status"] = data.status

                # If the order status is filled, canceled, or expired,
                # remove it from open orders and add it to closed orders
                if data.status in [
                    ORDER_STATUS_FILLED,
                    ORDER_STATUS_CANCELED,
                    ORDER_STATUS_EXPIRED,
                ]:
                    self.strategy_logger.info("Order fil, can or exp: %s", data.status)
                    self.strategy_logger.info(
                        "Length of open orders: %s", len(open_orders)
                    )
                    self.strategy_logger.info(
                        "Length of closed orders: %s", len(self.closed_orders)
                    )
                    closed_orders.append(order)
                    open_orders.remove(order)
                    self.strategy_logger.info(
                        "Length of open orders after removal: %s",
                        len(open_orders),
                    )
                    self.strategy_logger.info(
                        "Length of closed orders after appending: %s",
                        len(closed_orders),
                    )
                    self.order_count -= 1

                self.strategy_logger.info("Updated Orders: %s", open_orders)

        return open_orders, closed_orders

    def update_position(
        self,
        data: PositionData,
    ) -> None:
        self.strategy_logger.info(
            "Entering update position, len open positions: %s", len(self.open_positions)
        )
        symbol = data.symbol

        if len(self.open_positions) != 0:
            if any(position["symbol"] == symbol for position in self.open_positions):
                self.update_existing_position(data=data)
            else:
                self.add_new_position(data=data, symbol=symbol)
        else:
            # Without this if statement, the cancelled strategy was adding new position.
            if data.status != PositionStatus.CLOSED:
                self.add_new_position(data=data, symbol=symbol)

    def update_order(
        self, open_orders: List, closed_orders: List, data: OrderData
    ) -> Tuple[List, List]:
        order_id = str(data.order_id)

        if any(order["order_id"] == order_id for order in open_orders):
            open_orders, closed_orders = self.update_existing_order(
                closed_orders=closed_orders, data=data, open_orders=open_orders
            )
        else:
            # If the order does not exist, create it
            open_orders = self.add_new_order(data=data, open_orders=open_orders)

        return open_orders, closed_orders

    def on_strategy_change(self, instance, value):
        self.trading_system.strategy_name = value
        self.strategy_logger.info("Strategy: Chosen strategy is %s", value)

    def on_start_trading(self):
        loop = asyncio.get_event_loop()
        loop.create_task(self.trading_system.start_trading())
        self.strategy_logger.info("App: Start button pressed.")

    def on_cancel(self):
        loop = asyncio.get_event_loop()
        loop.create_task(self.trading_system.stop())
        self.strategy_logger.info("App: Cancel button pressed.")
