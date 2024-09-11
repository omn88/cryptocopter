import asyncio
import threading
import queue
import logging
from typing import Dict, Optional

from decouple import Config, RepositoryEnv

from binance import BinanceSocketManager
from src.common.identifiers.common import BinanceClient
from src.common.identifiers.spot import (
    AccountPosition,
    Balance,
    Event,
    EventName,
    ExecutionReport,
    TickerUpdate,
)

logger = logging.getLogger("broker")

# Specify the path to the .env file
DOTENV_FILE = "config/.env"
config_env = Config(RepositoryEnv(DOTENV_FILE))


class BrokerSpot:
    def __init__(self) -> None:
        self.client: Optional[BinanceClient] = None
        self.subscriptions: Dict[str, list] = {}
        self.queues: Dict[str, queue.Queue] = {}
        self.loop = None
        self.stop_producers_event: asyncio.Event = asyncio.Event()
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
        logger.info(
            "Main entry point for running the broker, thread: %s", self.thread.name
        )

        self.client = BinanceClient(
            api_key=config_env("API_KEY"), api_secret=config_env("API_SECRET")
        )

        socket_manager = BinanceSocketManager(client=self.client)

        tasks = [
            self.loop.create_task(
                self.handle_socket(
                    socket_manager.ticker_socket(),
                    self.stop_producers_event,
                    self.handle_ticker_message,
                    reconnect_attempts=10,
                )
            ),
            self.loop.create_task(
                self.handle_socket(
                    socket_manager.user_socket(),
                    self.stop_producers_event,
                    self.handle_user_message,
                    reconnect_attempts=10,
                )
            ),
        ]

        # Await all tasks
        await asyncio.gather(*tasks, return_exceptions=True)

    async def handle_socket(
        self, socket, stop_event, message_handler, reconnect_attempts=10
    ):
        """Handles incoming data from the WebSocket with reconnection logic."""
        logger.info("Entering handle_socket for %s", socket)

        while not stop_event.is_set():
            try:
                logger.info("Trying to start a stream")
                if not socket:
                    logger.error("Socket is None or not properly initialized.")
                    break  # Exit if socket is not valid

                async with socket as stream:
                    logger.info("WebSocket connected.")
                    while not stop_event.is_set():
                        try:
                            msg = await asyncio.wait_for(stream.recv(), timeout=1.0)
                            # logger.info("[Event]: %s", msg)
                            message_handler(msg)
                        except asyncio.TimeoutError:
                            continue
                        except asyncio.CancelledError:
                            logger.error("Async task was cancelled.")
                            raise
                        except Exception as e:
                            logger.exception("Error while receiving data: %s", e)
                            break

            except ConnectionResetError as e:
                logger.error("Connection was reset: %s. Reconnecting...", e)
                for attempt in range(reconnect_attempts):
                    if stop_event.is_set():
                        return  # Exit if stop_event is set
                    await asyncio.sleep(2**attempt)  # Exponential backoff
                    logger.info("Reconnecting attempt %d...", attempt + 1)
                    break  # Break out of the retry loop to re-establish the connection

            except Exception as e:
                logger.exception("Unexpected error in handle_socket: %s", e)
                break  # Exit the outer loop if an unexpected error occurs

    def handle_user_message(self, msg):
        """Handle user-specific WebSocket messages."""
        symbol = msg.get("s")
        event_type = msg.get("e")
        if event_type == EventName.EXECUTION_REPORT.value:
            for strategy, criteria_list in self.subscriptions.items():
                if ("USER", symbol) in criteria_list:
                    self.queues[strategy].put(
                        Event(
                            name=EventName.EXECUTION_REPORT,
                            content=self.create_execution_report(msg),
                        )
                    )
        if event_type == EventName.ACCOUNT_POSITION.value:
            msg = self.create_account_position(msg)

            for strategy, criteria_list in self.subscriptions.items():
                if ("USER", symbol) in criteria_list:
                    self.queues[strategy].put(
                        Event(
                            name=EventName.ACCOUNT_POSITION,
                            content=self.create_account_position(msg),
                        )
                    )

    def handle_ticker_message(self, msg):
        """Handle all market ticker WebSocket messages."""
        for ticker in msg:
            symbol = ticker.get("s")
            if symbol:
                # Extract the relevant fields from the ticker message
                last_price = float(ticker.get("c", 0))  # Current last price
                best_bid_price = float(ticker.get("b", 0))  # Best bid price
                best_ask_price = float(ticker.get("a", 0))  # Best ask price
                high_price = float(ticker.get("h", 0))  # High price
                low_price = float(ticker.get("l", 0))  # Low price
                volume = float(ticker.get("v", 0))  # Volume

                # Create the TickerUpdate NamedTuple with the extracted values
                ticker_update = TickerUpdate(
                    symbol=symbol,
                    last_price=last_price,
                    best_bid_price=best_bid_price,
                    best_ask_price=best_ask_price,
                    high_price=high_price,
                    low_price=low_price,
                    volume=volume,
                )

                # Place the TickerUpdate event in the appropriate queue
                for strategy, criteria_list in self.subscriptions.items():
                    if ("PRICE", symbol) in criteria_list:
                        self.queues[strategy].put(
                            Event(name=EventName.TICKER, content=ticker_update)
                        )

    def subscribe(self, strategy, data_type, symbol, core_queue):
        """Allows a strategy to subscribe to user data or specific symbol price feed."""
        criteria = (data_type, symbol)
        if strategy not in self.subscriptions:
            self.subscriptions[strategy] = []
            self.queues[strategy] = core_queue
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
                del self.queues[strategy]  # Remove the queue for this strategy

    def stop(self):
        """Stops the broker and closes all connections."""
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join()

    async def close(self):
        """Closes the AsyncClient and socket manager."""
        await self.client.close_connection()

    def create_execution_report(self, msg) -> ExecutionReport:
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

    def create_account_position(self, msg) -> AccountPosition:
        balances = [
            Balance(asset=b["a"], free=float(b["f"]), locked=float(b["l"]))
            for b in msg["B"]
        ]
        return AccountPosition(
            event_time=msg["E"], last_update_time=msg["u"], balances=balances
        )
