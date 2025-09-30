import asyncio
from dataclasses import dataclass, field
import datetime
from enum import Enum, auto
import logging
import queue
import time
from typing import Dict, List, NamedTuple, Optional, Union, Any
from binance.enums import ORDER_TYPE_LIMIT, TIME_IN_FORCE_GTC, ORDER_STATUS_NEW
from binance import AsyncClient
from src.common.symbol import Symbol


@dataclass
class InventoryItem:
    id: str
    coin: str
    buy_price: float
    quantity: float
    available_quantity: float
    locked_quantity: float
    source: str = "UNKNOWN"  # Add default value for source
    timestamp: Optional[Any] = None  # Add timestamp field
    notes: str = ""  # Add notes field


@dataclass
class HPSellPositionCreated:
    """Event data for when an HP sell position is created (locks quantities)."""

    hp_id: str
    coin: str
    quantity: float
    buy_price: float
    sell_price: float
    end_currency: str  # Usually USDC


@dataclass
class HPBuyPositionCreated:
    """Event data for when an HP buy position is created (locks budget)."""

    hp_id: str
    coin: str
    budget: float
    price_low: float
    price_high: float
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


class State(Enum):
    NEW = "NEW"
    BUYING = "BUYING"
    PARTIALLY_BOUGHT = "PARTIALLY_BOUGHT"
    BOUGHT = "BOUGHT"
    READY_TO_SELL = "READY_TO_SELL"
    SELLING = "SELLING"
    PARTIALLY_SOLD = "PARTIALLY_SOLD"
    SOLD = "SOLD"
    PART_SOLD_PART_BOUGHT = "PART_SOLD_PART_BOUGHT"
    SOLD_PART_BOUGHT = "SOLD_PART_BOUGHT"
    CLOSED = "CLOSED"
    WAITING_CHILD = "WAITING_CHILD"
    NONE = ""


class Signal(Enum):
    HP_ALL_ORDERS_FILLED = "HP_ALL_ORDERS_FILLED"
    NULL = "NULL"


class SignalUpdate(NamedTuple):
    signal: Signal = Signal.NULL

    def __repr__(self) -> str:
        return f"SignalUpdate(signal={self.signal})"


class EventName(Enum):
    ACCOUNT_POSITION = "outboundAccountPosition"
    EXECUTION_REPORT = "executionReport"
    ERROR = "error"
    SIGNAL = "Signal"
    SENTINEL = "Sentinel"
    TICKER = "Ticker"
    ALL_TICKERS = "All"
    PRICE_UPDATES = "PriceUpdates"
    PORTFOLIO_INVENTORY = "PortfolioInventory"
    # HP Manager → Portfolio Events
    HP_SELL_POSITION_CREATED = "HP_SELL_POSITION_CREATED"
    HP_SELL_POSITION_PARTIALLY_FILLED = "HP_SELL_POSITION_PARTIALLY_FILLED"
    HP_SELL_POSITION_COMPLETED = "HP_SELL_POSITION_COMPLETED"
    HP_BUY_POSITION_CREATED = "HP_BUY_POSITION_CREATED"
    HP_BUY_ORDERS_PLACED = "HP_BUY_ORDERS_PLACED"
    HP_BUY_POSITION_FILLED = "HP_BUY_POSITION_FILLED"
    HP_BUY_POSITION_PARTIALLY_FILLED = "HP_BUY_POSITION_PARTIALLY_FILLED"
    HP_POSITION_CANCELLED = "HP_POSITION_CANCELLED"


class CsvConfig(NamedTuple):
    symbol: str
    side: str
    price_low: float
    price_high: float
    budget: float
    order_trigger: float
    mode: str


class UiState(Enum):
    NEW = "NEW"
    OPEN = "OPEN"
    STAGNATED = "STAGNATED"
    CLOSED = "CLOSED"


@dataclass
class Order:
    quantity: float
    precision: int = 0
    price_precision: int = 0
    price: float = 0
    quantity_stable: float = 0
    order_id: int = 0
    realized_quantity: float = 0
    open_time = None
    time_in_force: str = TIME_IN_FORCE_GTC
    status: str = ORDER_STATUS_NEW
    order_type: str = ORDER_TYPE_LIMIT

    def __repr__(self) -> str:
        return (
            f"Order(price={self.price:.{self.price_precision}f}, quantity={self.quantity:.{self.precision}f}, "
            f"quantity_stable={self.quantity_stable}, order_id={self.order_id}, "
            f"realized_quantity={self.realized_quantity:.{self.precision}f}, open_time={self.open_time}, "
            f"time_in_force={self.time_in_force}, status={self.status}, "
            f"order_type={self.order_type})"
        )


@dataclass
class ExecutionReport:
    symbol: str = ""
    client_order_id: str = ""
    side: str = ""
    order_type: str = ""
    time_in_force: str = ""
    quantity: float = 0.0
    price: float = 0.0
    stop_price: float = 0.0
    iceberg_quantity: float = 0.0
    order_list_id: int = 0
    original_client_order_id: str = ""
    current_execution_type: str = ""
    current_order_status: str = ""
    order_reject_reason: str = ""
    order_id: int = 0
    last_executed_quantity: float = 0.0
    cumulative_filled_quantity: float = 0.0
    last_executed_price: float = 0.0
    commission_amount: Optional[float] = None
    commission_asset: Optional[str] = None
    transaction_time: int = 0
    trade_id: int = 0
    ignore_1: int = 0
    is_order_working: bool = False
    is_trade_maker_side: bool = False
    ignore_2: bool = False
    order_creation_time: int = 0
    cumulative_quote_asset_transacted_quantity: float = 0.0
    last_quote_asset_transacted_quantity: float = 0.0
    quote_order_quantity: float = 0.0
    working_time: int = 0
    self_trade_prevention_mode: str = ""

    def __str__(self):
        return (
            f"ExecutionReport(symbol={self.symbol}, client_order_id={self.client_order_id}, side={self.side}, "
            f"order_type={self.order_type}, time_in_force={self.time_in_force}, quantity={self.quantity}, "
            f"price={self.price}, stop_price={self.stop_price}, iceberg_quantity={self.iceberg_quantity}, "
            f"order_list_id={self.order_list_id}, original_client_order_id={self.original_client_order_id}, "
            f"current_execution_type={self.current_execution_type}, current_order_status={self.current_order_status}, "
            f"order_reject_reason={self.order_reject_reason}, order_id={self.order_id}, last_executed_quantity={self.last_executed_quantity}, "
            f"cumulative_filled_quantity={self.cumulative_filled_quantity}, last_executed_price={self.last_executed_price}, "
            f"commission_amount={self.commission_amount}, commission_asset={self.commission_asset}, transaction_time={self.transaction_time}, "
            f"trade_id={self.trade_id}, ignore_1={self.ignore_1}, is_order_working={self.is_order_working}, is_trade_maker_side={self.is_trade_maker_side}, "
            f"ignore_2={self.ignore_2}, order_creation_time={self.order_creation_time}, cumulative_quote_asset_transacted_quantity={self.cumulative_quote_asset_transacted_quantity}, "
            f"last_quote_asset_transacted_quantity={self.last_quote_asset_transacted_quantity}, quote_order_quantity={self.quote_order_quantity}, "
            f"working_time={self.working_time}, self_trade_prevention_mode={self.self_trade_prevention_mode})"
        )


@dataclass
class Balance:
    coin: str = ""
    free: float = 0.0
    locked: float = 0.0

    def __str__(self):
        return f"Balance(coin={self.coin}, free={self.free}, locked={self.locked})"


@dataclass
class AccountPosition:
    event_time: int = 0
    last_update_time: int = 0
    balances: List[Balance] = field(default_factory=list)

    def __str__(self):
        balances_str = ", ".join(str(balance) for balance in self.balances)
        return (
            f"AccountPosition(event_time={self.event_time}, last_update_time={self.last_update_time}, "
            f"balances=[{balances_str}])"
        )


class AllTickers(NamedTuple):
    msg: List[Dict]


class PriceUpdates(NamedTuple):
    msg: Dict[str, float]


class ErrorMessage(NamedTuple):
    msg: Dict


class TickerUpdate(NamedTuple):
    symbol: str = ""
    last_price: float = 0
    best_bid_price: float = 0
    best_ask_price: float = 0
    high_price: float = 0
    low_price: float = 0
    volume: float = 0

    def __repr__(self):
        return (
            f"TickerUpdate(symbol={self.symbol}, last_price={self.last_price}, best_bid_price={self.best_bid_price}, "
            f"best_ask_price={self.best_ask_price}, high_price={self.high_price}, "
            f"low_price={self.low_price}, volume={self.volume})"
        )


class Event(NamedTuple):
    name: EventName
    content: Union[
        SignalUpdate,
        TickerUpdate,
        ExecutionReport,
        AccountPosition,
        AllTickers,
        PriceUpdates,
        ErrorMessage,
        List[InventoryItem],
        HPBuyPositionCreated,
    ]

    def __repr__(self) -> str:
        return f"Event(name={self.name}, content={self.content})"


class PositionSide(Enum):
    LONG = "BUY"
    SHORT = "SELL"
    FLAT = "FLAT"


class RemoveRecord(NamedTuple):
    hp_id: str
    symbol: str
    side: PositionSide

    def __str__(self):
        return f"RemoveRecord(hp_id='{self.hp_id}', symbol='{self.symbol}', side='{self.side}')"


class Mode(Enum):
    SINGLE = "SINGLE"
    DCA = "DCA"


@dataclass
class StateInfo:
    state: State = State.NEW
    open_time: str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    close_time: str = ""
    side: PositionSide = PositionSide.LONG
    completeness: float = 0.0
    ui_state: UiState = UiState.NEW

    def __str__(self):
        return (
            f"StateInfo(state={self.state},"
            f"open_time='{self.open_time}', close_time='{self.close_time}', side={self.side}, ui_state={self.ui_state}, "
            f"completeness={self.completeness:.2f})"
        )

    def generate_open_time(self):
        self.open_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def get_completeness(self, orders: Union[Order, List[Order]]):
        if isinstance(orders, List):
            realized_quantity = sum(order.realized_quantity for order in orders)
            quantity = sum(order.quantity for order in orders)
        else:
            assert isinstance(orders, Order)
            realized_quantity = orders.realized_quantity
            quantity = orders.quantity

        if quantity:
            self.completeness = round(float(realized_quantity) / float(quantity), 2)
        else:
            self.completeness = 0.0


@dataclass
class HPBuyConfig:
    symbol: Symbol
    coin: str
    hp_id: str = "0"
    price_low: float = 0
    price_high: float = 0
    order_trigger: float = 0
    order_cancel: float = 0
    budget: float = 0
    mode: Mode = Mode.DCA

    def __post_init__(self):
        """Ensure order_cancel is always set correctly based on order_trigger"""
        if self.order_trigger:
            self.order_cancel = 2 * self.order_trigger

    def __str__(self):
        return (
            f"HPBuyConfig(hp_id={self.hp_id}, symbol={self.symbol}"
            f"price_low={self.price_low}, price_high={self.price_high}, "
            f"order_trigger={self.order_trigger}, budget={self.budget}, mode={self.mode})"
        )


@dataclass
class HPBuy:
    config: HPBuyConfig
    state_info: StateInfo

    def __str__(self):
        return f"HPBuy(config={self.config}, state_info={self.state_info})"


@dataclass
class HPSellConfig:
    symbol: Symbol
    hp_id: str = ""
    coin: str = ""
    quantity: float = 0.0
    buy_price: float = 0.0
    sell_price: float = 0.0
    end_currency: str = "USDC"
    is_child: bool = False
    parent_hp_id: Optional[str] = None

    def __str__(self):
        return (
            f"HPSellConfig(hp_id={self.hp_id}, coin={self.coin}, "
            f"quantity={self.quantity}, buy_price={self.buy_price}, "
            f"sell_price={self.sell_price}, end_currency={self.end_currency}, symbol={self.symbol})"
        )


class SellType(Enum):
    DIRECT = auto()
    TWOHOPS = auto()
    CONVERT = auto()


@dataclass
class SellPosition:
    sell_order: Order
    config: HPSellConfig
    state_info: StateInfo
    sell_type: SellType = SellType.DIRECT


@dataclass
class HPSell:
    config: HPSellConfig
    state_info: StateInfo

    def __str__(self):
        return f"HPSell(config={self.config}, state_info={self.state_info})"


class SubscriptionType(Enum):
    PRICE = auto()
    USER = auto()


class SubscriptionTarget(Enum):
    FRONTEND = auto()
    BACKEND = auto()
    PORTFOLIO = auto()


class SubscriptionInfo(NamedTuple):
    data_type: SubscriptionType
    symbol: str
    target: SubscriptionTarget
    queue: queue.Queue


class BinanceClient(AsyncClient):
    def __init__(self, api_key: str, api_secret: str, sync_interval: int = 60):
        super().__init__(api_key, api_secret)
        self.time_difference: float = 0.0
        self.sync_interval: int = sync_interval
        self.last_sync: float = 0.0
        self.logger = logging.getLogger(__name__)
        # asyncio.create_task(self.time_sync_loop())

    async def time_sync_loop(self):
        while True:
            try:
                self.time_difference = await self.get_server_time_difference()
                self.last_sync = time.time()
            except Exception as e:
                self.logger.info("Failed to sync time: %s", e)
            await asyncio.sleep(self.sync_interval)

    async def get_server_time_difference(self) -> float:
        server_time = await self.get_server_time()
        server_time = server_time["serverTime"] / 1000  # Convert from ms to s
        local_time = time.time()
        return local_time - server_time

    async def get_adjusted_time(self) -> float:
        if time.time() - self.last_sync > self.sync_interval:
            self.time_difference = await self.get_server_time_difference()
            self.last_sync = time.time()
        return time.time() - self.time_difference
