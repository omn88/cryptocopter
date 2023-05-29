import asyncio

import pytest
from src.common.identifiers import AccountData, PositionData, OrderData, EventName
from unittest.mock import MagicMock

from src.gui.async_app import AsyncApp


def test_update_order(basic_rsi):
    async_app = AsyncApp()
    async_app.trading_system = basic_rsi
    order_id = "14"
    async_app.open_orders = {
        order_id: {
            "order_id": order_id,
            "open_time": "12345",
            "symbol": "BTC",
            "order_type": "LIMIT",
            "side": "BUY",
            "price": "10",
            "quantity": "1",
            "realized_quantity": "0",
            "status": "NEW",
        }
    }

    assert async_app.open_orders[order_id]["price"] == "10"

    async_app.update_order(
        data=OrderData(
            order_id=order_id,
            price="20",
            open_time="12345",
            symbol="BTC",
            order_type="LIMIT",
            side="BUY",
            quantity="1",
            realized_quantity="0",
            status="NEW",
        )
    )
    assert async_app.open_orders[order_id]["price"] == "20"


# def test_count_open_orders(basic_rsi):
#     async_app = AsyncApp()
#     async_app.trading_system = basic_rsi
#     async_app.open_orders = {
#         "1": {"order_id": "1", "status": "NEW"},
#         "2": {"order_id": "2", "status": "PARTIALLY_FILLED"},
#         "3": {"order_id": "3", "status": "FILLED"}
#     }
#     count = async_app.order_count
#     assert count == 2
#
#
# def test_count_open_positions(basic_rsi):
#     async_app = AsyncApp()
#     async_app.trading_system = basic_rsi
#     async_app.open_positions = {
#         "BTC": {"symbol": "BTC", "quantity": "1"},
#         "ETH": {"symbol": "ETH", "quantity": "0"},
#         "LTC": {"symbol": "LTC", "quantity": "0.5"},
#     }
#     count = async_app.position_count
#     assert count == 2


async def test_update_ui(basic_rsi, mock_AsyncClient):
    async_app = AsyncApp()
    async_app.ui_queue = asyncio.Queue()
    async_app.trading_system = basic_rsi
    account_data = AccountData(balance=1000)
    position_data = PositionData(
        symbol="BTC",
        quantity="1",
        entry_price="1",
        mark_price="1",
        liquidation_price="1",
        pnl="1",
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
    assert len(async_app.open_positions) == 1
    assert len(async_app.open_orders) == 1


async def test_update_ui_with_multiple_orders_one_filled(mock_AsyncClient):
    async_app = AsyncApp()
    async_app.trading_system = MagicMock()
    async_app.ui_queue = asyncio.Queue()
    async_app.logger = MagicMock()

    # Create 4 new orders
    for i in range(1, 5):
        order_data = OrderData(
            order_id=str(i),
            open_time="12345",
            symbol="BTC",
            order_type="LIMIT",
            side="BUY",
            price="10",
            quantity="1",
            realized_quantity="0",
            status="NEW",
        )
        await async_app.ui_queue.put(order_data)

    await async_app.ui_queue.put(EventName.SENTINEL)

    # Mock the logger
    async_app.logger = MagicMock()
    # Run the update_ui() method once to process all orders
    await async_app.update_ui()

    # Now mark the first order as filled
    first_order = async_app.open_orders["1"]
    first_order["status"] = "FILLED"
    first_order["realized_quantity"] = "1"
    await async_app.ui_queue.put(first_order)
    await async_app.update_ui()

    # Check if the data has been processed
    assert len(async_app.open_positions) == 1
    assert len(async_app.open_orders) == 4
    assert async_app.closed_orders["1"].status == "FILLED"
    assert len(async_app.closed_orders) == 1
