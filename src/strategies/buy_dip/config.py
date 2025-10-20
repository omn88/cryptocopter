"""BuyDipConfig - Configuration validation for Buy Dip strategy.

Validates strategy parameters including:
- ATR period (must be >= 1)
- Order size percentage (must be > 0 and <= 100)
- DCA distances (must be non-empty list)
- Mathematical constants (φ, e, π percentages)
"""

from typing import List, Optional


class BuyDipConfig:
    """Configuration for Buy Dip strategy with validation."""

    def __init__(
        self,
        atr_period: int = 14,
        order_size_percentage: float = 2.0,
        dca_distances_pct: Optional[List[float]] = None,
        min_consecutive_rising: int = 3,
        min_total_gain_pct: float = 0.25,
        atr_multiplier: float = 2.0,
        min_pullback_pct: float = 0.5,
        # Invalidation controls
        invalidation_cooldown_seconds: float = 0.15,
        invalidation_min_delta_pct: float = 0.01,
        invalidation_atr_multiplier: float = 0.0,
    ):
        """Initialize and validate configuration.

        Args:
            atr_period: ATR calculation period (default: 14)
            order_size_percentage: Order size as % of available budget (default: 2%)
            dca_distances_pct: DCA distances below top (default: [φ=1.618, e=2.718, π=3.142])
            min_consecutive_rising: Min consecutive rising candles (default: 3)
            min_total_gain_pct: Min total gain % for rising pattern (default: 0.25%)
            atr_multiplier: ATR multiplier for adaptive threshold (default: 2.0)
            min_pullback_pct: Min pullback % for top confirmation (default: 0.5%)

        Raises:
            ValueError: If any validation fails
        """
        # Set defaults
        if dca_distances_pct is None:
            dca_distances_pct = [1.618, 2.718, 3.142]  # φ, e, π

        # Store attributes
        self.atr_period = atr_period
        self.order_size_percentage = order_size_percentage
        self.dca_distances_pct = dca_distances_pct
        self.min_consecutive_rising = min_consecutive_rising
        self.min_total_gain_pct = min_total_gain_pct
        self.atr_multiplier = atr_multiplier
        self.min_pullback_pct = min_pullback_pct
        # Invalidation tuning
        self.invalidation_cooldown_seconds = invalidation_cooldown_seconds
        self.invalidation_min_delta_pct = invalidation_min_delta_pct
        self.invalidation_atr_multiplier = invalidation_atr_multiplier

        # Validate on initialization
        self.validate()

    def validate(self) -> None:
        """Validate all configuration parameters.

        Raises:
            ValueError: If any parameter is invalid
        """
        # Validate ATR period
        if self.atr_period < 1:
            raise ValueError("atr_period must be >= 1")

        # Validate order size percentage
        if self.order_size_percentage <= 0:
            raise ValueError("order_size_percentage must be > 0")
        if self.order_size_percentage > 100:
            raise ValueError("order_size_percentage must be <= 100")

        # Validate DCA distances
        if not self.dca_distances_pct:
            raise ValueError("dca_distances_pct must not be empty")
