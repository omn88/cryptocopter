"""Unit tests for BuyDipPosition state machine.

Tests position lifecycle:
- State transitions
- Order management (ONE pending at a time)
- Top detection and invalidation
- DCA progression
- Profit calculation
"""

from decimal import Decimal
from src.strategies.buy_dip.position import (
    BuyDipPosition,
    PositionState,
    OrderInfo,
)
import pytest


class TestPositionStates:
    """Test position state transitions."""

    def test_initial_state_is_watching(self, sample_position):
        """Test that new position starts in WATCHING state."""
        assert sample_position.state == PositionState.WATCHING
        assert sample_position.top_price is None
        assert sample_position.pending_order is None

    def test_transition_to_potential_top(self, sample_position):
        """Test transition from WATCHING to POTENTIAL_TOP."""
        top_price = Decimal("67890")
        sample_position.set_potential_top(top_price)

        assert sample_position.state == PositionState.POTENTIAL_TOP
        assert sample_position.top_price == top_price

    def test_transition_to_active_on_first_fill(self, sample_position):
        """Test transition from POTENTIAL_TOP to ACTIVE on first order fill."""
        # Set potential top
        top_price = Decimal("67890")
        sample_position.set_potential_top(top_price)

        # Place and fill first order
        sample_position.place_buy_order(
            order_id="order1",
            price=Decimal("66792.78"),
            quantity=Decimal("0.003"),
            dca_level=0,
        )

        sample_position.handle_order_fill(
            order_id="order1",
            filled_price=Decimal("66792.78"),
            filled_quantity=Decimal("0.003"),
        )

        assert sample_position.state == PositionState.ACTIVE
        assert sample_position.confirmed_top == top_price

    def test_transition_to_completed_on_sell_fill(self, sample_position):
        """Test transition from ACTIVE to COMPLETED on sell fill."""
        # Setup active position
        sample_position.state = PositionState.ACTIVE
        sample_position.place_sell_order(
            order_id="sell1",
            price=Decimal("67890"),
            quantity=Decimal("0.003"),
        )

        # Fill sell order
        sample_position.handle_sell_fill(
            order_id="sell1",
            filled_price=Decimal("67890"),
            filled_quantity=Decimal("0.003"),
        )

        assert sample_position.state == PositionState.COMPLETED


class TestOrderPlacement:
    """Test order placement and ONE pending order constraint."""

    def test_can_place_order_when_no_pending(self, sample_position):
        """Test can place order when no pending order exists."""
        assert sample_position.can_place_order() is True

    def test_cannot_place_order_when_pending_exists(self, sample_position):
        """Test cannot place order when pending order exists."""
        sample_position.place_buy_order(
            order_id="order1",
            price=Decimal("66792.78"),
            quantity=Decimal("0.003"),
            dca_level=0,
        )

        assert sample_position.can_place_order() is False

    def test_place_buy_order_sets_pending(self, sample_position):
        """Test placing buy order sets pending_order."""
        sample_position.place_buy_order(
            order_id="order1",
            price=Decimal("66792.78"),
            quantity=Decimal("0.003"),
            dca_level=0,
        )

        assert sample_position.pending_order is not None
        assert sample_position.pending_order.order_id == "order1"
        assert sample_position.pending_order.status == "NEW"
        assert len(sample_position.buy_orders) == 1

    def test_place_order_fails_when_pending_exists(self, sample_position):
        """Test placing order fails when another order is pending."""
        sample_position.place_buy_order(
            order_id="order1",
            price=Decimal("66792.78"),
            quantity=Decimal("0.003"),
            dca_level=0,
        )

        with pytest.raises(RuntimeError, match="pending order order1 exists"):
            sample_position.place_buy_order(
                order_id="order2",
                price=Decimal("66046.50"),
                quantity=Decimal("0.003"),
                dca_level=1,
            )

    def test_order_fill_clears_pending(self, sample_position):
        """Test order fill clears pending_order."""
        sample_position.place_buy_order(
            order_id="order1",
            price=Decimal("66792.78"),
            quantity=Decimal("0.003"),
            dca_level=0,
        )

        sample_position.handle_order_fill(
            order_id="order1",
            filled_price=Decimal("66792.78"),
            filled_quantity=Decimal("0.003"),
        )

        assert sample_position.pending_order is None
        assert sample_position.can_place_order() is True

    def test_order_cancel_clears_pending(self, sample_position):
        """Test order cancellation clears pending_order."""
        sample_position.place_buy_order(
            order_id="order1",
            price=Decimal("66792.78"),
            quantity=Decimal("0.003"),
            dca_level=0,
        )

        sample_position.handle_order_cancel(order_id="order1")

        assert sample_position.pending_order is None
        assert sample_position.can_place_order() is True
        assert sample_position.buy_orders[0].status == "CANCELED"


class TestTopInvalidation:
    """Test top detection and invalidation."""

    def test_invalidate_top_cancels_pending_order(self, sample_position):
        """Test invalidating top cancels pending order."""
        sample_position.set_potential_top(Decimal("67890"))
        sample_position.place_buy_order(
            order_id="order1",
            price=Decimal("66792.78"),
            quantity=Decimal("0.003"),
            dca_level=0,
        )

        sample_position.invalidate_top()

        assert sample_position.pending_order is None
        assert sample_position.buy_orders[0].status == "CANCELED"

    def test_invalidate_top_resets_to_watching(self, sample_position):
        """Test invalidating top resets state to WATCHING."""
        sample_position.set_potential_top(Decimal("67890"))
        sample_position.invalidate_top()

        assert sample_position.state == PositionState.WATCHING
        assert sample_position.top_price is None

    def test_invalidate_top_does_not_affect_active_position(self, sample_position):
        """Test invalidating top doesn't affect ACTIVE position."""
        # Create active position
        sample_position.state = PositionState.ACTIVE
        sample_position.confirmed_top = Decimal("67890")

        sample_position.invalidate_top()

        # State should remain ACTIVE
        assert sample_position.state == PositionState.ACTIVE


class TestDCAProgression:
    """Test DCA level progression."""

    def test_initial_dca_level_is_zero(self, sample_position):
        """Test initial DCA level is 0."""
        assert sample_position.next_dca_level == 0

    def test_dca_level_advances_on_fill(self, sample_position):
        """Test DCA level advances after each fill."""
        # Fill Order 1 (φ)
        sample_position.place_buy_order(
            order_id="order1",
            price=Decimal("66792.78"),
            quantity=Decimal("0.003"),
            dca_level=0,
        )
        sample_position.handle_order_fill(
            order_id="order1",
            filled_price=Decimal("66792.78"),
            filled_quantity=Decimal("0.003"),
        )
        assert sample_position.next_dca_level == 1

        # Fill Order 2 (e)
        sample_position.place_buy_order(
            order_id="order2",
            price=Decimal("66046.50"),
            quantity=Decimal("0.003"),
            dca_level=1,
        )
        sample_position.handle_order_fill(
            order_id="order2",
            filled_price=Decimal("66046.50"),
            filled_quantity=Decimal("0.003"),
        )
        assert sample_position.next_dca_level == 2

        # Fill Order 3 (π)
        sample_position.place_buy_order(
            order_id="order3",
            price=Decimal("65758.30"),
            quantity=Decimal("0.003"),
            dca_level=2,
        )
        sample_position.handle_order_fill(
            order_id="order3",
            filled_price=Decimal("65758.30"),
            filled_quantity=Decimal("0.003"),
        )
        assert sample_position.next_dca_level == 3

    def test_max_dca_reached(self, sample_position):
        """Test max DCA detection."""
        assert sample_position.has_max_dca_reached() is False

        # Fill all 3 DCA orders
        for i in range(3):
            sample_position.place_buy_order(
                order_id=f"order{i + 1}",
                price=Decimal("66000"),
                quantity=Decimal("0.003"),
                dca_level=i,
            )
            sample_position.handle_order_fill(
                order_id=f"order{i + 1}",
                filled_price=Decimal("66000"),
                filled_quantity=Decimal("0.003"),
            )

        assert sample_position.has_max_dca_reached() is True


class TestPositionMetrics:
    """Test position investment and profit calculations."""

    def test_total_invested_updates_on_fill(self, sample_position):
        """Test total invested updates correctly."""
        sample_position.place_buy_order(
            order_id="order1",
            price=Decimal("66792.78"),
            quantity=Decimal("0.003"),
            dca_level=0,
        )
        sample_position.handle_order_fill(
            order_id="order1",
            filled_price=Decimal("66792.78"),
            filled_quantity=Decimal("0.003"),
        )

        expected = Decimal("66792.78") * Decimal("0.003")
        assert sample_position.total_invested == expected

    def test_average_entry_calculation(self, sample_position):
        """Test average entry price calculation."""
        # First fill
        sample_position.place_buy_order(
            order_id="order1",
            price=Decimal("66792.78"),
            quantity=Decimal("0.003"),
            dca_level=0,
        )
        sample_position.handle_order_fill(
            order_id="order1",
            filled_price=Decimal("66792.78"),
            filled_quantity=Decimal("0.003"),
        )

        assert sample_position.average_entry == Decimal("66792.78")

        # Second fill
        sample_position.place_buy_order(
            order_id="order2",
            price=Decimal("66046.50"),
            quantity=Decimal("0.003"),
            dca_level=1,
        )
        sample_position.handle_order_fill(
            order_id="order2",
            filled_price=Decimal("66046.50"),
            filled_quantity=Decimal("0.003"),
        )

        # Average should be weighted
        total_cost = (Decimal("66792.78") * Decimal("0.003")) + (
            Decimal("66046.50") * Decimal("0.003")
        )
        total_qty = Decimal("0.006")
        expected_avg = total_cost / total_qty

        assert sample_position.average_entry == expected_avg

    def test_profit_calculation(self, sample_position):
        """Test profit calculation on position close."""
        # Buy at 66792.78
        sample_position.place_buy_order(
            order_id="order1",
            price=Decimal("66792.78"),
            quantity=Decimal("0.003"),
            dca_level=0,
        )
        sample_position.handle_order_fill(
            order_id="order1",
            filled_price=Decimal("66792.78"),
            filled_quantity=Decimal("0.003"),
        )

        # Sell at 67890
        sample_position.state = PositionState.ACTIVE
        sample_position.place_sell_order(
            order_id="sell1",
            price=Decimal("67890"),
            quantity=Decimal("0.003"),
        )
        sample_position.handle_sell_fill(
            order_id="sell1",
            filled_price=Decimal("67890"),
            filled_quantity=Decimal("0.003"),
        )

        # Profit = (67890 - 66792.78) * 0.003
        expected_profit = (Decimal("67890") - Decimal("66792.78")) * Decimal("0.003")
        assert sample_position.get_profit() == expected_profit

    def test_profit_percentage_calculation(self, sample_position):
        """Test profit percentage calculation."""
        # Buy at 100
        sample_position.place_buy_order(
            order_id="order1",
            price=Decimal("100"),
            quantity=Decimal("1"),
            dca_level=0,
        )
        sample_position.handle_order_fill(
            order_id="order1",
            filled_price=Decimal("100"),
            filled_quantity=Decimal("1"),
        )

        # Sell at 110 (10% profit)
        sample_position.state = PositionState.ACTIVE
        sample_position.place_sell_order(
            order_id="sell1",
            price=Decimal("110"),
            quantity=Decimal("1"),
        )
        sample_position.handle_sell_fill(
            order_id="sell1",
            filled_price=Decimal("110"),
            filled_quantity=Decimal("1"),
        )

        assert sample_position.get_profit_percentage() == Decimal("10")


class TestSerialization:
    """Test position serialization."""

    def test_to_dict_includes_all_fields(self, sample_position):
        """Test to_dict includes all important fields."""
        data = sample_position.to_dict()

        assert data["position_id"] == "test_pos_1"
        assert data["symbol"] == "BTCUSDC"
        assert data["state"] == "WATCHING"
        assert data["top_price"] is None
        assert data["total_invested"] == "0"
        assert data["next_dca_level"] == 0
        assert data["pending_order"] is None

    def test_to_dict_with_pending_order(self, sample_position):
        """Test to_dict includes pending order details."""
        sample_position.place_buy_order(
            order_id="order1",
            price=Decimal("66792.78"),
            quantity=Decimal("0.003"),
            dca_level=0,
        )

        data = sample_position.to_dict()
        assert data["pending_order"] is not None
        assert data["pending_order"]["order_id"] == "order1"
        assert data["pending_order"]["price"] == "66792.78"
        assert data["pending_order"]["dca_level"] == 0
