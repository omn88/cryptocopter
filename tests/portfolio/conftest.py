import queue
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.enums import EventName
from src.domain.inventory import InventoryItem
from src.domain.orders import AccountPosition, Balance, Event
from src.portfolio.portfolio import PortfolioManager
from src.portfolio.usd_price_resolver import UsdPriceResolver
from tests.strategies.hp.hp_simulator import HPSimulator
from tests.portfolio.inventory_simulator import InventorySellSimulator


@pytest.fixture
def make_item():
    """Factory fixture: create an InventoryItem with sensible defaults."""

    def _factory(
        coin: str = "BTC", quantity: float = 1.0, buy_price: float = 50000.0
    ) -> InventoryItem:
        return InventoryItem(
            id="test-id",
            coin=coin,
            buy_price=buy_price,
            quantity=quantity,
            available_quantity=quantity,
            locked_quantity=0.0,
            source="TEST",
            timestamp=time.time(),
        )

    return _factory


@pytest.fixture
def make_portfolio():
    """Factory fixture: create a PortfolioManager with fully mocked dependencies."""

    def _factory(
        db_items: list | None = None, client_account: dict | None = None
    ) -> PortfolioManager:
        mock_broker = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_account = AsyncMock(
            return_value=client_account or {"balances": []}
        )
        mock_db = AsyncMock()
        mock_db.fetch_all_inventory_items = AsyncMock(
            return_value=db_items if db_items is not None else []
        )
        mock_db.insert_inventory_item = AsyncMock()
        price_resolver = MagicMock(spec=UsdPriceResolver)
        return PortfolioManager(
            broker=mock_broker,
            ui_queue=queue.Queue(),
            price_resolver=price_resolver,
            db=mock_db,
            client=mock_client,
        )

    return _factory


@pytest.fixture
async def portfolio_initialized(portfolio_crash_recovery_factory):
    """Portfolio + HP + backend with exchange balances initialized to zero-locked state.

    Yields (portfolio_ui, hp_frontend, backend, create_portfolio_hp_setup, simulate_crash).
    """
    create_portfolio_hp_setup, simulate_crash = portfolio_crash_recovery_factory
    portfolio_ui, hp_frontend, backend = create_portfolio_hp_setup("test")
    coin_totals: dict[str, float] = {}
    for item in portfolio_ui.inventory:
        coin_totals[item.coin] = coin_totals.get(item.coin, 0.0) + item.quantity
    balances = [
        Balance(coin=coin, free=total, locked=0.0)
        for coin, total in coin_totals.items()
    ]
    account_position = AccountPosition(
        event_time=0, last_update_time=0, balances=balances
    )
    portfolio_ui.ui_queue.put(
        Event(name=EventName.ACCOUNT_POSITION, content=account_position)
    )
    await portfolio_ui.process_test_events()
    yield portfolio_ui, hp_frontend, backend, create_portfolio_hp_setup, simulate_crash


@pytest.fixture
async def inv_sim(portfolio_hp_backend_setup):
    """InventorySellSimulator + HPSimulator from portfolio_hp_backend_setup.

    Yields (sim, hp_sim, portfolio, hp_front, hp_back).
    """
    portfolio, hp_front, hp_back = portfolio_hp_backend_setup
    sim = InventorySellSimulator(portfolio, hp_front, hp_back)
    hp_sim = HPSimulator(front=hp_front, back=hp_back)
    yield sim, hp_sim, portfolio, hp_front, hp_back
