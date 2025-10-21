"""WebSocket manager for Binance real-time data streams.

This module handles all WebSocket connectivity, health monitoring, and recovery logic
for Binance spot trading streams (ticker data and user data streams).
"""

import asyncio
import json
import logging
import time
import threading
from typing import Dict, List, Optional, Callable, Any, Union

from binance import BinanceSocketManager

from src.common.client import BinanceClient
from src.common.identifiers import SubscriptionInfo
from src.websocket.config import ULTRA_ROBUST_CONFIG

logger = logging.getLogger("broker.websocket_manager")


class WebSocketManager:
    """Manages WebSocket connections, health monitoring, and recovery for Binance streams."""

    def __init__(
        self,
        client: BinanceClient,
        subscriptions: Dict[str, List[SubscriptionInfo]],
        stop_event: asyncio.Event,
        loop: asyncio.AbstractEventLoop,
    ):
        """Initialize WebSocket manager.

        Args:
            client: Binance AsyncClient instance
            subscriptions: Dict mapping system_id to list of SubscriptionInfo
            stop_event: Event to signal shutdown
            loop: Asyncio event loop
        """
        self.client = client
        self.subscriptions = subscriptions
        self.stop_event = stop_event
        self.loop = loop

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
        self._max_ticker_silence_duration = 300  # 5 minutes
        self._ticker_timeout_check_interval = 60  # Check every minute
        self._restart_base_delay = 60
        self._max_restart_delay = 3600

        # Subscription registry for resubscription after restart
        self._subscription_registry: Dict[str, SubscriptionInfo] = {}

        # Message handler callbacks
        self._user_message_handler: Optional[Callable] = None
        self._ticker_message_handler: Optional[Callable] = None
        self._kline_message_handler: Optional[Callable] = None

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
        self._connection_health_task = self.loop.create_task(
            self._monitor_connection_health()
        )

        # Start ticker timeout monitoring
        self._ticker_timeout_task = self.loop.create_task(
            self._monitor_ticker_timeout()
        )

        # Start websocket streams
        await self._start_websocket_tasks()

        # Return all tasks - mypy: all are guaranteed to be not None after start
        assert self._connection_health_task is not None
        assert self._ticker_timeout_task is not None
        assert self._ticker_socket_task is not None
        assert self._user_socket_task is not None

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
        """Start or restart websocket connection tasks with fresh socket manager."""
        logger.info("Starting websocket tasks with fresh BinanceSocketManager")

        # Create new socket manager
        socket_manager = BinanceSocketManager(client=self.client)

        # Ensure message handlers are set before creating tasks
        assert (
            self._ticker_message_handler is not None
        ), "Ticker message handler must be set before starting"
        assert (
            self._user_message_handler is not None
        ), "User message handler must be set before starting"

        # Create websocket tasks
        self._ticker_socket_task = self.loop.create_task(
            self._handle_socket(
                socket_manager.ticker_socket(),
                self._ticker_message_handler,
                reconnect_attempts=self._ws_config.max_reconnect_attempts,
            )
        )

        self._user_socket_task = self.loop.create_task(
            self._handle_socket(
                socket_manager.user_socket(),
                self._user_message_handler,
                reconnect_attempts=self._ws_config.max_reconnect_attempts,
            )
        )

        # Create kline socket tasks for each subscribed symbol
        if self._kline_message_handler:
            from src.common.identifiers import SubscriptionType

            # Collect unique symbols that need kline streams
            kline_symbols = set()
            for _, subscription_list in self.subscriptions.items():
                for sub_info in subscription_list:
                    if sub_info.data_type == SubscriptionType.KLINE:
                        kline_symbols.add(sub_info.symbol)

            # Create a kline socket task for each symbol
            for symbol in kline_symbols:
                task_key = f"kline_{symbol}"
                self._kline_socket_tasks[task_key] = self.loop.create_task(
                    self._handle_socket(
                        socket_manager.kline_socket(symbol=symbol, interval="15m"),
                        self._kline_message_handler,
                        reconnect_attempts=self._ws_config.max_reconnect_attempts,
                    )
                )
                logger.info(f"Created kline socket task for {symbol} (15m)")

        logger.info("Websocket tasks started successfully")

    async def _handle_socket(
        self, socket, message_handler: Callable, reconnect_attempts: int = 10
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

    def _parse_message(self, raw_msg: Any) -> Optional[Union[Dict, List]]:
        """Parse raw WebSocket message.

        Args:
            raw_msg: Raw message from WebSocket

        Returns:
            Parsed message dict/list or None if invalid
        """
        if isinstance(raw_msg, str):
            try:
                return json.loads(raw_msg)
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
        """Monitor ticker timeout and trigger restart if silent too long."""
        logger.info(
            "Starting ticker timeout monitoring (max silence: %d seconds)",
            self._max_ticker_silence_duration,
        )

        while not self.stop_event.is_set():
            try:
                await asyncio.sleep(self._ticker_timeout_check_interval)

                if self.stop_event.is_set():
                    break

                # Check for ticker timeout
                time_since_ticker = time.time() - self._last_ticker_time
                if time_since_ticker > self._max_ticker_silence_duration:
                    logger.error(
                        "Ticker silent for %.1f seconds (max: %d). Forcing restart...",
                        time_since_ticker,
                        self._max_ticker_silence_duration,
                    )

                    # Trigger restart
                    timeout_error = {
                        "type": "TickerTimeoutError",
                        "m": f"Ticker silent for {time_since_ticker:.1f} seconds",
                    }
                    await self._handle_websocket_error(timeout_error)
                    return

            except asyncio.CancelledError:
                logger.info("Ticker timeout monitoring cancelled")
                break
            except Exception as e:
                logger.error("Error in ticker timeout monitoring: %s", e)
                await asyncio.sleep(10)

        logger.info("Ticker timeout monitoring stopped")

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

            # Reset counter if it's been a while
            if time_since_last > 600:
                self._restart_count = 1

            # Calculate progressive delay
            restart_delay = min(
                self._restart_base_delay * (self._restart_count**1.5),
                self._max_restart_delay,
            )

            logger.error(
                "Unrecoverable error: %s. Restart #%d in %.1f seconds...",
                error_msg,
                self._restart_count,
                restart_delay,
            )

            await asyncio.sleep(restart_delay)
            self._last_restart_time = time.time()

            await self._restart_websocket_client()
        else:
            logger.error("WebSocket error: %s", error_msg)

    async def _restart_websocket_client(self) -> None:
        """Restart WebSocket streams by recreating socket manager."""
        retry_count = 0
        while True:
            try:
                logger.info("Attempting WebSocket restart #%d...", self._restart_count)

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
                    logger.info("WebSocket restart successful")
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
        """Handle errors reported by message handlers (called from outside)."""
        if self.loop and self._restart_lock.acquire(blocking=False):
            try:
                asyncio.run_coroutine_threadsafe(
                    self._handle_websocket_error(error_msg), self.loop
                )
            finally:
                self._restart_lock.release()
