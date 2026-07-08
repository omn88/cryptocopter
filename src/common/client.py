import asyncio
import logging

from kraken.spot import Market, Trade

from src.domain.constants import ORDER_STATUS_NEW

_KNOWN_QUOTE_CURRENCIES = ("USDC", "USDT", "BTC", "PLN", "BNB")


class KrakenClient:
    """Thin async wrapper around python-kraken-sdk's synchronous REST clients.

    python-kraken-sdk's REST clients are synchronous (requests-based); calls are
    offloaded to a thread so they don't block the asyncio event loop.
    """

    def __init__(self, api_key: str, api_secret: str):
        self._trade = Trade(key=api_key, secret=api_secret)
        self._market = Market()
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _to_kraken_symbol(internal: str) -> str:
        """ "BTCUSDC" -> "XBT/USDC"; "ETHBTC" -> "ETH/XBT" """
        for quote in _KNOWN_QUOTE_CURRENCIES:
            if internal.endswith(quote) and internal != quote:
                base = internal[: -len(quote)]
                base = "XBT" if base == "BTC" else base
                quote = "XBT" if quote == "BTC" else quote
                return f"{base}/{quote}"
        raise ValueError(
            f"Symbol '{internal}' does not end with a known quote currency"
        )

    @staticmethod
    def _from_kraken_symbol(kraken: str) -> str:
        """ "XBT/USDC" -> "BTCUSDC" """
        base, _, quote = kraken.partition("/")
        base = "BTC" if base == "XBT" else base
        quote = "BTC" if quote == "XBT" else quote
        return f"{base}{quote}"

    async def create_order(
        self,
        symbol: str,
        side: str,
        type: str,
        quantity: float,
        price: str,
        timeInForce: str,
    ) -> dict:
        resp = await asyncio.to_thread(
            self._trade.create_order,
            ordertype=type.lower(),
            side=side.lower(),
            pair=self._to_kraken_symbol(symbol),
            volume=quantity,
            price=price,
            timeinforce=timeInForce,
        )
        return {"orderId": resp["txid"][0], "status": ORDER_STATUS_NEW}

    async def cancel_order(self, symbol: str, orderId: str) -> dict:
        return await asyncio.to_thread(self._trade.cancel_order, txid=orderId)

    async def get_asset_pairs(self) -> dict:
        """Fetch Kraken AssetPairs, keyed by internal symbol name (e.g. "BTCUSDC").

        Pairs without a usable `wsname` (e.g. dark-pool pairs) are dropped here,
        since normalizing Kraken's naming is this class's job alone.
        """
        raw_pairs = await asyncio.to_thread(self._market.get_asset_pairs)
        pairs = {}
        for altname, pair in raw_pairs.items():
            try:
                name = self._from_kraken_symbol(pair["wsname"])
            except (KeyError, ValueError) as e:
                self.logger.warning("Skipping Kraken pair %s: %s", altname, e)
                continue
            pairs[name] = pair
        return pairs
