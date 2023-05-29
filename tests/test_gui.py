import asyncio

import pytest
from src.common.identifiers import AccountData, PositionData, OrderData, EventName
from unittest.mock import MagicMock

from src.gui.async_app import AsyncApp


def test_update_order(basic_rsi):
    async_app = AsyncApp()
    async_app.trading_system = basic_rsi
    async_app.order_data_list = [
        {
            "order_id": "1",
            "open_time": "12345",
            "symbol": "BTC",
            "order_type": "LIMIT",
            "side": "BUY",
            "price": "10",
            "quantity": "1",
            "realized_quantity": "0",
            "status": "NEW",
        }
    ]
    async_app.update_order(order_id="1", price="20")
    assert async_app.order_data_list[0]["price"] == "20"


def test_count_open_orders(basic_rsi):
    async_app = AsyncApp()
    async_app.trading_system = basic_rsi
    async_app.order_data_list = [
        {"order_id": "1", "status": "NEW"},
        {"order_id": "2", "status": "PARTIALLY_FILLED"},
        {"order_id": "3", "status": "FILLED"},
    ]
    count = async_app.count_open_orders()
    assert count == 2


def test_count_open_positions(basic_rsi):
    async_app = AsyncApp()
    async_app.trading_system = basic_rsi
    async_app.position_data_list = [
        {"symbol": "BTC", "quantity": "1"},
        {"symbol": "ETH", "quantity": "0"},
        {"symbol": "LTC", "quantity": "0.5"},
    ]
    count = async_app.count_open_positions()
    assert count == 2


async def test_update_ui(basic_rsi, mock_AsyncClient):
    async_app = AsyncApp()
    async_app.ui_queue = asyncio.Queue()
    async_app.trading_system = basic_rsi
    account_data = AccountData(balance=1000)
    position_data = PositionData(
        symbol="BTC", quantity="1", entry_price="1", mark_price="1", liquidation_price="1", pnl="1"
    )
    order_data = OrderData(
        order_id="1",
        open_time="12345",
        symbol="BTC",
        order_type="LIMIT",
        side="BUY",
        price="10",
        quantity="1",
        realized_quantity="0",
        status="NEW",
    )
    # Put some data in the queue
    await async_app.ui_queue.put(account_data)
    await async_app.ui_queue.put(position_data)
    await async_app.ui_queue.put(order_data)
    await async_app.ui_queue.put(EventName.SENTINEL)
    # Mock the logger
    async_app.logger = MagicMock()
    # Run the update_ui() method once
    await async_app.update_ui()
    # Check if the data has been processed
    assert async_app.balance_label == "1000 USDT"
    assert len(async_app.position_data_list) == 1
    assert len(async_app.order_data_list) == 1
