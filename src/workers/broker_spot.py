import asyncio
import threading
import queue
import logging
from typing import Dict

from binance import BinanceSocketManager
from src.common.identifiers.common import BinanceClient
from src.common.identifiers.spot import (
    AccountPosition,
    Balance,
    EventName,
    ExecutionReport,
)

logger = logging.getLogger("broker")


class BrokerSpot:
    def __init__(
        self,
        client: BinanceClient,
        data_queue: queue.Queue,
        stop_producers_event: asyncio.Event,
    ):
        self.client = client
        self.data_queue = data_queue
        self.subscriptions: Dict = {}
        self.loop = None
        self.stop_producers_event = stop_producers_event
        self.socket_manager = BinanceSocketManager(client=client)
        self.thread = threading.Thread(target=self.start_loop)
        self.thread.start()

    def start_loop(self):
        """Starts the asyncio loop in a new thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.run())

    async def run(self):
        """Main entry point for running the broker."""
        # Maby the stop producers event is not
        asyncio.create_task(
            self.handle_socket(
                self.socket_manager.user_socket(),
                self.stop_producers_event,
                self.handle_user_message,
                reconnect_attempts=10,
            )
        )

        asyncio.create_task(
            self.handle_socket(
                self.socket_manager.ticker_socket(),
                self.stop_producers_event,
                self.handle_ticker_message,
                reconnect_attempts=10,
            )
        )

    async def handle_socket(
        self, socket, stop_event, message_handler, reconnect_attempts=10
    ):
        """Handles incoming data from the WebSocket with reconnection logic."""
        while not stop_event.is_set():
            try:
                async with socket as stream:
                    logger.info("WebSocket connected.")
                    while not stop_event.is_set():
                        try:
                            msg = await asyncio.wait_for(stream.recv(), timeout=1.0)
                            logger.debug("[Event]: %s", msg)
                            await message_handler(msg)
                        except asyncio.TimeoutError:
                            continue
            except ConnectionResetError as e:
                logger.error("Connection was reset: %s. Reconnecting...", e)
                for attempt in range(reconnect_attempts):
                    if stop_event.is_set():
                        return  # Exit if stop_event is set

                    await asyncio.sleep(2**attempt)  # Exponential backoff
                    logger.info("Reconnecting attempt %d...", attempt + 1)
                    break  # Break out of the retry loop to re-establish the connection
            except Exception as e:
                logger.error("Unexpected error: %s", e)
                break

    def handle_user_message(self, msg):
        """Handle user-specific WebSocket messages."""
        symbol = msg.get("s")
        event_type = msg.get("e")
        if event_type == EventName.EXECUTION_REPORT.value:
            msg = self.create_execution_report(msg)
        if event_type == EventName.ACCOUNT_POSITION.value:
            msg = self.create_account_position(msg)

        # Forward the user message to strategies subscribed to this symbol
        for strategy, criteria_list in self.subscriptions.items():
            if ("USER", symbol) in criteria_list:
                self.data_queue.put((strategy, msg))  # Non-awaitable put operation

    def handle_ticker_message(self, msg):
        """Handle all market ticker WebSocket messages."""
        # Assuming the message is a list of dictionaries, one for each symbol
        for ticker in msg:
            symbol = ticker.get("s")
            if symbol:
                for strategy, criteria_list in self.subscriptions.items():
                    if ("PRICE", symbol) in criteria_list:
                        # Send the entire ticker data related to this symbol to the strategy
                        self.data_queue.put((strategy, ticker))

    def subscribe(self, strategy, data_type, symbol):
        """Allows a strategy to subscribe to user data or specific symbol price feed."""
        criteria = (data_type, symbol)
        if strategy not in self.subscriptions:
            self.subscriptions[strategy] = []

        if criteria not in self.subscriptions[strategy]:
            self.subscriptions[strategy].append(criteria)

    def unsubscribe(self, strategy, data_type, symbol):
        """Allows a strategy to unsubscribe from a user or price feed."""
        criteria = (data_type, symbol)
        if strategy in self.subscriptions:
            self.subscriptions[strategy] = [
                sub for sub in self.subscriptions[strategy] if sub != criteria
            ]
            if not self.subscriptions[strategy]:
                del self.subscriptions[strategy]

    def stop(self):
        """Stops the broker and closes all connections."""
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join()

    async def close(self):
        """Closes the AsyncClient and socket manager."""
        await self.client.close_connection()

    async def create_execution_report(self, msg) -> ExecutionReport:
        return ExecutionReport(
            symbol=msg["s"],
            client_order_id=msg["c"],
            side=msg["S"],
            order_type=msg["o"],
            time_in_force=msg["f"],
            quantity=float(msg["q"]),
            price=float(msg["p"]),
            stop_price=float(msg["P"]),
            iceberg_quantity=float(msg["F"]),
            order_list_id=msg["g"],
            original_client_order_id=msg["C"],
            current_execution_type=msg["x"],
            current_order_status=msg["X"],
            order_reject_reason=msg["r"],
            order_id=int(msg["i"]),
            last_executed_quantity=float(msg["l"]),
            cumulative_filled_quantity=float(msg["z"]),
            last_executed_price=float(msg["L"]),
            commission_amount=float(msg["n"]) if msg["n"] else None,
            commission_asset=msg["N"],
            transaction_time=msg["T"],
            trade_id=msg["t"],
            ignore_1=msg["I"],
            is_order_working=msg["w"],
            is_trade_maker_side=msg["m"],
            ignore_2=msg["M"],
            order_creation_time=msg["O"],
            cumulative_quote_asset_transacted_quantity=float(msg["Z"]),
            last_quote_asset_transacted_quantity=float(msg["Y"]),
            quote_order_quantity=float(msg["Q"]),
            working_time=msg["W"],
            self_trade_prevention_mode=msg["V"],
        )

    async def create_account_position(self, msg) -> AccountPosition:
        balances = [
            Balance(asset=b["a"], free=float(b["f"]), locked=float(b["l"]))
            for b in msg["B"]
        ]
        return AccountPosition(
            event_time=msg["E"], last_update_time=msg["u"], balances=balances
        )
