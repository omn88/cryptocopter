import logging
import queue
import time
from typing import Dict, List
from kivy.properties import ObjectProperty, ListProperty
from kivy.uix.label import Label
from kivy.uix.boxlayout import BoxLayout

from src.common.identifiers.spot import (
    AccountPosition,
    AllTickers,
    Balances,
    Event,
    EventName,
    PriceUpdates,
)
from src.common.symbol_info import SymbolInfo

logger = logging.getLogger("portfolio_gui_handler")


from kivy.uix.boxlayout import BoxLayout
import asyncio
import logging

logger = logging.getLogger("PortfolioUI")


class PortfolioUI(BoxLayout):
    saldo_usdt_label = ObjectProperty(None)  # Label for USDT saldo in the GUI
    saldo_btc_label = ObjectProperty(None)  # Label for BTC saldo in the GUI

    coin_list_data = ListProperty()

    def __init__(
        self, ui_queue: queue.Queue, symbols_info: Dict[str, SymbolInfo], **kwargs
    ) -> None:
        # Initialize the base class (BoxLayout)
        super().__init__(**kwargs)  # This ensures proper widget initialization
        self.ui_queue = ui_queue
        self.symbols_info = symbols_info
        self.coin_list_data = []
        # Start UI update loop
        asyncio.create_task(self.update_ui())

    async def update_ui(self) -> None:
        logger.info("Ready to receive portfolio UI updates.")
        while True:
            try:
                data = self.ui_queue.get_nowait()
                # logger.info("Received data: %s", data)
                # Process the data and update the UI
                assert isinstance(data, Event)

                if data.name == EventName.BALANCES:
                    assert isinstance(data.content, Balances)
                    self.create_coin_list(data.content)
                if data.name == EventName.ACCOUNT_POSITION:
                    assert isinstance(data.content, AccountPosition)
                    self.update_coin_list(data.content)
                if data.name == EventName.PRICE_UPDATES:
                    assert isinstance(data.content, PriceUpdates)
                    # Update saldo in USDT and BTC
                    await self.update_coin_prices(data.content)

            except queue.Empty:
                await asyncio.sleep(0.1)

    def create_coin_list(self, balances: Balances):
        """Create the coin list in the UI based on new ticker data."""
        logger.info("Going to prepare initial coin list.")

        for symbol, quantity in balances.msg.items():
            try:
                if symbol == "USDT":
                    coin_data = {
                        "symbol": symbol,
                        "quantity": str(round(quantity, 2)),
                        "price_usdt": "1.00",
                        "total_usdt": str(round(quantity, 2)),
                    }
                    self.coin_list_data.append(coin_data)
                else:
                    # Round up to coins precision, to filter out first close to zero quantities
                    rounded = self.symbols_info[f"{symbol}USDT"].adjust_quantity(
                        quantity=quantity
                    )
                    if rounded:
                        coin_data = {
                            "symbol": symbol,
                            "quantity": str(rounded),
                            "price_usdt": "0.00",  # Placeholder value for now
                            "total_usdt": "0.00",  # Placeholder value for now
                        }
                        self.coin_list_data.append(coin_data)
            except KeyError as e:
                # Log the error and skip the symbol
                logger.warning(
                    f"Symbol {symbol} not found in symbol info. Skipping. Error: {e}"
                )
                continue

        # Set the data for the RecycleView (this will update the list in the UI)
        logger.info(f"Coin list data: {self.coin_list_data}")

    async def update_coin_prices(self, price_updates: PriceUpdates) -> None:
        """Update the prices of coins based on ticker data from AllTickers and filter based on total value."""

        # Iterate through the coin_list_data and update only coins that are in price_updates
        for coin in self.coin_list_data:
            symbol = coin["symbol"]

            # If the symbol is in the price updates, update its price
            if symbol in price_updates.msg:
                price = price_updates.msg[symbol]

                # Update the price and total in USDT for this coin
                coin["price_usdt"] = str(
                    self.symbols_info[f"{symbol}USDT"].adjust_price(price)
                )
                total_in_usdt = round(float(coin["quantity"]) * price, 2)
                coin["total_usdt"] = str(total_in_usdt)

        # Sort the filtered list by 'total_usdt' in descending order (highest to lowest)
        sorted_coin_list = sorted(
            [coin for coin in self.coin_list_data],
            key=lambda x: float(x["total_usdt"]),
            reverse=True,
        )

        # Re-assign the ListProperty with the sorted list to trigger the UI update
        self.coin_list_data = sorted_coin_list

        # Notify the UI to refresh the view (in case you're using RecycleView)
        self.ids.coin_list.refresh_from_data()

        logger.info("Updated coin list data: %s", self.coin_list_data)

    def update_coin_list(self, account_position: AccountPosition) -> None:
        pass
