"""
Trading constants and configuration values.

This module centralizes all magic numbers and constants used throughout the codebase.
Each constant is documented with its purpose and reasoning.
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class TradingConstants:
    """Core trading constants that control system behavior."""

    # ============================================================================
    # Price Trigger Multipliers
    # ============================================================================

    SELL_TRIGGER_MULTIPLIER: float = 0.96
    """Sell orders are triggered when price reaches 96% of target (4% below).
    
    This gives a safety margin to ensure orders execute before price drops too far.
    """

    BUY_TRIGGER_MULTIPLIER: float = 1.04
    """Buy orders are triggered when price reaches 104% of target (4% above).
    
    This ensures we don't miss opportunities when price is rising.
    """

    CANCEL_SELL_MULTIPLIER: float = 0.92
    """Cancel unfilled sell orders when price drops to 92% of target (8% below).
    
    If price drops this far, better to cancel and wait for better opportunity.
    """

    # ============================================================================
    # Polling and Refresh Intervals
    # ============================================================================

    QUEUE_POLL_INTERVAL: float = 0.1
    """Seconds to wait between queue polling attempts.
    
    Balance between responsiveness and CPU usage. 100ms is fast enough for
    trading while not overwhelming the system.
    """

    UI_REFRESH_INTERVAL: float = 1.0
    """Maximum UI refresh rate in seconds.
    
    Prevents excessive UI updates that can break button bindings and cause
    visual flickering. One refresh per second is sufficient for monitoring.
    """

    # ============================================================================
    # Order Management
    # ============================================================================

    MAX_ORDER_RETRIES: int = 10
    """Maximum number of times to retry a failed order.
    
    After 10 attempts with exponential backoff, order is marked as failed.
    Prevents infinite retry loops on persistent failures.
    """

    RETRY_DELAY: float = 1.0
    """Initial delay in seconds before retrying failed operation.
    
    Will be multiplied by exponential backoff factor on subsequent retries.
    """

    # ============================================================================
    # Position Configuration
    # ============================================================================

    MAX_MULTIHOP_LEGS: int = 2
    """Maximum number of legs in a multihop trade.
    
    Currently supports 2-hop trades (e.g., COIN→BTC→USDC).
    More legs increase complexity and failure points.
    """

    # ============================================================================
    # Database
    # ============================================================================

    DB_CONNECTION_TIMEOUT: float = 5.0
    """Seconds to wait for database connection before timing out."""

    DB_QUERY_TIMEOUT: float = 10.0
    """Seconds to wait for database query before timing out."""

    DB_MAX_RETRIES: int = 3
    """Maximum number of times to retry failed database operations."""

    # ============================================================================
    # WebSocket
    # ============================================================================

    WS_PING_INTERVAL: float = 20.0
    """Seconds between WebSocket ping messages to keep connection alive."""

    WS_RECONNECT_DELAY: float = 5.0
    """Seconds to wait before attempting WebSocket reconnection."""


# Global instance for easy access
TRADING: Final[TradingConstants] = TradingConstants()


# ============================================================================
# Usage Examples
# ============================================================================

"""
Instead of:
    if price >= target_price * 0.96:
        await send_sell_order()
    
Use:
    from src.common.constants import TRADING
    
    if price >= target_price * TRADING.SELL_TRIGGER_MULTIPLIER:
        await send_sell_order()

Instead of:
    await asyncio.sleep(0.1)
    
Use:
    await asyncio.sleep(TRADING.QUEUE_POLL_INTERVAL)
"""


# ============================================================================
# Environment-Specific Overrides (Future Enhancement)
# ============================================================================

"""
Future enhancement: Allow overriding via environment variables or config file.

Example:
    from pydantic import BaseSettings
    
    class Settings(BaseSettings):
        sell_trigger_multiplier: float = TRADING.SELL_TRIGGER_MULTIPLIER
        buy_trigger_multiplier: float = TRADING.BUY_TRIGGER_MULTIPLIER
        
        class Config:
            env_prefix = "TRADING_"
            env_file = ".env"
    
    settings = Settings()
    
Then use:
    if price >= target_price * settings.sell_trigger_multiplier:
        await send_sell_order()
"""
