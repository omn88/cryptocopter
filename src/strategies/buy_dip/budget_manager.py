"""BudgetManager - Percentage-based budget management.

Manages available and locked budget for Buy Dip strategy.
Calculates order sizes as percentage of available budget.
Supports dynamic budget add/withdraw operations.
"""

from typing import Optional


class BudgetManager:
    """Manage budget with percentage-based order sizing."""

    def __init__(
        self,
        initial_budget: float,
        order_size_percentage: float = 2.0,
        min_order_size: float = 10.0,
    ):
        """Initialize budget manager.

        Args:
            initial_budget: Starting budget amount
            order_size_percentage: Percentage of available budget per order (default: 2%)
            min_order_size: Minimum order size (default: 10.0)
        """
        self._available_budget = initial_budget
        self._locked_budget = 0.0
        self._order_size_percentage = order_size_percentage
        self._min_order_size = min_order_size

    def calculate_order_size(self) -> Optional[float]:
        """Calculate order size based on available budget percentage.

        Returns:
            Order size, or None if insufficient budget (< min_order_size)
        """
        order_size = self._available_budget * (self._order_size_percentage / 100.0)
        return order_size if order_size >= self._min_order_size else None

    def lock_funds(self, amount: float) -> None:
        """Lock funds for a pending order.

        Args:
            amount: Amount to lock
        """
        self._available_budget -= amount
        self._locked_budget += amount

    def release_funds(self, amount: float, profit: float = 0.0) -> None:
        """Release locked funds after order fill/cancel.

        Args:
            amount: Locked amount to release
            profit: Profit from the trade (default: 0.0)
        """
        self._locked_budget -= amount
        self._available_budget += amount + profit

    def add_budget(self, amount: float) -> None:
        """Add budget to available funds.

        Args:
            amount: Amount to add
        """
        self._available_budget += amount

    def withdraw_budget(self, amount: float) -> None:
        """Withdraw budget from available funds.

        Args:
            amount: Amount to withdraw
        """
        self._available_budget -= amount

    def get_available_budget(self) -> float:
        """Get current available budget.

        Returns:
            Available budget amount
        """
        return self._available_budget

    def get_locked_budget(self) -> float:
        """Get current locked budget.

        Returns:
            Locked budget amount
        """
        return self._locked_budget
