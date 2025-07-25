import logging
import queue
from typing import Dict, List
import uuid
from kivy.properties import ObjectProperty, ListProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.label import Label

from src.database.models import Position, PositionStatus, PositionType
from src.identifiers import (
    AccountPosition,
    Balances,
    Event,
    EventName,
    InventoryItem,
    PriceUpdates,
)
from src.common.symbol_info import SymbolInfo
from src.database import TradingDatabase

logger = logging.getLogger("portfolio_gui_handler")


from kivy.uix.boxlayout import BoxLayout
import asyncio
import logging

logger = logging.getLogger("portfolio_ui")


class PortfolioUI(BoxLayout):
    virtual_positions = ListProperty([])
    saldo_usd_label = ObjectProperty(None)  # Label for USD saldo in the GUI
    saldo_btc_label = ObjectProperty(None)  # Label for BTC saldo in the GUI

    coin_list_data = ListProperty()

    def __init__(
        self,
        ui_queue: queue.Queue,
        symbols_info: Dict[str, SymbolInfo],
        db: TradingDatabase,
        **kwargs,
    ) -> None:
        # Initialize the base class (BoxLayout)
        super().__init__(**kwargs)  # This ensures proper widget initialization
        self.ui_queue = ui_queue
        self.symbols_info = symbols_info
        self.coin_list_data = []
        self.inventory: List[InventoryItem] = []
        self.db = db
        # Restore remote positions from DB
        asyncio.create_task(self.restore_remote_positions())
        # Start UI update loop
        asyncio.create_task(self.update_ui())

    async def restore_remote_positions(self):
        logger.info("Restoring remote positions from the database.")

        try:
            positions = await self.db.get_active_positions()
            for pos in positions:
                logger.info("Restoring position: %s", pos)
                if pos.status == PositionStatus.REMOTE:

                    self.coin_list_data.append(
                        {
                            "symbol": pos.symbol,
                            "quantity": str(pos.quantity),
                            "price_usd": "0.00",
                            "total_usd": "0.00",
                            "source": "remote",
                        }
                    )
        except Exception as e:
            logger.error(f"Failed to restore remote positions: {e}")

    def open_virtual_position_popup(self):
        layout = BoxLayout(orientation="vertical", spacing=10, padding=20)
        symbol_input = TextInput(hint_text="Symbol", multiline=False)
        quantity_input = TextInput(
            hint_text="Quantity", multiline=False, input_filter="float"
        )
        wallet_input = TextInput(hint_text="Wallet name (optional)", multiline=False)
        add_btn = Button(text="Add", size_hint_y=None, height=40)

        def add_virtual_position_callback(instance):
            symbol = symbol_input.text.strip().upper()
            quantity = quantity_input.text.strip()
            wallet = wallet_input.text.strip()
            if symbol and quantity:
                pos = Position(
                    hp_id=str(uuid.uuid4()),
                    position_type=PositionType.SELL,
                    status=PositionStatus.REMOTE,
                    symbol=symbol,
                    coin=symbol,
                    quantity=float(quantity),
                    metadata={"wallet_name": wallet} if wallet else {},
                )
                # Save to DB if available
                if self.db:
                    asyncio.create_task(self.db.save_position(pos))
                # Add to UI table
                self.coin_list_data.append(
                    {
                        "symbol": symbol,
                        "quantity": quantity,
                        "price_usd": "0.00",
                        "total_usd": "0.00",
                        "source": wallet if wallet else "remote",
                    }
                )
                popup.dismiss()

        add_btn.bind(on_release=add_virtual_position_callback)

        layout.add_widget(
            Label(text="Add Virtual Position", size_hint_y=None, height=30)
        )
        layout.add_widget(symbol_input)
        layout.add_widget(quantity_input)
        layout.add_widget(wallet_input)
        layout.add_widget(add_btn)

        popup = Popup(
            title="Add Virtual Position",
            content=layout,
            size_hint=(0.5, 0.5),
            auto_dismiss=True,
        )
        popup.open()

    def remove_virtual_position(self, symbol, source):
        """Remove a virtual/remote position from the UI and DB."""
        # Find the matching coin in coin_list_data
        idx_to_remove = None
        for idx, coin in enumerate(self.coin_list_data):
            if coin["symbol"] == symbol and (
                coin["source"] == source or (not source and coin["source"] == "remote")
            ):
                idx_to_remove = idx
                break
        if idx_to_remove is not None:
            removed = self.coin_list_data.pop(idx_to_remove)
            # Remove from DB if possible
            if hasattr(self, "db") and self.db:
                import asyncio

                asyncio.create_task(
                    self._remove_virtual_position_from_db(symbol, source)
                )
            # Refresh UI
            self.ids.coin_list.refresh_from_data()

    async def _remove_virtual_position_from_db(self, symbol, source):
        """Remove the virtual/remote position from the database."""

        try:
            positions = await self.db.get_active_positions()
            for pos in positions:
                if pos.status == PositionStatus.REMOTE and pos.symbol == symbol:
                    wallet = (
                        pos.metadata.get("wallet_name", "remote")
                        if hasattr(pos, "metadata")
                        else "remote"
                    )
                    if wallet == source:
                        await self.db.delete_position(pos.hp_id)
                        break
        except Exception as e:
            logger.error(f"Failed to remove remote position from DB: {e}")

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
                    # Update saldo in USD and BTC
                    await self.update_coin_prices(data.content)

            except queue.Empty:
                await asyncio.sleep(0.1)

    def create_coin_list(self, balances: Balances):
        """Create the coin list in the UI based on new ticker data."""
        logger.info("Going to prepare initial coin list.")

        for symbol, quantity in balances.msg.items():
            try:
                # Round up to coins precision, to filter out first close to zero quantities
                rounded = self.symbols_info[f"{symbol}USDT"].adjust_quantity(
                    quantity=quantity
                )
                if rounded:
                    coin_data = {
                        "symbol": symbol,
                        "quantity": str(rounded),
                        "price_usd": "0.00",
                        "total_usd": "0.00",
                        "source": "binance",
                    }
                    self.coin_list_data.append(coin_data)
            except KeyError as e:
                # Log the error and skip the symbol
                logger.warning(
                    f"Symbol {symbol} not found in symbol info. Skipping. Error: {e}"
                )
                continue

    async def update_coin_prices(self, price_updates: PriceUpdates) -> None:
        """Update the prices of coins based on ticker data from AllTickers and filter based on total value."""

        last_btc_price = price_updates.msg.get("BTC")
        # Iterate through the coin_list_data and update only coins that are in price_updates
        for coin in self.coin_list_data:
            symbol = coin["symbol"]

            # If the symbol is in the price updates, update its price
            if symbol in price_updates.msg:
                price = price_updates.msg[symbol]

                # Update the price and total in USD for this coin
                coin["price_usd"] = str(
                    self.symbols_info[f"{symbol}USDT"].adjust_price(price)
                )
                total_in_usd = round(float(coin["quantity"]) * price, 2)
                coin["total_usd"] = str(total_in_usd)

        # Sort the filtered list by 'total_usd' in descending order (highest to lowest)
        sorted_coin_list = sorted(
            [coin for coin in self.coin_list_data],
            key=lambda x: float(x["total_usd"]),
            reverse=True,
        )

        # Re-assign the ListProperty with the sorted list to trigger the UI update
        self.coin_list_data = sorted_coin_list
        self.saldo_usd_label = round(
            sum([float(coin["total_usd"]) for coin in self.coin_list_data]), 2
        )
        if last_btc_price:
            self.saldo_btc_label = round(self.saldo_usd_label / last_btc_price, 8)

        # Notify the UI to refresh the view (in case you're using RecycleView)
        self.ids.coin_list.refresh_from_data()
        self.ids.saldo_usd_label.text = str(self.saldo_usd_label)
        self.ids.saldo_btc_label.text = str(self.saldo_btc_label)

    def update_coin_list(self, account_position: AccountPosition) -> None:
        """Update the coin list based on AccountPosition updates."""
        logger.info("Updating coin list based on AccountPosition updates.")

        for balance in account_position.balances:
            symbol = balance.coin
            total_balance = balance.free + balance.locked

            # Check if the coin exists in the current coin list
            found = False
            for coin in self.coin_list_data:
                if coin["symbol"] == symbol:
                    coin["quantity"] = str(round(total_balance, 2))
                    found = True
                    logger.info(f"Updated {symbol} quantity to {total_balance}")
                    break

            # If the coin is not in the current coin list, add it
            if not found:
                logger.info(f"Adding new symbol {symbol} to the coin list.")

                coin_data = {
                    "symbol": symbol,
                    "quantity": str(total_balance),
                    "price_usd": "0.00",
                    "total_usd": "0.00",
                }
                self.coin_list_data.append(coin_data)

        # Sort the updated coin list again by total value
        self.coin_list_data = sorted(
            self.coin_list_data,
            key=lambda x: float(x["total_usd"]),
            reverse=True,
        )

        # Notify the UI to refresh the view (in case you're using RecycleView)
        self.ids.coin_list.refresh_from_data()

        # logger.debug(
        #     "Coin list after updating with account positions: %s", self.coin_list_data
        # )
