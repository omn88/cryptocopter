import asyncio

from binance.enums import (
    ORDER_STATUS_FILLED,
    ORDER_STATUS_EXPIRED,
    ORDER_STATUS_CANCELED,
)
from kivy.app import App
from kivy.lang import Builder
from kivy.logger import Logger
from kivy.properties import ObjectProperty, ListProperty, NumericProperty

from src.common.identifiers import AccountData, PositionData, OrderData
from src.trading_system import TradingSystem


class AsyncApp(App):
    balance_label = ObjectProperty(None)
    position_data_list = ListProperty([])
    order_data_list = ListProperty([])
    history_data_list = ListProperty([])
    order_count = NumericProperty(0)
    position_count = NumericProperty(0)

    def build(self):
        return Builder.load_file("src/gui/main.kv")

    def count_open_orders(self):
        Logger.info(
            "CALLING COUNT OPEN ORDERS: ORDER DATA LIST: %s", self.order_data_list
        )
        if not self.order_data_list:  # check if order_data_list is empty
            self.order_count = 0
            return 0
        else:
            count = sum(
                1
                for order in self.order_data_list
                if order["status"] in ["NEW", "PARTIALLY_FILLED"]
            )
            # Update order_count
            self.order_count = count
            Logger.info("ORDER COUNT: %s", self.order_count)
            return count

    def count_open_positions(self):
        Logger.info(
            "CALLING COUNT OPEN POSITIONS: POSITION DATA LIST: %s",
            self.position_data_list,
        )
        if not self.position_data_list:  # check if position_data_list is empty
            self.position_count = 0
            return 0
        else:
            count = sum(
                1
                for position in self.position_data_list
                if float(position["quantity"]) > 0
            )
            # Update position_count
            self.position_count = count
            Logger.info("SELF POSITION COUNT: %s", self.position_count)
            return count

    def on_strategy_change(self, instance, value):
        self.trading_system.strategy_name = value
        Logger.info("Strategy: Chosen strategy is %s" % value)

    async def move_to_history(self, order_id):
        # Find the order in the list
        for i, order in enumerate(self.order_data_list):
            if order["order_id"] == order_id:
                # If the order is found, remove it from order_data_list and add it to history_data_list
                self.history_data_list = self.history_data_list + [order]
                self.order_data_list = (
                    self.order_data_list[:i] + self.order_data_list[i + 1 :]
                )
                break

    def on_start_trading(self):
        loop = asyncio.get_event_loop()
        loop.create_task(self.trading_system.start_trading())
        Logger.info("App: Start button pressed.")

    def on_cancel(self):
        loop = asyncio.get_event_loop()
        loop.create_task(self.trading_system.stop())
        Logger.info("App: Cancel button pressed.")

    def update_order(self, order_id, **kwargs):
        # Find the order in the list
        for i, order in enumerate(self.order_data_list):
            if order["order_id"] == order_id:
                # If the order is found, update the fields
                for key, value in kwargs.items():
                    if key in order:
                        order[key] = value
                # Reassign the list to trigger the UI update
                # self.order_data_list = self.order_data_list
                break

    async def update_ui(self):
        while True:
            Logger.info("Events in UI queue: %s", self.ui_queue.qsize())
            if self.ui_queue.qsize() == 0:
                Logger.info("Awaiting new Event...")
            data = await self.ui_queue.get()
            # Update the UI based on data
            if isinstance(data, AccountData):
                Logger.info("PANU  DYS IS update account")
                self.balance_label.text = f"{str(data.balance)} USDT"
            if isinstance(data, PositionData):
                self.position_data_list = [
                    {
                        "symbol": data.symbol,
                        "quantity": str(data.quantity),
                        "entry_price": str(data.entry_price),
                        "mark_price": str(data.mark_price),
                        "liquidation_price": str(data.liquidation_price),
                        "pnl": str(data.pnl),
                    }
                ]
                self.position_data_list = self.position_data_list

            if isinstance(data, OrderData):
                # Check if the order already exists
                existing_orders = []

                if self.order_data_list is not None:
                    existing_orders = [
                        order
                        for order in self.order_data_list
                        if order["order_id"] == data.order_id
                    ]
                if existing_orders:
                    # If it does, update it
                    self.update_order(
                        order_id=data.order_id,
                        open_time=data.open_time,
                        symbol=data.symbol,
                        order_type=data.order_type,
                        side=data.side,
                        price=str(data.price),
                        quantity=str(data.quantity),
                        realized_quantity=str(data.realized_quantity),
                        status=data.status,
                    )
                    if data.status in [
                        ORDER_STATUS_FILLED,
                        ORDER_STATUS_CANCELED,
                        ORDER_STATUS_EXPIRED,
                    ]:
                        await self.move_to_history(order_id=data.order_id)
                else:
                    # If not, add it to the list
                    order_data = {
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
                    self.order_data_list = self.order_data_list + [order_data]
            self.count_open_orders()
            self.count_open_positions()

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
