"""Base interface for sell execution strategies.

Provides the abstract contract that all sell strategies must implement.
Each strategy handles one specific sell scenario:
- DirectSellStrategy: coin → stable (simple)
- ConvertSellStrategy: coin → stable1, stable1 → stable2 (convert path)
- MultihopSellStrategy: coin → inter → stable (multihop routing)
"""

import queue
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from src.common.client import BinanceClient
from src.common.identifiers import ExecutionReport, TickerUpdate
from src.common.symbol import Symbol
from src.database import Database

if TYPE_CHECKING:
    from src.strategies.hp_manager_v2.position_buy_v2 import HPPositionBuyV2


class SellExecutionStrategy(ABC):
    """Abstract base class for sell execution strategies.

    Each strategy encapsulates the logic for one specific sell scenario,
    handling ticker monitoring, order execution, and fill processing.
    """

    def __init__(
        self,
        client: BinanceClient,
        symbol: Symbol,
        coin: str,
        quantity: float,
        target_price: float,
        db: Database,
        hp_id: str,
        worker_queue: queue.Queue,
        buy_position: "HPPositionBuyV2",
    ):
        """Initialize sell strategy with common dependencies.

        Args:
            client: Binance API client for order operations
            symbol: Primary trading symbol for this strategy
            coin: Coin being sold (e.g., "BTC")
            quantity: Amount of coin to sell
            target_price: Target sell price in quote currency
            db: Database for persistence
            hp_id: High price position identifier
            worker_queue: Queue for portfolio events
            buy_position: Buy position data (for database updates)
        """
        self.client = client
        self.symbol = symbol
        self.coin = coin
        self.quantity = quantity
        self.target_price = target_price
        self.db = db
        self.hp_id = hp_id
        self.worker_queue = worker_queue
        self.buy_position = buy_position

        # Tracked by strategy
        self.ticker_price: Optional[float] = None
        self.order_id: Optional[int] = None
        self.filled_quantity: float = 0.0

    def _get_quote_currency(self, symbol: Symbol) -> str:
        """Extract quote currency from symbol name.

        Args:
            symbol: Symbol to extract quote from

        Returns:
            Quote currency (e.g., "USDC", "BTC")
        """
        # Use Symbol's method to extract coin, then infer quote
        known_quotes = ["USDC", "USDT", "BTC", "BNB", "PLN"]
        for quote in known_quotes:
            if symbol.name.endswith(quote):
                return quote
        # Fallback
        return "USDC"

    @abstractmethod
    def should_send_sell(self, ticker_price: float) -> bool:
        """Check if sell orders should be sent based on current price.

        Args:
            ticker_price: Current market price

        Returns:
            True if sell orders should be sent now
        """
        pass

    @abstractmethod
    def should_cancel_sell(self, ticker_price: float) -> bool:
        """Check if sell orders should be cancelled based on current price.

        Args:
            ticker_price: Current market price

        Returns:
            True if sell orders should be cancelled now
        """
        pass

    @abstractmethod
    async def execute_sell(self) -> None:
        """Execute sell orders.

        Sends sell orders to exchange and updates database state.
        Implementation varies by strategy (direct vs convert vs multihop).
        """
        pass

    @abstractmethod
    async def handle_execution_report(self, report: ExecutionReport) -> None:
        """Process order execution report.

        Args:
            report: Execution report from exchange

        Updates filled quantities, triggers portfolio events, and handles
        order state transitions.
        """
        pass

    @abstractmethod
    async def handle_ticker_update(self, ticker: TickerUpdate) -> None:
        """Process ticker price update.

        Args:
            ticker: Ticker update from exchange

        Updates internal ticker price for trigger logic.
        """
        pass

    @abstractmethod
    async def cancel_sell(self) -> None:
        """Cancel active sell orders.

        Cancels all active orders for this strategy and updates database.
        """
        pass

    @abstractmethod
    def is_complete(self) -> bool:
        """Check if sell is fully complete.

        Returns:
            True if all quantity sold and no pending orders
        """
        pass

    @abstractmethod
    def get_required_symbols(self) -> list[Symbol]:
        """Get list of symbols this strategy needs to trade.

        Returns:
            List of symbols (e.g., [BTC/USDC] for direct, [BTC/USDC, USDC/USDT] for convert)
        """
        pass
