"""Message handlers for processing Kraken WS v2 WebSocket messages.

This module turns the channel-envelope messages `WebSocketManager` dispatches
(`{"channel": ..., "type": "snapshot"|"update", "data": [...]}`) into domain
events and fans them out to subscribed systems:
- `executions`/`balances` (private, account-wide) -> ExecutionReport / AccountPosition
- `ticker` (public, per-symbol) -> TickerUpdate
- `ohlc` (public, per-symbol) -> raw kline entries

Kraken has no all-symbols ticker stream, so unlike the old Binance handlers
this module no longer produces an `AllTickers`/`ALL_TICKERS` broadcast - see
the "ALL"-ticker subscription gap noted in CLAUDE.md.
"""

import logging
from typing import Callable, Dict, List, Optional

from src.domain.constants import (
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_EXPIRED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_NEW,
    ORDER_STATUS_PARTIALLY_FILLED,
)
from src.domain.enums import EventName, SubscriptionTarget, SubscriptionType
from src.domain.orders import (
    AccountPosition,
    Balance,
    ErrorMessage,
    Event,
    ExecutionReport,
    TickerUpdate,
)
from src.domain.subscriptions import SubscriptionInfo

logger = logging.getLogger(__name__)


def _derive_order_status(order_status: str, exec_type: str, cum_qty: float) -> str:
    """Map Kraken's `order_status` (+ `exec_type`/`cum_qty` for the ambiguous
    "open" case) to this codebase's exchange-agnostic ORDER_STATUS_* constants.

    Kraken sends "open" for both NEW and PARTIALLY_FILLED orders; the two are
    only distinguishable via cum_qty > 0 on a "trade" execution (CLAUDE.md,
    "Kraken WS - key differences from Binance", #3).
    """
    if order_status == "open":
        if exec_type == "trade" and cum_qty > 0:
            return ORDER_STATUS_PARTIALLY_FILLED
        return ORDER_STATUS_NEW
    if order_status == "filled":
        return ORDER_STATUS_FILLED
    if order_status == "canceled":
        return ORDER_STATUS_CANCELED
    if order_status == "expired":
        return ORDER_STATUS_EXPIRED

    logger.warning(
        "Unrecognized Kraken order_status %r; defaulting to NEW", order_status
    )
    return ORDER_STATUS_NEW


def create_execution_report(msg: Dict) -> ExecutionReport:
    """Create an ExecutionReport from a single Kraken `executions` channel data entry."""
    cum_qty = float(msg.get("cum_qty", 0) or 0)
    exec_type = msg.get("exec_type", "")
    fees = msg.get("fees") or []
    fee = fees[0] if fees else {}

    return ExecutionReport(
        symbol=msg.get("symbol", ""),
        order_id=str(msg.get("order_id", "")),
        side=msg.get("side", "").upper(),
        order_type=msg.get("order_type", "").upper(),
        time_in_force=msg.get("time_in_force", "").upper(),
        quantity=float(msg.get("order_qty", 0) or 0),
        price=float(msg.get("limit_price") or msg.get("price") or 0),
        current_execution_type=exec_type,
        current_order_status=_derive_order_status(
            msg.get("order_status", ""), exec_type, cum_qty
        ),
        last_executed_quantity=float(msg.get("last_qty", 0) or 0),
        cumulative_filled_quantity=cum_qty,
        last_executed_price=float(msg.get("last_price", 0) or 0),
        commission_amount=(
            float(fee["asset_qty"]) if fee.get("asset_qty") is not None else None
        ),
        commission_asset=fee.get("asset"),
    )


def create_account_position(msg: Dict) -> AccountPosition:
    """Create an AccountPosition from a Kraken `balances` channel message.

    Caveat: Kraken v2's balances channel is documented as reporting a total
    `balance` per asset plus `hold_trade` (amount held by open orders), with
    free = balance - hold_trade. As with the `instrument` channel mapping
    (see CLAUDE.md), this has not been verified against a live connection -
    this codebase's test suite always mocks the WebSocket layer.
    """
    balances = []
    for entry in msg.get("data") or []:
        total = float(entry.get("balance", 0) or 0)
        hold = float(entry.get("hold_trade", 0) or 0)
        balances.append(
            Balance(
                coin=entry.get("asset", ""),
                free=max(total - hold, 0.0),
                locked=hold,
            )
        )
    return AccountPosition(balances=balances)


def handle_user_message(
    msg: Dict,
    subscriptions: Dict[str, List[SubscriptionInfo]],
    websocket_error_callback: Optional[Callable[..., None]] = None,
) -> None:
    """Handle a Kraken `executions`/`balances` channel message.

    Args:
        msg: A single channel message: {"channel": ..., "type": ..., "data": [...]}
        subscriptions: Dict mapping system_id to list of SubscriptionInfo
        websocket_error_callback: Optional callback for handling websocket errors
    """
    channel = msg.get("channel")
    data = msg.get("data")

    if not isinstance(data, list):
        logger.warning("Kraken user message missing/invalid 'data': %s", msg)
        if websocket_error_callback:
            websocket_error_callback({"type": "UserStreamError", "msg": msg})
        for _, subscription_list in subscriptions.items():
            for subscription_info in subscription_list:
                if subscription_info.target in [
                    SubscriptionTarget.FRONTEND,
                    SubscriptionTarget.PORTFOLIO,
                ]:
                    subscription_info.queue.put_nowait(
                        Event(name=EventName.ERROR, content=ErrorMessage(msg=msg))
                    )
        return

    if channel == "executions":
        for entry in data:
            symbol = entry.get("symbol")
            execution_report = create_execution_report(entry)
            for _, subscription_list in subscriptions.items():
                for subscription_info in subscription_list:
                    if (
                        subscription_info.data_type == SubscriptionType.USER
                        and subscription_info.symbol == symbol
                    ):
                        subscription_info.queue.put_nowait(
                            Event(
                                name=EventName.EXECUTION_REPORT,
                                content=execution_report,
                            )
                        )

    elif channel == "balances":
        account_position = create_account_position(msg)
        for _, subscription_list in subscriptions.items():
            for subscription_info in subscription_list:
                if subscription_info.target == SubscriptionTarget.PORTFOLIO:
                    subscription_info.queue.put_nowait(
                        Event(
                            name=EventName.ACCOUNT_POSITION,
                            content=account_position,
                        )
                    )

    else:
        logger.debug("Unhandled user channel message: %s", msg)


def handle_ticker_message(
    msg: Dict,
    subscriptions: Dict[str, List[SubscriptionInfo]],
    last_ticker_time_callback: Optional[Callable[[], None]] = None,
    websocket_error_callback: Optional[Callable[..., None]] = None,
) -> None:
    """Handle a Kraken `ticker` channel message.

    Args:
        msg: A single channel message: {"channel": "ticker", "type": ..., "data": [...]}
        subscriptions: Dict mapping system_id to list of SubscriptionInfo
        last_ticker_time_callback: Optional callback to update last ticker timestamp
        websocket_error_callback: Optional callback for handling websocket errors
    """
    if last_ticker_time_callback:
        last_ticker_time_callback()

    data = msg.get("data")
    if not isinstance(data, list):
        logger.warning("Unexpected ticker message format: %s", msg)
        if websocket_error_callback:
            websocket_error_callback({"type": "TickerStreamError", "msg": str(msg)})
        return

    for ticker in data:
        symbol = ticker.get("symbol")
        if not symbol:
            logger.warning("Ticker without symbol: %s", ticker)
            continue

        ticker_update = TickerUpdate(
            symbol=symbol,
            last_price=float(ticker.get("last", 0) or 0),
            best_bid_price=float(ticker.get("bid", 0) or 0),
            best_ask_price=float(ticker.get("ask", 0) or 0),
            high_price=float(ticker.get("high", 0) or 0),
            low_price=float(ticker.get("low", 0) or 0),
            volume=float(ticker.get("volume", 0) or 0),
        )

        for _, subscription_list in subscriptions.items():
            for subscription_info in subscription_list:
                if (
                    subscription_info.data_type == SubscriptionType.PRICE
                    and subscription_info.symbol == symbol
                ):
                    subscription_info.queue.put_nowait(
                        Event(name=EventName.TICKER, content=ticker_update)
                    )


def handle_kline_message(
    msg: Dict,
    subscriptions: Dict[str, List[SubscriptionInfo]],
) -> None:
    """Handle a Kraken `ohlc` channel message.

    Args:
        msg: A single channel message: {"channel": "ohlc", "type": ..., "data": [...]}
        subscriptions: Dict mapping system_id to list of SubscriptionInfo
    """
    data = msg.get("data")
    if not isinstance(data, list):
        logger.warning("Unexpected ohlc message format: %s", msg)
        return

    for entry in data:
        symbol = entry.get("symbol")
        if not symbol:
            logger.warning("Kline entry without symbol: %s", entry)
            continue

        for _, subscription_list in subscriptions.items():
            for subscription_info in subscription_list:
                if (
                    subscription_info.data_type == SubscriptionType.KLINE
                    and subscription_info.symbol == symbol
                ):
                    # Forward the raw Kraken ohlc entry
                    subscription_info.queue.put_nowait(entry)
