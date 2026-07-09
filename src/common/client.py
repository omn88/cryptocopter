import asyncio
import json
import logging

import websockets
from kraken.spot import Market, Trade

from src.domain.constants import ORDER_STATUS_NEW

_KNOWN_QUOTE_CURRENCIES = ("USDC", "USDT", "BTC", "PLN", "BNB")
_KRAKEN_WS_PUBLIC_URL = "wss://ws.kraken.com/v2"


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

    async def get_ws_token(self) -> dict:
        """Fetch a one-time WS auth token via GetWebSocketsToken (valid 15 min).

        python-kraken-sdk has no dedicated wrapper for this endpoint, so it's called
        through the generic signed-request method the SDK's REST clients expose.
        """
        return await asyncio.to_thread(
            self._trade.request,  # type: ignore[arg-type]
            method="POST",
            uri="/0/private/GetWebSocketsToken",
        )

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

    async def get_asset_pairs_ws(self, timeout: float = 5.0) -> dict:
        """Fetch the WS v2 `instrument` channel snapshot, normalized to the same
        shape get_asset_pairs() (REST) returns, so callers can treat either source
        interchangeably.

        One-shot connect -> subscribe -> wait for the snapshot -> disconnect. This is
        the preferred source for fetch_symbols() per the "WS is primary, REST is
        fallback" migration direction; callers should catch any exception (including
        timeout) from this method and fall back to get_asset_pairs().

        NOTE: the field mapping below is based on Kraken's documented WS v2 instrument
        schema and has not been verified against a live connection - this codebase's
        test suite always mocks KrakenClient. Smoke-test against the real API before
        relying on this in production.
        """
        async with websockets.connect(_KRAKEN_WS_PUBLIC_URL) as ws:
            await ws.send(
                json.dumps({"method": "subscribe", "params": {"channel": "instrument"}})
            )
            async with asyncio.timeout(timeout):
                while True:
                    raw = await ws.recv()
                    msg = json.loads(raw)
                    if (
                        msg.get("channel") == "instrument"
                        and msg.get("type") == "snapshot"
                    ):
                        return self._normalize_ws_instrument_snapshot(msg)

    def _normalize_ws_instrument_snapshot(self, msg: dict) -> dict:
        pairs = {}
        for pair in msg.get("data", {}).get("pairs", []):
            try:
                name = self._from_kraken_symbol(pair["symbol"])
                pairs[name] = {
                    "status": pair["status"],
                    "lot_decimals": pair["qty_precision"],
                    "pair_decimals": pair["price_precision"],
                    "ordermin": pair["qty_min"],
                    "costmin": pair["cost_min"],
                    "tick_size": pair.get("tick_size", pair.get("price_increment")),
                }
            except (KeyError, ValueError) as e:
                self.logger.warning(
                    "Skipping WS instrument pair %s: %s", pair.get("symbol"), e
                )
        return pairs
