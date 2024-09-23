import asyncio
import logging
import queue
import threading
from typing import Dict, Optional
from decouple import Config, RepositoryEnv
from src.common.identifiers.common import BinanceClient
from src.common.identifiers.spot import (
    AccountPosition,
    AllTickers,
    Balances,
    Event,
    EventName,
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
)
from src.workers.broker_spot import BrokerSpot

# Specify the path to the .env file
DOTENV_FILE = "config/.env"
config_env = Config(RepositoryEnv(DOTENV_FILE))

logger = logging.getLogger("portofolio")


class PortfolioManager:
    def __init__(self, broker: BrokerSpot, ui_queue: queue.Queue):
        self.client: Optional[BinanceClient] = None
        self.broker = broker
        self.ui_queue = ui_queue
        self.core_queue: queue.Queue = queue.Queue()
        self.balances: Dict[str, float] = {}
        self.price_updates: Dict[str, float] = {}  # Store latest price updates
        self.btc_saldo = 0.0
        self.usdt_saldo = 0.0

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

        # Fetch initial balances from the exchange
        await self.fetch_initial_balances()

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
                queue=self.core_queue,
            ),
        )

        self.broker.subscribe(
            system_id="PORTFOLIO",
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol="ALL",  # Subscribing to all symbols for price updates
                target=SubscriptionTarget.PORTFOLIO,
                queue=self.core_queue,
            ),
        )

        while not self.stop_event.is_set():
            try:
                event = self.core_queue.get_nowait()
                logger.info("Portfolio go new event: %s", event)
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

    async def fetch_initial_balances(self) -> None:
        """Fetch the initial balances from the exchange on startup."""
        logger.info("Fetching initial balances from the exchange.")
        assert self.client
        # Fetch account info using the Binance API
        account_info = await self.client.get_account()  # Fetch all balances

        # Iterate through balances and store them
        for balance_info in account_info["balances"]:
            asset = balance_info["asset"]
            free = float(balance_info["free"])
            locked = float(balance_info["locked"])
            total_balance = free + locked

            if total_balance > 0:  # Only store assets with a non-zero balance
                self.balances[asset] = total_balance

        logger.info("Initial balances fetched: %s", self.balances)

    async def handle_account_position(self, account_position: AccountPosition) -> None:
        """Handle account position updates (update balances)."""
        logger.info("Handling account position update.")
        for balance in account_position.balances:
            asset = balance.asset
            total_balance = balance.free + balance.locked
            self.balances[asset] = total_balance
        self.calculate_total_saldo()

    async def handle_tickers(self, tickers_update: AllTickers) -> None:
        """Handle ticker updates to get latest prices."""
        logger.info("Handling ticker updates.")
        for ticker in tickers_update.msg:
            symbol = ticker.get("s")
            assert symbol
            price = float(ticker.get("c", 0))
            base_asset, quote_asset = symbol[:-4], symbol[-4:]
            if base_asset in self.balances and quote_asset == "USDT":
                self.price_updates[base_asset] = price
        self.calculate_total_saldo()

    def calculate_total_saldo(self):
        """Calculates the total saldo in USDT and BTC."""
        total_usdt_saldo = 0.0
        total_btc_saldo = 0.0

        # Loop over all assets and calculate their USDT and BTC equivalent
        for asset, quantity in self.balances.items():
            if asset == "USDT":
                total_usdt_saldo += quantity
            elif asset == "BTC":
                total_btc_saldo += quantity
            else:
                # Convert other assets to USDT and BTC based on the latest price
                if asset in self.price_updates:
                    usdt_price = self.price_updates[asset]
                    total_usdt_saldo += quantity * usdt_price
                    # To convert to BTC, divide the USDT price by BTC/USDT price
                    if "BTCUSDT" in self.price_updates:
                        btc_price = self.price_updates["BTCUSDT"]
                        total_btc_saldo += (quantity * usdt_price) / btc_price

        self.usdt_saldo = total_usdt_saldo
        self.btc_saldo = total_btc_saldo

        logger.info(
            "Total USDT Saldo: %s, Total BTC Saldo: %s", self.usdt_saldo, self.btc_saldo
        )
