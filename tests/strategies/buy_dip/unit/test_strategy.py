"""
Unit tests for BuyDipStrategy orchestrator.

Tests the main strategy coordinator that integrates all detection
components and manages position lifecycle.
"""

import pytest
from decimal import Decimal

from src.strategies.buy_dip.strategy import BuyDipStrategy
from src.strategies.buy_dip.config import BuyDipConfig
from src.strategies.buy_dip.position import PositionState


@pytest.fixture
def sample_config():
    """Sample configuration for testing."""
    return BuyDipConfig(
        atr_period=14,
        order_size_percentage=2.0,
        dca_distances_pct=[1.0, 2.0, 3.0],
        min_consecutive_rising=3,
        min_total_gain_pct=0.25,
        atr_multiplier=2.0,
        min_pullback_pct=0.5,
    )


class TestStrategyInitialization:
    """Test strategy initialization and symbol management."""

    def test_initializes_with_config(self, sample_config):
        """Strategy initializes with configuration."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        assert strategy.config == sample_config
        assert len(strategy.get_all_positions()) == 0

    def test_adds_symbol_tracking(self, sample_config):
        """Can add symbols for tracking."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        strategy.add_symbol("BTCUSDC")

        # Verify components created
        assert "BTCUSDC" in strategy._candle_buffers
        assert "BTCUSDC" in strategy._atr_indicators
        assert "BTCUSDC" in strategy._rising_detectors
        assert "BTCUSDC" in strategy._hwm_detectors

    def test_add_symbol_idempotent(self, sample_config):
        """Adding same symbol multiple times is safe."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        strategy.add_symbol("BTCUSDC")
        buffer1 = strategy._candle_buffers["BTCUSDC"]

        strategy.add_symbol("BTCUSDC")
        buffer2 = strategy._candle_buffers["BTCUSDC"]

        assert buffer1 is buffer2  # Same instance


class TestCandleProcessing:
    """Test candle processing through detection pipeline."""

    @pytest.mark.asyncio
    async def test_processes_candle_for_new_symbol(self, sample_config, sample_candle):
        """Processes candle and auto-adds symbol if needed."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        await strategy.process_candle("BTCUSDC", sample_candle())

        # Verify symbol was added
        assert "BTCUSDC" in strategy._candle_buffers
        assert len(strategy._candle_buffers["BTCUSDC"].get_all()) == 1

    @pytest.mark.asyncio
    async def test_processes_multiple_candles(self, sample_config, sample_candle):
        """Processes multiple candles correctly."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        # Add 5 candles
        for i in range(5):
            candle = {**sample_candle(), "timestamp": 1000 + i * 60}
            await strategy.process_candle("BTCUSDC", candle)

        # Verify all candles stored
        candles = strategy._candle_buffers["BTCUSDC"].get_all()
        assert len(candles) == 5


class TestRisingPatternDetection:
    """Test rising pattern detection and position creation."""

    @pytest.mark.asyncio
    async def test_creates_position_on_rising_pattern(
        self, sample_candle, sample_config
    ):
        """Creates position when rising pattern detected."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        # Add 3 rising candles
        for i in range(3):
            candle = {
                **sample_candle(),
                "close": 100.0 + i * 10,  # Rising closes
                "high": 105.0 + i * 10,
                "timestamp": 1000 + i * 60,
            }
            await strategy.process_candle("BTCUSDC", candle)

        # Verify position created
        positions = strategy.get_all_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "BTCUSDC"
        # New behavior: Rising pattern creates POTENTIAL_TOP directly (not WATCHING)
        assert positions[0].state == PositionState.POTENTIAL_TOP

    @pytest.mark.asyncio
    async def test_no_position_without_budget(self, sample_candle, sample_config):
        """Does not create position if no budget available."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        # Allocate all budget
        strategy._budget_manager.lock_funds(200.0)

        # Try to create position with rising pattern
        for i in range(3):
            candle = {
                **sample_candle(),
                "close": 100.0 + i * 10,
                "timestamp": 1000 + i * 60,
            }
            await strategy.process_candle("BTCUSDC", candle)

        # No position created due to budget
        assert len(strategy.get_all_positions()) == 0

    @pytest.mark.asyncio
    async def test_does_not_duplicate_watching_position(
        self, sample_candle, sample_config
    ):
        """Does not create duplicate position for same symbol in POTENTIAL_TOP state."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        # Create first position with rising candles
        for i in range(3):
            candle = {
                **sample_candle(),
                "high": 100.0 + i * 10,  # Rising highs
                "close": 100.0 + i * 10,
                "timestamp": 1000 + i * 60,
            }
            await strategy.process_candle("BTCUSDC", candle)

        assert len(strategy.get_all_positions()) == 1

        # Try to create another (more rising candles)
        for i in range(3, 6):
            candle = {
                **sample_candle(),
                "high": 100.0 + i * 10,  # Rising highs
                "close": 100.0 + i * 10,
                "timestamp": 1000 + i * 60,
            }
            await strategy.process_candle("BTCUSDC", candle)

        # Still only one position
        assert len(strategy.get_all_positions()) == 1


class TestTopConfirmation:
    """Test top confirmation and order placement."""

    @pytest.mark.asyncio
    async def test_sets_potential_top_on_confirmation(
        self, sample_candle, sample_config
    ):
        """Sets potential top when confirmed."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        # Create position with rising pattern
        for i in range(3):
            candle = {
                **sample_candle(),
                "close": 100.0 + i * 10,
                "high": 100.0 + i * 10,
                "timestamp": 1000 + i * 60,
            }
            await strategy.process_candle("BTCUSDC", candle)

        position = strategy.get_all_positions()[0]
        # New behavior: Rising pattern creates POTENTIAL_TOP immediately
        assert position.state == PositionState.POTENTIAL_TOP
        assert position.top_price is not None

        # Add candle at the top
        candle = {
            **sample_candle(),
            "close": 120.0,
            "high": 120.0,
            "timestamp": 1000 + 3 * 60,
        }
        await strategy.process_candle("BTCUSDC", candle)

        # Position should remain in POTENTIAL_TOP with potentially updated top
        assert position.state == PositionState.POTENTIAL_TOP
        assert position.top_price is not None


class TestOrderPlacement:
    """Test order placement logic."""

    def test_places_order_for_position(self, sample_config):
        """Can place order for position."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        # Create position manually
        from src.strategies.buy_dip.position import BuyDipPosition

        position = BuyDipPosition(
            position_id="test_pos",
            symbol="BTCUSDC",
            dca_distances_pct=[1.0, 2.0, 3.0],
            order_size=Decimal("200"),
        )
        position.set_potential_top(Decimal("100.0"))
        strategy._positions["test_pos"] = position

        # Place order
        success = strategy.place_order("test_pos", 99.0, "order_123")

        assert success is True
        assert position.pending_order is not None
        assert position.pending_order.order_id == "order_123"
        assert "order_123" in strategy._order_to_position

    def test_cannot_place_order_with_pending(self, sample_config):
        """Cannot place order if position has pending order."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        # Create position with pending order
        from src.strategies.buy_dip.position import BuyDipPosition

        position = BuyDipPosition(
            position_id="test_pos",
            symbol="BTCUSDC",
            dca_distances_pct=[1.0, 2.0, 3.0],
            order_size=Decimal("200"),
        )
        position.set_potential_top(Decimal("100.0"))
        position.place_buy_order("order_1", Decimal("99.0"), Decimal("2.0"), 0)
        strategy._positions["test_pos"] = position

        # Try to place another order
        success = strategy.place_order("test_pos", 98.0, "order_2")

        assert success is False
        assert position.pending_order.order_id == "order_1"  # Original order unchanged


class TestOrderFills:
    """Test order fill handling."""

    def test_handles_order_fill(self, sample_config):
        """Handles order fill and updates position."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        # Create position and place order
        from src.strategies.buy_dip.position import BuyDipPosition

        position = BuyDipPosition(
            position_id="test_pos",
            symbol="BTCUSDC",
            dca_distances_pct=[1.0, 2.0, 3.0],
            order_size=Decimal("200"),
        )
        position.set_potential_top(Decimal("100.0"))
        strategy._positions["test_pos"] = position
        strategy.place_order("test_pos", 99.0, "order_123")

        # Handle fill
        strategy.handle_order_fill("order_123", 99.0, 2.0)

        # Verify position updated
        assert position.state == PositionState.ACTIVE
        assert position.total_quantity == Decimal("2.0")
        # Strategy auto-places next DCA order after fill
        assert position.pending_order is not None
        assert position.pending_order.dca_level == 1  # Next DCA level
        assert "order_123" not in strategy._order_to_position

    def test_places_next_dca_after_fill(self, sample_config):
        """Automatically places next DCA order after fill."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        # Create position and place first order
        from src.strategies.buy_dip.position import BuyDipPosition

        position = BuyDipPosition(
            position_id="test_pos",
            symbol="BTCUSDC",
            dca_distances_pct=[1.0, 2.0, 3.0],
            order_size=Decimal("200"),
        )
        position.set_potential_top(Decimal("100.0"))
        strategy._positions["test_pos"] = position
        strategy.place_order("test_pos", 99.0, "order_1")

        # Handle fill - should auto-place next DCA
        strategy.handle_order_fill("order_1", 99.0, 2.0)

        # Verify next DCA level order placed
        assert position.next_dca_level == 1
        assert position.pending_order is not None


class TestOrderCancellation:
    """Test order cancellation handling."""

    def test_handles_order_cancel(self, sample_config):
        """Handles order cancellation and frees budget."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        # Create position and place order
        from src.strategies.buy_dip.position import BuyDipPosition

        position = BuyDipPosition(
            position_id="test_pos",
            symbol="BTCUSDC",
            dca_distances_pct=[1.0, 2.0, 3.0],
            order_size=Decimal("200"),
        )
        position.set_potential_top(Decimal("100.0"))
        strategy._positions["test_pos"] = position
        strategy.place_order("test_pos", 99.0, "order_123")

        budget_before = strategy._budget_manager.get_available_budget()

        # Handle cancel
        strategy.handle_order_cancel("order_123")

        # Verify budget freed
        budget_after = strategy._budget_manager.get_available_budget()
        assert budget_after > budget_before
        assert position.pending_order is None
        assert "order_123" not in strategy._order_to_position


class TestTopInvalidation:
    """Test top invalidation handling."""

    @pytest.mark.asyncio
    async def test_invalidates_top_on_new_high(self, sample_candle, sample_config):
        """Invalidates top and cancels orders when new high detected."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        # Create position with potential top
        from src.strategies.buy_dip.position import BuyDipPosition

        position = BuyDipPosition(
            position_id="test_pos",
            symbol="BTCUSDC",
            dca_distances_pct=[1.0, 2.0, 3.0],
            order_size=Decimal("200"),
        )
        position.set_potential_top(Decimal("100.0"))
        position.place_buy_order("order_123", Decimal("99.0"), Decimal("2.0"), 0)
        strategy._positions["test_pos"] = position
        strategy._symbol_positions["BTCUSDC"].append("test_pos")
        strategy._order_to_position["order_123"] = "test_pos"

        # Add symbol tracking
        strategy.add_symbol("BTCUSDC")

        # Process candle with new high (triggers invalidation in HWM detector)
        # First need to establish the top in HWM detector
        for i in range(10):
            candle = {
                **sample_candle(),
                "close": 100.0,
                "high": 100.0,
                "timestamp": 1000 + i * 60,
            }
            await strategy.process_candle("BTCUSDC", candle)

        # Now add a new high
        new_high_candle = {
            **sample_candle(),
            "close": 110.0,  # New high
            "high": 110.0,
            "timestamp": 1000 + 10 * 60,
        }
        await strategy.process_candle("BTCUSDC", new_high_candle)

        # Position should stay in POTENTIAL_TOP with updated top price
        assert position.state == PositionState.POTENTIAL_TOP
        assert position.top_price == Decimal("110.0")  # Updated to new high
        # New behavior: Replacement order placed immediately (not None)
        assert position.pending_order is not None
        assert position.pending_order.order_id != "order_123"  # Different order ID
        assert (
            "order_123" not in strategy._order_to_position
        )  # Old order removed from tracking


class TestMultiPositionManagement:
    """Test managing multiple positions across symbols."""

    def test_tracks_multiple_positions(self, sample_config):
        """Can track multiple positions for different symbols."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        # Create positions for different symbols
        from src.strategies.buy_dip.position import BuyDipPosition

        pos1 = BuyDipPosition(
            position_id="pos_1",
            symbol="BTCUSDC",
            dca_distances_pct=[1.0, 2.0, 3.0],
            order_size=Decimal("200"),
        )
        pos2 = BuyDipPosition(
            position_id="pos_2",
            symbol="ETHUSDC",
            dca_distances_pct=[1.0, 2.0, 3.0],
            order_size=Decimal("200"),
        )

        strategy._positions["pos_1"] = pos1
        strategy._positions["pos_2"] = pos2
        strategy._symbol_positions["BTCUSDC"].append("pos_1")
        strategy._symbol_positions["ETHUSDC"].append("pos_2")

        # Verify retrieval
        assert len(strategy.get_all_positions()) == 2
        assert len(strategy.get_positions_for_symbol("BTCUSDC")) == 1
        assert len(strategy.get_positions_for_symbol("ETHUSDC")) == 1

    def test_budget_shared_across_positions(self, sample_config):
        """Budget is shared across all positions."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        # Calculate expected order size: 2% of 10000 = 200
        # Each DCA level allocates: order_size / (1 - sum(dca_distances_pct/100))
        # With [1.0, 2.0, 3.0], total distance = 6%, allocation = 200 / (1-0.06) = 212.77

        initial_budget = strategy._budget_manager.get_available_budget()

        # Create and place order for first position
        from src.strategies.buy_dip.position import BuyDipPosition

        pos = BuyDipPosition(
            position_id="pos_1",
            symbol="BTCUSDC",
            dca_distances_pct=[1.0, 2.0, 3.0],
            order_size=Decimal("200"),
        )
        pos.set_potential_top(Decimal("100.0"))
        strategy._positions["pos_1"] = pos
        strategy.place_order("pos_1", 99.0, "order_1")

        # Budget should be reduced
        budget_after = strategy._budget_manager.get_available_budget()
        assert budget_after < initial_budget
        assert strategy._budget_manager.get_locked_budget() > Decimal("0")


class TestSellOrders:
    """Test sell order placement and handling."""

    def test_places_sell_order(self, sample_config):
        """Can place sell order for active position."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        # Create active position with quantity
        from src.strategies.buy_dip.position import BuyDipPosition

        position = BuyDipPosition(
            position_id="test_pos",
            symbol="BTCUSDC",
            dca_distances_pct=[1.0, 2.0, 3.0],
            order_size=Decimal("200"),
        )
        position.set_potential_top(Decimal("100.0"))
        position.place_buy_order("buy_order", Decimal("99.0"), Decimal("2.0"), 0)
        position.handle_order_fill("buy_order", Decimal("99.0"), Decimal("2.0"))
        strategy._positions["test_pos"] = position

        # Place sell order
        success = strategy.place_sell_order("test_pos", "sell_order_123")

        assert success is True
        assert position.sell_order is not None
        assert position.sell_order.order_id == "sell_order_123"

    def test_handles_sell_fill(self, sample_config):
        """Handles sell fill and frees budget."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        # Create active position with filled order
        from src.strategies.buy_dip.position import BuyDipPosition

        position = BuyDipPosition(
            position_id="test_pos",
            symbol="BTCUSDC",
            dca_distances_pct=[1.0, 2.0, 3.0],
            order_size=Decimal("200"),
        )
        position.set_potential_top(Decimal("100.0"))
        strategy._positions["test_pos"] = position

        # Place and fill buy order (allocates budget)
        strategy.place_order("test_pos", 99.0, "buy_order")
        strategy.handle_order_fill("buy_order", 99.0, 2.0)

        budget_allocated = strategy._budget_manager.get_locked_budget()

        # Place and fill sell order
        strategy.place_sell_order("test_pos", "sell_order")
        strategy._order_to_position["sell_order"] = "test_pos"
        strategy.handle_sell_fill("sell_order", 105.0)

        # Verify budget freed
        assert strategy._budget_manager.get_locked_budget() < budget_allocated
        assert position.state == PositionState.COMPLETED
        assert position.sell_order is not None
        assert position.sell_order.filled_price == Decimal("105.0")


class TestBudgetInfo:
    """Test budget information retrieval."""

    def test_returns_budget_info(self, sample_config):
        """Returns correct budget information."""
        strategy = BuyDipStrategy(
            config=sample_config,
            total_budget=Decimal("10000"),
            order_budget_pct=Decimal("2.0"),
        )

        info = strategy.get_budget_info()

        assert info["total"] == Decimal("10000")
        assert info["locked"] == Decimal("0")
        assert info["available"] == Decimal("10000")
        assert info["order_size"] == Decimal("200")  # 2% of 10000
