from dataclasses import dataclass, field
from typing import Dict, List, NamedTuple, Optional, Union

from binance.enums import ORDER_STATUS_NEW, ORDER_TYPE_LIMIT, TIME_IN_FORCE_GTC

from src.domain.enums import EventName, Signal, SignalUpdate
from src.domain.events import (
    HPBuyOrdersPlaced,
    HPBuyPositionCreated,
    HPBuyPositionFilled,
    HPBuyPositionPartiallyFilled,
    HPPositionCancelled,
    HPSellPositionCompleted,
    HPSellPositionCreated,
    HPSellPositionPartiallyFilled,
)
from src.domain.inventory import InventoryItem


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
