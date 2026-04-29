from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class InventoryItem:
    id: str
    coin: str
    buy_price: float
    quantity: float
    available_quantity: float
    locked_quantity: float
    source: str = "UNKNOWN"
    timestamp: Optional[Any] = None
    notes: str = ""
