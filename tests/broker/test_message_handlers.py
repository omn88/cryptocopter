"""Comprehensive tests for broker message handlers.

This module tests the parsing and validation of WebSocket messages from Binance:
- Execution reports (order updates)
- Ticker updates (price data)
- Account position updates
- Error handling and validation
"""

import logging
import queue
from typing import Dict, List
from unittest.mock import MagicMock, patch, call
import pytest

from src.broker.message_handlers import (
    handle_user_message,
    handle_ticker_message,
    create_execution_report,
    create_account_position,
)
from src.common.identifiers import (
    EventName,
    SubscriptionInfo,
    SubscriptionType,
    SubscriptionTarget,
    ExecutionReport,
    AccountPosition,
    Balance,
)


# ============================================================================
# Fixtures - Sample Binance API Messages
# ============================================================================

@pytest.fixture
def execution_report_new():
    """Sample execution report for a new order."""
    return {
        "e": "executionReport",
        "s": "BTCUSDC",
        "c": "test_client_order_id_123",
        "S": "BUY",
        "o": "LIMIT",
        "f": "GTC",
        "q": "0.5",
        "p": "50000.00",
        "P": "0.00",
        "F": "0.00",
        "g": -1,
        "C": "",
        "x": "NEW",
        "X": "NEW",
        "r": "NONE",
        "i": 123456789,
        "l": "0.00",
        "z": "0.00",
        "L": "0.00",
        "n": None,
        "N": None,
        "T": 1640000000000,
        "t": -1,
        "I": 123456,
        "w": True,
        "m": False,
        "M": False,
        "O": 1640000000000,
        "Z": "0.00",
        "Y": "0.00",
        "Q": "0.00",
        "W": 1640000000000,
        "V": "NONE",
    }


@pytest.fixture
def execution_report_partial_fill():
    """Sample execution report for a partially filled order."""
    return {
        "e": "executionReport",
        "s": "ETHUSDC",
        "c": "test_order_456",
        "S": "SELL",
        "o": "LIMIT",
        "f": "GTC",
        "q": "2.0",
        "p": "3000.00",
        "P": "0.00",
        "F": "0.00",
        "g": -1,
        "C": "",
        "x": "TRADE",
        "X": "PARTIALLY_FILLED",
        "r": "NONE",
        "i": 987654321,
        "l": "0.5",
        "z": "1.0",
        "L": "3000.00",
        "n": "0.001",
        "N": "USDC",
        "T": 1640000100000,
        "t": 111222,
        "I": 123457,
        "w": True,
        "m": False,
        "M": False,
        "O": 1640000000000,
        "Z": "3000.00",
        "Y": "1500.00",
        "Q": "0.00",
        "W": 1640000000000,
        "V": "NONE",
    }


@pytest.fixture
def execution_report_filled():
    """Sample execution report for a filled order."""
    return {
        "e": "executionReport",
        "s": "ADAUSDC",
        "c": "test_order_789",
        "S": "BUY",
        "o": "LIMIT",
        "f": "GTC",
        "q": "100.0",
        "p": "0.50",
        "P": "0.00",
        "F": "0.00",
        "g": -1,
        "C": "",
        "x": "TRADE",
        "X": "FILLED",
        "r": "NONE",
        "i": 555666777,
        "l": "100.0",
        "z": "100.0",
        "L": "0.50",
        "n": "0.05",
        "N": "USDC",
        "T": 1640000200000,
        "t": 333444,
        "I": 123458,
        "w": False,
        "m": True,
        "M": False,
        "O": 1640000000000,
        "Z": "50.00",
        "Y": "50.00",
        "Q": "0.00",
        "W": 1640000000000,
        "V": "NONE",
    }


@pytest.fixture
def execution_report_cancelled():
    """Sample execution report for a cancelled order."""
    return {
        "e": "executionReport",
        "s": "SOLUSDC",
        "c": "test_order_cancelled",
        "S": "SELL",
        "o": "LIMIT",
        "f": "GTC",
        "q": "10.0",
        "p": "100.00",
        "P": "0.00",
        "F": "0.00",
        "g": -1,
        "C": "",
        "x": "CANCELED",
        "X": "CANCELED",
        "r": "NONE",
        "i": 999888777,
        "l": "0.00",
        "z": "0.00",
        "L": "0.00",
        "n": None,
        "N": None,
        "T": 1640000300000,
        "t": -1,
        "I": 123459,
        "w": False,
        "m": False,
        "M": False,
        "O": 1640000000000,
        "Z": "0.00",
        "Y": "0.00",
        "Q": "0.00",
        "W": 1640000000000,
        "V": "NONE",
    }


@pytest.fixture
def ticker_message():
    """Sample ticker message with multiple symbols."""
    return [
        {
            "s": "BTCUSDC",
            "c": "50000.00",
            "b": "49999.00",
            "a": "50001.00",
            "h": "51000.00",
            "l": "49000.00",
            "v": "100.5",
        },
        {
            "s": "ETHUSDC",
            "c": "3000.00",
            "b": "2999.50",
            "a": "3000.50",
            "h": "3100.00",
            "l": "2900.00",
            "v": "500.25",
        },
    ]


@pytest.fixture
def account_position_message():
    """Sample account position update message."""
    return {
        "e": "outboundAccountPosition",
        "E": 1640000000000,
        "u": 1640000000000,
        "B": [
            {"a": "BTC", "f": "1.5", "l": "0.5"},
            {"a": "USDC", "f": "10000.0", "l": "5000.0"},
            {"a": "ETH", "f": "10.0", "l": "2.0"},
        ],
    }


@pytest.fixture
def error_message():
    """Sample error message."""
    return {"e": "error", "m": "Connection lost"}


# ============================================================================
# Test Execution Report Parsing
# ============================================================================


class TestExecutionReportParsing:
    """Tests for execution report message parsing."""

    def test_create_execution_report_new_order(self, execution_report_new):
        """Test parsing a new order execution report."""
        report = create_execution_report(execution_report_new)

        assert isinstance(report, ExecutionReport)
        assert report.symbol == "BTCUSDC"
        assert report.client_order_id == "test_client_order_id_123"
        assert report.side == "BUY"
        assert report.order_type == "LIMIT"
        assert report.quantity == 0.5
        assert report.price == 50000.00
        assert report.current_order_status == "NEW"
        assert report.current_execution_type == "NEW"
        assert report.order_id == 123456789
        assert report.cumulative_filled_quantity == 0.0

    def test_create_execution_report_partial_fill(self, execution_report_partial_fill):
        """Test parsing a partially filled order execution report."""
        report = create_execution_report(execution_report_partial_fill)

        assert report.symbol == "ETHUSDC"
        assert report.side == "SELL"
        assert report.current_order_status == "PARTIALLY_FILLED"
        assert report.current_execution_type == "TRADE"
        assert report.quantity == 2.0
        assert report.cumulative_filled_quantity == 1.0
        assert report.last_executed_quantity == 0.5
        assert report.last_executed_price == 3000.00
        assert report.commission_amount == 0.001
        assert report.commission_asset == "USDC"

    def test_create_execution_report_filled(self, execution_report_filled):
        """Test parsing a fully filled order execution report."""
        report = create_execution_report(execution_report_filled)

        assert report.symbol == "ADAUSDC"
        assert report.side == "BUY"
        assert report.current_order_status == "FILLED"
        assert report.quantity == 100.0
        assert report.cumulative_filled_quantity == 100.0
        assert report.is_order_working is False
        assert report.is_trade_maker_side is True

    def test_create_execution_report_cancelled(self, execution_report_cancelled):
        """Test parsing a cancelled order execution report."""
        report = create_execution_report(execution_report_cancelled)

        assert report.symbol == "SOLUSDC"
        assert report.current_order_status == "CANCELED"
        assert report.current_execution_type == "CANCELED"
        assert report.cumulative_filled_quantity == 0.0

    @pytest.mark.parametrize(
        "field,value",
        [
            ("symbol", "BTCUSDC"),
            ("side", "BUY"),
            ("order_type", "LIMIT"),
            ("current_order_status", "NEW"),
            ("order_id", 123456789),
        ],
    )
    def test_execution_report_field_extraction(
        self, execution_report_new, field, value
    ):
        """Test extraction of specific fields from execution report."""
        report = create_execution_report(execution_report_new)
        assert getattr(report, field) == value

    def test_execution_report_numeric_conversion(self, execution_report_new):
        """Test numeric field conversion in execution report."""
        report = create_execution_report(execution_report_new)

        # Verify string to float conversion
        assert isinstance(report.quantity, float)
        assert isinstance(report.price, float)
        assert isinstance(report.last_executed_quantity, float)
        assert isinstance(report.cumulative_filled_quantity, float)

        # Verify string to int conversion
        assert isinstance(report.order_id, int)


# ============================================================================
# Test Ticker Message Parsing
# ============================================================================


class TestTickerMessageParsing:
    """Tests for ticker message parsing."""

    def test_ticker_message_parsing(self, ticker_message):
        """Test basic ticker message parsing."""
        test_queue = queue.Queue()
        subscriptions = {
            "test_system": [
                SubscriptionInfo(
                    data_type=SubscriptionType.PRICE,
                    symbol="BTCUSDC",
                    target=SubscriptionTarget.FRONTEND,
                    queue=test_queue,
                )
            ]
        }

        handle_ticker_message(ticker_message, subscriptions)

        # Verify message was dispatched
        assert not test_queue.empty()
        event = test_queue.get()
        assert event.name == EventName.TICKER
        assert event.content.symbol == "BTCUSDC"
        assert event.content.last_price == 50000.00

    def test_ticker_numeric_conversion(self, ticker_message):
        """Test numeric conversion in ticker updates."""
        test_queue = queue.Queue()
        subscriptions = {
            "test_system": [
                SubscriptionInfo(
                    data_type=SubscriptionType.PRICE,
                    symbol="ETHUSDC",
                    target=SubscriptionTarget.FRONTEND,
                    queue=test_queue,
                )
            ]
        }

        handle_ticker_message(ticker_message, subscriptions)

        event = test_queue.get()
        ticker = event.content

        # All price fields should be floats
        assert isinstance(ticker.last_price, float)
        assert isinstance(ticker.best_bid_price, float)
        assert isinstance(ticker.best_ask_price, float)
        assert isinstance(ticker.high_price, float)
        assert isinstance(ticker.low_price, float)
        assert isinstance(ticker.volume, float)

    def test_ticker_all_symbols(self, ticker_message):
        """Test ALL symbol subscription receives all tickers."""
        test_queue = queue.Queue()
        subscriptions = {
            "test_system": [
                SubscriptionInfo(
                    data_type=SubscriptionType.PRICE,
                    symbol="ALL",
                    target=SubscriptionTarget.FRONTEND,
                    queue=test_queue,
                )
            ]
        }

        handle_ticker_message(ticker_message, subscriptions)

        # Should receive ALL_TICKERS event
        event = test_queue.get()
        assert event.name == EventName.ALL_TICKERS
        assert len(event.content.msg) == 2

    def test_ticker_missing_symbol(self, caplog):
        """Test handling of ticker without symbol field."""
        malformed_ticker = [{"c": "50000.00", "b": "49999.00"}]  # Missing 's' field

        test_queue = queue.Queue()
        subscriptions = {
            "test_system": [
                SubscriptionInfo(
                    data_type=SubscriptionType.PRICE,
                    symbol="BTCUSDC",
                    target=SubscriptionTarget.FRONTEND,
                    queue=test_queue,
                )
            ]
        }

        with caplog.at_level(logging.WARNING):
            handle_ticker_message(malformed_ticker, subscriptions)

        # Should log warning about missing symbol
        assert "Ticker without symbol" in caplog.text

    def test_ticker_default_values_for_missing_fields(self):
        """Test ticker parsing with missing optional fields."""
        ticker_minimal = [{"s": "BTCUSDC"}]  # Only symbol, no price fields

        test_queue = queue.Queue()
        subscriptions = {
            "test_system": [
                SubscriptionInfo(
                    data_type=SubscriptionType.PRICE,
                    symbol="BTCUSDC",
                    target=SubscriptionTarget.FRONTEND,
                    queue=test_queue,
                )
            ]
        }

        handle_ticker_message(ticker_minimal, subscriptions)

        event = test_queue.get()
        ticker = event.content

        # Should default to 0 for missing fields
        assert ticker.last_price == 0.0
        assert ticker.best_bid_price == 0.0
        assert ticker.best_ask_price == 0.0

    def test_ticker_malformed_price_data(self):
        """Test handling of non-numeric price strings."""
        ticker_bad_price = [
            {"s": "BTCUSDC", "c": "invalid_price", "b": "49999.00", "a": "50001.00"}
        ]

        test_queue = queue.Queue()
        subscriptions = {
            "test_system": [
                SubscriptionInfo(
                    data_type=SubscriptionType.PRICE,
                    symbol="BTCUSDC",
                    target=SubscriptionTarget.FRONTEND,
                    queue=test_queue,
                )
            ]
        }

        # Should raise ValueError when trying to convert invalid price
        with pytest.raises(ValueError):
            handle_ticker_message(ticker_bad_price, subscriptions)


# ============================================================================
# Test Account Position Parsing
# ============================================================================


class TestAccountPositionParsing:
    """Tests for account position message parsing."""

    def test_create_account_position(self, account_position_message):
        """Test parsing account position update."""
        position = create_account_position(account_position_message)

        assert isinstance(position, AccountPosition)
        assert position.event_time == 1640000000000
        assert position.last_update_time == 1640000000000
        assert len(position.balances) == 3

    def test_account_position_balance_parsing(self, account_position_message):
        """Test parsing of individual balances."""
        position = create_account_position(account_position_message)

        # Check first balance (BTC)
        btc_balance = position.balances[0]
        assert isinstance(btc_balance, Balance)
        assert btc_balance.coin == "BTC"
        assert btc_balance.free == 1.5
        assert btc_balance.locked == 0.5

        # Check second balance (USDC)
        usdc_balance = position.balances[1]
        assert usdc_balance.coin == "USDC"
        assert usdc_balance.free == 10000.0
        assert usdc_balance.locked == 5000.0

    def test_account_position_numeric_conversion(self, account_position_message):
        """Test numeric conversion in balance fields."""
        position = create_account_position(account_position_message)

        for balance in position.balances:
            assert isinstance(balance.free, float)
            assert isinstance(balance.locked, float)


# ============================================================================
# Test Message Dispatch Logic
# ============================================================================


class TestMessageDispatch:
    """Tests for message routing and dispatch logic."""

    def test_handle_user_message_execution_report_dispatch(
        self, execution_report_new
    ):
        """Test execution report is dispatched to correct subscribers."""
        test_queue = queue.Queue()
        subscriptions = {
            "test_system": [
                SubscriptionInfo(
                    data_type=SubscriptionType.USER,
                    symbol="BTCUSDC",
                    target=SubscriptionTarget.FRONTEND,
                    queue=test_queue,
                )
            ]
        }

        handle_user_message(execution_report_new, subscriptions)

        # Verify execution report was dispatched
        assert not test_queue.empty()
        event = test_queue.get()
        assert event.name == EventName.EXECUTION_REPORT
        assert event.content.symbol == "BTCUSDC"

    def test_handle_user_message_wrong_symbol(self, execution_report_new):
        """Test execution report not dispatched to wrong symbol subscriber."""
        test_queue = queue.Queue()
        subscriptions = {
            "test_system": [
                SubscriptionInfo(
                    data_type=SubscriptionType.USER,
                    symbol="ETHUSDC",  # Different symbol
                    target=SubscriptionTarget.FRONTEND,
                    queue=test_queue,
                )
            ]
        }

        handle_user_message(execution_report_new, subscriptions)

        # Queue should remain empty
        assert test_queue.empty()

    def test_handle_user_message_account_position_dispatch(
        self, account_position_message
    ):
        """Test account position is dispatched to portfolio subscribers."""
        test_queue = queue.Queue()
        subscriptions = {
            "test_system": [
                SubscriptionInfo(
                    data_type=SubscriptionType.USER,
                    symbol="BTCUSDC",
                    target=SubscriptionTarget.PORTFOLIO,
                    queue=test_queue,
                )
            ]
        }

        handle_user_message(account_position_message, subscriptions)

        # Verify account position was dispatched
        assert not test_queue.empty()
        event = test_queue.get()
        assert event.name == EventName.ACCOUNT_POSITION
        assert isinstance(event.content, AccountPosition)

    def test_multiple_subscribers_receive_message(self, execution_report_new):
        """Test message is sent to multiple subscribers."""
        queue1 = queue.Queue()
        queue2 = queue.Queue()

        subscriptions = {
            "system1": [
                SubscriptionInfo(
                    data_type=SubscriptionType.USER,
                    symbol="BTCUSDC",
                    target=SubscriptionTarget.FRONTEND,
                    queue=queue1,
                )
            ],
            "system2": [
                SubscriptionInfo(
                    data_type=SubscriptionType.USER,
                    symbol="BTCUSDC",
                    target=SubscriptionTarget.BACKEND,
                    queue=queue2,
                )
            ],
        }

        handle_user_message(execution_report_new, subscriptions)

        # Both queues should receive the message
        assert not queue1.empty()
        assert not queue2.empty()


# ============================================================================
# Test Error Handling
# ============================================================================


class TestErrorHandling:
    """Tests for error handling and validation."""

    def test_handle_user_message_error_event(self, error_message):
        """Test handling of error events."""
        test_queue = queue.Queue()
        subscriptions = {
            "test_system": [
                SubscriptionInfo(
                    data_type=SubscriptionType.USER,
                    symbol="BTCUSDC",
                    target=SubscriptionTarget.FRONTEND,
                    queue=test_queue,
                )
            ]
        }

        with patch("src.broker.message_handlers.logger") as mock_logger:
            handle_user_message(error_message, subscriptions)

            # Should log warning
            mock_logger.warning.assert_called_once()

        # Error should be dispatched to frontend
        assert not test_queue.empty()
        event = test_queue.get()
        assert event.name == EventName.ERROR

    def test_handle_user_message_with_error_callback(self, error_message):
        """Test error callback is invoked for error events."""
        error_callback = MagicMock()
        subscriptions = {}

        handle_user_message(
            error_message, subscriptions, websocket_error_callback=error_callback
        )

        # Error callback should be called
        error_callback.assert_called_once_with(error_message)

    def test_handle_ticker_message_control_frame(self, caplog):
        """Test handling of control frame (string message)."""
        control_msg = "ping"

        subscriptions = {}

        with caplog.at_level(logging.DEBUG):
            handle_ticker_message(control_msg, subscriptions)

        # Should log debug message
        assert "Received control frame" in caplog.text

    def test_handle_ticker_message_invalid_format(self, caplog):
        """Test handling of invalid message format."""
        invalid_msg = {"not": "a list"}  # Should be a list

        test_queue = queue.Queue()
        subscriptions = {
            "test_system": [
                SubscriptionInfo(
                    data_type=SubscriptionType.PRICE,
                    symbol="BTCUSDC",
                    target=SubscriptionTarget.FRONTEND,
                    queue=test_queue,
                )
            ]
        }

        with caplog.at_level(logging.WARNING):
            handle_ticker_message(invalid_msg, subscriptions)

        # Should log warning about unexpected format
        assert "Unexpected message format" in caplog.text

    def test_handle_ticker_message_with_error_callback(self):
        """Test ticker error callback is invoked for invalid messages."""
        error_callback = MagicMock()
        invalid_msg = {"not": "a list"}

        subscriptions = {}

        handle_ticker_message(
            invalid_msg, subscriptions, websocket_error_callback=error_callback
        )

        # Error callback should be called
        error_callback.assert_called_once()

    def test_ticker_last_time_callback_invoked(self, ticker_message):
        """Test last ticker time callback is invoked."""
        last_time_callback = MagicMock()
        subscriptions = {}

        handle_ticker_message(
            ticker_message,
            subscriptions,
            last_ticker_time_callback=last_time_callback,
        )

        # Callback should be invoked
        last_time_callback.assert_called_once()

    def test_execution_report_missing_required_fields(self):
        """Test execution report with missing required fields raises KeyError."""
        incomplete_msg = {
            "e": "executionReport",
            "s": "BTCUSDC",
            # Missing many required fields
        }

        # Should raise KeyError when trying to access missing field
        with pytest.raises(KeyError):
            create_execution_report(incomplete_msg)


# ============================================================================
# Test Unknown Message Types
# ============================================================================


class TestUnknownMessageTypes:
    """Tests for handling unknown message types."""

    def test_handle_user_message_unknown_event_type(self):
        """Test unknown event types are silently ignored."""
        unknown_msg = {"e": "unknownEventType", "s": "BTCUSDC", "data": "test"}

        test_queue = queue.Queue()
        subscriptions = {
            "test_system": [
                SubscriptionInfo(
                    data_type=SubscriptionType.USER,
                    symbol="BTCUSDC",
                    target=SubscriptionTarget.FRONTEND,
                    queue=test_queue,
                )
            ]
        }

        # Should not raise exception
        handle_user_message(unknown_msg, subscriptions)

        # Should not dispatch anything
        assert test_queue.empty()

    def test_handle_user_message_missing_event_type(self):
        """Test messages without event type are silently ignored."""
        no_event_msg = {"s": "BTCUSDC", "data": "test"}

        test_queue = queue.Queue()
        subscriptions = {
            "test_system": [
                SubscriptionInfo(
                    data_type=SubscriptionType.USER,
                    symbol="BTCUSDC",
                    target=SubscriptionTarget.FRONTEND,
                    queue=test_queue,
                )
            ]
        }

        # Should not raise exception
        handle_user_message(no_event_msg, subscriptions)

        # Should not dispatch anything
        assert test_queue.empty()


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Integration tests for complete message processing flows."""

    def test_complete_order_lifecycle(
        self,
        execution_report_new,
        execution_report_partial_fill,
        execution_report_filled,
    ):
        """Test processing complete order lifecycle: NEW -> PARTIAL -> FILLED."""
        test_queue = queue.Queue()
        subscriptions = {
            "test_system": [
                SubscriptionInfo(
                    data_type=SubscriptionType.USER,
                    symbol="ETHUSDC",
                    target=SubscriptionTarget.FRONTEND,
                    queue=test_queue,
                )
            ]
        }

        # Process new order
        execution_report_new["s"] = "ETHUSDC"
        handle_user_message(execution_report_new, subscriptions)
        event1 = test_queue.get()
        assert event1.content.current_order_status == "NEW"

        # Process partial fill
        handle_user_message(execution_report_partial_fill, subscriptions)
        event2 = test_queue.get()
        assert event2.content.current_order_status == "PARTIALLY_FILLED"
        assert event2.content.cumulative_filled_quantity == 1.0

        # Process full fill
        execution_report_filled["s"] = "ETHUSDC"
        execution_report_filled["q"] = "2.0"
        execution_report_filled["z"] = "2.0"
        handle_user_message(execution_report_filled, subscriptions)
        event3 = test_queue.get()
        assert event3.content.current_order_status == "FILLED"
        assert event3.content.cumulative_filled_quantity == 2.0

    def test_multiple_symbols_ticker_updates(self):
        """Test ticker updates for multiple symbols are correctly routed."""
        queue_btc = queue.Queue()
        queue_eth = queue.Queue()

        subscriptions = {
            "system1": [
                SubscriptionInfo(
                    data_type=SubscriptionType.PRICE,
                    symbol="BTCUSDC",
                    target=SubscriptionTarget.FRONTEND,
                    queue=queue_btc,
                ),
                SubscriptionInfo(
                    data_type=SubscriptionType.PRICE,
                    symbol="ETHUSDC",
                    target=SubscriptionTarget.FRONTEND,
                    queue=queue_eth,
                ),
            ]
        }

        ticker_msg = [
            {
                "s": "BTCUSDC",
                "c": "50000.00",
                "b": "49999.00",
                "a": "50001.00",
                "h": "51000.00",
                "l": "49000.00",
                "v": "100.5",
            },
            {
                "s": "ETHUSDC",
                "c": "3000.00",
                "b": "2999.50",
                "a": "3000.50",
                "h": "3100.00",
                "l": "2900.00",
                "v": "500.25",
            },
        ]

        handle_ticker_message(ticker_msg, subscriptions)

        # Each queue should have its symbol's update
        btc_event = queue_btc.get()
        assert btc_event.content.symbol == "BTCUSDC"
        assert btc_event.content.last_price == 50000.00

        eth_event = queue_eth.get()
        assert eth_event.content.symbol == "ETHUSDC"
        assert eth_event.content.last_price == 3000.00
