from dataclasses import dataclass, field
from decimal import Decimal
from typing import Union


@dataclass
class HPSellPositionCreated:
    """Event data for when an HP sell position is created (locks quantities)."""

    hp_id: str
    coin: str
    quantity: float
    buy_price: float
    sell_price: float
    end_currency: str  # Usually USDC

    def __post_init__(self):
        if isinstance(self.quantity, Decimal):
            self.quantity = float(self.quantity)
        if isinstance(self.buy_price, Decimal):
            self.buy_price = float(self.buy_price)
        if isinstance(self.sell_price, Decimal):
            self.sell_price = float(self.sell_price)


@dataclass
class HPBuyPositionCreated:
    """Event data for when an HP buy position is created (locks budget)."""

    hp_id: str
    coin: str
    budget: float
    buy_price: float
    end_currency: str  # Usually USDC


@dataclass
class HPSellPositionPartiallyFilled:
    """Event data for when an HP sell position is partially filled (reduces inventory incrementally)."""

    hp_id: str
    coin: str
    filled_quantity: float
    total_filled: float


@dataclass
class HPSellPositionCompleted:
    """Event data for when an HP sell position is completed (removes inventory, adds end currency)."""

    hp_id: str
    coin: str
    quantity_sold: float
    buy_price: float
    sell_price: float
    end_currency: str
    end_currency_received: float = field(init=False)

    def __post_init__(self):
        if isinstance(self.quantity_sold, Decimal):
            self.quantity_sold = float(self.quantity_sold)
        if isinstance(self.buy_price, Decimal):
            self.buy_price = float(self.buy_price)
        if isinstance(self.sell_price, Decimal):
            self.sell_price = float(self.sell_price)
        self.end_currency_received = self.quantity_sold * self.sell_price


@dataclass
class HPBuyPositionFilled:
    """Event data for when an HP buy position is filled (adds inventory)."""

    hp_id: str
    coin: str
    symbol: str
    quantity_bought: float
    buy_price: float
    total_cost: float


@dataclass
class HPBuyPositionPartiallyFilled:
    """Event data for when an HP buy position is partially filled (adds inventory incrementally)."""

    hp_id: str
    coin: str
    filled_quantity: float
    total_filled: float
    buy_price: float
    partial_cost: float


@dataclass
class HPBuyOrdersPlaced:
    """Event data for when HP buy orders are placed (locks budget in inventory)."""

    hp_id: str
    coin: str
    budget_amount: float
    end_currency: str  # Usually USDC


@dataclass
class HPPositionCancelled:
    """Event data for when an HP position is cancelled (unlocks quantities)."""

    hp_id: str
    coin: str
    quantity: float
    position_type: str  # "BUY" or "SELL"

    def __post_init__(self):
        if isinstance(self.quantity, Decimal):
            self.quantity = float(self.quantity)
