"""Layered fixtures for Buy Dip E2E tests.

Fixture hierarchy:
    buy_dip_simulator (root conftest)
        └── bd_potential_top   ← rising(67000→67890, 3 candles) → POTENTIAL_TOP
              └── bd_active    ← order 1 filled → ACTIVE → order 2 placed
"""

import pytest

from src.strategies.buy_dip.position import PositionState
from tests.strategies.buy_dip.buy_dip_simulator import BuyDipSimulator


@pytest.fixture
async def bd_potential_top(buy_dip_simulator: BuyDipSimulator):
    """Single position at POTENTIAL_TOP state with order 1 pending.

    BTC rises 67000 → 67890 over 3 candles. The strategy detects a potential
    top and places order 1 at φ=1.618% below the top.

    Yields:
        (sim, position): simulator and the POTENTIAL_TOP position
    """
    sim = buy_dip_simulator
    await sim.simulate_rising_to_top(start_price=67000, end_price=67890, num_candles=3)
    await sim.wait_for_potential_top(timeout=2.0)
    positions = sim.get_active_positions()
    assert len(positions) == 1
    position = positions[0]
    assert position.state == PositionState.POTENTIAL_TOP
    yield sim, position


@pytest.fixture
async def bd_active(bd_potential_top):
    """Position ACTIVE after order 1 fill. Order 2 placed and pending.

    Extends bd_potential_top: fills order 1 (confirming the top), waits for
    the position to become ACTIVE, then waits for order 2 to be placed.

    Yields:
        (sim, position): simulator and the ACTIVE position with order 2 pending
    """
    sim, position = bd_potential_top
    order_1 = position.pending_order
    assert order_1 is not None
    await sim.fill_order(order_1.order_id, float(order_1.price))
    await sim.wait_for_active_position(timeout=2.0)
    await sim.wait_for_order_placed(position.position_id, timeout=2.0)
    assert position.state == PositionState.ACTIVE
    yield sim, position
