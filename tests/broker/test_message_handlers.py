"""Unit tests for Kraken WS v2 message handling (src/broker/message_handlers.py)."""

import queue

from src.broker.message_handlers import (
    create_account_position,
    create_execution_report,
    handle_kline_message,
    handle_ticker_message,
    handle_user_message,
)
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
    ExecutionReport,
    TickerUpdate,
)
from src.domain.subscriptions import SubscriptionInfo


def _sub(data_type, symbol, target):
    q: "queue.Queue" = queue.Queue()
    return (
        SubscriptionInfo(data_type=data_type, symbol=symbol, target=target, queue=q),
        q,
    )


# ---------------------------------------------------------------------------
# create_execution_report / order status derivation
# ---------------------------------------------------------------------------


class TestCreateExecutionReport:
    def test_open_no_fill_is_new(self):
        report = create_execution_report(
            {
                "symbol": "BTC/USDC",
                "order_id": "OB5VMB-B4U2U-DJD7WS",
                "side": "buy",
                "order_type": "limit",
                "order_status": "open",
                "exec_type": "pending",
                "cum_qty": 0,
            }
        )
        assert report.current_order_status == ORDER_STATUS_NEW
        assert report.symbol == "BTC/USDC"
        assert report.order_id == "OB5VMB-B4U2U-DJD7WS"
        assert report.side == "BUY"
        assert report.order_type == "LIMIT"

    def test_open_with_trade_and_cum_qty_is_partially_filled(self):
        report = create_execution_report(
            {
                "order_status": "open",
                "exec_type": "trade",
                "cum_qty": 0.5,
            }
        )
        assert report.current_order_status == ORDER_STATUS_PARTIALLY_FILLED

    def test_open_with_cum_qty_but_no_trade_exec_type_is_new(self):
        # cum_qty > 0 alone isn't enough - must be a "trade" execution too.
        report = create_execution_report(
            {
                "order_status": "open",
                "exec_type": "pending",
                "cum_qty": 0.5,
            }
        )
        assert report.current_order_status == ORDER_STATUS_NEW

    def test_filled(self):
        report = create_execution_report({"order_status": "filled", "cum_qty": 1.0})
        assert report.current_order_status == ORDER_STATUS_FILLED

    def test_canceled(self):
        report = create_execution_report({"order_status": "canceled"})
        assert report.current_order_status == ORDER_STATUS_CANCELED

    def test_expired(self):
        report = create_execution_report({"order_status": "expired"})
        assert report.current_order_status == ORDER_STATUS_EXPIRED

    def test_unrecognized_status_defaults_to_new(self):
        report = create_execution_report({"order_status": "something_new"})
        assert report.current_order_status == ORDER_STATUS_NEW

    def test_execution_type_passed_through_raw(self):
        report = create_execution_report(
            {"order_status": "filled", "exec_type": "trade"}
        )
        assert report.current_execution_type == "trade"

    def test_quantities_and_prices(self):
        report = create_execution_report(
            {
                "order_qty": 2.0,
                "limit_price": 100.5,
                "last_qty": 1.0,
                "last_price": 99.9,
                "cum_qty": 1.0,
            }
        )
        assert report.quantity == 2.0
        assert report.price == 100.5
        assert report.last_executed_quantity == 1.0
        assert report.last_executed_price == 99.9
        assert report.cumulative_filled_quantity == 1.0

    def test_price_falls_back_to_plain_price_field(self):
        report = create_execution_report({"price": 42.0})
        assert report.price == 42.0

    def test_commission_from_first_fee_entry(self):
        report = create_execution_report(
            {
                "fees": [
                    {"asset": "USDC", "asset_qty": 0.01},
                    {"asset": "BTC", "asset_qty": 0.0},
                ]
            }
        )
        assert report.commission_amount == 0.01
        assert report.commission_asset == "USDC"

    def test_no_fees_leaves_commission_none(self):
        report = create_execution_report({})
        assert report.commission_amount is None
        assert report.commission_asset is None


# ---------------------------------------------------------------------------
# create_account_position
# ---------------------------------------------------------------------------


class TestCreateAccountPosition:
    def test_free_is_balance_minus_hold(self):
        position = create_account_position(
            {
                "channel": "balances",
                "data": [{"asset": "USDC", "balance": 100.0, "hold_trade": 30.0}],
            }
        )
        assert position.balances == [Balance(coin="USDC", free=70.0, locked=30.0)]

    def test_missing_hold_trade_defaults_to_fully_free(self):
        position = create_account_position(
            {"channel": "balances", "data": [{"asset": "BTC", "balance": 1.5}]}
        )
        assert position.balances[0].coin == "BTC"
        assert position.balances[0].free == 1.5
        assert position.balances[0].locked == 0.0

    def test_no_data_yields_empty_balances(self):
        position = create_account_position({"channel": "balances"})
        assert position.balances == []


# ---------------------------------------------------------------------------
# handle_user_message
# ---------------------------------------------------------------------------


class TestHandleUserMessage:
    def test_executions_routed_by_symbol_to_user_subscribers(self):
        sub, q = _sub(SubscriptionType.USER, "BTC/USDC", SubscriptionTarget.BACKEND)
        subscriptions = {"hp1": [sub]}

        handle_user_message(
            {
                "channel": "executions",
                "type": "update",
                "data": [{"symbol": "BTC/USDC", "order_status": "filled"}],
            },
            subscriptions,
        )

        event = q.get_nowait()
        assert event.name == EventName.EXECUTION_REPORT
        assert isinstance(event.content, ExecutionReport)
        assert event.content.current_order_status == ORDER_STATUS_FILLED

    def test_executions_not_delivered_to_mismatched_symbol(self):
        sub, q = _sub(SubscriptionType.USER, "ETH/USDC", SubscriptionTarget.BACKEND)
        subscriptions = {"hp1": [sub]}

        handle_user_message(
            {
                "channel": "executions",
                "data": [{"symbol": "BTC/USDC", "order_status": "filled"}],
            },
            subscriptions,
        )

        assert q.empty()

    def test_balances_routed_to_portfolio_target_only(self):
        portfolio_sub, portfolio_q = _sub(
            SubscriptionType.USER, "ALL", SubscriptionTarget.PORTFOLIO
        )
        backend_sub, backend_q = _sub(
            SubscriptionType.USER, "BTC/USDC", SubscriptionTarget.BACKEND
        )
        subscriptions = {"portfolio": [portfolio_sub], "hp1": [backend_sub]}

        handle_user_message(
            {
                "channel": "balances",
                "data": [{"asset": "USDC", "balance": 100.0}],
            },
            subscriptions,
        )

        event = portfolio_q.get_nowait()
        assert event.name == EventName.ACCOUNT_POSITION
        assert isinstance(event.content, AccountPosition)
        assert backend_q.empty()

    def test_malformed_data_reports_error_and_notifies_frontend_and_portfolio(self):
        frontend_sub, frontend_q = _sub(
            SubscriptionType.USER, "ALL", SubscriptionTarget.FRONTEND
        )
        backend_sub, backend_q = _sub(
            SubscriptionType.USER, "BTC/USDC", SubscriptionTarget.BACKEND
        )
        subscriptions = {"frontend": [frontend_sub], "hp1": [backend_sub]}
        errors = []

        handle_user_message(
            {"channel": "executions", "data": "not-a-list"},
            subscriptions,
            websocket_error_callback=errors.append,
        )

        assert len(errors) == 1
        event = frontend_q.get_nowait()
        assert event.name == EventName.ERROR
        assert isinstance(event.content, ErrorMessage)
        assert backend_q.empty()

    def test_unknown_channel_is_ignored(self):
        sub, q = _sub(SubscriptionType.USER, "ALL", SubscriptionTarget.PORTFOLIO)
        subscriptions = {"portfolio": [sub]}

        handle_user_message({"channel": "heartbeat", "data": []}, subscriptions)

        assert q.empty()


# ---------------------------------------------------------------------------
# handle_ticker_message
# ---------------------------------------------------------------------------


class TestHandleTickerMessage:
    def test_ticker_routed_by_symbol(self):
        sub, q = _sub(SubscriptionType.PRICE, "BTC/USDC", SubscriptionTarget.BACKEND)
        subscriptions = {"hp1": [sub]}

        handle_ticker_message(
            {
                "channel": "ticker",
                "type": "update",
                "data": [
                    {
                        "symbol": "BTC/USDC",
                        "bid": 100.0,
                        "ask": 101.0,
                        "last": 100.5,
                        "high": 105.0,
                        "low": 95.0,
                        "volume": 10.0,
                    }
                ],
            },
            subscriptions,
        )

        event = q.get_nowait()
        assert event.name == EventName.TICKER
        assert event.content == TickerUpdate(
            symbol="BTC/USDC",
            last_price=100.5,
            best_bid_price=100.0,
            best_ask_price=101.0,
            high_price=105.0,
            low_price=95.0,
            volume=10.0,
        )

    def test_ticker_not_delivered_to_mismatched_symbol(self):
        sub, q = _sub(SubscriptionType.PRICE, "ETH/USDC", SubscriptionTarget.BACKEND)
        subscriptions = {"hp1": [sub]}

        handle_ticker_message(
            {"channel": "ticker", "data": [{"symbol": "BTC/USDC", "last": 100.5}]},
            subscriptions,
        )

        assert q.empty()

    def test_last_ticker_time_callback_invoked(self):
        calls = []
        handle_ticker_message(
            {"channel": "ticker", "data": []},
            {},
            last_ticker_time_callback=lambda: calls.append(1),
        )
        assert calls == [1]

    def test_malformed_message_invokes_error_callback(self):
        errors = []
        handle_ticker_message(
            {"channel": "ticker", "data": "oops"},
            {},
            websocket_error_callback=errors.append,
        )
        assert len(errors) == 1
        assert errors[0]["type"] == "TickerStreamError"

    def test_ticker_entry_without_symbol_is_skipped(self):
        sub, q = _sub(SubscriptionType.PRICE, "BTC/USDC", SubscriptionTarget.BACKEND)
        subscriptions = {"hp1": [sub]}

        handle_ticker_message(
            {"channel": "ticker", "data": [{"last": 100.5}]},
            subscriptions,
        )

        assert q.empty()


# ---------------------------------------------------------------------------
# handle_kline_message
# ---------------------------------------------------------------------------


class TestHandleKlineMessage:
    def test_kline_routed_by_symbol(self):
        sub, q = _sub(SubscriptionType.KLINE, "BTC/USDC", SubscriptionTarget.BACKEND)
        subscriptions = {"buy_dip": [sub]}
        entry = {"symbol": "BTC/USDC", "open": 100.0, "close": 101.0}

        handle_kline_message(
            {"channel": "ohlc", "type": "update", "data": [entry]}, subscriptions
        )

        assert q.get_nowait() == entry

    def test_kline_not_delivered_to_mismatched_symbol(self):
        sub, q = _sub(SubscriptionType.KLINE, "ETH/USDC", SubscriptionTarget.BACKEND)
        subscriptions = {"buy_dip": [sub]}

        handle_kline_message(
            {"channel": "ohlc", "data": [{"symbol": "BTC/USDC"}]}, subscriptions
        )

        assert q.empty()

    def test_malformed_message_is_ignored(self):
        # Should not raise.
        handle_kline_message({"channel": "ohlc", "data": "oops"}, {})
