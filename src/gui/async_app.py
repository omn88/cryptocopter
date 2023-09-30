import asyncio
import logging
from typing import List, Tuple

from binance.enums import (
    ORDER_STATUS_FILLED,
    ORDER_STATUS_EXPIRED,
    ORDER_STATUS_CANCELED,
)
from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.logger import Logger
from kivy.properties import (
    ListProperty,
    NumericProperty,
    StringProperty,
    ObjectProperty,
)

from logging_config import KivyGuiHandler
from src.common.constants import LEVERAGE
from src.common.identifiers import EventName, Event
from src.gui.identifiers import (
    AccountData,
    PositionData,
    OrderData,
    PriceData,
    PositionStatus,
)
from src.trading_system import TradingSystem

logger = logging.getLogger("async_app")


class AsyncApp(App):
    balance_label = StringProperty("0")
    price_label = StringProperty("0")
    open_positions = ListProperty([])
    open_orders = ListProperty([])
    closed_orders = ListProperty([])
    closed_positions = ListProperty([])

    order_count = NumericProperty(0)
    position_count = NumericProperty(0)

    log_display = ObjectProperty(None)

    def on_start(self):
        # This is a Kivy App lifecycle method that gets called after the app has started.
        # We will schedule the logging handler setup to be run immediately after.

        Clock.schedule_once(self.setup_logging_handler, 0.1)

    def setup_logging_handler(self, *args):
        logger.info("Log display: %s", self.log_display)
        log_display_widget = self.log_display
        if not log_display_widget:
            print("Failed to bind to the log_display widget!")
            return
        else:
            print("Successfully bound to the log_display widget!")

        gui_log_handler = KivyGuiHandler(log_display_widget)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        gui_log_handler.setFormatter(formatter)

        logging.getLogger().addHandler(gui_log_handler)

        logger.info("Logging handler configured with success")

    def build(self):
        return Builder.load_file("src/gui/main.kv")

    def on_strategy_change(self, instance, value):
        self.trading_system.strategy_name = value
        Logger.info("Strategy: Chosen strategy is %s" % value)

    def on_start_trading(self):
        loop = asyncio.get_event_loop()
        loop.create_task(self.trading_system.start_trading())
        Logger.info("App: Start button pressed.")

    def on_cancel(self):
        loop = asyncio.get_event_loop()
        loop.create_task(self.trading_system.stop())
        Logger.info("App: Cancel button pressed.")

    async def update_ui(self):
        while True:
            Logger.debug("Events in UI queue: %s", self.ui_queue.qsize())
            if self.ui_queue.qsize() == 0:
                Logger.debug("Awaiting new Event")
            data = await self.ui_queue.get()
            # Update the UI based on data
            if isinstance(data, Event):
                if data.name == EventName.SENTINEL:
                    Logger.info("SENTINEL -> Exiting UI updates.")
                    await asyncio.sleep(3)
                    return
            if isinstance(data, AccountData):
                Logger.info("PANU  DYS IS update account")
                self.balance_label = f"{str(data.balance)} USDT"
            if isinstance(data, PositionData):
                self.open_positions, self.closed_positions = self.update_position(
                    open_positions=self.open_positions,
                    closed_positions=self.closed_positions,
                    data=data,
                )

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
                        self.open_positions = self.update_price_data(
                            data=data, open_positions=self.open_positions
                        )

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

    def update_price_data(self, open_positions: List, data: PriceData) -> List:
        new_positions = [pos.copy() for pos in open_positions]

        if len(new_positions) != 0:
            for position in new_positions:
                if position["symbol"] == data.symbol:
                    pnl = str(
                        round(
                            self.calculate_pnl(
                                quantity=round(float(position["quantity"]), 3),
                                index_price=float(data.mark_price),
                                entry_price=float(position["entry_price"]),
                            ),
                            3,
                        )
                    )
                    position["quantity"] = str(position["quantity"])
                    position["entry_price"] = str(position["entry_price"])
                    position["mark_price"] = str(data.mark_price)
                    position["liquidation_price"] = str(position["liquidation_price"])
                    position["pnl"] = pnl
                    position["state"] = str(position["state"])
                    position["status"] = str(position["status"])

        return new_positions

    def add_new_position(self, symbol, open_positions, data) -> List:
        Logger.info("Creating a new position: %s", symbol)
        # If the position does not exist, create it
        self.position_count += 1
        open_positions.append(
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

        Logger.info("Open Positions after adding position: %s", open_positions)

        return open_positions

    def update_existing_position(self, open_positions, data, closed_positions):
        for position in open_positions:
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
                    Logger.info("Position status: %s", data.status)
                    Logger.info("Length of open positions: %s", len(open_positions))
                    Logger.info(
                        "Length of closed positions: %s",
                        len(closed_positions),
                    )
                    closed_positions.append(position)
                    open_positions.remove(position)
                    Logger.info(
                        "Length of open positions after removal: %s",
                        len(open_positions),
                    )
                    Logger.info(
                        "Length of closed positions after appending: %s",
                        len(closed_positions),
                    )
                    self.position_count -= 1

                Logger.info("Updated positions: %s", open_positions)

        return open_positions, closed_positions

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
        Logger.info("Open Orders after adding order: %s", open_orders)

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
                    Logger.info("Order fil, can or exp: %s", data.status)
                    Logger.info("Length of open orders: %s", len(open_orders))
                    Logger.info("Length of closed orders: %s", len(self.closed_orders))
                    closed_orders.append(order)
                    open_orders.remove(order)
                    Logger.info(
                        "Length of open orders after removal: %s",
                        len(open_orders),
                    )
                    Logger.info(
                        "Length of closed orders after appending: %s",
                        len(closed_orders),
                    )
                    self.order_count -= 1

                Logger.info("Updated Orders: %s", open_orders)

        return open_orders, closed_orders

    def update_position(
        self, open_positions: List, closed_positions: List, data: PositionData
    ) -> Tuple[List, List]:
        symbol = data.symbol

        if len(open_positions) != 0:
            if any(position["symbol"] == symbol for position in open_positions):
                open_positions, closed_positions = self.update_existing_position(
                    closed_positions=closed_positions,
                    data=data,
                    open_positions=open_positions,
                )
            else:
                open_positions = self.add_new_position(
                    data=data, open_positions=open_positions, symbol=symbol
                )
        else:
            open_positions = self.add_new_position(
                data=data, open_positions=open_positions, symbol=symbol
            )

        return open_positions, closed_positions

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

    def app_func(self):
        """This will run both methods asynchronously and then block until they
        are finished
        """
        self.ui_queue = asyncio.Queue()

        self.trading_system = TradingSystem(ui_queue=self.ui_queue)
        initialize_trading_system_task = asyncio.ensure_future(
            self.trading_system.initialize()
        )

        # Start the task for updating the UI
        ui_update_task = asyncio.ensure_future(self.update_ui())

        async def run_wrapper():
            # we don't actually need to set asyncio as the lib because it is
            # the default, but it doesn't hurt to be explicit
            await self.async_run(async_lib="asyncio")
            Logger.info("App done")
            initialize_trading_system_task.cancel()
            ui_update_task.cancel()

        return asyncio.gather(
            run_wrapper(), initialize_trading_system_task, ui_update_task
        )
