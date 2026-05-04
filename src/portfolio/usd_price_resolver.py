# src/utils/usd_price_resolver.py
from typing import Dict
import logging
from src.common.symbol import Symbol
from src.common.client import BinanceClient
from src.strategies.hp_manager.sell_strategies.factory import DELISTED_COINS

logger = logging.getLogger(__name__)


class UsdPriceResolver:
    def __init__(self, client: BinanceClient, symbols: Dict[str, Symbol]):
        self.client = client
        self.symbols = symbols
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
            if item["symbol"] in self.symbols
        }
        # logger.debug("Latest prices: %s", self.latest_prices)

    def resolve_usd(self, coin: str) -> float:
        raw_price = None

        # Priority 1: coinUSDC
        if f"{coin}USDC" in self.latest_prices:
            raw_price = self.latest_prices[f"{coin}USDC"]
            # logger.info("Coin %s has direct pair to USDC, price: %s", coin, raw_price)

        # Priority 2: coinBTC + BTCUSDC — only if coin is NOT delisted
        elif (
            coin not in DELISTED_COINS
            and f"{coin}BTC" in self.latest_prices
            and "BTCUSDC" in self.latest_prices
        ):
            raw_price = self.latest_prices[f"{coin}BTC"] * self.latest_prices["BTCUSDC"]
        #     logger.info(
        #         "Coin %s has pair to BTC and BTC has USDC, resolved price: %s",
        #         coin,
        #         raw_price,
        #     )
        # elif coin in delisted_coins:
        #     logger.info(
        #         "Coin %s is delisted, skipping BTC and exotic pair resolution", coin
        #     )

        # Priority 3: Exotic pairs like coinTRY + TRYUSDC
        elif coin not in DELISTED_COINS:
            for pair, price in self.latest_prices.items():
                if pair.startswith(coin):
                    quote = pair.replace(coin, "")
                    usdc_pair = f"{quote}USDC"
                    if quote in DELISTED_COINS:
                        # logger.info(
                        #     "Coin %s has pair to %s, but %s is delisted — skipping",
                        #     coin,
                        #     quote,
                        #     quote,
                        # )
                        continue
                    if usdc_pair in self.latest_prices:
                        raw_price = price * self.latest_prices[usdc_pair]
                        # logger.info(
                        #     "Coin %s has pair to %s and %s has USDC, resolved price: %s",
                        #     coin,
                        #     quote,
                        #     quote,
                        #     raw_price,
                        # )
                        break

        # Priority 4: Fallback to coinUSDT ONLY
        if raw_price is None and f"{coin}USDT" in self.latest_prices:
            raw_price = self.latest_prices[f"{coin}USDT"]
            # logger.info("Coin %s uses fallback to USDT, price: %s", coin, raw_price)

        if raw_price is None:
            logger.debug("Cannot resolve USD price for coin: %s", coin)
            raise ValueError(f"Cannot resolve USD price for {coin}")

        # Apply adjustment using symbol info if available
        try:
            symbol = self.symbols[f"{coin}USDT"]
            price = symbol.adjust_price(raw_price)
            # logger.info("Adjusted price for coin %s using symbol info: %s", coin, price)
            return price
        except KeyError:
            # logger.error("Key error while adjusting price for coin: %s", coin)
            return round(raw_price, 6)
