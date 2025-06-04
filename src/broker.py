import asyncio
import json
import os
import threading
import queue
import logging
from typing import Any, Dict, List, Optional

from decouple import Config, RepositoryEnv

from binance import BinanceSocketManager
from src.identifiers.common import BinanceClient
from src.identifiers.spot import (
    AccountPosition,
    AllTickers,
    Balance,
    Event,
    EventName,
    ExecutionReport,
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
    TickerUpdate,
)

logger = logging.getLogger("broker")

# Specify the path to the .env file
DOTENV_FILE = "config/.env"

if os.path.exists(DOTENV_FILE):
    config_env = Config(RepositoryEnv(DOTENV_FILE))
else:
    print("Warning: .env file not found! Using default values.")
    config_env = {
        "API_KEY": "key",
        "API_SECRET": "secret",
    }


class BrokerSpot:
    def __init__(self) -> None:
        self.client: Optional[BinanceClient] = None
        self.subscriptions: Dict[str, list] = {}
        self.queues: Dict[str, queue.Queue] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.stop_producers_event: asyncio.Event = asyncio.Event()
        self.tasks: Optional[List[asyncio.Task]] = None
        self.thread = threading.Thread(target=self.start_loop)
        self.thread.start()

    def start_loop(self) -> None:
        """Starts the asyncio loop in a new thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.run())

    async def run(self) -> None:
        """Main entry point for running the broker."""
        logger.info(
            "Main entry point for running the broker, thread: %s", self.thread.name
        )

        self.client = BinanceClient(
            api_key=config_env("API_KEY"), api_secret=config_env("API_SECRET")
        )

        socket_manager = BinanceSocketManager(client=self.client)
        assert self.loop
        self.tasks = [
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
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def handle_socket(
        self, socket, stop_event, message_handler, reconnect_attempts=10
    ) -> None:
        """Handles incoming data from the WebSocket with reconnection logic."""
        logger.info("Entering handle_socket for %s", socket)

        while not stop_event.is_set():
            try:
                logger.info("Trying to start a stream")
                if not socket:
                    logger.error("Socket is None or not properly initialized.")
                    break

                async with socket as stream:
                    logger.info("WebSocket connected.")
                    while not stop_event.is_set():
                        try:
                            raw_msg = await asyncio.wait_for(stream.recv(), timeout=1.0)
                            # logger.debug("Raw WebSocket message: %s", raw_msg)

                            # Pre-filter and parse message
                            msg = None
                            if isinstance(raw_msg, str):
                                try:
                                    msg = json.loads(raw_msg)
                                except json.JSONDecodeError:
                                    logger.warning(
                                        "Received non-JSON string from WebSocket: %s",
                                        raw_msg,
                                    )
                                    continue
                            elif isinstance(raw_msg, dict):
                                msg = raw_msg
                            elif isinstance(raw_msg, list):
                                if all(isinstance(item, dict) for item in raw_msg):
                                    msg = raw_msg
                                else:
                                    logger.warning(
                                        "Received list with non-dict items: %s", raw_msg
                                    )
                                    continue
                            else:
                                logger.warning(
                                    "Unexpected WebSocket message type: %s",
                                    type(raw_msg),
                                )
                                continue

                            # Pass parsed msg to message_handler
                            if msg:
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
                        return
                    await asyncio.sleep(2**attempt)
                    logger.info("Reconnecting attempt %d...", attempt + 1)

            except Exception as e:
                logger.exception("Unexpected error in handle_socket: %s", e)
                break

        logger.info(
            "Gracefully getting out of handle socket method for socket: %s", socket
        )

    def handle_user_message(self, msg: Dict) -> None:
        """Handle user-specific WebSocket messages."""
        event_type = msg.get("e")

        # Handle internal 'error' messages injected by python-binance
        if event_type == EventName.ERROR.value:
            logger.warning("Received internal error event: %s", msg)
            for _, subscriptions in self.subscriptions.items():
                for subscription_info in subscriptions:
                    assert isinstance(subscription_info, SubscriptionInfo)
                    if subscription_info.target in [
                        SubscriptionTarget.FRONTEND,
                        SubscriptionTarget.PORTFOLIO,
                    ]:
                        subscription_info.queue.put_nowait(
                            Event(name=EventName.ERROR, content=msg)
                        )
            return  # Exit early, do not continue processing this as a user message

        symbol = msg.get("s")

        if event_type == EventName.EXECUTION_REPORT.value:
            for _, subscriptions in self.subscriptions.items():
                for subscription_info in subscriptions:
                    assert isinstance(subscription_info, SubscriptionInfo)
                    if (
                        subscription_info.data_type == SubscriptionType.USER
                        and subscription_info.symbol == symbol
                    ):
                        subscription_info.queue.put_nowait(
                            Event(
                                name=EventName.EXECUTION_REPORT,
                                content=self.create_execution_report(msg),
                            )
                        )

        if event_type == EventName.ACCOUNT_POSITION.value:
            for _, subscriptions in self.subscriptions.items():
                for subscription_info in subscriptions:
                    assert isinstance(subscription_info, SubscriptionInfo)
                    if subscription_info.target == SubscriptionTarget.PORTFOLIO:
                        subscription_info.queue.put_nowait(
                            Event(
                                name=EventName.ACCOUNT_POSITION,
                                content=self.create_account_position(msg),
                            )
                        )

            # SEND IT ALSO TO THE PARTICULAR STRATEGIES TO UPDATE THE BALANCE?

    def handle_ticker_message(self, msg: List[Dict]) -> None:
        """Handle all market ticker WebSocket messages."""

        if isinstance(msg, str):
                logging.debug("Received control frame: %s", msg)
                return  # Ignore control messages like "pong"
        if not isinstance(msg, list):
            logging.warning("Unexpected message format(%s): %s", type(msg), msg)
            return  # Defensive: Ignore unexpected types

        # Send the full msg to FrontEnd if subscribed to "ALL" symbols
        for strategy, subscriptions in self.subscriptions.items():
            for subscription_info in subscriptions:
                assert isinstance(subscription_info, SubscriptionInfo)
                if subscription_info.target in [
                    SubscriptionTarget.FRONTEND,
                    SubscriptionTarget.PORTFOLIO,
                ]:
                    if subscription_info.symbol == "ALL":
                        subscription_info.queue.put_nowait(
                            Event(
                                name=EventName.ALL_TICKERS, content=AllTickers(msg=msg)
                            )
                        )

        for ticker in msg:
            symbol = ticker.get("s")
            if not symbol:
                logger.warning("Ticker without symbol: %s", ticker)
                return

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

            # Send symbol-specific updates for other subscriptions
            for strategy, subscriptions in self.subscriptions.items():
                for subscription_info in subscriptions:
                    assert isinstance(subscription_info, SubscriptionInfo)
                    if (
                        subscription_info.data_type == SubscriptionType.PRICE
                        and subscription_info.symbol == symbol
                    ):
                        subscription_info.queue.put_nowait(
                            Event(name=EventName.TICKER, content=ticker_update)
                        )

    def subscribe(self, system_id: str, subscription_info: SubscriptionInfo) -> None:
        """Allows a strategy to subscribe to user data or specific symbol price feed."""

        # If the system_id is not in subscriptions, create an empty list for it
        if system_id not in self.subscriptions:
            self.subscriptions[system_id] = []

        # Only add the subscription if it does not already exist
        if subscription_info not in self.subscriptions[system_id]:
            self.subscriptions[system_id].append(subscription_info)
            logger.info(
                "New subscription for ID: %s: %s", system_id, subscription_info.symbol
            )

    def unsubscribe(self, system_id: str) -> None:
        """Allows a strategy to unsubscribe from a user or price feed."""

        # Check if the system_id exists in the subscriptions
        if system_id in self.subscriptions:
            del self.subscriptions[system_id]
            logger.info("Deleted all subscriptions for ID: %s", system_id)

    def stop(self):
        """Shut down BrokerSpot gracefully."""
        logger.info("Stopping BrokerSpot gracefully.")

        # Set stop event to notify all tasks to exit
        self.stop_producers_event.set()

        self.shutdown()

    def join_thread(self):
        """Join the broker's thread."""
        if self.thread.is_alive():
            self.thread.join()

    def shutdown(self):
        """Shutdown the broker and close resources."""
        logger.info("Shutting down BrokerSpot...")

        try:
            # Log current tasks before shutdown
            logger.info("Current tasks: %s", asyncio.all_tasks())

            if self.loop:
                # Stop the event loop safel

                # Give some time for pending tasks to handle cancellation
                pending_tasks = [
                    task for task in asyncio.all_tasks(self.loop) if not task.done()
                ]

                if pending_tasks:
                    # Wait for the remaining tasks to be canceled or completed
                    self.loop.run_until_complete(
                        asyncio.gather(*pending_tasks, return_exceptions=True)
                    )

                self.loop.call_soon_threadsafe(self.loop.stop)

        except RuntimeError as error:
            # Handle the event loop stop error gracefully
            logger.error("RuntimeError during shutdown: %s", error)

        except Exception as error:
            # Catch any other exceptions
            logger.error("Unexpected error during shutdown: %s", error)

        finally:
            # Ensure the thread is stopped even if errors occur
            loop = asyncio.get_running_loop()
            loop.create_task(self.client.close_connection())
            self.join_thread()

            # Final log statement indicating complete shutdown
            logger.info("BrokerSpot shutdown complete.")

    def create_execution_report(self, msg: Dict) -> ExecutionReport:
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
            Balance(coin=b["a"], free=float(b["f"]), locked=float(b["l"]))
            for b in msg["B"]
        ]
        return AccountPosition(
            event_time=msg["E"], last_update_time=msg["u"], balances=balances
        )
