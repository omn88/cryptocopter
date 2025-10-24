"""Dynamic configuration GUI for Buy Dip strategy.

Allows users to:
- Add/remove DCA order levels dynamically
- Set custom percentage for each level
- Use presets (mathematical constants, custom ranges)
- Preview order prices for a given top
"""

from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.properties import ListProperty, NumericProperty
from typing import List, Callable, Optional


class DCALevelWidget(BoxLayout):
    """Widget for a single DCA level configuration."""

    def __init__(
        self, level_num: int, percentage: float, on_remove: Callable, **kwargs
    ):
        super().__init__(
            orientation="horizontal", size_hint_y=None, height=40, **kwargs
        )

        self.level_num = level_num
        self.on_remove_callback = on_remove

        # Level label
        self.add_widget(Label(text=f"Order {level_num}:", size_hint_x=0.25))

        # Percentage input
        self.percentage_input = TextInput(
            text=f"{percentage:.3f}",
            multiline=False,
            input_filter="float",
            size_hint_x=0.4,
        )
        self.add_widget(self.percentage_input)

        # Percentage symbol
        self.add_widget(Label(text="% below top", size_hint_x=0.25))

        # Remove button
        remove_btn = Button(
            text="X", size_hint_x=0.1, background_color=(0.8, 0.2, 0.2, 1)
        )
        remove_btn.bind(on_press=self._on_remove)
        self.add_widget(remove_btn)

    def _on_remove(self, instance):
        """Handle remove button press."""
        if self.on_remove_callback:
            self.on_remove_callback(self)

    def get_percentage(self) -> float:
        """Get the percentage value."""
        try:
            return float(self.percentage_input.text)
        except ValueError:
            return 0.0


class BuyDipConfigPopup(Popup):
    """Popup for configuring Buy Dip strategy parameters."""

    dca_levels = ListProperty([1.618, 2.718, 3.142])  # Default: φ, e, π

    def __init__(
        self,
        initial_levels: Optional[List[float]] = None,
        on_save: Optional[Callable] = None,
        **kwargs,
    ):
        """Initialize configuration popup.

        Args:
            initial_levels: Initial DCA levels (default: [φ, e, π])
            on_save: Callback when configuration is saved, receives list of percentages
        """
        self.on_save_callback = on_save

        if initial_levels:
            self.dca_levels = sorted(initial_levels)

        super().__init__(
            title="Buy Dip Strategy Configuration", size_hint=(0.9, 0.9), **kwargs
        )

        self._build_content()

    def _build_content(self):
        """Build the popup content."""
        main_layout = BoxLayout(orientation="vertical", padding=10, spacing=10)

        # Header
        header = Label(
            text="Configure DCA Order Levels\n(Distances below detected top)",
            size_hint_y=None,
            height=60,
            font_size="16sp",
            bold=True,
        )
        main_layout.add_widget(header)

        # Preset buttons
        preset_layout = BoxLayout(size_hint_y=None, height=50, spacing=5)
        preset_layout.add_widget(Label(text="Presets:", size_hint_x=0.2))

        presets = [
            ("φ,e,π (Elegant)", [1.618, 2.718, 3.142]),
            ("3 Levels", [1.0, 2.0, 3.0]),
            ("6 Levels", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
            ("Fibonacci", [1.618, 2.618, 4.236, 6.854]),
        ]

        for preset_name, preset_values in presets:
            btn = Button(text=preset_name, size_hint_x=0.2)
            btn.bind(on_press=lambda x, vals=preset_values: self._apply_preset(vals))
            preset_layout.add_widget(btn)

        main_layout.add_widget(preset_layout)

        # Scrollable DCA levels list
        scroll_container = BoxLayout(orientation="vertical", size_hint_y=0.6)

        self.levels_layout = GridLayout(cols=1, spacing=5, size_hint_y=None)
        self.levels_layout.bind(minimum_height=self.levels_layout.setter("height"))

        scroll_view = ScrollView(size_hint=(1, 1))
        scroll_view.add_widget(self.levels_layout)
        scroll_container.add_widget(scroll_view)

        main_layout.add_widget(scroll_container)

        # Rebuild DCA levels
        self._rebuild_levels()

        # Add level button
        add_btn = Button(
            text="+ Add Order Level",
            size_hint_y=None,
            height=50,
            background_color=(0.2, 0.8, 0.2, 1),
        )
        add_btn.bind(on_press=self._add_level)
        main_layout.add_widget(add_btn)

        # Preview section
        preview_layout = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=80, spacing=10
        )

        preview_left = BoxLayout(orientation="vertical")
        preview_left.add_widget(Label(text="Preview for top:"))
        self.preview_top_input = TextInput(
            text="67890", multiline=False, input_filter="float"
        )
        self.preview_top_input.bind(text=self._update_preview)
        preview_left.add_widget(self.preview_top_input)

        self.preview_label = Label(
            text="",
            size_hint_x=0.6,
            text_size=(None, None),
            halign="left",
            valign="top",
        )

        preview_layout.add_widget(preview_left)
        preview_layout.add_widget(self.preview_label)

        main_layout.add_widget(preview_layout)

        # Update initial preview
        self._update_preview()

        # Action buttons
        action_layout = BoxLayout(size_hint_y=None, height=50, spacing=10)

        save_btn = Button(
            text="Save Configuration", background_color=(0.2, 0.6, 0.8, 1)
        )
        save_btn.bind(on_press=self._save)

        cancel_btn = Button(text="Cancel", background_color=(0.6, 0.6, 0.6, 1))
        cancel_btn.bind(on_press=self.dismiss)

        action_layout.add_widget(cancel_btn)
        action_layout.add_widget(save_btn)

        main_layout.add_widget(action_layout)

        self.content = main_layout

    def _rebuild_levels(self):
        """Rebuild the DCA levels list."""
        self.levels_layout.clear_widgets()

        for i, pct in enumerate(self.dca_levels, start=1):
            level_widget = DCALevelWidget(
                level_num=i, percentage=pct, on_remove=self._remove_level
            )
            self.levels_layout.add_widget(level_widget)

    def _add_level(self, instance):
        """Add a new DCA level."""
        # Add new level 1% above the last one
        if self.dca_levels:
            new_pct = self.dca_levels[-1] + 1.0
        else:
            new_pct = 1.0

        self.dca_levels.append(new_pct)
        self._rebuild_levels()
        self._update_preview()

    def _remove_level(self, level_widget: DCALevelWidget):
        """Remove a DCA level."""
        if len(self.dca_levels) <= 1:
            # Don't allow removing the last level
            from kivy.uix.label import Label
            from kivy.uix.popup import Popup

            error_popup = Popup(
                title="Cannot Remove",
                content=Label(text="Must have at least one DCA level!"),
                size_hint=(0.6, 0.3),
            )
            error_popup.open()
            return

        # Remove from list
        index = level_widget.level_num - 1
        if 0 <= index < len(self.dca_levels):
            self.dca_levels.pop(index)
            self._rebuild_levels()
            self._update_preview()

    def _apply_preset(self, preset_values: List[float]):
        """Apply a preset configuration."""
        self.dca_levels = sorted(preset_values.copy())
        self._rebuild_levels()
        self._update_preview()

    def _update_preview(self, *args):
        """Update the preview of order prices."""
        try:
            top_price = float(self.preview_top_input.text)
        except ValueError:
            self.preview_label.text = "Invalid top price"
            return

        # Collect current percentages
        current_levels = []
        for widget in self.levels_layout.children:
            if isinstance(widget, DCALevelWidget):
                pct = widget.get_percentage()
                current_levels.append(pct)

        current_levels = sorted(current_levels, reverse=True)  # Reverse for display

        # Build preview text
        preview_lines = [f"Top: ${top_price:,.2f}\n"]
        for i, pct in enumerate(reversed(current_levels), start=1):
            order_price = top_price * (1 - pct / 100)
            preview_lines.append(f"Order {i}: ${order_price:,.2f} (-{pct:.3f}%)")

        self.preview_label.text = "\n".join(preview_lines)

    def _save(self, instance):
        """Save configuration and close popup."""
        # Collect all percentages
        saved_levels = []
        for widget in self.levels_layout.children:
            if isinstance(widget, DCALevelWidget):
                pct = widget.get_percentage()
                if pct > 0:  # Only save valid percentages
                    saved_levels.append(pct)

        if not saved_levels:
            from kivy.uix.label import Label
            from kivy.uix.popup import Popup

            error_popup = Popup(
                title="Invalid Configuration",
                content=Label(text="Must have at least one valid DCA level!"),
                size_hint=(0.6, 0.3),
            )
            error_popup.open()
            return

        # Sort and save
        saved_levels = sorted(saved_levels)

        # Call callback
        if self.on_save_callback:
            self.on_save_callback(saved_levels)

        self.dismiss()


def show_config_popup(
    initial_levels: Optional[List[float]] = None, on_save: Optional[Callable] = None
):
    """Show the configuration popup.

    Args:
        initial_levels: Initial DCA levels (default: [φ, e, π])
        on_save: Callback when configuration is saved, receives list of percentages

    Example:
        def handle_save(levels: List[float]):
            print(f"New configuration: {levels}")

        show_config_popup(
            initial_levels=[1.618, 2.718, 3.142],
            on_save=handle_save
        )
    """
    popup = BuyDipConfigPopup(initial_levels=initial_levels, on_save=on_save)
    popup.open()


if __name__ == "__main__":
    """Test the configuration popup."""
    from kivy.app import App

    class TestApp(App):
        def build(self):
            layout = BoxLayout(orientation="vertical", padding=20)

            btn = Button(text="Open Config Popup")
            btn.bind(on_press=self.show_popup)
            layout.add_widget(btn)

            self.result_label = Label(text="Configure to see result")
            layout.add_widget(self.result_label)

            return layout

        def show_popup(self, instance):
            def on_save(levels):
                self.result_label.text = f"Saved configuration:\n{levels}"

            show_config_popup(initial_levels=[1.618, 2.718, 3.142], on_save=on_save)

    TestApp().run()
