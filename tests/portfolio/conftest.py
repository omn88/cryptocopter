import pytest

from src.common.identifiers import AccountPosition, Balance, Event, EventName
from tests.strategies.hp.hp_simulator import HPSimulator
from tests.portfolio.inventory_simulator import InventorySellSimulator


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
