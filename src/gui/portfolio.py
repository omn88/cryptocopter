import logging
import queue
from typing import Dict
from kivy.properties import ObjectProperty
from kivy.uix.label import Label
from kivy.uix.boxlayout import BoxLayout

from src.common.identifiers.spot import AccountPosition, Balances, Event, EventName

logger = logging.getLogger("portfolio_gui_handler")


from kivy.uix.boxlayout import BoxLayout
import asyncio
import logging

logger = logging.getLogger("PortfolioUI")


class PortfolioUI(BoxLayout):
    saldo_usdt_label = ObjectProperty(None)  # Label for USDT saldo in the GUI
    saldo_btc_label = ObjectProperty(None)  # Label for BTC saldo in the GUI
    coin_list = ObjectProperty(None)  # List or grid to show portfolio items

    def __init__(self, ui_queue, **kwargs) -> None:
        # Initialize the base class (BoxLayout)
        super().__init__(**kwargs)  # This ensures proper widget initialization
        self.ui_queue: queue.Queue = ui_queue
        # Start UI update loop
        asyncio.create_task(self.update_ui())

    async def update_ui(self) -> None:
        logger.info("Ready to receive portfolio UI updates.")
        while True:
            try:
                data = self.ui_queue.get_nowait()
                logger.info("Received data: %s", data)
                # Process the data and update the UI
                assert isinstance(data, Event)

                if data.name == EventName.BALANCES:
                    assert isinstance(data.content, Balances)
                    self.create_coin_list(data.content)
                if data.name == EventName.ACCOUNT_POSITION:
                    assert isinstance(data.content, AccountPosition)
                    self.update_coin_list(data.content)
                # if "balances" in data:
                #     self.update_saldo(data["balances"])
            except queue.Empty:
                await asyncio.sleep(0.1)

    def update_saldo(self, balances):
        """Update the saldo labels in the UI."""
        self.ids.saldo_usdt_label.text = f"{balances['usdt']} USDT"
        self.ids.saldo_btc_label.text = f"{balances['btc']} BTC"

    def create_coin_list(self, balances: Balances):
        """Create the coin list in the UI based on new ticker data."""
        logger.info("Going to prepare initial coin list.")
        coin_list_data = []

        for symbol, quantity in balances.msg.items():
            coin_data = {
                "symbol": symbol,  # Symbol of the coin (e.g., BTC, ETH)
                "quantity": f"{quantity:.6f}",  # Format the quantity to 6 decimal places
                "price_in_usdt": "0.00",  # Placeholder value for now
                "total_in_usdt": "0.00",  # Placeholder value for now
            }
            coin_list_data.append(coin_data)

        # Set the data for the RecycleView (this will update the list in the UI)
        logger.info(f"Coin list data: {coin_list_data}")
        self.ids.coin_list.data = (
            coin_list_data  # Correctly update the RecycleView's data property
        )

    def update_coin_list(self, account_position: AccountPosition) -> None:
        pass
