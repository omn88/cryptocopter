"""WebSocket manager for Kraken WS v2 real-time data streams.

Handles WebSocket connectivity, per-symbol subscriptions, token-authenticated
private channels, and reconnect logic for Kraken spot trading streams.
"""

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Union, cast

import websockets

from src.common.client import KrakenClient
from src.domain.subscriptions import SubscriptionInfo
from src.websocket.config import ULTRA_ROBUST_CONFIG

logger = logging.getLogger(__name__)

KRAKEN_WS_PUBLIC_URL = "wss://ws.kraken.com/v2"
KRAKEN_WS_AUTH_URL = "wss://ws-auth.kraken.com/v2"
KLINE_INTERVAL_MINUTES = 15


class WebSocketManager:
    """Manages Kraken WS v2 connectivity.

    Two long-lived connections are maintained: a public socket carrying
    per-symbol `ticker`/`ohlc` subscriptions (reference-counted, so multiple
    strategies subscribing to the same symbol only subscribe once on the
    wire), and a token-authenticated private socket carrying the account-wide
    `executions`/`balances` channels. Each connection's own recv loop acts as
    its dead-connection watchdog: a read timeout (Kraken sends heartbeats
    ~once/sec once subscribed to anything) triggers that connection's
    reconnect, independent of the other.
    """

    def __init__(
        self,
        client: KrakenClient,
        subscriptions: Dict[str, List[SubscriptionInfo]],
        stop_event: asyncio.Event,
    ):
        """Initialize WebSocket manager.

        Args:
            client: KrakenClient instance (used for the WS auth token).
            subscriptions: Dict mapping system_id to list of SubscriptionInfo.
            stop_event: Event to signal shutdown.
        """
        self.client = client
        self.subscriptions = subscriptions
        self.stop_event = stop_event

        self._ws_config = ULTRA_ROBUST_CONFIG

        # Live connection handles; set while connected, used to send subscribe/
        # unsubscribe frames from outside the connection's own recv loop.
        self._public_ws: Optional[Any] = None
        self._private_ws: Optional[Any] = None

        # {symbol: subscriber_count} - a network subscribe/unsubscribe frame is
        # only sent on a 0->1 / 1->0 transition.
        self._ticker_subscribers: Dict[str, int] = {}
        self._kline_subscribers: Dict[str, int] = {}

        self._ws_token: Optional[str] = None

        self._public_socket_task: Optional[asyncio.Task] = None
        self._private_socket_task: Optional[asyncio.Task] = None
        self._token_refresh_task: Optional[asyncio.Task] = None

        self._user_message_handler: Optional[Callable] = None
        self._ticker_message_handler: Optional[Callable] = None
        self._kline_message_handler: Optional[Callable] = None

        logger.info("WebSocketManager initialized for Kraken WS v2")

    def set_message_handlers(
        self,
        user_handler: Callable,
        ticker_handler: Callable,
        kline_handler: Optional[Callable] = None,
    ) -> None:
        """Set message handler callbacks.

        Args:
            user_handler: Function to handle executions/balances messages.
            ticker_handler: Function to handle ticker channel messages.
            kline_handler: Optional function to handle ohlc channel messages.
        """
        self._user_message_handler = user_handler
        self._ticker_message_handler = ticker_handler
        self._kline_message_handler = kline_handler

    async def start(self) -> List[asyncio.Task]:
        """Start WebSocket connections and the token refresh loop.

        Returns:
            List of all active tasks.
        """
        logger.info("Starting Kraken WebSocket streams...")

        if self._ticker_message_handler is None:
            raise RuntimeError("Ticker message handler must be set before starting")
        if self._user_message_handler is None:
            raise RuntimeError("User message handler must be set before starting")

        await self._refresh_ws_token()

        self._public_socket_task = asyncio.create_task(self._run_public_stream())
        self._private_socket_task = asyncio.create_task(self._run_private_stream())
        self._token_refresh_task = asyncio.create_task(self._token_refresh_loop())

        logger.info("Kraken WebSocket streams started")
        return [
            self._public_socket_task,
            self._private_socket_task,
            self._token_refresh_task,
        ]

    async def stop(self) -> None:
        """Stop all WebSocket connections and the token refresh loop."""
        logger.info("Stopping WebSocket manager...")

        for task in (
            self._public_socket_task,
            self._private_socket_task,
            self._token_refresh_task,
        ):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        logger.info("WebSocket manager stopped")

    # ------------------------------------------------------------------
    # Per-symbol subscriptions (public socket, reference-counted)
    # ------------------------------------------------------------------

    async def subscribe_ticker(self, symbol: str) -> None:
        """Subscribe to the ticker channel for `symbol` (ref-counted)."""
        await self._adjust_subscription(self._ticker_subscribers, symbol, "ticker")

    async def unsubscribe_ticker(self, symbol: str) -> None:
        """Unsubscribe from the ticker channel for `symbol` (ref-counted)."""
        await self._adjust_subscription(
            self._ticker_subscribers, symbol, "ticker", delta=-1
        )

    async def subscribe_kline(self, symbol: str) -> None:
        """Subscribe to the ohlc channel for `symbol` (ref-counted)."""
        await self._adjust_subscription(
            self._kline_subscribers,
            symbol,
            "ohlc",
            extra_params={"interval": KLINE_INTERVAL_MINUTES},
        )

    async def unsubscribe_kline(self, symbol: str) -> None:
        """Unsubscribe from the ohlc channel for `symbol` (ref-counted)."""
        await self._adjust_subscription(
            self._kline_subscribers,
            symbol,
            "ohlc",
            delta=-1,
            extra_params={"interval": KLINE_INTERVAL_MINUTES},
        )

    async def _adjust_subscription(
        self,
        registry: Dict[str, int],
        symbol: str,
        channel: str,
        delta: int = 1,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> None:
        previous = registry.get(symbol, 0)
        current = max(previous + delta, 0)
        if current == 0:
            registry.pop(symbol, None)
        else:
            registry[symbol] = current

        # Only the 0->1 (subscribe) and 1->0 (unsubscribe) transitions need a
        # network frame; intermediate ref-count changes are silent.
        if (previous > 0) == (current > 0):
            return

        method = "subscribe" if current > 0 else "unsubscribe"
        await self._send_public_channel_message(channel, method, [symbol], extra_params)

    async def _send_public_channel_message(
        self,
        channel: str,
        method: str,
        symbols: List[str],
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._public_ws is None:
            logger.debug(
                "Public socket not connected; %s %s for %s will be sent on next connect",
                method,
                channel,
                symbols,
            )
            return
        params: Dict[str, Any] = {"channel": channel, "symbol": symbols}
        if extra_params:
            params.update(extra_params)
        try:
            await self._public_ws.send(json.dumps({"method": method, "params": params}))
        except Exception as e:
            logger.warning("Failed to %s %s for %s: %s", method, channel, symbols, e)

    async def _resubscribe_public_channels(self) -> None:
        """Replay all active ref-counted subscriptions onto a freshly (re)connected socket."""
        for symbol in list(self._ticker_subscribers):
            await self._send_public_channel_message("ticker", "subscribe", [symbol])
        for symbol in list(self._kline_subscribers):
            await self._send_public_channel_message(
                "ohlc", "subscribe", [symbol], {"interval": KLINE_INTERVAL_MINUTES}
            )

    # ------------------------------------------------------------------
    # Public socket (ticker, ohlc)
    # ------------------------------------------------------------------

    async def _run_public_stream(self) -> None:
        while not self.stop_event.is_set():
            try:
                logger.info("Connecting to Kraken public WebSocket...")
                async with websockets.connect(
                    KRAKEN_WS_PUBLIC_URL,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._public_ws = ws
                    logger.info("Kraken public WebSocket connected")
                    await self._resubscribe_public_channels()

                    while not self.stop_event.is_set():
                        try:
                            raw_msg = await asyncio.wait_for(
                                ws.recv(),
                                timeout=self._ws_config.connection_silence_timeout,
                            )
                        except asyncio.TimeoutError:
                            logger.warning(
                                "No message on public socket for %ds; reconnecting",
                                self._ws_config.connection_silence_timeout,
                            )
                            break
                        msg = self._parse_message(raw_msg)
                        if msg is not None:
                            self._dispatch_public_message(msg)
            except asyncio.CancelledError:
                logger.info("Public stream task cancelled")
                self._public_ws = None
                return
            except Exception as e:
                logger.error("Public WebSocket error: %s. Reconnecting...", e)
            finally:
                self._public_ws = None

            try:
                await asyncio.sleep(self._ws_config.initial_reconnect_delay)
            except asyncio.CancelledError:
                return

        logger.info("Public stream task exiting")

    def _dispatch_public_message(self, msg: Union[Dict, List]) -> None:
        if not isinstance(msg, dict):
            logger.debug("Unexpected public message shape: %s", msg)
            return

        channel = msg.get("channel")
        if channel == "heartbeat":
            return
        if "method" in msg:
            if not msg.get("success", True):
                logger.warning("Kraken WS public subscribe error: %s", msg)
            return
        if channel == "ticker":
            if self._ticker_message_handler:
                self._ticker_message_handler(msg)
        elif channel == "ohlc":
            if self._kline_message_handler:
                self._kline_message_handler(msg)
        else:
            logger.debug("Unhandled public channel message: %s", msg)

    # ------------------------------------------------------------------
    # Private socket (executions, balances) - token-authenticated
    # ------------------------------------------------------------------

    async def _run_private_stream(self) -> None:
        while not self.stop_event.is_set():
            try:
                logger.info("Connecting to Kraken private WebSocket...")
                async with websockets.connect(
                    KRAKEN_WS_AUTH_URL,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._private_ws = ws
                    logger.info("Kraken private WebSocket connected")
                    await self._subscribe_private_channels()

                    while not self.stop_event.is_set():
                        try:
                            raw_msg = await asyncio.wait_for(
                                ws.recv(),
                                timeout=self._ws_config.connection_silence_timeout,
                            )
                        except asyncio.TimeoutError:
                            logger.warning(
                                "No message on private socket for %ds; reconnecting",
                                self._ws_config.connection_silence_timeout,
                            )
                            break
                        msg = self._parse_message(raw_msg)
                        if msg is not None:
                            self._dispatch_private_message(msg)
            except asyncio.CancelledError:
                logger.info("Private stream task cancelled")
                self._private_ws = None
                return
            except Exception as e:
                logger.error("Private WebSocket error: %s. Reconnecting...", e)
            finally:
                self._private_ws = None

            try:
                await asyncio.sleep(self._ws_config.initial_reconnect_delay)
            except asyncio.CancelledError:
                return

        logger.info("Private stream task exiting")

    async def _subscribe_private_channels(self) -> None:
        if self._ws_token is None:
            await self._refresh_ws_token()
        if self._ws_token is None:
            logger.error("No WS token available; cannot subscribe to private channels")
            return
        if self._private_ws is None:
            return
        for channel in ("executions", "balances"):
            frame = {
                "method": "subscribe",
                "params": {"channel": channel, "token": self._ws_token},
            }
            try:
                await self._private_ws.send(json.dumps(frame))
            except Exception as e:
                logger.warning("Failed to subscribe to %s: %s", channel, e)

    def _dispatch_private_message(self, msg: Union[Dict, List]) -> None:
        if not isinstance(msg, dict):
            logger.debug("Unexpected private message shape: %s", msg)
            return

        channel = msg.get("channel")
        if channel == "heartbeat":
            return
        if "method" in msg:
            if not msg.get("success", True):
                logger.warning("Kraken WS private subscribe error: %s", msg)
            return
        if channel in ("executions", "balances"):
            if self._user_message_handler:
                self._user_message_handler(msg)
        else:
            logger.debug("Unhandled private channel message: %s", msg)

    # ------------------------------------------------------------------
    # Token auth
    # ------------------------------------------------------------------

    async def _refresh_ws_token(self) -> None:
        try:
            resp = await self.client.get_ws_token()
            self._ws_token = resp["token"]
            logger.info("Refreshed Kraken WS auth token")
        except Exception as e:
            logger.error("Failed to fetch Kraken WS token: %s", e)

    async def _token_refresh_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                await asyncio.sleep(self._ws_config.token_refresh_interval)
            except asyncio.CancelledError:
                return
            if self.stop_event.is_set():
                break
            await self._refresh_ws_token()
        logger.info("Token refresh loop exiting")

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _parse_message(self, raw_msg: Any) -> Optional[Union[Dict, List]]:
        """Parse raw WebSocket message.

        Args:
            raw_msg: Raw message from WebSocket.

        Returns:
            Parsed message dict/list, or None if invalid.
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
