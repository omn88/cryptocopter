from typing import Dict


class Symbol:
    def __init__(
        self,
        name: str = "",
        exchange: str = "",
        min_notional: float = 0,
        lot_size: float = 0,
        min_qty: float = 0,
        max_qty: float = 0,
        price_filter: float = 0,
        precision: int = 0,
        price_precision: int = 0,
        is_convert_only: bool = False,
    ):
        self.name = name
        self.exchange = exchange
        self.min_notional = min_notional
        self.lot_size = lot_size
        self.min_qty = min_qty
        self.max_qty = max_qty
        self.price_filter = price_filter
        self.precision = precision
        self.price_precision = price_precision
        self.is_convert_only = is_convert_only

    def __repr__(self):
        return (
            f"Symbol(name={self.name}, exchange={self.exchange}, min_notional={self.min_notional}, "
            f"lot_size={self.lot_size}, min_qty={self.min_qty}, max_qty={self.max_qty}, "
            f"price_filter={self.price_filter}, precision={self.precision}, "
            f"price_precision={self.price_precision}, is_convert_only={self.is_convert_only})"
        )

    def format_price(self, price: float) -> str:
        if price == 0:
            return "0.0"
        if price < 1:
            return (
                f"{price:.{self.price_precision}f}".rstrip("0").rstrip(".")
                if "." in f"{price:.{self.price_precision}f}"
                else f"{price:.{self.price_precision}f}"
            )
        return f"{price:.1f}" if price == round(price, 1) else f"{price:.2f}"

    def format_quantity(self, quantity: float) -> str:
        if quantity == 0:
            return "0.0"
        if quantity < 1:
            return (
                f"{quantity:.{self.precision}f}".rstrip("0").rstrip(".")
                if "." in f"{quantity:.{self.precision}f}"
                else f"{quantity:.{self.precision}f}"
            )

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

    def extract_coin_from_symbol(self) -> str:
        """Extract base coin from symbol name based on exchange format"""
        if self.exchange == "binance":
            return self._extract_binance_format()
        elif self.exchange == "kraken":
            return self._extract_kraken_format()
        else:
            raise ValueError(f"Unknown exchange: {self.exchange}")

    def _extract_binance_format(self) -> str:
        """Extract coin from Binance format (e.g., BTCUSDC -> BTC)"""
        known_quote_currencies = ["BTC", "USDC", "PLN", "BNB", "USDT"]
        for quote in known_quote_currencies:
            if self.name.endswith(quote):
                return self.name[: -len(quote)]
        raise ValueError(
            f"Symbol '{self.name}' does not end with a known quote currency"
        )

    def _extract_kraken_format(self) -> str:
        """Extract coin from Kraken format (e.g., XBT/USD -> XBT)"""
        if "/" in self.name:
            return self.name.split("/")[0]
        # Handle legacy format if needed (XXBTZUSD)
        raise ValueError(f"Unable to parse Kraken symbol: {self.name}")

    @staticmethod
    def calculate_precision(step_size):
        step_size_str = str(step_size).rstrip("0")
        if "." in step_size_str:
            return len(step_size_str.split(".")[1])
        return 0


# NOTE: fetch_symbols() has been moved to exchange client implementations
# (BinanceExchangeClient.fetch_symbols() and KrakenExchangeClient.fetch_symbols())
# This allows each exchange to parse its own trading rules format.
