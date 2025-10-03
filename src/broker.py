import asyncio
import json
import os
import threading
import queue
import logging
from typing import Dict, List, Optional, Union, Any
import time

from decouple import Config, RepositoryEnv

from binance import BinanceSocketManager
from src.identifiers import (
    AccountPosition,
    AllTickers,
    Balance,
    ErrorMessage,
    Event,
    EventName,
    ExecutionReport,
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
    TickerUpdate,
    BinanceClient,
)
from src.common.websocket_config import ULTRA_ROBUST_CONFIG

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

        # WebSocket error handling - remove external handler dependency
        self._restart_lock = threading.Lock()  # Prevent double restart
        self._last_keepalive_error_log = 0  # Connection health monitoring
        self._connection_health_task: Optional[asyncio.Task] = None
        self._last_message_time: Dict[str, float] = {}
        self._connection_timeout = ULTRA_ROBUST_CONFIG.message_timeout_threshold

        # Ticker monitoring attributes
        self._last_ticker_time: float = time.time()
        self._ticker_timeout_threshold: float = 300.0  # 5 minutes default

        # WebSocket error handling attributes (moved from StrategyExecutor)
        self._websocket_error_count = 0
        self._last_websocket_error_time = 0.0
        self._websocket_error_suppression_time = 600  # 10 minutes

        # BinanceClient restart tracking for circuit breaker pattern
        self._restart_count = 0
        self._last_restart_time = 0.0
        self._restart_base_delay = 60  # Start with 1 minute delay
        self._max_restart_delay = 3600  # Maximum 1 hour delay

        # Ticker timeout monitoring for backup circuit breaker
        self._max_ticker_silence_duration = 300  # 5 minutes max silence before restart
        self._ticker_timeout_check_interval = 60  # Check every minute
        self._ticker_timeout_task: Optional[asyncio.Task] = None

        # Subscription registry for automatic resubscription after restarts
        self._subscription_registry: Dict[str, SubscriptionInfo] = {}

        # Use ultra-robust WebSocket configuration for unstable networks
        self._ws_config = ULTRA_ROBUST_CONFIG
        logger.info("Using ultra-robust WebSocket configuration for network stability")
        self._ws_config.log_config()

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
        assert self.loop  # Start the connection health monitor
        self._connection_health_task = self.loop.create_task(
            self.monitor_connection_health()
        )

        # Start ticker timeout monitoring
        self._ticker_timeout_task = self.loop.create_task(
            self._monitor_ticker_timeout()
        )

        self.tasks = [
            self._connection_health_task,
            self._ticker_timeout_task,
            self.loop.create_task(
                self.handle_socket(
                    socket_manager.ticker_socket(),
                    self.stop_producers_event,
                    self.handle_ticker_message,
                    reconnect_attempts=self._ws_config.max_reconnect_attempts,
                )
            ),
            self.loop.create_task(
                self.handle_socket(
                    socket_manager.user_socket(),
                    self.stop_producers_event,
                    self.handle_user_message,
                    reconnect_attempts=self._ws_config.max_reconnect_attempts,
                )
            ),
        ]

        # Await all tasks
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def monitor_connection_health(self):
        """Monitor WebSocket connection health and restart if needed"""
        logger.info("Starting connection health monitor")
        health_check_counter = 0
        last_warning_time = {}  # Track when we last warned about each connection

        while not self.stop_producers_event.is_set():
            try:
                current_time = time.time()
                health_check_counter += 1

                # Log periodic heartbeat every 5 minutes (10 cycles of 30s)
                if health_check_counter % 10 == 0:
                    active_connections = len(self._last_message_time)
                    logger.info(
                        "Connection health check #%d: %d active connections monitored",
                        health_check_counter,
                        active_connections,
                    )

                    # Log details of each connection's last activity
                    for connection_type, last_time in self._last_message_time.items():
                        seconds_since_last = current_time - last_time
                        logger.info(
                            "  %s: last message %.1f seconds ago",
                            connection_type,
                            seconds_since_last,
                        )

                # Check if we haven't received messages in a while
                for connection_type, last_time in self._last_message_time.items():
                    seconds_since_last = current_time - last_time

                    if seconds_since_last > self._connection_timeout:
                        # Only warn for ticker streams - user streams can be silent for long periods
                        if "ticker" in connection_type:
                            # Only warn once every 5 minutes per connection to avoid spam
                            last_warn = last_warning_time.get(connection_type, 0)
                            if current_time - last_warn > 300:  # 5 minutes
                                logger.warning(
                                    "Ticker connection timeout detected for %s. "
                                    "Last message received %.1f seconds ago.",
                                    connection_type,
                                    seconds_since_last,
                                )
                                last_warning_time[connection_type] = current_time
                        elif "user" in connection_type:
                            # For user streams, only log if extremely long silence (>1 hour)
                            # and only as INFO level since it might be normal
                            if seconds_since_last > 3600:  # 1 hour
                                last_warn = last_warning_time.get(connection_type, 0)
                                if (
                                    current_time - last_warn > 1800
                                ):  # Log every 30 minutes
                                    logger.info(
                                        "User stream has been silent for %.1f seconds "
                                        "(normal if no trading activity)",
                                        seconds_since_last,
                                    )
                                    last_warning_time[connection_type] = current_time

                await asyncio.sleep(self._ws_config.health_check_interval)

            except Exception as e:
                logger.error("Error in connection health monitor: %s", e)
                await asyncio.sleep(self._ws_config.health_check_interval)

        logger.info("Connection health monitor stopped")

    def update_message_timestamp(self, connection_type: str):
        """Update the last message timestamp for a connection type"""
        self._last_message_time[connection_type] = time.time()

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

                            # Update the last message timestamp for this connection
                            self.update_message_timestamp(
                                "user" if "e" in msg else "ticker"
                            )

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
                    # Use configuration-based delay with exponential backoff
                    delay = min(
                        self._ws_config.initial_reconnect_delay * (2**attempt),
                        self._ws_config.max_reconnect_delay,
                    )
                    logger.info(
                        "Reconnecting attempt %d in %.1f seconds...", attempt + 1, delay
                    )
                    await asyncio.sleep(delay)

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
            # Handle websocket errors internally using our own error handling
            if self.loop and self._restart_lock.acquire(blocking=False):
                try:
                    asyncio.run_coroutine_threadsafe(
                        self._handle_websocket_error(msg), self.loop
                    )
                finally:
                    self._restart_lock.release()
                return  # Don't process this error further

            logger.warning("Received internal error event: %s", msg)
            for _, subscriptions in self.subscriptions.items():
                for subscription_info in subscriptions:
                    assert isinstance(subscription_info, SubscriptionInfo)
                    if subscription_info.target in [
                        SubscriptionTarget.FRONTEND,
                        SubscriptionTarget.PORTFOLIO,
                    ]:
                        subscription_info.queue.put_nowait(
                            Event(name=EventName.ERROR, content=ErrorMessage(msg=msg))
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
                        )  # SEND IT ALSO TO THE PARTICULAR STRATEGIES TO UPDATE THE BALANCE?

    def handle_ticker_message(self, msg: List[Dict]) -> None:
        """Handle all market ticker WebSocket messages, and invoke error handler if ticker stream is dead."""

        # Update last ticker timestamp for timeout monitoring
        self._last_ticker_time = time.time()

        if isinstance(msg, str):
            logging.debug("Received control frame: %s", msg)
            return  # Ignore control messages like "pong"
        if not isinstance(msg, list):
            logging.warning("Unexpected message format(%s): %s", type(msg), msg)
            # Handle ticker stream error internally
            if self.loop and self._restart_lock.acquire(blocking=False):
                try:
                    asyncio.run_coroutine_threadsafe(
                        self._handle_websocket_error(
                            {"type": "TickerStreamError", "m": str(msg)}
                        ),
                        self.loop,
                    )
                finally:
                    self._restart_lock.release()
            return  # Defensive: Ignore unexpected types
        for _, subscriptions in self.subscriptions.items():
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
                continue

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
            )  # Send symbol-specific updates for other subscriptions
            for _, subscriptions in self.subscriptions.items():
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
            # Store in registry for automatic resubscription after restart
            self._subscription_registry[system_id] = subscription_info
            logger.info(
                "New subscription for ID: %s: %s", system_id, subscription_info.symbol
            )

    def unsubscribe(self, system_id: str) -> None:
        """Allows a strategy to unsubscribe from a user or price feed."""

        # Check if the system_id exists in the subscriptions
        if system_id in self.subscriptions:
            del self.subscriptions[system_id]
            logger.info("Deleted all subscriptions for ID: %s", system_id)

        # Remove from registry as well
        if system_id in self._subscription_registry:
            del self._subscription_registry[system_id]

    def stop(self):
        """Shut down BrokerSpot gracefully."""
        logger.info("Stopping BrokerSpot gracefully.")

        # Set stop event to notify all tasks to exit
        self.stop_producers_event.set()

        # Cancel ticker timeout monitoring task if it exists
        if self._ticker_timeout_task and not self._ticker_timeout_task.done():
            self._ticker_timeout_task.cancel()
            logger.info("Cancelled ticker timeout monitoring task")

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
                # Stop the event loop safely

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

    async def _handle_websocket_error(
        self, error_msg: Union[str, Dict[str, Any]]
    ) -> None:
        """Handle WebSocket errors, especially keepalive timeouts and
        unrecoverable failures."""
        current_time = time.time()

        # Check for unrecoverable errors
        unrecoverable_types = [
            "BinanceWebsocketUnableToConnect",
            "BinanceWebsocketClosed",
            "ConnectionClosedError",
            "ConnectionClosedOK",  # Server-initiated disconnections (e.g., "going away")
            "ConnectionClosed",  # Generic connection closed errors
            "TickerTimeoutError",  # Backup circuit breaker for silent ticker streams
        ]
        unrecoverable_msgs = [
            "Max reconnections",
            "timed out during opening handshake",
            "Cannot connect to host",
            "Temporary failure in name resolution",
            "getaddrinfo failed",
            "going away",  # WebSocket close code 1001
            "abnormal closure",  # WebSocket close code 1006
            "received 1001",  # Explicit check for going away code
            "received 1006",  # Explicit check for abnormal closure
        ]

        is_unrecoverable = False
        if isinstance(error_msg, dict):
            error_type = error_msg.get("type", "")
            error_message = error_msg.get("m", "")

            # Check direct error type and message first
            if any(t in error_type for t in unrecoverable_types) or any(
                m in error_message for m in unrecoverable_msgs
            ):
                is_unrecoverable = True

            # Check for nested error messages (common with TickerStreamError)
            if not is_unrecoverable and error_type == "TickerStreamError":
                try:
                    # Handle malformed JSON by extracting key info
                    if "'e': 'error'" in error_message and "'type':" in error_message:
                        # Extract nested error type using string parsing
                        start_idx = error_message.find("'type': '") + 9
                        if start_idx > 8:  # Found the pattern
                            end_idx = error_message.find("'", start_idx)
                            if end_idx > start_idx:
                                nested_error_type = error_message[start_idx:end_idx]
                                if any(
                                    t in nested_error_type for t in unrecoverable_types
                                ):
                                    logger.warning(
                                        "Detected unrecoverable error in nested "
                                        "TickerStreamError: %s",
                                        nested_error_type,
                                    )
                                    is_unrecoverable = True
                except Exception as e:
                    logger.debug("Error parsing nested error message: %s", e)

        # If unrecoverable, restart websocket client with circuit breaker pattern
        if is_unrecoverable:
            # Calculate delay using circuit breaker pattern
            self._restart_count += 1
            time_since_last_restart = current_time - self._last_restart_time

            # If it's been more than 10 minutes since last restart, reset counter
            if time_since_last_restart > 600:
                self._restart_count = 1

            # Calculate progressive delay: base_delay * (restart_count ^ 1.5), capped at max
            restart_delay = min(
                self._restart_base_delay * (self._restart_count**1.5),
                self._max_restart_delay,
            )

            logger.error(
                "Unrecoverable websocket error detected: %s. Restart #%d. "
                "Waiting %.1f seconds before restarting to allow network to stabilize...",
                error_msg,
                self._restart_count,
                restart_delay,
            )

            # Wait before attempting restart to let network stabilize
            await asyncio.sleep(restart_delay)
            self._last_restart_time = time.time()  # Update after the delay

            await self._restart_websocket_client()
            return

        # Check if this is a keepalive timeout error (legacy logic)
        if isinstance(error_msg, dict):
            error_type = error_msg.get("type", "")
            error_message = error_msg.get("m", "")
            if (
                "keepalive ping timeout" in error_message
                or "ConnectionClosedError" in error_type
            ):
                # Suppress frequent logging of the same error
                if (
                    current_time - self._last_websocket_error_time
                    > self._websocket_error_suppression_time
                ):
                    logger.warning(
                        "WebSocket keepalive timeout detected. This is a known issue with "
                        "python-binance + Python 3.12. Connection will auto-reconnect."
                    )
                    self._last_websocket_error_time = current_time
                    self._websocket_error_count = 1
                else:
                    self._websocket_error_count += 1
                if self._websocket_error_count > 20:
                    logger.warning(
                        "Excessive WebSocket reconnections detected (%d errors), "
                        "will resubscribe all streams",
                        self._websocket_error_count,
                    )
                    await self._resubscribe_all_subscriptions()
                    self._websocket_error_count = 0
                return

        # Handle other WebSocket errors normally
        logger.error("WebSocket error: %s", error_msg)

    async def _restart_websocket_client(self) -> None:
        """Restart the WebSocket client and resubscribe all active subscriptions."""
        retry_count = 0
        while True:
            try:
                # Stop current client if exists
                logger.info(
                    "Attempting to restart BinanceClient (restart #%d)...",
                    self._restart_count,
                )
                if self.client:
                    try:
                        await self.client.close_connection()
                    except Exception as e:
                        logger.warning("Error closing client: %s", e)
                    self.client = None

                # Recreate client
                logger.info("Recreating BinanceClient...")
                self.client = BinanceClient(
                    api_key=config_env("API_KEY"),
                    api_secret=config_env("API_SECRET"),
                )
                logger.info("BinanceClient restarted successfully.")

                # Resubscribe all active subscriptions
                await self._resubscribe_all_subscriptions()
                logger.info("Resubscription after restart complete.")

                # Reset restart count on successful restart
                if retry_count == 0:  # Only reset if first attempt succeeded
                    logger.info(
                        "WebSocket client restart successful. Circuit breaker reset."
                    )
                    # Don't reset _restart_count here - keep it for progressive delay
                break

            except Exception as e:
                retry_count += 1
                restart_retry_delay = min(30, 2**retry_count)
                logger.error(
                    "Websocket restart attempt #%d failed: %s. Retrying in %d seconds...",
                    retry_count,
                    e,
                    restart_retry_delay,
                )
                await asyncio.sleep(restart_retry_delay)

    async def _monitor_ticker_timeout(self) -> None:
        """Monitor for ticker timeout and trigger circuit breaker if no
        ticker data for too long."""
        logger.info(
            "Starting ticker timeout monitoring (max silence: %d seconds)",
            self._max_ticker_silence_duration,
        )

        while not self.stop_producers_event.is_set():
            try:
                await asyncio.sleep(self._ticker_timeout_check_interval)

                if self.stop_producers_event.is_set():
                    break

                # Check for ticker timeout
                time_since_ticker = time.time() - self._last_ticker_time
                if time_since_ticker > self._max_ticker_silence_duration:
                    logger.error(
                        "Backup circuit breaker triggered: ticker silent for %.1f seconds "
                        "(max: %d seconds). Forcing WebSocket restart...",
                        time_since_ticker,
                        self._max_ticker_silence_duration,
                    )

                    # Trigger circuit breaker by simulating an unrecoverable error
                    timeout_error = {
                        "type": "TickerTimeoutError",
                        "m": (
                            f"Ticker silent for {time_since_ticker:.1f} seconds - "
                            "backup circuit breaker activated"
                        ),
                    }
                    await self._handle_websocket_error(timeout_error)
                    return  # Exit monitoring after triggering restart

            except asyncio.CancelledError:
                logger.info("Ticker timeout monitoring task cancelled")
                break
            except Exception as e:
                logger.error("Error in ticker timeout monitoring: %s", e)
                await asyncio.sleep(10)  # Wait before retrying

        logger.info("Ticker timeout monitoring stopped")

    async def _resubscribe_all_subscriptions(self) -> None:
        """Resubscribe all active subscriptions after WebSocket restart."""
        logger.info("Resubscribing all active WebSocket subscriptions...")

        # Create a copy of the registry to avoid modification during iteration
        subscriptions_to_restore = self._subscription_registry.copy()

        for system_id, subscription_info in subscriptions_to_restore.items():
            try:
                logger.info("Resubscribing system %s", system_id)

                # Remove from current subscriptions
                if system_id in self.subscriptions:
                    del self.subscriptions[system_id]

                # Re-add the subscription
                self.subscribe(system_id=system_id, subscription_info=subscription_info)

                # Small delay between resubscriptions
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error("Failed to resubscribe system %s: %s", system_id, e)

        logger.info("Finished resubscribing all subscriptions")
