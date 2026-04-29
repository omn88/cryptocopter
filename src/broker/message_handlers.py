"""Message handlers for processing WebSocket messages from Binance.

This module contains functions to handle different types of WebSocket messages:
- User data stream messages (execution reports, balance updates)
- Ticker stream messages (price updates for all symbols)
"""

import logging
from typing import Dict, List

from src.common.identifiers import (
    Event,
    EventName,
    ErrorMessage,
    ExecutionReport,
    AllTickers,
    TickerUpdate,
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
    AccountPosition,
    Balance,
)

logger = logging.getLogger(__name__)


def handle_user_message(
    msg: Dict,
    subscriptions: Dict[str, List[SubscriptionInfo]],
    websocket_error_callback=None,
) -> None:
    """Handle user-specific WebSocket messages.

    Args:
        msg: The WebSocket message dict
        subscriptions: Dict mapping system_id to list of SubscriptionInfo
        websocket_error_callback: Optional callback for handling websocket errors
    """
    event_type = msg.get("e")

    # Handle internal 'error' messages injected by python-binance
    if event_type == EventName.ERROR.value:
        logger.warning("Received internal error event: %s", msg)

        # Call error callback if provided
        if websocket_error_callback:
            websocket_error_callback(msg)

        # Distribute error to subscribed systems
        for _, subscription_list in subscriptions.items():
            for subscription_info in subscription_list:
                if subscription_info.target in [
                    SubscriptionTarget.FRONTEND,
                    SubscriptionTarget.PORTFOLIO,
                ]:
                    subscription_info.queue.put_nowait(
                        Event(name=EventName.ERROR, content=ErrorMessage(msg=msg))
                    )
        return  # Exit early, do not continue processing

    symbol = msg.get("s")

    # Handle execution reports (order updates)
    if event_type == EventName.EXECUTION_REPORT.value:
        execution_report = create_execution_report(msg)
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

    # Handle account position updates (balance changes)
    if event_type == EventName.ACCOUNT_POSITION.value:
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


def handle_ticker_message(
    msg: List[Dict],
    subscriptions: Dict[str, List[SubscriptionInfo]],
    last_ticker_time_callback=None,
    websocket_error_callback=None,
) -> None:
    """Handle all market ticker WebSocket messages.

    Args:
        msg: List of ticker data dicts for all symbols
        subscriptions: Dict mapping system_id to list of SubscriptionInfo
        last_ticker_time_callback: Optional callback to update last ticker timestamp
        websocket_error_callback: Optional callback for handling websocket errors
    """
    # Update last ticker timestamp if callback provided
    if last_ticker_time_callback:
        last_ticker_time_callback()

    # Handle control frames
    if isinstance(msg, str):
        logger.debug("Received control frame: %s", msg)
        return

    # Validate message format
    if not isinstance(msg, list):
        logger.warning("Unexpected message format(%s): %s", type(msg), msg)
        if websocket_error_callback:
            websocket_error_callback({"type": "TickerStreamError", "m": str(msg)})
        return

    # Send all tickers to systems subscribed to "ALL"
    for _, subscription_list in subscriptions.items():
        for subscription_info in subscription_list:
            if subscription_info.target in [
                SubscriptionTarget.FRONTEND,
                SubscriptionTarget.PORTFOLIO,
            ]:
                if subscription_info.symbol == "ALL":
                    subscription_info.queue.put_nowait(
                        Event(name=EventName.ALL_TICKERS, content=AllTickers(msg=msg))
                    )

    # Process individual ticker updates
    for ticker in msg:
        symbol = ticker.get("s")
        if not symbol:
            logger.warning("Ticker without symbol: %s", ticker)
            continue

        # Extract ticker fields
        ticker_update = TickerUpdate(
            symbol=symbol,
            last_price=float(ticker.get("c", 0)),
            best_bid_price=float(ticker.get("b", 0)),
            best_ask_price=float(ticker.get("a", 0)),
            high_price=float(ticker.get("h", 0)),
            low_price=float(ticker.get("l", 0)),
            volume=float(ticker.get("v", 0)),
        )

        # Send symbol-specific updates
        for _, subscription_list in subscriptions.items():
            for subscription_info in subscription_list:
                if (
                    subscription_info.data_type == SubscriptionType.PRICE
                    and subscription_info.symbol == symbol
                ):
                    subscription_info.queue.put_nowait(
                        Event(name=EventName.TICKER, content=ticker_update)
                    )


def create_execution_report(msg: Dict) -> ExecutionReport:
    """Create ExecutionReport from WebSocket message."""
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


def create_account_position(msg: Dict) -> AccountPosition:
    """Create AccountPosition from WebSocket message."""
    balances = [
        Balance(coin=b["a"], free=float(b["f"]), locked=float(b["l"])) for b in msg["B"]
    ]
    return AccountPosition(
        event_time=msg["E"],
        last_update_time=msg["u"],
        balances=balances,
    )


def handle_kline_message(
    msg: Dict,
    subscriptions: Dict[str, List[SubscriptionInfo]],
) -> None:
    """Handle kline (candlestick) WebSocket messages.

    Args:
        msg: The kline WebSocket message dict
        subscriptions: Dict mapping system_id to list of SubscriptionInfo
    """
    event_type = msg.get("e")

    if event_type != "kline":
        return

    symbol = msg.get("s")
    if not symbol:
        logger.warning("Kline message without symbol: %s", msg)
        return

    # Forward to systems subscribed to KLINE for this symbol
    for _, subscription_list in subscriptions.items():
        for subscription_info in subscription_list:
            if (
                subscription_info.data_type == SubscriptionType.KLINE
                and subscription_info.symbol == symbol
            ):
                # Send the raw kline message
                subscription_info.queue.put_nowait(msg)
