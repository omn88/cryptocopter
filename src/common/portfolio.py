import asyncio
import logging
import queue
import threading
from typing import Dict
from src.common.identifiers.spot import (
    AccountPosition,
    AllTickers,
    EventName,
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
)
from src.workers.broker_spot import BrokerSpot


logger = logging.getLogger("portofolio")


class PortfolioManager:
    def __init__(self, broker: BrokerSpot):
        self.broker = broker
        self.queue: queue.Queue = queue.Queue()
        self.symbols: Dict = {}

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

        # Subscribe to user and price updates for portfolio management
        self.broker.subscribe(
            system_id="PORTFOLIO",
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.USER,
                symbol="ALL",  # Subscribing to all symbols for user account positions
                target=SubscriptionTarget.PORTFOLIO,
                queue=self.queue,
            ),
        )

        self.broker.subscribe(
            system_id="PORTFOLIO",
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol="ALL",  # Subscribing to all symbols for price updates
                target=SubscriptionTarget.PORTFOLIO,
                queue=self.queue,
            ),
        )

        while not self.stop_event.is_set():
            try:
                event = self.queue.get_nowait()
                if event.name == EventName.ACCOUNT_POSITION:
                    await self.handle_account_position(event.content)
                elif event.name == EventName.ALL_TICKERS:
                    await self.handle_tickers(event.content)
            except queue.Empty:
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
        # Handle account position updates (update balance, etc.)
        pass

    async def handle_tickers(self, tickers_update: AllTickers) -> None:
        # Handle price updates (update symbols in portfolio, etc.)
        pass

    # def calculate_total_saldo(self):
    #     """Calculates the total saldo in USDT and BTC."""
    #     total_usdt_saldo = 0.0
    #     total_btc_saldo = 0.0

    #     # Loop over all assets and calculate their USDT and BTC equivalent
    #     for asset, quantity in self.balances.items():
    #         if asset == "USDT":
    #             total_usdt_saldo += quantity
    #         elif asset == "BTC":
    #             total_btc_saldo += quantity
    #         else:
    #             # Convert other assets to USDT and BTC based on the latest price
    #             if asset in self.price_updates:
    #                 usdt_price = self.price_updates[asset]
    #                 total_usdt_saldo += quantity * usdt_price
    #                 # To convert to BTC, divide the USDT price by BTC/USDT price
    #                 if "BTCUSDT" in self.price_updates:
    #                     btc_price = self.price_updates["BTCUSDT"]
    #                     total_btc_saldo += (quantity * usdt_price) / btc_price

    #     self.usdt_saldo = total_usdt_saldo
    #     self.btc_saldo = total_btc_saldo

    #     logger.info("Total USDT Saldo: %s, Total BTC Saldo: %s", self.usdt_saldo, self.btc_saldo)
