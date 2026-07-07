"""WebSocket manager for Binance real-time data streams.

This module handles all WebSocket connectivity, health monitoring, and recovery logic
for Binance spot trading streams (ticker data and user data streams).
"""

import asyncio
import json
import logging
import time
import threading
from typing import Dict, List, Optional, Callable, Any, Union, cast

import websockets

from src.common.client import KrakenClient
from src.domain.subscriptions import SubscriptionInfo
from src.websocket.config import ULTRA_ROBUST_CONFIG

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections, health monitoring, and recovery for Binance streams."""

    def __init__(
        self,
        client: KrakenClient,
        subscriptions: Dict[str, List[SubscriptionInfo]],
        stop_event: asyncio.Event,
    ):
        """Initialize WebSocket manager.

        Args:
            client: Binance AsyncClient instance
            subscriptions: Dict mapping system_id to list of SubscriptionInfo
            stop_event: Event to signal shutdown
        """
        self.client = client
        self.subscriptions = subscriptions
        self.stop_event = stop_event

        # WebSocket tasks
        self._ticker_socket_task: Optional[asyncio.Task] = None
        self._user_socket_task: Optional[asyncio.Task] = None
        self._kline_socket_tasks: Dict[str, asyncio.Task] = {}  # symbol -> task

        # Monitoring tasks
        self._connection_health_task: Optional[asyncio.Task] = None
        self._ticker_timeout_task: Optional[asyncio.Task] = None

        # Health monitoring
        self._last_message_time: Dict[str, float] = {}
        self._last_ticker_time: float = time.time()

        # Error handling
        self._restart_lock = threading.Lock()
        self._restart_count = 0
        self._last_restart_time = 0.0

        # Configuration
        self._ws_config = ULTRA_ROBUST_CONFIG
        self._connection_timeout = ULTRA_ROBUST_CONFIG.message_timeout_threshold
        self._max_ticker_silence_duration = 180  # 3 minutes - more aggressive
        self._ticker_timeout_check_interval = 30  # Check every 30 seconds
        self._force_restart_threshold = 600  # Force full restart after 10 min silence
        self._restart_base_delay = 60
        self._max_restart_delay = 300  # 5 minutes max instead of 1 hour

        # Network fallback configuration
        self._use_fallback_connection = False
        self._proxy_failed_count = 0
        self._max_proxy_failures_before_fallback = (
            3  # Switch to direct after 3 failures
        )

        # Health reporting
        self._health_report_interval = 300  # Report every 5 minutes

        # Subscription registry for resubscription after restart
        self._subscription_registry: Dict[str, SubscriptionInfo] = {}

        # Message handler callbacks
        self._user_message_handler: Optional[Callable] = None
        self._ticker_message_handler: Optional[Callable] = None
        self._kline_message_handler: Optional[Callable] = None

        # Direct WebSocket connection state
        self._base_ws_url: str = "wss://stream.binance.com:9443"

        logger.info("WebSocketManager initialized with ultra-robust configuration")
        self._ws_config.log_config()

    def set_message_handlers(
        self,
        user_handler: Callable,
        ticker_handler: Callable,
        kline_handler: Optional[Callable] = None,
    ) -> None:
        """Set message handler callbacks.

        Args:
            user_handler: Function to handle user data stream messages
            ticker_handler: Function to handle ticker stream messages
            kline_handler: Optional function to handle kline stream messages
        """
        self._user_message_handler = user_handler
        self._ticker_message_handler = ticker_handler
        self._kline_message_handler = kline_handler

    async def start(self) -> List[asyncio.Task]:
        """Start WebSocket streams and monitoring tasks.

        Returns:
            List of all active tasks
        """
        logger.info("Starting WebSocket streams and monitors...")

        # Start health monitoring
        self._connection_health_task = asyncio.create_task(
            self._monitor_connection_health()
        )

        # Start ticker timeout monitoring
        self._ticker_timeout_task = asyncio.create_task(self._monitor_ticker_timeout())

        # Start health reporting
        self._health_report_task = asyncio.create_task(self._report_system_health())

        # Start websocket streams
        await self._start_websocket_tasks()

        # Return all tasks - mypy: all are guaranteed to be not None after start
        if self._connection_health_task is None:
            raise RuntimeError("_connection_health_task not initialized")
        if self._ticker_timeout_task is None:
            raise RuntimeError("_ticker_timeout_task not initialized")
        if self._ticker_socket_task is None:
            raise RuntimeError("_ticker_socket_task not initialized")
        if self._user_socket_task is None:
            raise RuntimeError("_user_socket_task not initialized")

        tasks: List[asyncio.Task] = [
            self._connection_health_task,
            self._ticker_timeout_task,
            self._ticker_socket_task,
            self._user_socket_task,
        ]

        logger.info("WebSocket streams and monitors started successfully")
        return tasks

    async def stop(self) -> None:
        """Stop all WebSocket streams and monitoring."""
        logger.info("Stopping WebSocket manager...")

        # Stop monitoring tasks
        if self._ticker_timeout_task and not self._ticker_timeout_task.done():
            self._ticker_timeout_task.cancel()
            try:
                await self._ticker_timeout_task
            except asyncio.CancelledError:
                pass

        logger.info("WebSocket manager stopped")

    async def _start_websocket_tasks(self) -> None:
        """Start websocket connection tasks using direct websockets connections."""
        logger.info("Starting websocket tasks with direct WebSocket connections")

        # Ensure message handlers are set before creating tasks
        if self._ticker_message_handler is None:
            raise RuntimeError("Ticker message handler must be set before starting")
        if self._user_message_handler is None:
            raise RuntimeError("User message handler must be set before starting")

        # Derive base URL from client TLD (default: com)
        tld = getattr(self.client, "tld", "com")
        self._base_ws_url = f"wss://stream.binance.{tld}:9443"

        # Ticker stream — 24hr mini-tickers for all symbols
        # NOTE: !ticker@arr is deprecated/non-functional; !miniTicker@arr is the working
        # equivalent. Mini ticker provides: symbol (s), close/last price (c), open (o),
        # high (h), low (l), volume (v). Bid/ask fields (b, a) are absent and default to 0.
        ticker_url = f"{self._base_ws_url}/ws/!miniTicker@arr"
        self._ticker_socket_task = asyncio.create_task(
            self._run_stream(ticker_url, self._ticker_message_handler, "ticker")
        )

        # User data stream (listen key managed inside _run_user_stream)
        self._user_socket_task = asyncio.create_task(self._run_user_stream())

        # Kline streams for subscribed symbols
        if self._kline_message_handler:
            from src.domain.enums import SubscriptionType

            kline_symbols = set()
            for _, subscription_list in self.subscriptions.items():
                for sub_info in subscription_list:
                    if sub_info.data_type == SubscriptionType.KLINE:
                        kline_symbols.add(sub_info.symbol)

            for symbol in kline_symbols:
                kline_url = f"{self._base_ws_url}/ws/{symbol.lower()}@kline_15m"
                task_key = f"kline_{symbol}"
                self._kline_socket_tasks[task_key] = asyncio.create_task(
                    self._run_stream(kline_url, self._kline_message_handler, task_key)
                )
                logger.info("Created kline stream task for %s (15m)", symbol)

        logger.info("Websocket tasks started successfully")

    async def _handle_socket(
        self, socket: Any, message_handler: Callable, reconnect_attempts: int = 10
    ) -> None:
        """Handle incoming data from WebSocket with reconnection logic.

        Args:
            socket: WebSocket socket object
            message_handler: Function to handle incoming messages
            reconnect_attempts: Maximum number of reconnection attempts
        """
        logger.info("Entering handle_socket for %s", socket)

        while not self.stop_event.is_set():
            try:
                logger.info("Trying to start a stream")
                if not socket:
                    logger.error("Socket is None or not properly initialized.")
                    break

                async with socket as stream:
                    logger.info("WebSocket connected.")
                    while not self.stop_event.is_set():
                        try:
                            raw_msg = await asyncio.wait_for(stream.recv(), timeout=1.0)

                            # Parse message
                            msg = self._parse_message(raw_msg)
                            if msg is None:
                                continue

                            # Update timestamp for health monitoring
                            self._update_message_timestamp(
                                "user" if "e" in msg else "ticker"
                            )

                            # Call message handler
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
                    if self.stop_event.is_set():
                        return
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

        logger.info("Gracefully exiting handle_socket for socket: %s", socket)

    async def _run_stream(
        self, url: str, message_handler: Callable, stream_name: str
    ) -> None:
        """Connect directly to a Binance WebSocket stream URL and dispatch messages.

        Replaces BinanceSocketManager socket objects to avoid the broken
        call_soon_threadsafe(create_task, _read_loop) pattern in python-binance
        that is incompatible with websockets >= 14 / Python 3.12.

        Args:
            url: Full WebSocket URL to connect to
            message_handler: Callback to invoke for each received message
            stream_name: Human-readable name used in logs and health tracking
        """
        logger.info("Starting %s stream task", stream_name)
        while not self.stop_event.is_set():
            try:
                logger.info("Connecting %s stream...", stream_name)
                async with websockets.connect(
                    url, ping_interval=20, ping_timeout=10, close_timeout=5
                ) as ws:
                    logger.info("WebSocket connected (%s).", stream_name)
                    while not self.stop_event.is_set():
                        try:
                            raw_msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                            self._update_message_timestamp(stream_name)
                            msg = self._parse_message(raw_msg)
                            if msg:
                                message_handler(msg)
                        except asyncio.TimeoutError:
                            continue
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            logger.error(
                                "Error receiving from %s stream: %s", stream_name, e
                            )
                            break
            except asyncio.CancelledError:
                logger.info("%s stream task cancelled", stream_name)
                return
            except Exception as e:
                logger.error(
                    "%s stream connection error: %s. Reconnecting in 5s...",
                    stream_name,
                    e,
                )
                try:
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    return
        logger.info("%s stream task exiting", stream_name)

    async def _run_user_stream(self) -> None:
        """Connect to the Binance user data stream via the WebSocket API.

        Delegates to python-binance's _ws_api_request() which handles signing
        (apiKey, timestamp, HMAC-SHA256 signature) internally. Events are routed
        to a local asyncio.Queue via WebsocketAPI.register_subscription_queue().
        """
        stream_name = "user"
        logger.info("Starting user data stream task (WebSocket API)")

        while not self.stop_event.is_set():
            subscription_id: Optional[str] = None
            queue: asyncio.Queue = asyncio.Queue()
            try:
                # Subscribe — python-binance handles all signing internally
                result = await self.client._ws_api_request(
                    "userDataStream.subscribe.signature",
                    signed=True,
                    params={},
                )
                subscription_id = str(result.get("subscriptionId"))
                self.client.ws_api.register_subscription_queue(subscription_id, queue)
                logger.info(
                    "User data stream subscribed (subscriptionId=%s)", subscription_id
                )

                while not self.stop_event.is_set():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=30.0)
                        self._update_message_timestamp(stream_name)
                        if self._user_message_handler is None:
                            raise RuntimeError("User message handler not set")
                        self._user_message_handler(event)
                    except asyncio.TimeoutError:
                        pass
                    except asyncio.CancelledError:
                        raise

            except asyncio.CancelledError:
                logger.info("User data stream task cancelled")
                if subscription_id:
                    self.client.ws_api.unregister_subscription_queue(subscription_id)
                return
            except Exception as e:
                logger.error("User stream error: %s. Reconnecting in 5s...", e)
                if subscription_id:
                    self.client.ws_api.unregister_subscription_queue(subscription_id)
                try:
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    return
        logger.info("User data stream task exiting")

    def _parse_message(self, raw_msg: Any) -> Optional[Union[Dict, List]]:
        """Parse raw WebSocket message.

        Args:
            raw_msg: Raw message from WebSocket

        Returns:
            Parsed message dict/list or None if invalid
        """
        if isinstance(raw_msg, str):
            try:
                return cast(Union[Dict[Any, Any], List[Any]], json.loads(raw_msg))
            except json.JSONDecodeError:
                logger.warning("Received non-JSON string: %s", raw_msg)
                return None
        elif isinstance(raw_msg, dict):
            return raw_msg
        elif isinstance(raw_msg, list):
            if all(isinstance(item, dict) for item in raw_msg):
                return raw_msg
            logger.warning("Received list with non-dict items: %s", raw_msg)
            return None
        else:
            logger.warning("Unexpected message type: %s", type(raw_msg))
            return None

    def _update_message_timestamp(self, connection_type: str) -> None:
        """Update the last message timestamp for a connection type."""
        self._last_message_time[connection_type] = time.time()

    def update_last_ticker_time(self) -> None:
        """Update the last ticker message timestamp (called by ticker handler)."""
        self._last_ticker_time = time.time()

    async def _monitor_connection_health(self) -> None:
        """Monitor WebSocket connection health and detect timeouts."""
        logger.info("Starting connection health monitor")
        health_check_counter = 0
        last_warning_time: Dict[str, float] = {}

        while not self.stop_event.is_set():
            try:
                current_time = time.time()
                health_check_counter += 1

                # Periodic heartbeat log every 5 minutes
                if health_check_counter % 10 == 0:
                    active_connections = len(self._last_message_time)
                    logger.info(
                        "Connection health check #%d: %d active connections",
                        health_check_counter,
                        active_connections,
                    )
                    for conn_type, last_time in self._last_message_time.items():
                        seconds_since_last = current_time - last_time
                        logger.info(
                            "  %s: last message %.1f seconds ago",
                            conn_type,
                            seconds_since_last,
                        )

                # Check for timeouts
                for conn_type, last_time in self._last_message_time.items():
                    seconds_since_last = current_time - last_time

                    if seconds_since_last > self._connection_timeout:
                        # Only warn for ticker streams
                        if "ticker" in conn_type:
                            last_warn = last_warning_time.get(conn_type, 0)
                            if current_time - last_warn > 300:  # Warn every 5 minutes
                                logger.warning(
                                    "Ticker timeout: %s silent for %.1f seconds",
                                    conn_type,
                                    seconds_since_last,
                                )
                                last_warning_time[conn_type] = current_time

                await asyncio.sleep(self._ws_config.health_check_interval)

            except Exception as e:
                logger.error("Error in connection health monitor: %s", e)
                await asyncio.sleep(self._ws_config.health_check_interval)

        logger.info("Connection health monitor stopped")

    async def _monitor_ticker_timeout(self) -> None:
        """Monitor ticker timeout and trigger restart if silent too long.

        This is the DEAD-MAN SWITCH that forces restart if no ticker data received.
        """
        logger.info(
            "Starting ticker timeout monitoring (warning: %d seconds, force restart: %d seconds)",
            self._max_ticker_silence_duration,
            self._force_restart_threshold,
        )

        while not self.stop_event.is_set():
            try:
                await asyncio.sleep(self._ticker_timeout_check_interval)

                if self.stop_event.is_set():
                    break

                # Check for ticker timeout
                time_since_ticker = time.time() - self._last_ticker_time

                # CRITICAL: Force complete restart if silent too long
                if time_since_ticker > self._force_restart_threshold:
                    logger.critical(
                        "DEAD-MAN SWITCH ACTIVATED: No ticker data for %.1f seconds. "
                        "Forcing complete WebSocket restart...",
                        time_since_ticker,
                    )

                    # Trigger restart
                    timeout_error = {
                        "type": "TickerTimeoutError",
                        "m": f"CRITICAL: Ticker silent for {time_since_ticker:.1f} seconds (threshold: {self._force_restart_threshold}s)",
                    }
                    await self._handle_websocket_error(timeout_error)

                    # Reset last ticker time after restart to avoid immediate re-trigger
                    # The restart should restore ticker flow; if not, we'll detect again
                    self._last_ticker_time = time.time()

                    # Continue monitoring instead of exiting - the dead-man switch
                    # must keep running to handle future connection failures
                    continue

                elif time_since_ticker > self._max_ticker_silence_duration:
                    logger.warning(
                        "Ticker timeout: ticker silent for %.1f seconds (warning threshold: %d seconds)",
                        time_since_ticker,
                        self._max_ticker_silence_duration,
                    )

            except asyncio.CancelledError:
                logger.info("Ticker timeout monitoring cancelled")
                break
            except Exception as e:
                logger.error("Error in ticker timeout monitoring: %s", e)
                await asyncio.sleep(10)

        logger.info("Ticker timeout monitoring stopped")

    async def _report_system_health(self) -> None:
        """Periodically report system health status for monitoring.

        This provides visibility into system state and helps detect issues early.
        """
        logger.info(
            "Starting system health reporter (interval: %d seconds)",
            self._health_report_interval,
        )

        while not self.stop_event.is_set():
            try:
                await asyncio.sleep(self._health_report_interval)

                if self.stop_event.is_set():
                    break

                ticker_silence = time.time() - self._last_ticker_time

                # Determine health status
                if ticker_silence > self._force_restart_threshold:
                    health_status = "CRITICAL"
                    message = (
                        f"SYSTEM CRITICAL: No ticker data for {ticker_silence:.0f}s"
                    )
                elif ticker_silence > self._max_ticker_silence_duration:
                    health_status = "DEGRADED"
                    message = (
                        f"SYSTEM DEGRADED: No ticker data for {ticker_silence:.0f}s"
                    )
                elif self._restart_count > 0:
                    health_status = "RECOVERING"
                    message = f"RECOVERING: {self._restart_count} restarts, fallback={self._use_fallback_connection}"
                else:
                    health_status = "HEALTHY"
                    num_subscriptions = sum(
                        len(subs) for subs in self.subscriptions.values()
                    )
                    message = f"SYSTEM HEALTHY: Ticker active, {num_subscriptions} subscriptions"

                logger.info("[HEALTH CHECK] %s - %s", health_status, message)

            except asyncio.CancelledError:
                logger.info("System health reporter cancelled")
                break
            except Exception as e:
                logger.error("Error in health reporter: %s", e)
                await asyncio.sleep(30)

        logger.info("System health reporter stopped")

    async def _handle_websocket_error(
        self, error_msg: Union[str, Dict[str, Any]]
    ) -> None:
        """Handle WebSocket errors and trigger restart if needed.

        Args:
            error_msg: Error message or dict
        """
        current_time = time.time()

        # Check for unrecoverable errors
        unrecoverable_types = [
            "BinanceWebsocketUnableToConnect",
            "BinanceWebsocketClosed",
            "ConnectionClosedError",
            "ConnectionClosedOK",
            "ConnectionClosed",
            "TickerTimeoutError",
        ]
        unrecoverable_msgs = [
            "Max reconnections",
            "timed out",
            "Cannot connect",
            "going away",
            "abnormal closure",
        ]

        is_unrecoverable = False
        if isinstance(error_msg, dict):
            error_type = error_msg.get("type", "")
            error_message = error_msg.get("m", "")

            if any(t in error_type for t in unrecoverable_types) or any(
                m in error_message for m in unrecoverable_msgs
            ):
                is_unrecoverable = True

        # Restart if unrecoverable
        if is_unrecoverable:
            self._restart_count += 1
            time_since_last = current_time - self._last_restart_time

            # Reset counter if it's been stable for 30 minutes
            if time_since_last > 1800:
                logger.info(
                    "System has been stable for 30+ minutes. Resetting restart counter."
                )
                self._restart_count = 1
                self._use_fallback_connection = False  # Can try proxy again
                self._proxy_failed_count = 0

            # Calculate progressive delay with gentler progression
            restart_delay = min(
                self._restart_base_delay
                * (self._restart_count**1.2),  # Gentler than 1.5
                self._max_restart_delay,
            )

            logger.error(
                "Unrecoverable error: %s. Restart #%d in %.1f seconds... (fallback mode: %s)",
                error_msg,
                self._restart_count,
                restart_delay,
                self._use_fallback_connection,
            )

            await asyncio.sleep(restart_delay)
            self._last_restart_time = time.time()

            await self._restart_websocket_client()
        else:
            logger.error("WebSocket error: %s", error_msg)

    async def _restart_websocket_client(self) -> None:
        """Restart WebSocket streams by recreating socket manager.

        Will switch to direct Binance connection as fallback if proxy fails repeatedly.
        """
        retry_count = 0

        # Check if we should enable fallback mode
        if (
            self._restart_count >= self._max_proxy_failures_before_fallback
            and not self._use_fallback_connection
        ):
            logger.warning(
                "Proxy connection failed %d times (threshold: %d). "
                "Switching to DIRECT Binance connection as fallback...",
                self._restart_count,
                self._max_proxy_failures_before_fallback,
            )
            self._use_fallback_connection = True
            # Note: Actual proxy removal would require recreating KrakenClient
            # For now, this flag can be used by client initialization code
            # TODO: Implement client recreation without proxy

        while True:
            try:
                logger.info(
                    "Attempting WebSocket restart #%d... (fallback mode: %s)",
                    self._restart_count,
                    self._use_fallback_connection,
                )

                # Cancel existing tasks
                logger.info("Cancelling existing websocket tasks...")
                if self._ticker_socket_task and not self._ticker_socket_task.done():
                    self._ticker_socket_task.cancel()
                    try:
                        await self._ticker_socket_task
                    except asyncio.CancelledError:
                        pass

                if self._user_socket_task and not self._user_socket_task.done():
                    self._user_socket_task.cancel()
                    try:
                        await self._user_socket_task
                    except asyncio.CancelledError:
                        pass

                logger.info("Websocket tasks cancelled")

                # Wait for cleanup
                await asyncio.sleep(1.0)

                # Restart streams
                logger.info("Creating fresh streams...")
                await self._start_websocket_tasks()
                logger.info("Websocket tasks restarted successfully")

                # Resubscribe
                await self._resubscribe_all_subscriptions()
                logger.info("Resubscription complete")

                if retry_count == 0:
                    logger.info(
                        "WebSocket restart successful on attempt #%d",
                        self._restart_count,
                    )
                break

            except Exception as e:
                retry_count += 1
                restart_retry_delay = min(30, 2**retry_count)
                logger.error(
                    "Restart attempt #%d failed: %s. Retrying in %d seconds...",
                    retry_count,
                    e,
                    restart_retry_delay,
                )
                await asyncio.sleep(restart_retry_delay)

    async def _resubscribe_all_subscriptions(self) -> None:
        """Resubscribe all active subscriptions after restart."""
        logger.info("Resubscribing all subscriptions...")

        subscriptions_to_restore = self._subscription_registry.copy()

        for system_id, subscription_info in subscriptions_to_restore.items():
            try:
                logger.info("Resubscribing system %s", system_id)

                # Remove from current subscriptions
                if system_id in self.subscriptions:
                    del self.subscriptions[system_id]

                # Re-add subscription
                if system_id not in self.subscriptions:
                    self.subscriptions[system_id] = []
                if subscription_info not in self.subscriptions[system_id]:
                    self.subscriptions[system_id].append(subscription_info)
                    self._subscription_registry[system_id] = subscription_info

                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error("Failed to resubscribe system %s: %s", system_id, e)

        logger.info("Finished resubscribing")

    def register_subscription(
        self, system_id: str, subscription_info: SubscriptionInfo
    ) -> None:
        """Register a subscription for automatic resubscription after restart."""
        self._subscription_registry[system_id] = subscription_info

    def unregister_subscription(self, system_id: str) -> None:
        """Unregister a subscription."""
        if system_id in self._subscription_registry:
            del self._subscription_registry[system_id]

    def handle_error_from_message_handler(self, error_msg: Union[str, Dict]) -> None:
        """Handle errors reported by message handlers (called from the event loop)."""
        if self._restart_lock.acquire(blocking=False):
            try:
                asyncio.ensure_future(self._handle_websocket_error(error_msg))
            finally:
                self._restart_lock.release()
