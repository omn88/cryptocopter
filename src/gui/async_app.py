import asyncio

from binance.enums import (
    ORDER_STATUS_FILLED,
    ORDER_STATUS_EXPIRED,
    ORDER_STATUS_CANCELED,
)
from kivy.app import App
from kivy.lang import Builder
from kivy.logger import Logger
from kivy.properties import (
    ListProperty,
    NumericProperty,
    StringProperty,
)
from kivy.uix.label import Label

from src.common.identifiers import (
    AccountData,
    PositionData,
    OrderData,
    EventName,
    PositionStatus,
    PriceData,
    PositionSide,
)
from src.trading_system import TradingSystem


GREEN_COLOR = [0, 0.5, 0, 1]
RED_COLOR = [0.5, 0, 0, 1]
WHITE_COLOR = [1, 1, 1, 1]


class ColorChangingQuantity(Label):
    quantity = NumericProperty(0)
    color = ListProperty(WHITE_COLOR)  # Default color is white

    def on_quantity(self, instance, value):
        value = float(value)
        if value > 0:
            self.color = GREEN_COLOR
        elif value < 0:
            self.color = RED_COLOR
        else:
            self.color = WHITE_COLOR


class ColorChangingSide(Label):
    side = StringProperty("")
    color = ListProperty([1, 1, 1, 1])  # Default color is white

    def on_side(self, instance, value):
        if value.lower() == "buy":
            self.color = GREEN_COLOR
        elif value.lower() == "sell":
            self.color = RED_COLOR
        else:
            self.color = WHITE_COLOR


class AsyncApp(App):
    balance_label = StringProperty("0")
    price_label = StringProperty("0")
    open_positions = ListProperty([])
    open_orders = ListProperty([])
    closed_orders = ListProperty([])
    closed_positions = ListProperty([])

    order_count = NumericProperty(0)
    position_count = NumericProperty(0)

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
            if data == EventName.SENTINEL:
                Logger.info("SENTINEL -> Exiting UI updates.")
                return
            if isinstance(data, AccountData):
                Logger.info("PANU  DYS IS update account")
                self.balance_label = f"{str(data.balance)} USDT"
            if isinstance(data, PositionData):
                self.update_position(data)

            if isinstance(data, OrderData):
                self.update_order(data)

            if isinstance(data, PriceData):
                self.update_price_data(data=data)

    def update_price_data(self, data):
        self.price_label = str(data.index_price)

        if len(self.open_positions) != 0:
            for position in self.open_positions:
                if position["symbol"] == data.symbol:
                    Logger.info(
                        "Received data for %s, updating mark price: %s",
                        data.symbol,
                        data.mark_price,
                    )
                    # position["quantity"] = str(position["quantity"])
                    # position["entry_price"] = str(position["entry_price"])
                    position["mark_price"] = str(data.mark_price)
                    # position["liquidation_price"] = str(position["liquidation_price"])
                    position["pnl"] = str(
                        (data.index_price / float(position["entry_price"]) - 1) * 100
                    )
                    # position["status"] = str(position["status"])

    def update_position(self, data):
        symbol = data.symbol

        if len(self.open_positions) == 0:
            Logger.info("Creating a new position: %s", symbol)
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
                    "status": str(data.status),
                }
            )

            Logger.info("Open Positions after adding position: %s", self.open_positions)

        if len(self.open_positions) > 0:
            if any(position["symbol"] == symbol for position in self.open_positions):
                for position in self.open_positions:
                    if position["symbol"] == data.symbol:
                        # If it exists, update the values
                        position["quantity"] = str(data.quantity)
                        position["entry_price"] = str(data.entry_price)
                        position["mark_price"] = str(data.mark_price)
                        position["liquidation_price"] = str(data.liquidation_price)
                        position["pnl"] = str(data.pnl)
                        position["status"] = str(data.status)

                        # If the quantity is 0, remove the position
                        if data.status == PositionStatus.CLOSED:
                            Logger.info("Position status: %s", data.status)
                            Logger.info(
                                "Length of open positions: %s", len(self.open_positions)
                            )
                            Logger.info(
                                "Length of closed positions: %s",
                                len(self.closed_positions),
                            )
                            self.closed_positions.append(position)
                            self.open_positions.remove(position)
                            Logger.info(
                                "Length of open positions after removal: %s",
                                len(self.open_positions),
                            )
                            Logger.info(
                                "Length of closed positions after appending: %s",
                                len(self.closed_positions),
                            )
                            self.position_count -= 1

                        Logger.info("Updated positions: %s", self.open_positions)
            else:
                Logger.info("Creating a new position: %s", symbol)
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
                        "status": str(data.status),
                    }
                )

                Logger.info(
                    "Open Positions after adding position: %s", self.open_positions
                )

    def update_order(self, data: OrderData):
        order_id = str(data.order_id)

        if any(order["order_id"] == order_id for order in self.open_orders):
            for order in self.open_orders:
                if order["order_id"] == order_id:
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
                        Logger.info("Length of open orders: %s", len(self.open_orders))
                        Logger.info(
                            "Length of closed orders: %s", len(self.closed_orders)
                        )
                        self.closed_orders.append(order)
                        self.open_orders.remove(order)
                        Logger.info(
                            "Length of open orders after removal: %s",
                            len(self.open_orders),
                        )
                        Logger.info(
                            "Length of closed orders after appending: %s",
                            len(self.closed_orders),
                        )
                        self.order_count -= 1

                    Logger.info("Updated Orders: %s", self.open_orders)
        else:
            # If the order does not exist, create it
            self.order_count += 1
            self.open_orders.append(
                {
                    "order_id": order_id,
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
            Logger.info("Open Orders after adding order: %s", self.open_orders)

    def app_func(self):
        """This will run both methods asynchronously and then block until they
        are finished
        """
        self.ui_queue = asyncio.Queue()

        self.trading_system: TradingSystem = TradingSystem(ui_queue=self.ui_queue)
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
