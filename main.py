import asyncio
import logging

from kivy.app import App
from kivy.lang import Builder

# import logging_config  # noinspection PyUnresolvedReferences
import warnings

from kivymd.app import MDApp

from src.common.constants import SYMBOL, ASSET, INTERVAL
from src.trading_system import TradingSystem

warnings.simplefilter(action="ignore", category=FutureWarning)

# from kivy.logger import Logger
#
# # Get Python's logger
# python_logger = logging.getLogger()
#
#
# # This handler will forward messages to Kivy's logger
# class KivyHandler(logging.Handler):
#     def emit(self, record):
#         Logger.log(record.levelno, record.msg, record.args)
#
#
# # Add the handler to Python's logger
# python_logger.addHandler(KivyHandler())


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
            text: 'RSI_basic'
            values: ['RSI_Basic', 'RSI_Extended']
            size_hint_x: 0.75

    # Balance Label
    BoxLayout:
        size_hint_x: 0.25
        Label:
            text: 'Balance:'
        Label:
            id: balance
            text: ''

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
        on_press: root.on_start()

    # Cancel button
    Button:
        text: 'Cancel'
        size_hint_x: 0.125
        on_press: root.on_cancel()

<BottomSection@BoxLayout>:
    orientation: 'horizontal'

    TabbedPanel:
        do_default_tab: False

        TabbedPanelItem:
            text: 'Position'
            Label:
                text: 'Position data'
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
    other_task = None

    def build(self):
        return Builder.load_string(kv)

    def app_func(self):
        """This will run both methods asynchronously and then block until they
        are finished
        """
        self.ui_queue = asyncio.Queue()

        self.trading_system: TradingSystem = TradingSystem(ui_queue=self.ui_queue)
        self.other_task = asyncio.ensure_future(self.trading_system.initialize())

        async def run_wrapper():
            # we don't actually need to set asyncio as the lib because it is
            # the default, but it doesn't hurt to be explicit
            await self.async_run(async_lib="asyncio")
            print("App done")
            self.other_task.cancel()

        return asyncio.gather(run_wrapper(), self.other_task)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(AsyncApp().app_func())
    loop.close()
