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

from src.common.symbol import Symbol
from src.gui.searchable_drop_down import SearchableDropDown
from .hp_config import HPConfiguration

logger = logging.getLogger(__name__)


class BaseHPModal(Popup):  # type: ignore[misc]
    """Base class for HP configuration modals."""

    def __init__(
        self, callback: Callable[[HPConfiguration], None], **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self.callback = callback
        self.size_hint = (0.7, 0.7)  # More reasonable modal size
        self.title_size = "18sp"
        self.auto_dismiss = False

        # Create main layout with proper spacing
        main_layout = BoxLayout(orientation="vertical", padding=30, spacing=10)

        # Validation message at top (hidden by default)
        self.validation_label = Label(
            text="",
            color=(1, 0, 0, 1),
            size_hint_y=None,
            height=0,  # Hidden by default
            markup=True,
        )
        main_layout.add_widget(self.validation_label)

        # Form container with scroll support for many fields
        from kivy.uix.scrollview import ScrollView

        scroll_view = ScrollView(size_hint=(1, 1), do_scroll_x=False)

        # Add form fields (implemented in subclasses)
        self.form_layout = BoxLayout(
            orientation="vertical", spacing=12, size_hint_y=None
        )
        self.form_layout.bind(minimum_height=self.form_layout.setter("height"))

        scroll_view.add_widget(self.form_layout)
        main_layout.add_widget(scroll_view)

        # Create button layout at bottom
        button_layout = BoxLayout(
            size_hint_y=None, height=50, spacing=15, padding=[0, 15, 0, 0]
        )

        cancel_btn = Button(text="Cancel", size_hint_x=None, width=150)
        cancel_btn.bind(on_release=self.dismiss)

        self.create_btn = Button(text="Create HP", size_hint_x=None, width=150)
        self.create_btn.bind(on_release=self.on_create)

        button_layout.add_widget(Label())  # Spacer
        button_layout.add_widget(cancel_btn)
        button_layout.add_widget(self.create_btn)

        main_layout.add_widget(button_layout)
        self.content = main_layout

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
            self.validation_label.text = f"[b]Error:[/b] {error_message}"
            self.validation_label.height = 40  # Show error
            return

        try:
            config = self.get_configuration()
            self.callback(config)
            self.dismiss()
        except Exception as e:
            logger.error("Error creating HP configuration: %s", e)
            self.validation_label.text = f"[b]Error:[/b] {str(e)}"
            self.validation_label.height = 40  # Show error

    def create_form_row(
        self, label_text: str, widget: Any, label_width: float = 0.35
    ) -> BoxLayout:
        """Create a form row with label and widget."""
        row = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=45, spacing=20
        )

        label = Label(
            text=label_text, size_hint_x=label_width, halign="right", valign="middle"
        )
        label.bind(size=label.setter("text_size"))

        row.add_widget(label)
        row.add_widget(widget)

        return row


class BuyHPModal(BaseHPModal):
    """Modal for creating Buy HP positions."""

    def __init__(
        self,
        available_symbols: List[str],
        symbols: Dict[str, Symbol],
        client: Any = None,
        **kwargs: Any,
    ) -> None:
        self.available_symbols = available_symbols
        self.symbols = symbols
        self.client = client
        self.selected_symbol = ""  # Initialize selected symbol
        super().__init__(title="Create Buy HP Position", **kwargs)

    def setup_form(self) -> None:
        """Setup Buy HP form fields."""
        # Symbol selection using SearchableDropDown
        self.symbol_input = SearchableDropDown(
            client=self.client, options=self.available_symbols, symbols=self.symbols
        )
        self.form_layout.add_widget(self.symbol_input)

        # Budget
        self.budget_input = TextInput(
            text="1000", input_filter="float", multiline=False, size_hint_x=0.65
        )
        self.form_layout.add_widget(
            self.create_form_row("Budget (USD):", self.budget_input)
        )

        # Order trigger
        self.order_trigger_spinner = Spinner(
            text="1.0",
            values=[str(round(x * 0.5, 1)) for x in range(0, 11)],
            size_hint_x=0.65,
        )
        self.form_layout.add_widget(
            self.create_form_row("Order Trigger (%):", self.order_trigger_spinner)
        )

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

        # Get price value from SearchableDropDown, ensure it's not zero
        buy_price = None

        if (
            hasattr(self.symbol_input, "buy_price_input")
            and self.symbol_input.buy_price_input.text
        ):
            try:
                buy_price = float(self.symbol_input.buy_price_input.text)
                if buy_price <= 0:
                    buy_price = None
            except ValueError:
                buy_price = None

        return HPConfiguration(
            hp_type="BUY",
            coin=coin,
            symbol=symbol,
            hp_id=str(uuid.uuid4())[:8],  # Generate unique ID
            budget=float(self.budget_input.text),
            buy_price=buy_price,
            order_trigger=float(self.order_trigger_spinner.text),
            mode=self.mode_spinner.text,
        )
