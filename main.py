import asyncio

from kivy.app import App
from kivy.lang import Builder
from kivy.logger import Logger
from kivy.properties import ObjectProperty, ListProperty
from kivy.uix.recycleview import RecycleView
import logging_config  # noinspection PyUnresolvedReferences
import warnings

from src.common.identifiers import AccountData, PositionData
from src.trading_system import TradingSystem

warnings.simplefilter(action="ignore", category=FutureWarning)


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


<BottomSection@BoxLayout>:
    id: bottom_section
    orientation: 'horizontal'

    TabbedPanel:
        do_default_tab: False

        TabbedPanelItem:
            text: 'Position'
            BoxLayout:
                orientation: "vertical"
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
            Label:
                text: 'Orders data'
        TabbedPanelItem:
            text: 'History'
            Label:
                text: 'History data'
        TabbedPanelItem:
            text: 'Logs'
            Label:
                text: 'Log data'
"""


class AsyncApp(App):
    # Change the button start method, on_start is automaticall callback
    # change the logger to INFO

    other_task = None
    balance_label = ObjectProperty(None)
    position_data_list = ListProperty([])

    def build(self):
        return Builder.load_string(kv)

    def on_start(self):
        print("Root IDS: W on start %s", self.root.ids)

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
            data = await self.ui_queue.get()
            Logger.info("Awaiting UI update...")
            # Update the UI based on data
            if isinstance(data, AccountData):
                Logger.info("PANU  DYS IS update account")
                self.balance_label.text = f"{str(data.balance)} USDT"
            if isinstance(data, PositionData):
                self.position_data_list.append(
                    {
                        "symbol": data.symbol,
                        "quantity": str(data.quantity),
                        "entry_price": str(data.entry_price),
                        "mark_price": str(data.mark_price),
                        "liquidation_price": str(data.liquidation_price),
                        "pnl": str(data.pnl),
                    }
                )

    def app_func(self):
        """This will run both methods asynchronously and then block until they
        are finished
        """
        self.ui_queue = asyncio.Queue()

        self.trading_system: TradingSystem = TradingSystem(ui_queue=self.ui_queue)
        other_task = asyncio.ensure_future(self.trading_system.initialize())

        # Start the task for updating the UI
        ui_update_task = asyncio.ensure_future(self.update_ui())

        async def run_wrapper():
            # we don't actually need to set asyncio as the lib because it is
            # the default, but it doesn't hurt to be explicit
            await self.async_run(async_lib="asyncio")
            print("App done")
            other_task.cancel()
            ui_update_task.cancel()

        return asyncio.gather(run_wrapper(), other_task, ui_update_task)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(AsyncApp().app_func())
    loop.close()
