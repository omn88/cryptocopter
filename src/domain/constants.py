"""Exchange-agnostic order constants.

Single source of truth for order status, type, and time-in-force strings.
The Kraken adapter normalises exchange-native values to these before they
reach the domain layer.
"""

# Order statuses
ORDER_STATUS_NEW = "NEW"
ORDER_STATUS_OPEN = "OPEN"  # Kraken uses "open" for both NEW and PARTIALLY_FILLED
ORDER_STATUS_FILLED = "FILLED"
ORDER_STATUS_PARTIALLY_FILLED = "PARTIALLY_FILLED"
ORDER_STATUS_CANCELED = "CANCELED"
ORDER_STATUS_EXPIRED = "EXPIRED"

# Order types
ORDER_TYPE_LIMIT = "LIMIT"
ORDER_TYPE_MARKET = "MARKET"

# Time in force
TIME_IN_FORCE_GTC = "GTC"
