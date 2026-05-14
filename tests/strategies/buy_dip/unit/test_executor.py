"""
Unit tests for BuyDipExecutor (src/strategies/buy_dip/executor.py).

Coverage targets (A10):
- Constructor initialisation (symbols_dict present / absent)
- _process_event: TICKER event, KLINE closed candle, KLINE open candle,
  EXECUTION_REPORT, ACCOUNT_POSITION, unsupported Event type,
  non-dict non-Event value
- _handle_config_update: budget + order_pct update, symbol change warning
- _on_order_filled / _on_order_cancelled callbacks
"""

import queue
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from src.broker import BrokerSpot
from src.common.client import BinanceClient
from src.common.symbol import Symbol
from src.database import Database
from src.domain.enums import EventName
from src.domain.orders import Event, TickerUpdate
from src.strategies.buy_dip.config import BuyDipConfig
from src.strategies.buy_dip.executor import BuyDipExecutor


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestBuyDipExecutorInit:
    def test_initialises_with_known_symbol(self, executor):
        assert "BTCUSDC" in executor.broker_adapters
        assert executor.strategy is not None
        assert not executor.stop_event.is_set()

    def test_initialises_with_unknown_symbol_uses_defaults(self, buy_dip_config):
        """Symbol not in symbols_dict → default Symbol created without error."""
        ex = BuyDipExecutor(
            db=MagicMock(spec=Database),
            broker=MagicMock(spec=BrokerSpot),
            client=AsyncMock(spec=BinanceClient),
            ui_queue=queue.Queue(),
            config=buy_dip_config,
            total_budget=Decimal("500"),
            order_budget_pct=Decimal("5"),
            symbols=["XYZUSDC"],
            symbols_dict={},  # empty → fallback
        )
        assert "XYZUSDC" in ex.broker_adapters

    async def test_start_creates_task(self, executor):
        """start() should create a task on the running loop."""
        executor.start()
        assert executor._task is not None
        executor.stop()


# ---------------------------------------------------------------------------
# _process_event: Event objects
# ---------------------------------------------------------------------------


class TestProcessEventEventObjects:
    async def test_ticker_event_updates_price_cache(self, executor):
        executor.strategy.process_ticker = AsyncMock()
        executor.strategy.check_for_invalidation = MagicMock()

        ticker = TickerUpdate(symbol="BTCUSDC", last_price=50000.0)
        event = Event(name=EventName.TICKER, content=ticker)

        await executor._process_event(event)

        assert executor._current_prices["BTCUSDC"] == 50000.0
        executor.strategy.process_ticker.assert_awaited_once_with("BTCUSDC", 50000.0)

    async def test_ticker_event_wrong_content_type_skipped(self, executor):
        executor.strategy.process_ticker = AsyncMock()

        event = Event(name=EventName.TICKER, content="not-a-ticker-update")
        await executor._process_event(event)

        executor.strategy.process_ticker.assert_not_called()

    async def test_account_position_event_is_ignored_gracefully(self, executor):
        event = Event(name=EventName.ACCOUNT_POSITION, content=MagicMock())
        await executor._process_event(event)  # should not raise

    async def test_unknown_event_name_is_logged_gracefully(self, executor):
        event = Event(name=EventName.SIGNAL, content=MagicMock())
        await executor._process_event(event)  # should not raise


# ---------------------------------------------------------------------------
# _process_event: raw dict (WebSocket) events
# ---------------------------------------------------------------------------


class TestProcessEventDictEvents:
    async def test_closed_kline_triggers_process_candle(self, executor):
        executor.strategy.process_candle = AsyncMock()

        kline_event = {
            "e": "kline",
            "s": "BTCUSDC",
            "k": {
                "x": True,
                "t": 1000000,
                "T": 1000900,
                "o": "49000",
                "h": "50500",
                "l": "48800",
                "c": "50000",
                "v": "100",
            },
        }

        await executor._process_event(kline_event)

        executor.strategy.process_candle.assert_awaited_once()
        call_args = executor.strategy.process_candle.call_args
        assert call_args[0][0] == "BTCUSDC"
        assert call_args[0][1]["close"] == 50000.0

    async def test_open_kline_does_not_trigger_process_candle(self, executor):
        executor.strategy.process_candle = AsyncMock()

        kline_event = {"e": "kline", "s": "BTCUSDC", "k": {"x": False}}
        await executor._process_event(kline_event)

        executor.strategy.process_candle.assert_not_called()

    async def test_execution_report_routes_to_adapter(self, executor):
        executor.broker_adapters["BTCUSDC"].handle_user_stream_update = MagicMock()

        exec_event = {"e": "executionReport", "s": "BTCUSDC", "X": "FILLED"}
        await executor._process_event(exec_event)

        executor.broker_adapters["BTCUSDC"].handle_user_stream_update.assert_called_once_with(
            exec_event
        )

    async def test_non_dict_non_event_is_silently_skipped(self, executor):
        await executor._process_event(12345)
        await executor._process_event(None)
        await executor._process_event("raw-string")


# ---------------------------------------------------------------------------
# _handle_config_update
# ---------------------------------------------------------------------------


class TestHandleConfigUpdate:
    def test_update_budget_and_order_pct(self, executor):
        update = {
            "type": "update_config",
            "total_budget": 2000.0,
            "order_budget_pct": 5.0,
            "symbol": None,
        }
        executor._handle_config_update(update)  # should not raise

    def test_update_with_new_symbol_calls_add_symbol(self, executor):
        executor.strategy.add_symbol = MagicMock()
        executor.strategy._create_placeholder_watching_position = MagicMock()

        update = {
            "type": "update_config",
            "total_budget": 1000.0,
            "order_budget_pct": 10.0,
            "symbol": "ETHUSDC",
        }
        executor._handle_config_update(update)

        executor.strategy.add_symbol.assert_called_with("ETHUSDC")


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


class TestCallbacks:
    def test_on_order_filled_buy_triggers_handle_order_fill(self, executor):
        executor.strategy.handle_order_fill = MagicMock()

        executor._on_order_filled("order_btc_123", 50000.0)

        executor.strategy.handle_order_fill.assert_called_once_with(
            "order_btc_123", 50000.0, 1.0
        )

    def test_on_order_filled_sell_triggers_handle_sell_fill(self, executor):
        executor.strategy.handle_sell_fill = MagicMock()

        executor._on_order_filled("order_btc_sell_456", 51000.0)

        executor.strategy.handle_sell_fill.assert_called_once_with(
            "order_btc_sell_456", 51000.0
        )

    def test_on_order_cancelled_does_not_raise(self, executor):
        executor._on_order_cancelled("order_123")  # should not raise

