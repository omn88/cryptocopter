"""BuyDipConfig - Configuration validation for Buy Dip strategy.

Validates strategy parameters including:
- Order size percentage (must be > 0 and <= 100)
- DCA distances (must be non-empty list)
- Mathematical constants (φ, e, π percentages)
"""

from typing import List, Optional


class BuyDipConfig:
    """Configuration for Buy Dip strategy with validation."""

    def __init__(
        self,
        order_size_percentage: float = 2.0,
        dca_distances_pct: Optional[List[float]] = None,
        min_consecutive_rising: int = 3,
        min_total_gain_pct: float = 0.25,
        # Invalidation controls
        invalidation_cooldown_seconds: float = 0.15,
        invalidation_min_delta_pct: float = 0.01,
        # Sell order management (ticker-based)
        sell_placement_distance_pct: float = 2.0,
        sell_cancellation_distance_pct: float = 4.0,
    ):
        """Initialize and validate configuration.

        Args:
            order_size_percentage: Order size as % of available budget (default: 2%)
            dca_distances_pct: DCA distances below top as list of percentages
                Example: [1.618, 2.718, 3.142] for 3 levels
                Example: [1.0, 2.0, 3.0, 4.0, 5.0, 6.0] for 6 levels
                Default: [φ=1.618, e=2.718, π=3.142] (mathematical constants)
                Can be ANY number of levels (minimum 1)
            min_consecutive_rising: Min consecutive rising candles (default: 3)
            min_total_gain_pct: Min total gain % for rising pattern (default: 0.25%)
            sell_placement_distance_pct: Place sell when price within this % of top (default: 2%)
            sell_cancellation_distance_pct: Cancel sell when price drops this % from top (default: 4%)

        Raises:
            ValueError: If any validation fails
        """
        # Set defaults - elegant mathematical constants
        if dca_distances_pct is None:
            dca_distances_pct = [1.618, 2.718, 3.142]  # φ, e, π

        # Store attributes
        self.order_size_percentage = order_size_percentage
        self.dca_distances_pct = sorted(dca_distances_pct)  # Always sort ascending
        self.min_consecutive_rising = min_consecutive_rising
        self.min_total_gain_pct = min_total_gain_pct
        # Invalidation tuning
        self.invalidation_cooldown_seconds = invalidation_cooldown_seconds
        self.invalidation_min_delta_pct = invalidation_min_delta_pct
        # Sell order management (ticker-based)
        self.sell_placement_distance_pct = sell_placement_distance_pct
        self.sell_cancellation_distance_pct = sell_cancellation_distance_pct

        # Validate on initialization
        self.validate()

    def validate(self) -> None:
        """Validate all configuration parameters.

        Raises:
            ValueError: If any parameter is invalid
        """
        # Validate order size percentage
        if self.order_size_percentage <= 0:
            raise ValueError("order_size_percentage must be > 0")
        if self.order_size_percentage > 100:
            raise ValueError("order_size_percentage must be <= 100")

        # Validate DCA distances
        if not self.dca_distances_pct:
            raise ValueError("dca_distances_pct must not be empty")

        # Validate each distance is positive
        for i, distance in enumerate(self.dca_distances_pct):
            if distance <= 0:
                raise ValueError(f"dca_distances_pct[{i}] must be > 0, got {distance}")
            if distance >= 100:
                raise ValueError(
                    f"dca_distances_pct[{i}] must be < 100, got {distance}"
                )

        # Warn if distances are not sorted (we auto-sort but let user know)
        if self.dca_distances_pct != sorted(self.dca_distances_pct):
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(
                f"DCA distances auto-sorted: {self.dca_distances_pct} "
                f"→ {sorted(self.dca_distances_pct)}"
            )

        # Validate sell order management thresholds
        if self.sell_placement_distance_pct <= 0:
            raise ValueError("sell_placement_distance_pct must be > 0")
        if self.sell_cancellation_distance_pct <= 0:
            raise ValueError("sell_cancellation_distance_pct must be > 0")
        if self.sell_placement_distance_pct >= self.sell_cancellation_distance_pct:
            raise ValueError(
                f"sell_placement_distance_pct ({self.sell_placement_distance_pct}) "
                f"must be < sell_cancellation_distance_pct ({self.sell_cancellation_distance_pct})"
            )
