import logging
import queue
from typing import Dict, List
from kivy.properties import ObjectProperty
from kivy.uix.label import Label
from kivy.uix.boxlayout import BoxLayout

from src.common.identifiers.spot import AccountPosition, Balances, Event, EventName
from src.common.symbol_info import SymbolInfo

logger = logging.getLogger("portfolio_gui_handler")


from kivy.uix.boxlayout import BoxLayout
import asyncio
import logging

logger = logging.getLogger("PortfolioUI")


class PortfolioUI(BoxLayout):
    saldo_usdt_label = ObjectProperty(None)  # Label for USDT saldo in the GUI
    saldo_btc_label = ObjectProperty(None)  # Label for BTC saldo in the GUI
    coin_list = ObjectProperty(None)  # List or grid to show portfolio items

    def __init__(
        self, ui_queue: queue.Queue, symbols_info: Dict[str, SymbolInfo], **kwargs
    ) -> None:
        # Initialize the base class (BoxLayout)
        super().__init__(**kwargs)  # This ensures proper widget initialization
        self.ui_queue = ui_queue
        self.symbols_info = symbols_info
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
            try:
                if symbol == "USDT":
                    coin_data = {
                        "symbol": symbol,
                        "quantity": str(round(quantity, 2)),
                        "price_in_usdt": str(round(quantity, 2)),
                        "total_in_usdt": str(round(quantity, 2)),
                    }
                    coin_list_data.append(coin_data)
                else:
                    # Attempt to form the trading pair
                    symbol = f"{symbol}USDT"

                    # Try to fetch symbol info for the asset and add to the list
                    coin_data = {
                        "symbol": symbol,
                        "quantity": str(
                            self.symbols_info[symbol].adjust_quantity(quantity=quantity)
                        ),
                        "price_in_usdt": "0.00",  # Placeholder value for now
                        "total_in_usdt": "0.00",  # Placeholder value for now
                    }
                    coin_list_data.append(coin_data)
            except KeyError as e:
                # Log the error and skip the symbol
                logger.warning(
                    f"Symbol {symbol} not found in symbol info. Skipping. Error: {e}"
                )
                continue

        # Set the data for the RecycleView (this will update the list in the UI)
        logger.info(f"Coin list data: {coin_list_data}")
        self.ids.coin_list.data = coin_list_data

    def update_coin_list(self, account_position: AccountPosition) -> None:
        pass
