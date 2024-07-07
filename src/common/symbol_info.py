from typing import Dict


class SymbolInfo:
    def __init__(
        self,
        symbol: str = "",
        min_notional: float = 0,
        lot_size: float = 0,
        min_qty: float = 0,
        max_qty: float = 0,
        price_filter: float = 0,
        precision: int = 0,
        price_precision: int = 0,
    ):
        self.symbol = symbol
        self.min_notional = min_notional
        self.lot_size = lot_size
        self.min_qty = min_qty
        self.max_qty = max_qty
        self.price_filter = price_filter
        self.precision = precision
        self.price_precision = price_precision

    def __repr__(self):
        return (
            f"SymbolInfo(symbol={self.symbol}, min_notional={self.min_notional}, lot_size={self.lot_size}, "
            f"min_qty={self.min_qty}, max_qty={self.max_qty}, price_filter={self.price_filter}, precision={self.precision}, price_precision={self.price_precision})"
        )

    def adjust_quantity(self, quantity):
        return round(max(self.min_qty, min(quantity, self.max_qty)), self.precision)

    def validate_order(self, price, quantity):
        notional = price * quantity
        if notional < self.min_notional:
            raise ValueError("Order notional is below MIN_NOTIONAL")

    @staticmethod
    def calculate_precision(step_size):
        step_size_str = str(step_size).rstrip("0")
        if "." in step_size_str:
            return len(step_size_str.split(".")[1])
        return 0


async def fetch_symbol_info(client) -> Dict[str, SymbolInfo]:
    exchange_info = await client.get_exchange_info()
    symbols_info = {}
    for symbol in exchange_info["symbols"]:
        if symbol["status"] == "TRADING":
            filters = {f["filterType"]: f for f in symbol["filters"]}
            symbols_info[symbol["symbol"]] = SymbolInfo(
                symbol=symbol["symbol"],
                min_notional=float(filters.get("NOTIONAL", {}).get("minNotional", 0)),
                lot_size=float(filters.get("LOT_SIZE", {}).get("stepSize", 0)),
                min_qty=float(filters.get("LOT_SIZE", {}).get("minQty", 0)),
                max_qty=float(filters.get("LOT_SIZE", {}).get("maxQty", 0)),
                price_filter=float(filters.get("PRICE_FILTER", {}).get("tickSize", 0)),
                precision=SymbolInfo.calculate_precision(
                    filters["LOT_SIZE"]["stepSize"]
                ),
                price_precision=SymbolInfo.calculate_precision(
                    filters.get("PRICE_FILTER", {}).get("tickSize", 0)
                ),
            )
    return symbols_info
