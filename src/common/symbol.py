import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class Symbol:
    def __init__(
        self,
        name: str = "",
        min_notional: float = 0,
        min_qty: float = 0,
        price_filter: float = 0,
        precision: int = 0,
        price_precision: int = 0,
        is_convert_only: bool = False,
    ):
        self.name = name
        self.min_notional = min_notional
        self.min_qty = min_qty
        self.price_filter = price_filter
        self.precision = precision
        self.price_precision = price_precision
        self.is_convert_only = is_convert_only

    def __repr__(self) -> str:
        return (
            f"Symbol(name={self.name}, min_notional={self.min_notional}, "
            f"min_qty={self.min_qty}, "
            f"price_filter={self.price_filter}, precision={self.precision}, "
            f"price_precision={self.price_precision}, is_convert_only={self.is_convert_only})"
        )

    def _format_decimal(self, value: float, precision: int) -> str:
        """Format a sub-1 decimal, stripping trailing zeros."""
        formatted = f"{value:.{precision}f}"
        if "." in formatted:
            return formatted.rstrip("0").rstrip(".")
        return formatted

    def format_price(self, price: float) -> str:
        if price == 0:
            return "0.0"
        if price < 1:
            return self._format_decimal(price, self.price_precision)
        return f"{price:.1f}" if price == round(price, 1) else f"{price:.2f}"

    def format_quantity(self, quantity: float) -> str:
        if quantity == 0:
            return "0.0"
        if quantity < 1:
            return self._format_decimal(quantity, self.precision)
        return (
            f"{quantity:.1f}" if quantity == round(quantity, 1) else f"{quantity:.2f}"
        )

    def adjust_quantity(self, quantity: float) -> float:
        return round(quantity, self.precision)

    def adjust_price(self, price: float) -> float:
        return round(price, self.price_precision)

    def validate_order(self, price: float, quantity: float) -> None:
        notional = price * quantity
        if notional < self.min_notional:
            price_str = f"{price:.{self.price_precision}f}"
            quantity_str = f"{quantity:.{self.precision}f}"
            notional_str = f"{notional:.{self.price_precision}f}"
            min_notional_str = f"{self.min_notional:.{self.price_precision}f}"

            raise ValueError(
                f"Order notional is below MIN_NOTIONAL, "
                f"notional: {notional_str}, "
                f"min notional: {min_notional_str}, "
                f"price: {price_str}, quantity: {quantity_str}"
            )

    def extract_coin_from_symbol(self, symbol: str) -> str:
        known_quote_currencies = ["BTC", "USDC", "PLN", "BNB", "USDT"]
        for quote in known_quote_currencies:
            if symbol.endswith(quote):
                return symbol[: -len(quote)]
        raise ValueError(f"Symbol '{symbol}' does not end with a known quote currency")

    @staticmethod
    def calculate_precision(step_size: object) -> int:
        step_size_str = str(step_size).rstrip("0")
        if "." in step_size_str:
            return len(step_size_str.split(".")[1])
        return 0


async def fetch_symbols(client: Any) -> Dict[str, Symbol]:
    asset_pairs = await client.get_asset_pairs()
    symbols = {}
    for name, pair in asset_pairs.items():
        if pair["status"] != "online":
            continue
        try:
            symbols[name] = Symbol(
                name=name,
                min_notional=float(pair["costmin"]),
                min_qty=float(pair["ordermin"]),
                price_filter=float(pair["tick_size"]),
                precision=pair["lot_decimals"],
                price_precision=pair["pair_decimals"],
            )
        except (KeyError, ValueError) as e:
            logger.warning("Skipping Kraken pair %s: %s", name, e)
    return symbols
