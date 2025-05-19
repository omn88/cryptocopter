import asyncio
import logging
import queue
import threading
from typing import Dict, Optional
from decouple import Config, RepositoryEnv
from src.common.symbol_info import SymbolInfo
from src.identifiers.common import BinanceClient
from src.identifiers.spot import (
    AccountPosition,
    AllTickers,
    Balances,
    Event,
    EventName,
    PriceUpdates,
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
)
from src.broker import BrokerSpot
from src.portfolio.usd_price_resolver import UsdPriceResolver

# Specify the path to the .env file
DOTENV_FILE = "config/.env"
config_env = Config(RepositoryEnv(DOTENV_FILE))

logger = logging.getLogger("portfolio")


class PortfolioManager:
    def __init__(
        self,
        broker: BrokerSpot,
        ui_queue: queue.Queue,
        balances: Dict[str, float],
        symbols_info: Dict[str, SymbolInfo],
        price_resolver: UsdPriceResolver,
    ):
        self.client: Optional[BinanceClient] = None
        self.broker = broker
        self.ui_queue = ui_queue
        self.worker_queue: queue.Queue = queue.Queue()
        self.balances = balances
        self.price_updates: Dict[str, float] = {}  # Store latest price updates
        self.btc_saldo = 0.0
        self.usd_saldo = 0.0
        self.price_resolver = price_resolver
        self.symbols_info = symbols_info

        # Starting the async loop
        self.loop = asyncio.new_event_loop()
        self.stop_event = asyncio.Event()
        self.thread = threading.Thread(target=self.start_loop)
        self.thread.start()

    def start_loop(self) -> None:
        """Starts the asyncio loop in a new thread."""
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.run())

    async def run(self) -> None:
        """Main portfolio manager loop."""
        logger.info("PortfolioManager is running.")

        self.client = BinanceClient(
            api_key=config_env("API_KEY"), api_secret=config_env("API_SECRET")
        )
        self.ui_queue.put_nowait(
            Event(name=EventName.BALANCES, content=Balances(msg=self.balances))
        )

        # Subscribe to user and price updates for portfolio management
        self.broker.subscribe(
            system_id="PORTFOLIO",
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.USER,
                symbol="ALL",  # Subscribing to all symbols for user account positions
                target=SubscriptionTarget.PORTFOLIO,
                queue=self.worker_queue,
            ),
        )
        self.broker.subscribe(
            system_id="PORTFOLIO",
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol="ALL",  # Subscribing to all symbols for price updates
                target=SubscriptionTarget.PORTFOLIO,
                queue=self.worker_queue,
            ),
        )

        while not self.stop_event.is_set():
            try:
                event = self.worker_queue.get_nowait()
                # logger.info("Portfolio go new event: %s", event)
                if event.name == EventName.ACCOUNT_POSITION:
                    await self.handle_account_position(event.content)
                elif event.name == EventName.ALL_TICKERS:
                    await self.handle_tickers(event.content)
            except queue.Empty:
                await asyncio.sleep(0.1)  # Sleep briefly to prevent busy waiting
                continue

        logger.info("PortfolioManager loop exiting.")

    def stop(self) -> None:
        """Gracefully stop the PortfolioManager."""
        logger.info("Stopping PortfolioManager...")

        # Set the stop event to notify the loop to exit
        self.stop_event.set()

        # Unsubscribe from the broker feeds
        self.broker.unsubscribe("PORTFOLIO")

        # Wait for the thread to finish
        if self.thread.is_alive():
            self.thread.join()

        logger.info("PortfolioManager stopped.")

    async def handle_account_position(self, account_position: AccountPosition) -> None:
        """Handle account position updates (update balances)."""
        logger.info("Handling account position update.")

        for balance in account_position.balances:
            coin = balance.coin
            total_balance = balance.free + balance.locked

            # Update the balance only if there's a change
            if total_balance != self.balances.get(coin, 0.0):
                self.balances[coin] = total_balance

        self.ui_queue.put_nowait(
            Event(name=EventName.ACCOUNT_POSITION, content=account_position)
        )

    async def handle_tickers(self, tickers_update: AllTickers) -> None:
        """Handle ticker updates to get latest prices."""
        for ticker in tickers_update.msg:
            symbol = ticker.get("s")
            assert symbol
            price = float(ticker.get("c", 0))
            # Update price map
            self.price_resolver.update_price(symbol, price)

        # Calculate USD-equivalent prices for known balances
        for coin in self.balances:
            try:
                usd_price = self.price_resolver.resolve_usd(coin)
                self.price_updates[coin] = usd_price

            except ValueError:
                logger.info("Errror to find price for coin: %s", coin)
        if "BTC" not in self.balances:
            usd_price = self.price_resolver.resolve_usd("BTC")
            self.price_updates["BTC"] = usd_price
        self.ui_queue.put(
            Event(
                name=EventName.PRICE_UPDATES,
                content=PriceUpdates(msg=self.price_updates),
            )
        )


async def fetch_initial_balances(
    client: BinanceClient, resolver: UsdPriceResolver
) -> Dict[str, float]:
    """Fetch the initial balances from the exchange on startup and filter by value in USD."""
    logger.info("Fetching initial balances from the exchange.")
    balances = {}
    account_info = await client.get_account()

    for balance_info in account_info["balances"]:
        coin = balance_info["asset"]
        free = float(balance_info["free"])
        locked = float(balance_info["locked"])
        total_balance = free + locked

        if total_balance <= 0:
            continue

        # logger.info("Coin with balance bigger than zero: %s - %s", coin, total_balance)

        try:
            price_in_usd = resolver.resolve_usd(coin)
            # logger.info("Coin: %s price in usd: %s", coin, price_in_usd)

            total_value = price_in_usd * total_balance

            if total_value >= 1.0:  # Only include balances >= $1 USD
                balances[coin] = total_balance
            else:
                logger.warning("Skipping coin %s: only worth $%.2f", coin, total_value)

        except ValueError:
            logger.warning("Skipping coin %s: no USD price available", coin)

    logger.info("Initial balances fetched: %s", balances)
    return balances
