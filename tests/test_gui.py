# import asyncio

# from src.common.identifiers import EventName, PositionStatus, State
# from unittest.mock import MagicMock

# from src.gui.asyncapp import AsyncApp
# from src.gui.identifiers import AccountData, OrderData, PositionData, StrategyData
# from src.gui.strategytab import StrategyTab
# from src.workers.trading_state_machine import TradingStateMachine


# async def test_strategy_data_updates_ui(async_app, base):
#     # Prepare StrategyData
#     strategy_data = StrategyData(
#         strategy_name="Test Strategy",
#         position_data=PositionData(
#             symbol="BTCUSDT",
#             quantity=1,
#             entry_price=1,
#             mark_price=1,
#             liquidation_price=1,
#             state=State.FLAT,
#             status=PositionStatus.OPEN,
#         ),
#     )

#     async_app.trading_systems[0].state_machine = base

#     async_app.trading_systems[0].gui_handler.update_strategy()

#     # # Simulate updating the UI with new strategy data
#     # await async_app.update_ui(strategy_data=strategy_data)
#     # Verify the internal state of async_app reflects the updated strategy
#     assert "Test Strategy" in [
#         strategy.name for strategy in async_app.active_strategies
#     ]
#     # Assuming strategy_tab is updated as part of async_app.update_ui()
#     # Verify the internal state of strategy_tab reflects the expected changes
#     assert strategy_tab.some_attribute == expected_value


# # Additional test cases for OrderData and different scenarios


# def test_update_order(base: TradingStateMachine):
#     strategy_tab = StrategyTab(trading_system=base)
#     async_app.trading_systems[0].state_machine = base
#     order_id = "14"
#     async_app.up = {
#         order_id: {
#             "order_id": order_id,
#             "open_time": "12345",
#             "symbol": "BTC",
#             "order_type": "LIMIT",
#             "side": "BUY",
#             "price": "10",
#             "quantity": "1",
#             "realized_quantity": "0",
#             "status": "NEW",
#         }
#     }

#     assert async_app.open_orders[order_id]["price"] == "10"

#     async_app.update_order(
#         data=OrderData(
#             order_id=order_id,
#             price="20",
#             open_time="12345",
#             symbol="BTC",
#             order_type="LIMIT",
#             side="BUY",
#             quantity="1",
#             realized_quantity="0",
#             status="NEW",
#         )
#     )
#     assert async_app.open_orders[order_id]["price"] == "20"


# # def test_count_open_orders(basic_rsi):
# #     async_app = AsyncApp()
# #     async_app.trading_system = basic_rsi
# #     async_app.open_orders = {
# #         "1": {"order_id": "1", "status": "NEW"},
# #         "2": {"order_id": "2", "status": "PARTIALLY_FILLED"},
# #         "3": {"order_id": "3", "status": "FILLED"}
# #     }
# #     count = async_app.order_count
# #     assert count == 2
# #
# #
# # def test_count_open_positions(basic_rsi):
# #     async_app = AsyncApp()
# #     async_app.trading_system = basic_rsi
# #     async_app.open_positions = {
# #         "BTC": {"symbol": "BTC", "quantity": "1"},
# #         "ETH": {"symbol": "ETH", "quantity": "0"},
# #         "LTC": {"symbol": "LTC", "quantity": "0.5"},
# #     }
# #     count = async_app.position_count
# #     assert count == 2


# async def test_update_ui(basic_rsi, mock_AsyncClient):
#     async_app = AsyncApp()
#     async_app.ui_queue = asyncio.Queue()
#     async_app.trading_system = basic_rsi
#     account_data = AccountData(balance=1000)
#     position_data = PositionData(
#         symbol="BTC",
#         quantity="1",
#         entry_price="1",
#         mark_price="1",
#         liquidation_price="1",
#         pnl="1",
#     )
#     order_data = OrderData(
#         order_id="1",
#         open_time="12345",
#         symbol="BTC",
#         order_type="LIMIT",
#         side="BUY",
#         price="10",
#         quantity="1",
#         realized_quantity="0",
#         status="NEW",
#     )
#     # Put some data in the queue
#     await async_app.ui_queue.put(account_data)
#     await async_app.ui_queue.put(position_data)
#     await async_app.ui_queue.put(order_data)
#     await async_app.ui_queue.put(EventName.SENTINEL)
#     # Mock the logger
#     async_app.logger = MagicMock()
#     # Run the update_ui() method once
#     await async_app.update_ui()
#     # Check if the data has been processed
#     assert async_app.balance_label == "1000 USDT"
#     assert len(async_app.open_positions) == 1
#     assert len(async_app.open_orders) == 1


# async def test_update_ui_with_multiple_orders_one_filled(mock_AsyncClient):
#     async_app = AsyncApp()
#     async_app.trading_system = MagicMock()
#     async_app.ui_queue = asyncio.Queue()
#     async_app.logger = MagicMock()

#     # Create 4 new orders
#     for i in range(1, 5):
#         order_data = OrderData(
#             order_id=str(i),
#             open_time="12345",
#             symbol="BTC",
#             order_type="LIMIT",
#             side="BUY",
#             price="10",
#             quantity="1",
#             realized_quantity="0",
#             status="NEW",
#         )
#         await async_app.ui_queue.put(order_data)

#     await async_app.ui_queue.put(EventName.SENTINEL)

#     # Mock the logger
#     async_app.logger = MagicMock()
#     # Run the update_ui() method once to process all orders
#     await async_app.update_ui()

#     # Now mark the first order as filled
#     first_order = async_app.open_orders["1"]
#     first_order["status"] = "FILLED"
#     first_order["realized_quantity"] = "1"
#     await async_app.ui_queue.put(first_order)
#     await async_app.update_ui()

#     # Check if the data has been processed
#     assert len(async_app.open_positions) == 1
#     assert len(async_app.open_orders) == 4
#     assert async_app.closed_orders["1"].status == "FILLED"
#     assert len(async_app.closed_orders) == 1
