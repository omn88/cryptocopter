import asyncio

from binance.enums import (
    ORDER_STATUS_FILLED,
    ORDER_STATUS_EXPIRED,
    ORDER_STATUS_CANCELED,
)
from kivy.app import App
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.logger import Logger
from kivy.properties import ObjectProperty, ListProperty
from kivy.uix.recycleview import RecycleView
import logging_config  # noinspection PyUnresolvedReferences
import warnings

from src.common.identifiers import AccountData, PositionData, OrderData
from src.trading_system import TradingSystem

warnings.simplefilter(action="ignore", category=FutureWarning)


# Set initial window size
Window.size = (960, 600)


kv = """
BoxLayout:
    orientation: "vertical"
    spacing: 8

    TopSection:
    MiddleSection:
    BottomSection:


<TopSection@BoxLayout>:
    orientation: 'horizontal'
    size_hint_y: None
    height: '50dp'


    # Strategy Selection
    BoxLayout:
        size_hint_x: 0.5
        Label:
            text: 'Strategy:'
            size_hint_x: 0.25
        Spinner:
            id: strategy
            text: 'Choose Strategy...'
            values: ['RSI_Basic', 'RSI_Extended']
            size_hint_x: 0.75
            on_text: app.on_strategy_change(self, self.text)

    # Balance Label
    BoxLayout:
        size_hint_x: 0.25
        Label:
            text: 'Balance:'
        Label:
            id: balance
            on_parent: app.balance_label = self

    # Mode Label
    BoxLayout:
        size_hint_x: 0.25
        Label:
            text: 'Auto-Pilot:'
        Switch:
            active: True

<MiddleSection@BoxLayout>:
    orientation: 'horizontal'
    size_hint_y: None
    height: '50dp'

    # Symbol Selection and DCA Orders
    BoxLayout:
        size_hint_x: 0.5
        Label:
            text: 'Symbol:'
        Spinner:
            id: symbol
            text: 'BTCUSDT'
            values: ['BTCUSDT']
        Label:
            text: 'DCA Orders:'
        Spinner:
            id: dca_orders
            text: '4'
            values: [str(i) for i in range(1, 9)]

    # Spacer
    Widget:
        size_hint_x: 0.25

    # Start button
    Button:
        text: 'Start'
        size_hint_x: 0.125
        on_press: app.on_start_trading()

    # Cancel button
    Button:
        text: 'Cancel'
        size_hint_x: 0.125
        on_press: app.on_cancel()


<PositionListItem@BoxLayout>:
    orientation: "horizontal"
    size_hint_y: None
    height: '30dp'
    
    symbol: ''
    quantity: ''
    entry_price: ''
    mark_price: ''
    liquidation_price: ''
    pnl: ''

    Label:
        text: root.symbol
    Label:
        text: root.quantity
    Label:
        text: root.entry_price
    Label:
        text: root.mark_price
    Label:
        text: root.liquidation_price
    Label:
        text: root.pnl


<OrderListItem@BoxLayout>:
    orientation: "horizontal"
    size_hint_y: None
    height: '30dp'
    
    open_time: ''
    symbol: ''
    order_type: ''
    side: ''
    price: ''
    quantity: ''
    realized_quantity: ''
    status: ''
    order_id: ''

    Label:
        text: root.open_time
        size_hint_x: 0.15
    Label:
        text: root.symbol
        size_hint_x: 0.11
    Label:
        text: root.order_type
        size_hint_x: 0.10
    Label:
        text: root.side
        size_hint_x: 0.08
    Label:
        text: root.price
        size_hint_x: 0.08
    Label:
        text: root.quantity
        size_hint_x: 0.09
    Label:
        text: root.realized_quantity
        size_hint_x: 0.09
    Label:
        text: root.status
        size_hint_x: 0.15
    Label:
        text: root.order_id
        size_hint_x: 0.15


<BottomSection@BoxLayout>:
    id: bottom_section
    orientation: 'horizontal'

    TabbedPanel:
        do_default_tab: False

        TabbedPanelItem:
            text: 'Position'
            BoxLayout:
                orientation: "vertical"
                BoxLayout:
                    size_hint_y: None
                    height: '30dp'
                    Label:
                        text: 'Symbol'
                    Label:
                        text: 'Quantity'
                    Label:
                        text: 'Entry Price'
                    Label:
                        text: 'Mark Price'
                    Label:
                        text: 'Liquidation Price'
                    Label:
                        text: 'PnL'
                RecycleView:
                    id: positions_list
                    data: app.position_data_list
                    viewclass: 'PositionListItem'
                    RecycleBoxLayout:
                        default_size: None, dp(56)
                        default_size_hint: 1, None
                        size_hint_y: None
                        height: self.minimum_height
                        orientation: 'vertical'
        TabbedPanelItem:
            text: 'Orders'
            BoxLayout:
                orientation: "vertical"
                BoxLayout:
                    size_hint_y: None
                    height: '30dp'
                    Label:
                        text: 'Open Time'
                        size_hint_x: 0.15
                    Label:
                        text: 'Symbol'
                        size_hint_x: 0.11
                    Label:
                        text: 'Type'
                        size_hint_x: 0.10
                    Label:
                        text: 'Side'
                        size_hint_x: 0.08
                    Label:
                        text: 'Price'
                        size_hint_x: 0.08
                    Label:
                        text: 'Quantity'
                        size_hint_x: 0.09
                    Label:
                        text: 'Realized'
                        size_hint_x: 0.09
                    Label:
                        text: 'Status'
                        size_hint_x: 0.15
                    Label:
                        text: 'Order ID'
                        size_hint_x: 0.15
                RecycleView:
                    id: orders_list
                    data: app.order_data_list
                    viewclass: 'OrderListItem'
                    RecycleBoxLayout:
                        default_size: None, dp(56)
                        default_size_hint: 1, None
                        size_hint_y: None
                        height: self.minimum_height
                        orientation: 'vertical'
        TabbedPanelItem:
            text: 'History'
            BoxLayout:
                orientation: "vertical"
                BoxLayout:
                    size_hint_y: None
                    height: '30dp'
                    Label:
                        text: 'Open Time'
                        size_hint_x: 0.15
                    Label:
                        text: 'Symbol'
                        size_hint_x: 0.11
                    Label:
                        text: 'Type'
                        size_hint_x: 0.10
                    Label:
                        text: 'Side'
                        size_hint_x: 0.08
                    Label:
                        text: 'Price'
                        size_hint_x: 0.08
                    Label:
                        text: 'Quantity'
                        size_hint_x: 0.09
                    Label:
                        text: 'Realized'
                        size_hint_x: 0.09
                    Label:
                        text: 'Status'
                        size_hint_x: 0.15
                    Label:
                        text: 'Order ID'
                        size_hint_x: 0.15
                RecycleView:
                    id: history_list
                    data: app.history_data_list
                    viewclass: 'OrderListItem'
                    RecycleBoxLayout:
                        default_size: None, dp(56)
                        default_size_hint: 1, None
                        size_hint_y: None
                        height: self.minimum_height
                        orientation: 'vertical'
        TabbedPanelItem:
            text: 'Logs'
            Label:
                text: 'Log data'
"""


class AsyncApp(App):
    # Change the button start method, on_start is automaticall callback
    # change the logger to INFO

    balance_label = ObjectProperty(None)
    position_data_list = ListProperty([])
    order_data_list = ListProperty([])
    history_data_list = ListProperty([])

    def build(self):
        return Builder.load_string(kv)

    def on_strategy_change(self, instance, value):
        self.trading_system.strategy_name = value
        Logger.info("Strategy: Chosen strategy is %s" % value)

    async def move_to_history(self, order_id):
        # pause the execution for 3 seconds
        await asyncio.sleep(3)
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
                self.order_data_list = self.order_data_list
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

            if isinstance(data, OrderData):
                # Check if the order already exists
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


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(AsyncApp().app_func())
    loop.close()
