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

import asyncio
import queue
from decimal import Decimal
from typing import Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.broker import BrokerSpot
from src.common.client import BinanceClient
from src.common.symbol import Symbol
from src.database import Database
from src.domain.enums import EventName
from src.domain.orders import Event, TickerUpdate
from src.strategies.buy_dip.config import BuyDipConfig
from src.strategies.buy_dip.executor import BuyDipExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config() -> BuyDipConfig:
    return BuyDipConfig(
        min_consecutive_rising=3,
        min_total_gain_pct=1.0,
        dca_distances_pct=[2.0, 4.0],
    )


def _make_symbols_dict() -> Dict[str, Any]:
    return {
        "BTCUSDC": Symbol(
            name="BTCUSDC",
            precision=5,
            price_precision=2,
            min_notional=10.0,
            lot_size=0.00001,
            price_filter=0.01,
        )
    }


def _make_executor(symbols: list[str] | None = None) -> BuyDipExecutor:
    symbols = symbols or ["BTCUSDC"]
    mock_db = MagicMock(spec=Database)
    mock_broker = MagicMock(spec=BrokerSpot)
    mock_client = AsyncMock(spec=BinanceClient)
    ui_queue: queue.Queue = queue.Queue()

    return BuyDipExecutor(
        db=mock_db,
        broker=mock_broker,
        client=mock_client,
        ui_queue=ui_queue,
        config=_make_config(),
        total_budget=Decimal("1000"),
        order_budget_pct=Decimal("10"),
        symbols=symbols,
        symbols_dict=_make_symbols_dict(),
    )


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestBuyDipExecutorInit:
    def test_initialises_with_known_symbol(self):
        ex = _make_executor(["BTCUSDC"])
        assert "BTCUSDC" in ex.broker_adapters
        assert ex.strategy is not None
        assert not ex.stop_event.is_set()

    def test_initialises_with_unknown_symbol_uses_defaults(self):
        """Symbol not in symbols_dict → default Symbol created without error."""
        mock_db = MagicMock(spec=Database)
        mock_broker = MagicMock(spec=BrokerSpot)
        mock_client = AsyncMock(spec=BinanceClient)

        ex = BuyDipExecutor(
            db=mock_db,
            broker=mock_broker,
            client=mock_client,
            ui_queue=queue.Queue(),
            config=_make_config(),
            total_budget=Decimal("500"),
            order_budget_pct=Decimal("5"),
            symbols=["XYZUSDC"],
            symbols_dict={},  # empty → fallback
        )
        assert "XYZUSDC" in ex.broker_adapters

    def test_start_creates_task(self):
        """start() should create a task on the running loop."""
        ex = _make_executor()

        async def _run():
            ex.start()
            assert ex._task is not None
            ex.stop()

        asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# _process_event: Event objects
# ---------------------------------------------------------------------------

class TestProcessEventEventObjects:
    @pytest.mark.asyncio
    async def test_ticker_event_updates_price_cache(self):
        ex = _make_executor()
        ex.strategy.process_ticker = AsyncMock()
        ex.strategy.check_for_invalidation = MagicMock()

        ticker = TickerUpdate(symbol="BTCUSDC", last_price=50000.0)
        event = Event(name=EventName.TICKER, content=ticker)

        await ex._process_event(event)

        assert ex._current_prices["BTCUSDC"] == 50000.0
        ex.strategy.process_ticker.assert_awaited_once_with("BTCUSDC", 50000.0)

    @pytest.mark.asyncio
    async def test_ticker_event_wrong_content_type_skipped(self):
        ex = _make_executor()
        ex.strategy.process_ticker = AsyncMock()

        event = Event(name=EventName.TICKER, content="not-a-ticker-update")

        await ex._process_event(event)

        ex.strategy.process_ticker.assert_not_called()

    @pytest.mark.asyncio
    async def test_account_position_event_is_ignored_gracefully(self):
        ex = _make_executor()
        event = Event(name=EventName.ACCOUNT_POSITION, content=MagicMock())
        # Should not raise
        await ex._process_event(event)

    @pytest.mark.asyncio
    async def test_unknown_event_name_is_logged_gracefully(self):
        ex = _make_executor()
        event = Event(name=EventName.SIGNAL, content=MagicMock())
        # Should not raise (unhandled Event types are just logged)
        await ex._process_event(event)


# ---------------------------------------------------------------------------
# _process_event: raw dict (WebSocket) events
# ---------------------------------------------------------------------------

class TestProcessEventDictEvents:
    @pytest.mark.asyncio
    async def test_closed_kline_triggers_process_candle(self):
        ex = _make_executor()
        ex.strategy.process_candle = AsyncMock()

        kline_event = {
            "e": "kline",
            "s": "BTCUSDC",
            "k": {
                "x": True,  # closed
                "t": 1000000,
                "T": 1000900,
                "o": "49000",
                "h": "50500",
                "l": "48800",
                "c": "50000",
                "v": "100",
            },
        }

        await ex._process_event(kline_event)

        ex.strategy.process_candle.assert_awaited_once()
        call_args = ex.strategy.process_candle.call_args
        assert call_args[0][0] == "BTCUSDC"
        assert call_args[0][1]["close"] == 50000.0

    @pytest.mark.asyncio
    async def test_open_kline_does_not_trigger_process_candle(self):
        ex = _make_executor()
        ex.strategy.process_candle = AsyncMock()

        kline_event = {
            "e": "kline",
            "s": "BTCUSDC",
            "k": {"x": False},  # not closed
        }

        await ex._process_event(kline_event)

        ex.strategy.process_candle.assert_not_called()

    @pytest.mark.asyncio
    async def test_execution_report_routes_to_adapter(self):
        ex = _make_executor()
        ex.broker_adapters["BTCUSDC"].handle_user_stream_update = MagicMock()

        exec_event = {"e": "executionReport", "s": "BTCUSDC", "X": "FILLED"}

        await ex._process_event(exec_event)

        ex.broker_adapters["BTCUSDC"].handle_user_stream_update.assert_called_once_with(exec_event)

    @pytest.mark.asyncio
    async def test_non_dict_non_event_is_silently_skipped(self):
        ex = _make_executor()
        # Should not raise
        await ex._process_event(12345)
        await ex._process_event(None)
        await ex._process_event("raw-string")


# ---------------------------------------------------------------------------
# _handle_config_update
# ---------------------------------------------------------------------------

class TestHandleConfigUpdate:
    def test_update_budget_and_order_pct(self):
        ex = _make_executor()
        update = {
            "type": "update_config",
            "total_budget": 2000.0,
            "order_budget_pct": 5.0,
            "symbol": None,
        }
        # Should not raise
        ex._handle_config_update(update)

    def test_update_with_new_symbol_calls_add_symbol(self):
        ex = _make_executor()
        ex.strategy.add_symbol = MagicMock()
        ex.strategy._create_placeholder_watching_position = MagicMock()

        update = {
            "type": "update_config",
            "total_budget": 1000.0,
            "order_budget_pct": 10.0,
            "symbol": "ETHUSDC",
        }
        ex._handle_config_update(update)

        ex.strategy.add_symbol.assert_called_with("ETHUSDC")


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

class TestCallbacks:
    def test_on_order_filled_buy_triggers_handle_order_fill(self):
        ex = _make_executor()
        ex.strategy.handle_order_fill = MagicMock()

        ex._on_order_filled("order_btc_123", 50000.0)

        ex.strategy.handle_order_fill.assert_called_once_with("order_btc_123", 50000.0, 1.0)

    def test_on_order_filled_sell_triggers_handle_sell_fill(self):
        ex = _make_executor()
        ex.strategy.handle_sell_fill = MagicMock()

        ex._on_order_filled("order_btc_sell_456", 51000.0)

        ex.strategy.handle_sell_fill.assert_called_once_with("order_btc_sell_456", 51000.0)

    def test_on_order_cancelled_does_not_raise(self):
        ex = _make_executor()
        ex._on_order_cancelled("order_123")  # should not raise
