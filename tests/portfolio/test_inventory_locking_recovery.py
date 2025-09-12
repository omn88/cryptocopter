# """Test inventory locking persistence and recovery."""
# import pytest
# import logging
# from unittest.mock import AsyncMock, MagicMock

# from src.identifiers import HPSellPositionCreated, EventName, InventoryItem, Order, State
# from src.portfolio.portfolio_gui import PortfolioUI


# logger = logging.getLogger(__name__)


# async def test_lock_quantities_persists_to_database(portfolio_gui_setup):
#     """Test that locking quantities persists changes to database."""
#     portfolio_ui, mock_db = portfolio_gui_setup

#     # Setup mock inventory with multiple lots for BTC
#     inventory_items = [
#         InventoryItem(
#             id="btc_lot1",
#             coin="BTC",
#             buy_price=30000.0,
#             quantity=0.5,
#             available_quantity=0.5,
#             locked_quantity=0.0,
#         ),
#         InventoryItem(
#             id="btc_lot2",
#             coin="BTC",
#             buy_price=35000.0,
#             quantity=0.3,
#             available_quantity=0.3,
#             locked_quantity=0.0,
#         ),
#     ]

#     # Set inventory in portfolio UI
#     portfolio_ui.set_inventory(inventory_items)

#     # Create HP sell position event to lock quantities
#     hp_sell_event = HPSellPositionCreated(
#         hp_id="1001",
#         coin="BTC",
#         quantity=0.6,  # Lock 0.6 BTC (should lock all of lot1 and 0.1 from lot2)
#         buy_price=30000.0,
#         sell_price=60000.0,
#         end_currency="USDC"
#     )

#     # Handle the event (this should lock quantities and persist to DB)
#     await portfolio_ui.handle_hp_sell_created(hp_sell_event)

#     # Verify database update was called for each lot that was locked
#     assert mock_db.update_inventory_item.call_count >= 1, "Database should be updated when quantities are locked"

#     # Verify the lots have correct locked/available quantities
#     btc_lots = None
#     for coin_data in portfolio_ui.coin_list_data:
#         if coin_data.get("symbol") == "BTC":
#             btc_lots = coin_data.get("lots", [])
#             break

#     assert btc_lots is not None, "BTC lots should exist"
#     assert len(btc_lots) == 2, "Should have 2 BTC lots"

#     # Sort by buy price to match FIFO order
#     btc_lots.sort(key=lambda lot: getattr(lot, 'buy_price', 0))

#     # First lot (30000): should be fully locked (0.5 BTC)
#     lot1 = btc_lots[0]
#     assert lot1.available_quantity == 0.0, "First lot should be fully locked"
#     assert lot1.locked_quantity == 0.5, "First lot should have 0.5 locked"

#     # Second lot (35000): should have 0.1 locked, 0.2 available
#     lot2 = btc_lots[1]
#     assert lot2.available_quantity == 0.2, "Second lot should have 0.2 available"
#     assert lot2.locked_quantity == 0.1, "Second lot should have 0.1 locked"


# @pytest.mark.asyncio
# async def test_unlock_quantities_persists_to_database(portfolio_gui_setup):
#     """Test that unlocking quantities persists changes to database."""
#     portfolio_ui, mock_db = portfolio_gui_setup

#     # Setup mock inventory with pre-locked quantities
#     inventory_items = [
#         InventoryItem(
#             id="btc_lot1",
#             coin="BTC",
#             buy_price=30000.0,
#             quantity=0.5,
#             available_quantity=0.0,  # Fully locked
#             locked_quantity=0.5,
#         ),
#         InventoryItem(
#             id="btc_lot2",
#             coin="BTC",
#             buy_price=35000.0,
#             quantity=0.3,
#             available_quantity=0.2,  # Partially locked
#             locked_quantity=0.1,
#         ),
#     ]

#     # Set inventory in portfolio UI
#     portfolio_ui.set_inventory(inventory_items)

#     # Unlock some quantities
#     await portfolio_ui._unlock_quantities_fifo("BTC", 0.3)  # Unlock 0.3 BTC

#     # Verify database update was called for each lot that was unlocked
#     assert mock_db.update_inventory_item.call_count >= 1, "Database should be updated when quantities are unlocked"

#     # Verify the lots have correct locked/available quantities after unlock
#     btc_lots = None
#     for coin_data in portfolio_ui.coin_list_data:
#         if coin_data.get("symbol") == "BTC":
#             btc_lots = coin_data.get("lots", [])
#             break

#     assert btc_lots is not None, "BTC lots should exist"

#     # Sort by buy price to match FIFO order
#     btc_lots.sort(key=lambda lot: getattr(lot, 'buy_price', 0))

#     # First lot (30000): should be partially unlocked (0.3 unlocked, 0.2 still locked)
#     lot1 = btc_lots[0]
#     assert lot1.available_quantity == 0.3, "First lot should have 0.3 available after unlock"
#     assert lot1.locked_quantity == 0.2, "First lot should have 0.2 still locked"

#     # Second lot (35000): should remain unchanged (0.2 available, 0.1 locked)
#     lot2 = btc_lots[1]
#     assert lot2.available_quantity == 0.2, "Second lot should remain unchanged"
#     assert lot2.locked_quantity == 0.1, "Second lot should remain unchanged"


# @pytest.mark.asyncio
# async def test_recovery_sends_lock_event_for_active_positions(mock_strategy_executor):
#     """Test that crash recovery sends HPSellPositionCreated events for restored positions."""

#     # This test validates that the fix in strategy_executor.py works:
#     # The event should be sent for both new AND restored positions

#     # Create mock sell position data for recovery
#     from src.identifiers import HPSellConfig, StateInfo, PositionSide, UiState
#     from src.portfolio.portfolio import SymbolInfo

#     mock_config = HPSellConfig(
#         hp_id="1001",
#         coin="BTC",
#         quantity=0.5,
#         buy_price=30000.0,
#         sell_price=60000.0,
#         end_currency="USDC",
#         symbol_info=SymbolInfo(
#             symbol="BTCUSDC",
#             min_notional=5.0,
#             lot_size=0.00001,
#             min_qty=0.00001,
#             max_qty=900.0,
#             price_filter=0.01,
#             precision=5,
#             price_precision=2,
#             is_convert_only=False,
#         )
#     )

#     mock_state_info = StateInfo(
#         state=State.NEW,
#         open_time="2025-09-11 13:32:39",
#         close_time="",
#         side=PositionSide.SHORT,
#         completeness=0.0,
#         ui_state=UiState.NEW
#     )

#     # Mock the _send_hp_event_to_portfolio method to capture events
#     sent_events = []
#     def capture_event(event_name, event_data):
#         sent_events.append((event_name, event_data))

#     mock_strategy_executor._send_hp_event_to_portfolio = capture_event

#     # Simulate restoring a sell position (is_restoration=True)
#     await mock_strategy_executor.setup_sell_position_with_new_hp(
#         strategy_data=MagicMock(config=mock_config, state_info=mock_state_info),
#         sell_strategy=MagicMock(),
#         is_restoration=True
#     )

#     # Verify that HP_SELL_POSITION_CREATED event was sent even during restoration
#     assert len(sent_events) >= 1, "Should send HP_SELL_POSITION_CREATED event during restoration"

#     event_name, event_data = sent_events[0]
#     assert event_name == EventName.HP_SELL_POSITION_CREATED, "Should send HP_SELL_POSITION_CREATED event"
#     assert isinstance(event_data, HPSellPositionCreated), "Event data should be HPSellPositionCreated"
#     assert event_data.hp_id == "1001", "Event should have correct HP ID"
#     assert event_data.coin == "BTC", "Event should have correct coin"
#     assert event_data.quantity == 0.5, "Event should have correct quantity"


# @pytest.fixture
# def portfolio_gui_setup():
#     """Setup PortfolioUI with mocked database for testing."""
#     # Create mock database
#     mock_db = AsyncMock()

#     # Create PortfolioUI instance with test mode enabled
#     portfolio_ui = PortfolioUI(test_mode=True)
#     portfolio_ui.db = mock_db
#     portfolio_ui.coin_list_data = []

#     return portfolio_ui, mock_db


# @pytest.fixture
# def mock_strategy_executor():
#     """Create a mock StrategyExecutor for testing."""
#     from src.strategy_executor import StrategyExecutor

#     # Create real instance but with mocked dependencies
#     executor = StrategyExecutor(test_mode=True)
#     executor.client = AsyncMock()
#     executor.db = AsyncMock()
#     executor.strategies = {}

#     # Mock internal methods that we don't want to actually execute
#     executor._initialize_strategy = AsyncMock()

#     return executor
