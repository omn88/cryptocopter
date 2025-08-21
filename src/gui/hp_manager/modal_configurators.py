"""Modal configurators for Buy and Sell HP creation.

These modals replace the tabbed interface with clean, focused popup dialogs
for creating new HP positions.
"""

from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.spinner import Spinner
from typing import Dict, List, Callable, Any, Tuple
import logging
import uuid

from src.common.symbol_info import SymbolInfo
from src.gui.searchable_drop_down import SearchableDropDown
from .models import HPConfiguration

logger = logging.getLogger(__name__)


class BaseHPModal(Popup):  # type: ignore[misc]
    """Base class for HP configuration modals."""

    def __init__(
        self, callback: Callable[[HPConfiguration], None], **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self.callback = callback
        self.size_hint = (0.9, 0.85)  # Increased from 0.8, 0.7 to 0.9, 0.85
        self.title_size = "18sp"
        self.auto_dismiss = False

        # Create main layout
        main_layout = BoxLayout(orientation="vertical", spacing=10, padding=20)

        # Add form fields (implemented in subclasses)
        self.form_layout = BoxLayout(orientation="vertical", spacing=15)
        main_layout.add_widget(self.form_layout)

        # Create button layout
        button_layout = BoxLayout(size_hint_y=None, height=50, spacing=10)

        cancel_btn = Button(text="Cancel", size_hint_x=0.3)
        cancel_btn.bind(on_release=self.dismiss)

        self.create_btn = Button(text="Create HP", size_hint_x=0.3)
        self.create_btn.bind(on_release=self.on_create)

        button_layout.add_widget(Label())  # Spacer
        button_layout.add_widget(cancel_btn)
        button_layout.add_widget(self.create_btn)

        main_layout.add_widget(button_layout)
        self.content = main_layout

        # Validation message label
        self.validation_label = Label(
            text="", color=(1, 0, 0, 1), size_hint_y=None, height=30
        )
        main_layout.add_widget(self.validation_label, index=1)

        self.setup_form()

    def setup_form(self) -> None:
        """Setup form fields - implemented in subclasses."""
        pass

    def validate_form(self) -> Tuple[bool, str]:
        """Validate form data - implemented in subclasses."""
        return True, ""

    def get_configuration(self) -> HPConfiguration:
        """Get configuration from form - implemented in subclasses."""
        raise NotImplementedError

    def on_create(self, instance: Any) -> None:
        """Handle create button press."""
        is_valid, error_message = self.validate_form()

        if not is_valid:
            self.validation_label.text = error_message
            return

        try:
            config = self.get_configuration()
            self.callback(config)
            self.dismiss()
        except Exception as e:
            logger.error(f"Error creating HP configuration: {e}")
            self.validation_label.text = f"Error: {str(e)}"

    def create_form_row(
        self, label_text: str, widget: Any, label_width: float = 0.3
    ) -> BoxLayout:
        """Create a form row with label and widget."""
        row = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=40, spacing=10
        )

        label = Label(text=label_text, size_hint_x=label_width, halign="right")
        label.bind(size=label.setter("text_size"))

        row.add_widget(label)
        row.add_widget(widget)

        return row


class BuyHPModal(BaseHPModal):
    """Modal for creating Buy HP positions."""

    def __init__(
        self,
        symbols: List[str],
        symbols_info: Dict[str, SymbolInfo],
        client: Any = None,
        **kwargs: Any,
    ) -> None:
        self.symbols = symbols
        self.symbols_info = symbols_info
        self.client = client
        self.selected_symbol = ""  # Initialize selected symbol
        super().__init__(title="Create Buy HP Position", **kwargs)

    def setup_form(self) -> None:
        """Setup Buy HP form fields."""
        # Symbol selection using SearchableDropDown
        self.symbol_input = SearchableDropDown(
            client=self.client, options=self.symbols, symbols_info=self.symbols_info
        )
        self.form_layout.add_widget(self.create_form_row("Symbol:", self.symbol_input))

        # Budget
        self.budget_input = TextInput(
            text="1000", input_filter="float", multiline=False, size_hint_x=0.7
        )
        self.form_layout.add_widget(
            self.create_form_row("Budget (USD):", self.budget_input)
        )

        # Order trigger
        self.order_trigger_spinner = Spinner(
            text="1.0",
            values=[str(round(x * 0.5, 1)) for x in range(0, 11)],
            size_hint_x=0.7,
        )
        self.form_layout.add_widget(
            self.create_form_row("Order Trigger (%):", self.order_trigger_spinner)
        )

        # Mode
        self.mode_spinner = Spinner(
            text="SINGLE", values=["SINGLE", "DCA"], size_hint_x=0.7
        )
        self.form_layout.add_widget(self.create_form_row("Mode:", self.mode_spinner))

    def validate_form(self) -> Tuple[bool, str]:
        """Validate Buy HP form."""
        if (
            not hasattr(self.symbol_input, "selected_value")
            or not self.symbol_input.selected_value
        ):
            return False, "Please select a symbol"

        try:
            budget = float(self.budget_input.text)
            if budget <= 0:
                return False, "Budget must be greater than 0"
        except ValueError:
            return False, "Invalid budget value"

        return True, ""

    def get_configuration(self) -> HPConfiguration:
        """Get Buy HP configuration."""
        symbol = (
            self.symbol_input.selected_value
            if hasattr(self.symbol_input, "selected_value")
            else ""
        )
        coin = symbol.replace("USDT", "").replace("USDC", "") if symbol else ""

        # Get price values from SearchableDropDown, ensure they're not zero
        price_low = None
        price_high = None

        if (
            hasattr(self.symbol_input, "price_low_input")
            and self.symbol_input.price_low_input.text
        ):
            try:
                price_low = float(self.symbol_input.price_low_input.text)
                if price_low <= 0:
                    price_low = None
            except ValueError:
                price_low = None

        if (
            hasattr(self.symbol_input, "price_high_input")
            and self.symbol_input.price_high_input.text
        ):
            try:
                price_high = float(self.symbol_input.price_high_input.text)
                if price_high <= 0:
                    price_high = None
            except ValueError:
                price_high = None

        return HPConfiguration(
            hp_type="BUY",
            coin=coin,
            symbol=symbol,
            hp_id=str(uuid.uuid4())[:8],  # Generate unique ID
            budget=float(self.budget_input.text),
            price_low=price_low,
            price_high=price_high,
            order_trigger=float(self.order_trigger_spinner.text),
            mode=self.mode_spinner.text,
        )


class SellHPModal(BaseHPModal):
    """Modal for creating Sell HP positions."""

    def __init__(self, inventory_coins: Dict[str, List[Any]], **kwargs: Any) -> None:
        self.inventory_coins = inventory_coins
        super().__init__(title="Create Sell HP Position", **kwargs)

    def setup_form(self) -> None:
        """Setup Sell HP form fields."""
        # Coin selection (from inventory)
        coin_symbols = list(self.inventory_coins.keys()) if self.inventory_coins else []
        self.coin_spinner = Spinner(
            text="Select Coin" if coin_symbols else "No coins available",
            values=coin_symbols,
            size_hint_x=0.7,
        )
        self.coin_spinner.bind(text=self.on_coin_selected)
        self.form_layout.add_widget(self.create_form_row("Coin:", self.coin_spinner))

        # Available quantity (info only)
        self.available_label = Label(text="0.0", size_hint_x=0.7, halign="left")
        self.available_label.bind(size=self.available_label.setter("text_size"))
        self.form_layout.add_widget(
            self.create_form_row("Available:", self.available_label)
        )

        # Quantity to sell
        self.quantity_input = TextInput(
            text="",
            input_filter="float",
            multiline=False,
            size_hint_x=0.7,
            hint_text="Amount to sell",
        )
        self.form_layout.add_widget(
            self.create_form_row("Quantity:", self.quantity_input)
        )

        # Sell price
        self.sell_price_input = TextInput(
            text="",
            input_filter="float",
            multiline=False,
            size_hint_x=0.7,
            hint_text="Target sell price",
        )
        self.form_layout.add_widget(
            self.create_form_row("Sell Price:", self.sell_price_input)
        )

        # End currency
        self.end_currency_spinner = Spinner(
            text="USDC", values=["USDC", "USDT", "BTC", "ETH"], size_hint_x=0.7
        )
        self.form_layout.add_widget(
            self.create_form_row("End Currency:", self.end_currency_spinner)
        )

    def on_coin_selected(self, spinner: Any, text: str) -> None:
        """Handle coin selection change."""
        if text in self.inventory_coins:
            lots = self.inventory_coins[text]
            total_available = sum(lot.get("available_quantity", 0) for lot in lots)
            self.available_label.text = f"{total_available:.6f}"
        else:
            self.available_label.text = "0.0"

    def validate_form(self) -> Tuple[bool, str]:
        """Validate Sell HP form."""
        if self.coin_spinner.text == "Select Coin" or not self.inventory_coins:
            return False, "Please select a coin to sell"

        try:
            quantity = float(self.quantity_input.text)
            if quantity <= 0:
                return False, "Quantity must be greater than 0"

            # Check available quantity
            if self.coin_spinner.text in self.inventory_coins:
                lots = self.inventory_coins[self.coin_spinner.text]
                total_available = sum(lot.get("available_quantity", 0) for lot in lots)
                if quantity > total_available:
                    return (
                        False,
                        f"Quantity exceeds available amount ({total_available:.6f})",
                    )
        except ValueError:
            return False, "Invalid quantity value"

        try:
            sell_price = float(self.sell_price_input.text)
            if sell_price <= 0:
                return False, "Sell price must be greater than 0"
        except ValueError:
            return False, "Invalid sell price value"

        return True, ""

    def get_configuration(self) -> HPConfiguration:
        """Get Sell HP configuration."""
        return HPConfiguration(
            hp_type="SELL",
            coin=self.coin_spinner.text,
            symbol=f"{self.coin_spinner.text}USDT",  # Default symbol
            hp_id=str(uuid.uuid4())[:8],  # Generate unique ID
            quantity=float(self.quantity_input.text),
            sell_price=float(self.sell_price_input.text),
            end_currency=self.end_currency_spinner.text,
            inventory_source=self.coin_spinner.text,
        )
