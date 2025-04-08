# src/utils/usd_price_resolver.py
from typing import Dict
import logging
from src.common.symbol_info import SymbolInfo
from src.identifiers.common import BinanceClient

logger = logging.getLogger("price_resolver")


class UsdPriceResolver:
    def __init__(self, client: BinanceClient, symbols_info: Dict[str, SymbolInfo]):
        self.client = client
        self.symbols_info = symbols_info
        self.latest_prices: Dict[str, float] = {}

    def update_price(self, symbol: str, price: float):
        self.latest_prices[symbol] = price

    async def fetch_all_prices(self) -> None:
        """Fetch all symbol prices using Binance REST API."""
        prices = await self.client.get_all_tickers()  # Wraps GET /api/v3/ticker/price
        # Filter only those pairs you actually trade
        self.latest_prices = {
            item["symbol"]: float(item["price"])
            for item in prices
            if item["symbol"] in self.symbols_info
        }
        logger.info("Latest prices: %s", self.latest_prices)

    def resolve_usd(self, coin: str) -> float:
        raw_price = None

        # Priority 1: coinUSDC
        if f"{coin}USDC" in self.latest_prices:
            raw_price = self.latest_prices[f"{coin}USDC"]
            logger.info("Coin %s has pair to USDC, price: %s", coin, raw_price)

        # Priority 2: coinBTC + BTCUSDC
        elif f"{coin}BTC" in self.latest_prices and "BTCUSDC" in self.latest_prices:
            raw_price = self.latest_prices[f"{coin}BTC"] * self.latest_prices["BTCUSDC"]
            logger.info("Coin %s has pair to BTC, price: %s", coin, raw_price)

        # Priority 3: Exotic pairs like coinTRY + TRYUSDC
        else:
            for pair, price in self.latest_prices.items():
                if pair.startswith(coin):
                    quote = pair.replace(coin, "")
                    usdc_pair = f"{quote}USDC"
                    if usdc_pair in self.latest_prices:
                        raw_price = price * self.latest_prices[usdc_pair]
                        logger.info(
                            "Coin %s has pair to %s, which has pair to USDC price: %s",
                            coin,
                            quote,
                            raw_price,
                        )
                        break

        # Priority 4: Fallback to USDT pricing (if available)
        if raw_price is None and f"{coin}USDT" in self.latest_prices:
            raw_price = self.latest_prices[f"{coin}USDT"]
            logger.info(
                "Coin %s has no proper pair and must be converted: %s", coin, raw_price
            )

        if raw_price is None:
            raise ValueError(f"Cannot resolve USD price for {coin}")

        # Attempt to apply adjustment using symbol info (usually symbolUSDT)
        try:
            symbol_info = self.symbols_info[f"{coin}USDT"]
            return symbol_info.adjust_price(raw_price)
        except KeyError:
            return round(raw_price, 6)  # Fallback rounding
