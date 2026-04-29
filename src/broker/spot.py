"""Binance spot trading broker with WebSocket integration.

This module provides the main BrokerSpot class for interacting with Binance spot markets,
handling subscriptions, and coordinating with WebSocket streams.
"""

import asyncio
import threading
import queue
import logging
from typing import Dict, List, Optional

from src.common.client import BinanceClient
from src.domain.enums import SubscriptionTarget, SubscriptionType
from src.domain.subscriptions import SubscriptionInfo
from src.websocket import WebSocketManager
from src.broker.message_handlers import (
    handle_kline_message,
    handle_user_message,
    handle_ticker_message,
)

from src.config import API_KEY, API_SECRET

logger = logging.getLogger(__name__)


class BrokerSpot:
    """Binance spot trading broker with real-time WebSocket integration."""

    def __init__(self) -> None:
        """Initialize BrokerSpot."""
        self.client: Optional[BinanceClient] = None
        self.subscriptions: Dict[str, list] = {}
        self.queues: Dict[str, queue.Queue] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.stop_producers_event: asyncio.Event = asyncio.Event()
        self.tasks: Optional[List[asyncio.Task]] = None
        self.thread = threading.Thread(target=self.start_loop)

        # WebSocket manager (will be initialized in run())
        self._ws_manager: Optional[WebSocketManager] = None

        logger.info("BrokerSpot initialized")
        self.thread.start()

    @property
    def _ticker_timeout_task(self) -> Optional[asyncio.Task]:
        """Task handle for ticker timeout monitoring (delegated to WebSocketManager)."""
        return self._ws_manager._ticker_timeout_task if self._ws_manager else None

    @property
    def _connection_health_task(self) -> Optional[asyncio.Task]:
        """Task handle for connection health monitoring (delegated to WebSocketManager)."""
        return self._ws_manager._connection_health_task if self._ws_manager else None

    @property
    def _ws_config(self):
        """WebSocket configuration (delegated to WebSocketManager)."""
        return self._ws_manager._ws_config if self._ws_manager else None

    def start_loop(self) -> None:
        """Start the asyncio loop in a new thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.run())

    async def run(self) -> None:
        """Main entry point for running the broker."""
        logger.info(
            "Main entry point for running the broker, thread: %s", self.thread.name
        )

        # Create Binance client
        self.client = BinanceClient(api_key=API_KEY, api_secret=API_SECRET)

        # Create WebSocket manager
        if self.loop is None:
            raise RuntimeError(
                "Event loop not initialized before creating WebSocket manager"
            )
        self._ws_manager = WebSocketManager(
            client=self.client,
            subscriptions=self.subscriptions,
            stop_event=self.stop_producers_event,
            loop=self.loop,
        )

        # Set up message handlers
        self._ws_manager.set_message_handlers(
            user_handler=self._create_user_message_handler(),
            ticker_handler=self._create_ticker_message_handler(),
            kline_handler=self._create_kline_message_handler(),
        )

        # Start WebSocket streams and monitoring
        self.tasks = await self._ws_manager.start()

        # Await all tasks
        await asyncio.gather(*self.tasks, return_exceptions=True)

    def _create_user_message_handler(self):
        """Create user message handler with error callback."""

        def handler(msg):
            handle_user_message(
                msg,
                self.subscriptions,
                websocket_error_callback=self._handle_websocket_error_callback,
            )

        return handler

    def _create_ticker_message_handler(self):
        """Create ticker message handler with callbacks."""

        def handler(msg):
            handle_ticker_message(
                msg,
                self.subscriptions,
                last_ticker_time_callback=self._update_last_ticker_time_callback,
                websocket_error_callback=self._handle_websocket_error_callback,
            )

        return handler

    def _create_kline_message_handler(self):
        """Create kline message handler."""

        def handler(msg):
            handle_kline_message(msg, self.subscriptions)

        return handler

    def _handle_websocket_error_callback(self, error_msg):
        """Callback for handling websocket errors from message handlers."""
        if self._ws_manager:
            self._ws_manager.handle_error_from_message_handler(error_msg)

    def _update_last_ticker_time_callback(self):
        """Callback for updating last ticker time from message handler."""
        if self._ws_manager:
            self._ws_manager.update_last_ticker_time()

    def subscribe(self, system_id: str, subscription_info: SubscriptionInfo) -> None:
        """Subscribe a strategy to user or price feeds.

        Args:
            system_id: Unique identifier for the strategy/system
            subscription_info: Information about what to subscribe to
        """
        if system_id not in self.subscriptions:
            self.subscriptions[system_id] = []

        # Avoid duplicate subscriptions
        if subscription_info not in self.subscriptions[system_id]:
            self.subscriptions[system_id].append(subscription_info)

            # Register for automatic resubscription after restart
            if self._ws_manager:
                self._ws_manager.register_subscription(system_id, subscription_info)

            logger.info(
                "New subscription for ID: %s: %s", system_id, subscription_info.symbol
            )

    def setup_subscriptions(
        self,
        hp_id: str,
        symbol: str,
        additional_symbols: Optional[List[str]],
        worker_queue: queue.Queue,
    ) -> None:
        """Setup USER and PRICE subscriptions for a strategy.

        Args:
            hp_id: The unique identifier for the holding pattern/strategy
            symbol: The main trading symbol (e.g., 'BTCUSDC')
            additional_symbols: Optional list of additional symbols for multihop strategies
            worker_queue: Queue for receiving subscription data
        """
        # User data subscription
        self.subscribe(
            system_id=hp_id,
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.USER,
                symbol=symbol,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )

        # Price subscription for main symbol
        self.subscribe(
            system_id=hp_id,
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol=symbol,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )

        # Additional price subscriptions (for multihop sell strategies)
        if additional_symbols:
            for add_symbol in additional_symbols:
                self.subscribe(
                    system_id=hp_id,
                    subscription_info=SubscriptionInfo(
                        data_type=SubscriptionType.PRICE,
                        symbol=add_symbol,
                        target=SubscriptionTarget.BACKEND,
                        queue=worker_queue,
                    ),
                )

    def unsubscribe(self, system_id: str) -> None:
        """Allows a strategy to unsubscribe from a user or price feed.

        Args:
            system_id: The unique identifier for the strategy/system
        """
        # Check if the system_id exists in the subscriptions
        if system_id in self.subscriptions:
            del self.subscriptions[system_id]
            logger.info("Deleted all subscriptions for ID: %s", system_id)

        # Remove from WebSocket manager registry
        if self._ws_manager:
            self._ws_manager.unregister_subscription(system_id)

    def stop(self):
        """Shut down BrokerSpot gracefully."""
        logger.info("Stopping BrokerSpot gracefully.")

        # Set stop event to notify all tasks to exit
        self.stop_producers_event.set()

        # Stop WebSocket manager
        if self._ws_manager and self.loop:
            self.loop.run_until_complete(self._ws_manager.stop())

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
            if self.loop and self.client:
                loop = asyncio.get_running_loop()
                loop.create_task(self.client.close_connection())
            self.join_thread()

            # Final log statement indicating complete shutdown
            logger.info("BrokerSpot shutdown complete.")
