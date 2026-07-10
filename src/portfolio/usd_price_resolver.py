# src/utils/usd_price_resolver.py
from typing import Dict
import logging
from src.common.symbol import Symbol
from src.common.client import KrakenClient
from src.strategies.hp_manager.sell_strategies.factory import DELISTED_COINS

logger = logging.getLogger(__name__)


class UsdPriceResolver:
    def __init__(self, client: KrakenClient, symbols: Dict[str, Symbol]):
        self.client = client
        self.symbols = symbols
        self.latest_prices: Dict[str, float] = {}

    def update_price(self, symbol: str, price: float) -> None:
        self.latest_prices[symbol] = price

    async def fetch_all_prices(self) -> None:
        """Fetch all symbol prices using the exchange REST API."""
        # TODO(PR4): KrakenClient.get_all_tickers not implemented yet.
        prices = await self.client.get_all_tickers()  # type: ignore[attr-defined]
        # Filter only those pairs you actually trade
        self.latest_prices = {
            item["symbol"]: float(item["price"])
            for item in prices
            if item["symbol"] in self.symbols
        }
        # logger.debug("Latest prices: %s", self.latest_prices)

    def resolve_usd(self, coin: str) -> float:
        raw_price = None

        # Priority 1: coinUSDC
        if f"{coin}USDC" in self.latest_prices:
            raw_price = self.latest_prices[f"{coin}USDC"]

        # Priority 2: coinBTC + BTCUSDC — only if coin is NOT delisted
        elif (
            coin not in DELISTED_COINS
            and f"{coin}BTC" in self.latest_prices
            and "BTCUSDC" in self.latest_prices
        ):
            raw_price = self.latest_prices[f"{coin}BTC"] * self.latest_prices["BTCUSDC"]

        # Priority 3: coinETH + ETHUSDC — only if coin is NOT delisted
        elif (
            coin not in DELISTED_COINS
            and f"{coin}ETH" in self.latest_prices
            and "ETHUSDC" in self.latest_prices
        ):
            raw_price = self.latest_prices[f"{coin}ETH"] * self.latest_prices["ETHUSDC"]

        if raw_price is None:
            logger.debug("Cannot resolve USD price for coin: %s", coin)
            raise ValueError(f"Cannot resolve USD price for {coin}")

        # Apply adjustment using symbol info if available
        try:
            symbol = self.symbols[f"{coin}USDC"]
            return symbol.adjust_price(raw_price)
        except KeyError:
            return round(raw_price, 6)
