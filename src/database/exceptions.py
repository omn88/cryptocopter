"""
Database exceptions for the trading system.
"""


class DatabaseError(Exception):
    """Base exception for database operations."""


class RecoveryError(DatabaseError):
    """Exception raised during position recovery operations."""


class DatabaseConnectionError(DatabaseError):
    """Exception raised for database connection issues."""


class IntegrityError(DatabaseError):
    """Exception raised for data integrity violations."""
