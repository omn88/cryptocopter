"""Layered fixtures for HP Manager E2E tests.

Each fixture builds on the previous one, giving tests a clean starting state
without repeating the bootstrap ceremony. Tests receive a `(sim, strategy)`
tuple already positioned at the desired state.

Fixture hierarchy:
    frontend_backend_setup          (from root conftest)
          │
    hp_sim                          HPSimulator wired to front+back
          │
    hp_idle                         position created, sitting at State.NEW
          │
    hp_buying                       buy order sent, State.BUYING
          │
    hp_bought                       buy order filled, State.BOUGHT
          │
    hp_sell_configured              sell position configured, sell order not yet sent
"""

import pytest

from tests.strategies.hp.hp_simulator import HPSimulator


# ---------------------------------------------------------------------------
# Level 0 — simulator only
# ---------------------------------------------------------------------------


@pytest.fixture
async def hp_sim(frontend_backend_setup):
    """Bare HPSimulator wired to frontend + backend. No position created yet."""
    front, back = frontend_backend_setup
    yield HPSimulator(front=front, back=back)


# ---------------------------------------------------------------------------
# Level 1 — position exists, State.NEW (idle, no order sent)
# ---------------------------------------------------------------------------


@pytest.fixture
async def hp_idle(hp_sim):
    """Position created and registered. State: NEW (no order sent).

    Yields (sim, strategy). Accepts optional parametrize via indirect for
    non-default symbol / buy_price / budget.
    """
    hp_sim.simulate_buy_position(symbol="BTCUSDC")
    await hp_sim.assert_default_buy_position()
    strategy = hp_sim.back.strategies["1000"]
    yield hp_sim, strategy


# ---------------------------------------------------------------------------
# Level 2 — buy order sent, State.BUYING
# ---------------------------------------------------------------------------


@pytest.fixture
async def hp_buying(hp_idle):
    """Buy order placed on exchange. State: BUYING / order NEW.

    Yields (sim, strategy).
    """
    sim, strategy = hp_idle
    await sim.move_to_position_active_buy()
    yield sim, strategy


# ---------------------------------------------------------------------------
# Level 3 — buy order fully filled, State.BOUGHT
# ---------------------------------------------------------------------------


@pytest.fixture
async def hp_bought(hp_sim):
    """Buy order fully filled. State: BOUGHT.

    Yields (sim, strategy).
    Note: uses simulate_bought_position() which internally advances through
    idle → buying → filled in one step.
    """
    strategy = await hp_sim.simulate_bought_position()
    yield hp_sim, strategy


# ---------------------------------------------------------------------------
# Level 4 — sell position configured (but order NOT yet sent)
# ---------------------------------------------------------------------------

_DEFAULT_SELL_PARAMS = dict(
    hp_id="1000",
    symbol="BTCUSDC",
    quantity=0.71429,
    buy_price=1400.0,
    sell_price=4200.0,
    end_currency="USDC",
    coin="BTC",
)


@pytest.fixture
async def hp_sell_configured(hp_bought):
    """Sell position configured, sell order not yet sent. State: BOUGHT (sell side NEW).

    Yields (sim, strategy).
    """
    sim, strategy = hp_bought
    await sim.setup_sell_position(**_DEFAULT_SELL_PARAMS)
    yield sim, strategy


# ---------------------------------------------------------------------------
# Level 5 — sell order sent (State.SELLING, order NEW)
# ---------------------------------------------------------------------------


@pytest.fixture
async def hp_selling(hp_sell_configured):
    """Sell order placed on exchange. State: SELLING / sell order NEW.

    Yields (sim, strategy).
    """
    sim, strategy = hp_sell_configured
    await sim.send_sell_order_for_bought_position()
    yield sim, strategy


# ---------------------------------------------------------------------------
# Partially-bought branch — buy order partially filled, then cancelled
# ---------------------------------------------------------------------------


@pytest.fixture
async def hp_partially_bought(hp_buying):
    """Buy order partially filled and then cancelled. State: PARTIALLY_BOUGHT.

    Yields (sim, strategy).
    """
    from binance.enums import ORDER_STATUS_PARTIALLY_FILLED
    from tests.strategies.hp.hp_simulator import wait_for_condition
    from src.domain.enums import State

    sim, strategy = hp_buying
    strategy = await sim.simulate_partial_fill()

    assert strategy.buy.order_cancel_price == 1428.0
    sim.new_price(price=1428.0)

    await wait_for_condition(
        condition_func=lambda: strategy.state == State.PARTIALLY_BOUGHT
    )
    yield sim, strategy


@pytest.fixture
async def hp_partially_bought_sell_configured(hp_partially_bought):
    """Sell position configured after a partial buy fill. State: PARTIALLY_BOUGHT (sell side NEW).

    Yields (sim, strategy).
    """
    sim, strategy = hp_partially_bought
    await sim.setup_sell_position_after_buy_order_filled_partially(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )
    yield sim, strategy


@pytest.fixture
async def hp_partially_bought_selling(hp_partially_bought_sell_configured):
    """Sell order sent after partial buy. State: PARTIALLY_BOUGHT (sell order NEW).

    Yields (sim, strategy).
    """
    sim, strategy = hp_partially_bought_sell_configured
    await sim.send_sell_order_for_part_bought_position()
    yield sim, strategy


@pytest.fixture
async def hp_partially_bought_part_sold(hp_partially_bought_selling):
    """Sell order partially filled after partial buy. State: PART_SOLD_PART_BOUGHT.

    Yields (sim, strategy).
    """
    sim, strategy = hp_partially_bought_selling
    await sim.simulate_sell_order_partial_fill_from_part_bought()
    yield sim, strategy


# ---------------------------------------------------------------------------
# Recovery fixtures — parallel hierarchy using crash_recovery_factory
# ---------------------------------------------------------------------------


@pytest.fixture
async def rec_sim(crash_recovery_factory):
    """HPSimulator wired to the 'original' crash-recovery pair. No position yet.

    Yields (sim, create_pair, simulate_crash).
    """
    create_pair, simulate_crash = crash_recovery_factory
    front, back = create_pair("_original")
    yield HPSimulator(front=front, back=back), create_pair, simulate_crash


@pytest.fixture
async def rec_idle(rec_sim):
    """Recovery fixture: position at State.NEW (buy order not sent).

    Yields (sim, create_pair, simulate_crash).
    """
    sim, create_pair, simulate_crash = rec_sim
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()
    yield sim, create_pair, simulate_crash


@pytest.fixture
async def rec_buying(rec_idle):
    """Recovery fixture: buy order sent, State.BUYING.

    Yields (sim, create_pair, simulate_crash).
    """
    sim, create_pair, simulate_crash = rec_idle
    await sim.move_to_position_active_buy()
    yield sim, create_pair, simulate_crash


@pytest.fixture
async def rec_bought(rec_sim):
    """Recovery fixture: buy order fully filled, State.BOUGHT.

    Yields (sim, create_pair, simulate_crash).
    """
    sim, create_pair, simulate_crash = rec_sim
    await sim.simulate_bought_position()
    yield sim, create_pair, simulate_crash


@pytest.fixture
async def rec_sell_configured(rec_bought):
    """Recovery fixture: sell position configured (order not sent). State: BOUGHT.

    Yields (sim, create_pair, simulate_crash).
    """
    sim, create_pair, simulate_crash = rec_bought
    await sim.setup_sell_position(**_DEFAULT_SELL_PARAMS)
    yield sim, create_pair, simulate_crash


@pytest.fixture
async def rec_selling(rec_sell_configured):
    """Recovery fixture: sell order sent. State: SELLING.

    Yields (sim, create_pair, simulate_crash).
    """
    sim, create_pair, simulate_crash = rec_sell_configured
    await sim.send_sell_order_for_bought_position()
    yield sim, create_pair, simulate_crash


@pytest.fixture
async def rec_partially_bought(rec_buying):
    """Recovery fixture: buy partially filled and cancelled. State: PARTIALLY_BOUGHT.

    Yields (sim, create_pair, simulate_crash).
    """
    sim, create_pair, simulate_crash = rec_buying
    await sim.simulate_partial_fill()
    await sim.cancel_buy_position_after_order_partial_fill()
    yield sim, create_pair, simulate_crash


@pytest.fixture
async def rec_partially_bought_sell_configured(rec_partially_bought):
    """Recovery fixture: sell configured after partial buy. State: PARTIALLY_BOUGHT.

    Yields (sim, create_pair, simulate_crash).
    """
    sim, create_pair, simulate_crash = rec_partially_bought
    strategy = sim.back.strategies["1000"]
    await sim.setup_sell_position(
        hp_id="1000",
        symbol="BTCUSDC",
        quantity=strategy.buy.calculate_realized_quantity(),
        buy_price=strategy.buy.calculate_avg_buy_price(),
        sell_price=4200.0,
        end_currency="USDC",
        coin="BTC",
    )
    yield sim, create_pair, simulate_crash


@pytest.fixture
async def rec_partially_bought_selling(rec_partially_bought_sell_configured):
    """Recovery fixture: sell order sent after partial buy.

    Yields (sim, create_pair, simulate_crash).
    """
    sim, create_pair, simulate_crash = rec_partially_bought_sell_configured
    await sim.send_sell_order_for_part_bought_position()
    yield sim, create_pair, simulate_crash


@pytest.fixture
async def rec_partially_bought_part_sold(rec_partially_bought_selling):
    """Recovery fixture: sell partially filled after partial buy. State: PART_SOLD_PART_BOUGHT.

    Yields (sim, create_pair, simulate_crash).
    """
    sim, create_pair, simulate_crash = rec_partially_bought_selling
    await sim.simulate_sell_order_partial_fill_from_part_bought()
    yield sim, create_pair, simulate_crash


# ---------------------------------------------------------------------------
# Two-hop trade recovery fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def rec_two_hop_opened(rec_sim):
    """Recovery fixture: first sell position opened for two-hop trade.

    Yields (sim, create_pair, simulate_crash).
    """
    sim, create_pair, simulate_crash = rec_sim
    await sim.open_first_sell_position_from_two_hop_trade()
    yield sim, create_pair, simulate_crash


@pytest.fixture
async def rec_two_hop_first_order_sent(rec_two_hop_opened):
    """Recovery fixture: sell order sent for first hop.

    Yields (sim, create_pair, simulate_crash).
    """
    sim, create_pair, simulate_crash = rec_two_hop_opened
    await sim.send_orders_for_first_position_from_two_hop_trade()
    yield sim, create_pair, simulate_crash


@pytest.fixture
async def rec_two_hop_first_partial(rec_two_hop_first_order_sent):
    """Recovery fixture: first hop sell order partially filled.

    Yields (sim, create_pair, simulate_crash).
    """
    sim, create_pair, simulate_crash = rec_two_hop_first_order_sent
    await sim.simulate_sell_order_partial_fill_in_first_hop()
    yield sim, create_pair, simulate_crash


@pytest.fixture
async def rec_two_hop_first_filled(rec_two_hop_first_order_sent):
    """Recovery fixture: first hop sell order fully filled.

    Yields (sim, create_pair, simulate_crash).
    """
    sim, create_pair, simulate_crash = rec_two_hop_first_order_sent
    await sim.simulate_sell_order_fill_in_first_hop()
    yield sim, create_pair, simulate_crash


@pytest.fixture
async def rec_two_hop_second_opened(rec_two_hop_first_filled):
    """Recovery fixture: second sell position opened for two-hop trade.

    Yields (sim, create_pair, simulate_crash).
    """
    sim, create_pair, simulate_crash = rec_two_hop_first_filled
    await sim.open_second_sell_position_from_two_hop_trade()
    yield sim, create_pair, simulate_crash


@pytest.fixture
async def rec_two_hop_second_partial(rec_two_hop_second_opened):
    """Recovery fixture: second hop sell order partially filled.

    Yields (sim, create_pair, simulate_crash).
    """
    sim, create_pair, simulate_crash = rec_two_hop_second_opened
    await sim.simulate_sell_order_partial_fill_in_second_hop()
    yield sim, create_pair, simulate_crash


@pytest.fixture
async def rec_two_hop_second_filled(rec_two_hop_second_opened):
    """Recovery fixture: second hop sell order fully filled.

    Yields (sim, create_pair, simulate_crash).
    """
    sim, create_pair, simulate_crash = rec_two_hop_second_opened
    await sim.simulate_sell_order_fill_in_second_hop()
    yield sim, create_pair, simulate_crash
