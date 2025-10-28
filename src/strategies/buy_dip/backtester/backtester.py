"""Historical data backtester for Buy Dip strategy.

Downloads real market data from Binance and runs the strategy against it
to test behavior and optimize parameters.

Features:
- Download historical kline data
- Replay through strategy
- Performance metrics (win rate, profit, drawdown)
- Parameter optimization (DCA distances, order sizes)
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from unittest.mock import AsyncMock

import aiohttp

from src.strategies.buy_dip.broker_adapter import BuyDipBrokerAdapter

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Results from a backtest run."""

    # Configuration
    symbol: str
    start_time: datetime
    end_time: datetime
    initial_budget: Decimal
    dca_distances_pct: List[float]
    order_size_pct: float

    # Performance metrics
    total_positions: int
    completed_positions: int
    winning_positions: int
    losing_positions: int

    total_profit: Decimal
    total_profit_pct: float
    win_rate: float

    # Per-position stats
    avg_profit_per_position: Decimal
    avg_holding_time_minutes: float
    max_drawdown_pct: float

    # Order fill statistics
    total_orders_placed: int
    total_orders_filled: int
    avg_fills_per_position: float

    # Top detection stats
    tops_detected: int
    tops_confirmed: int  # POTENTIAL_TOP → ACTIVE
    tops_invalidated: int

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        # Convert Decimal to float for JSON
        result["initial_budget"] = float(self.initial_budget)
        result["total_profit"] = float(self.total_profit)
        result["avg_profit_per_position"] = float(self.avg_profit_per_position)
        result["start_time"] = self.start_time.isoformat()
        result["end_time"] = self.end_time.isoformat()
        return result


class HistoricalDataDownloader:
    """Download historical kline data from Binance."""

    BINANCE_API = "https://api.binance.com"  # Spot API for historical data

    def __init__(self, cache_dir: str = "backtest_data"):
        """Initialize downloader with cache directory."""
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

    async def download_klines(
        self,
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime,
        use_cache: bool = True,
    ) -> List[Dict]:
        """Download kline data from Binance.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            interval: Kline interval (e.g., "15m", "1h")
            start_time: Start datetime
            end_time: End datetime
            use_cache: Use cached data if available

        Returns:
            List of kline dictionaries with keys:
            - timestamp: Unix timestamp (ms)
            - open, high, low, close, volume: Price/volume data
            - is_closed: Always True for historical data
        """
        # Check cache first
        cache_key = f"{symbol}_{interval}_{start_time.date()}_{end_time.date()}"
        cache_file = self.cache_dir / f"{cache_key}.json"

        if use_cache and cache_file.exists():
            logger.info(f"Loading cached data from {cache_file}")
            with open(cache_file, "r") as f:
                return json.load(f)

        logger.info(
            f"Downloading {symbol} {interval} data from {start_time} to {end_time}"
        )

        klines = []
        current_start = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)

        async with aiohttp.ClientSession() as session:
            while current_start < end_ms:
                url = f"{self.BINANCE_API}/api/v3/klines"  # Spot API endpoint
                params: Dict[str, Any] = {
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": str(current_start),
                    "endTime": str(end_ms),
                    "limit": "1500",  # Max per request
                }

                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        text = await response.text()
                        raise Exception(
                            f"Binance API error: {response.status} - {text}"
                        )

                    data = await response.json()

                    if not data:
                        break

                    # Convert Binance format to our format
                    for candle in data:
                        klines.append(
                            {
                                "timestamp": candle[0],  # Open time
                                "open": float(candle[1]),
                                "high": float(candle[2]),
                                "low": float(candle[3]),
                                "close": float(candle[4]),
                                "volume": float(candle[5]),
                                "is_closed": True,
                            }
                        )

                    # Move to next batch
                    current_start = data[-1][0] + 1

                    logger.info(f"Downloaded {len(klines)} klines so far...")

                    # Rate limiting
                    await asyncio.sleep(0.1)

        logger.info(f"Downloaded {len(klines)} total klines")

        # Cache the results
        with open(cache_file, "w") as f:
            json.dump(klines, f)

        return klines


class BuyDipBacktester:
    """Backtest Buy Dip strategy on historical data."""

    def __init__(self, downloader: Optional[HistoricalDataDownloader] = None):
        """Initialize backtester.

        Args:
            downloader: Historical data downloader (creates new if None)
        """
        self.downloader = downloader or HistoricalDataDownloader()

    async def run_backtest(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        initial_budget: Decimal,
        config: Dict,
        use_cache: bool = True,
    ) -> BacktestResult:
        """Run backtest on historical data.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            start_date: Start date for backtest
            end_date: End date for backtest
            initial_budget: Starting budget in USDT
            config: Strategy configuration dict
            use_cache: Use cached historical data

        Returns:
            BacktestResult with performance metrics
        """
        # Import here to avoid circular dependency
        from src.strategies.buy_dip.strategy import BuyDipStrategy
        from src.strategies.buy_dip.config import BuyDipConfig

        logger.info(f"Starting backtest: {symbol} from {start_date} to {end_date}")
        logger.info(
            f"Budget: ${initial_budget}, DCA distances: {config.get('dca_distances_pct')}"
        )

        # Download historical data
        klines = await self.downloader.download_klines(
            symbol=symbol,
            interval="15m",
            start_time=start_date,
            end_time=end_date,
            use_cache=use_cache,
        )

        if not klines:
            raise ValueError("No historical data downloaded")

        logger.info(f"Processing {len(klines)} candles...")

        # Create mock client for backtesting (similar to conftest)
        from unittest.mock import Mock
        
        mock_client = Mock()
        mock_client.placed_orders = {}
        
        async def create_order_side_effect(symbol, side, order_type, time_in_force, 
                                          quantity, price, new_client_order_id, **kwargs):
            """Mock order creation that tracks orders."""
            order_id = int(abs(hash((float(price) * float(quantity))))) % 1_000_000_000
            
            mock_client.placed_orders[order_id] = {
                "symbol": symbol,
                "side": side,
                "price": float(price),
                "quantity": float(quantity),
                "status": "NEW",
            }
            
            return {
                "orderId": order_id,
                "symbol": symbol,
                "price": str(price),
                "origQty": str(quantity),
                "status": "NEW",
                "side": side,
                "type": "LIMIT",
                "timeInForce": "GTC",
            }
        
        mock_client.create_order = AsyncMock(side_effect=create_order_side_effect)
        mock_client.cancel_order = AsyncMock(return_value={"orderId": 0, "status": "CANCELED"})

        # Create BuyDipBrokerAdapter with mocked client
        broker = BuyDipBrokerAdapter(client=mock_client, symbol=symbol)

        # Create strategy instance
        buy_dip_config = BuyDipConfig(**config)

        strategy = BuyDipStrategy(
            config=buy_dip_config,
            total_budget=initial_budget,
            order_budget_pct=Decimal(str(config.get("order_size_percentage", 2.0))),
            broker_adapter=broker,
        )

        # Register callbacks (like executor does)
        def on_order_filled(order_id: str, fill_price: Decimal) -> None:
            """Handle order fill from mock broker."""
            try:
                if "_sell" in order_id:
                    strategy.handle_sell_fill(order_id, float(fill_price))
                else:
                    strategy.handle_order_fill(order_id, float(fill_price), 1.0)
            except Exception as e:
                logger.warning(f"Error handling fill for {order_id}: {e}")

        broker.set_order_filled_callback(on_order_filled)

        # Track metrics
        metrics: Dict[str, Any] = {
            "positions_created": 0,
            "positions_completed": 0,
            "positions_won": 0,
            "positions_lost": 0,
            "total_profit": Decimal("0"),
            "orders_placed": 0,
            "orders_filled": 0,
            "tops_detected": 0,
            "tops_confirmed": 0,
            "tops_invalidated": 0,
            "position_holding_times": [],
            "position_profits": [],
            "position_fill_counts": [],
            "budget_history": [],
        }

        # Track position states for metrics
        position_start_times: Dict[str, datetime] = {}
        position_tops_detected: set[str] = set()

        # Process each candle
        for i, kline in enumerate(klines):
            # Convert to strategy format
            candle = {
                "timestamp": kline["timestamp"],
                "open": Decimal(str(kline["open"])),
                "high": Decimal(str(kline["high"])),
                "low": Decimal(str(kline["low"])),
                "close": Decimal(str(kline["close"])),
                "volume": Decimal(str(kline["volume"])),
                "is_closed": True,
            }

            # Track positions before processing
            positions_before = len(strategy._positions)

            # Process candle through strategy
            await strategy.process_candle(symbol, candle)

            # Give async order placement tasks time to complete
            # This simulates the delay in real trading where orders are placed
            # via API calls. Without this, multiple orders get scheduled before
            # the first one completes, causing duplicate orders.
            await asyncio.sleep(0.01)  # 10ms delay per candle

            # Check for new positions (top detected)
            if len(strategy._positions) > positions_before:
                metrics["tops_detected"] += 1
                new_positions = [
                    p
                    for p in strategy._positions.values()
                    if p.position_id not in position_tops_detected
                ]
                for pos in new_positions:
                    position_tops_detected.add(pos.position_id)
                    position_start_times[pos.position_id] = datetime.fromtimestamp(
                        kline["timestamp"] / 1000
                    )

            # Simulate order fills based on price action
            await self._simulate_order_fills(strategy, candle, metrics, broker)

            # Give fill callbacks time to complete and trigger next DCA orders
            await asyncio.sleep(0.01)  # 10ms delay after fills

            # Print candle summary after processing
            self._print_candle_summary(i, kline, candle, strategy, broker, metrics)

            # Track budget history every 100 candles
            if i % 100 == 0:
                current_budget = strategy._budget_manager.get_available_budget()
                locked_budget = strategy._budget_manager.get_locked_budget()
                metrics["budget_history"].append(
                    {
                        "candle": i,
                        "available": float(current_budget),
                        "locked": float(locked_budget),
                        "total": float(current_budget + locked_budget),
                    }
                )

            # Progress logging
            if (i + 1) % 500 == 0:
                logger.info(
                    f"Processed {i + 1}/{len(klines)} candles "
                    f"({(i+1)/len(klines)*100:.1f}%) - "
                    f"Positions: {len(strategy._positions)}"
                )

        # Final metrics calculation
        final_budget_float = strategy._budget_manager.get_available_budget()
        final_budget = Decimal(str(final_budget_float))
        total_profit = final_budget - initial_budget

        # Calculate averages
        holding_times: List[float] = metrics["position_holding_times"]  # type: ignore
        avg_holding_time = (
            sum(holding_times) / len(holding_times) if holding_times else 0.0
        )

        fill_counts: List[int] = metrics["position_fill_counts"]  # type: ignore
        avg_fills = sum(fill_counts) / len(fill_counts) if fill_counts else 0.0

        positions_completed: int = metrics["positions_completed"]  # type: ignore
        avg_profit = (
            total_profit / positions_completed
            if positions_completed > 0
            else Decimal("0")
        )

        # Calculate max drawdown
        budget_history: List[Dict[Any, Any]] = metrics["budget_history"]  # type: ignore
        max_drawdown = self._calculate_max_drawdown(budget_history, initial_budget)

        # Extract typed metrics
        tops_detected: int = metrics["tops_detected"]  # type: ignore
        positions_won: int = metrics["positions_won"]  # type: ignore
        positions_lost: int = metrics["positions_lost"]  # type: ignore
        orders_placed: int = metrics["orders_placed"]  # type: ignore
        orders_filled: int = metrics["orders_filled"]  # type: ignore
        tops_confirmed: int = metrics["tops_confirmed"]  # type: ignore
        tops_invalidated: int = metrics["tops_invalidated"]  # type: ignore

        # Create result
        result = BacktestResult(
            symbol=symbol,
            start_time=start_date,
            end_time=end_date,
            initial_budget=initial_budget,
            dca_distances_pct=config.get("dca_distances_pct", []),
            order_size_pct=config.get("order_size_percentage", 2.0),
            total_positions=tops_detected,
            completed_positions=positions_completed,
            winning_positions=positions_won,
            losing_positions=positions_lost,
            total_profit=total_profit,
            total_profit_pct=float(total_profit / initial_budget * 100),
            win_rate=(
                positions_won / positions_completed * 100
                if positions_completed > 0
                else 0.0
            ),
            avg_profit_per_position=avg_profit,
            avg_holding_time_minutes=avg_holding_time,
            max_drawdown_pct=max_drawdown,
            total_orders_placed=orders_placed,
            total_orders_filled=orders_filled,
            avg_fills_per_position=avg_fills,
            tops_detected=tops_detected,
            tops_confirmed=tops_confirmed,
            tops_invalidated=tops_invalidated,
        )

        logger.info(f"Backtest complete!")
        logger.info(
            f"Total profit: ${result.total_profit} ({result.total_profit_pct:.2f}%)"
        )
        logger.info(f"Win rate: {result.win_rate:.1f}%")
        logger.info(f"Completed: {result.completed_positions}/{result.total_positions}")

        return result

    async def _simulate_order_fills(
        self, strategy, candle: Dict, metrics: Dict, broker
    ) -> None:
        """Simulate order fills based on candle price action.

        For each pending order, check if candle's low/high touched the price.
        If yes, simulate the fill via mock broker (which triggers callbacks).
        """
        from src.strategies.buy_dip.position import PositionState

        high = float(candle["high"])
        low = float(candle["low"])

        # Get pending orders from mock broker
        pending_orders = broker.get_pending_orders()

        if pending_orders:
            logger.debug(
                f"Checking {len(pending_orders)} pending orders against candle low={low}, high={high}"
            )

        for order_id, order_data in list(pending_orders.items()):
            order_price = float(order_data["price"])
            side = order_data["side"]

            logger.debug(f"  Order {order_id}: {side} @ {order_price}")

            # Check if order should fill based on candle
            should_fill = False
            fill_price = None

            if side == "BUY":
                # Buy order fills if price dropped to or below order price
                if low <= order_price:
                    should_fill = True
                    fill_price = Decimal(str(order_price))
                    logger.debug(f"    -> BUY FILL (low {low} <= {order_price})")
            elif side == "SELL":
                # Sell order fills if price rose to or above order price
                if high >= order_price:
                    should_fill = True
                    fill_price = Decimal(str(order_price))
                    logger.debug(f"    -> SELL FILL (high {high} >= {order_price})")

            if should_fill and fill_price:
                # Simulate fill via mock broker (triggers callbacks like real WebSocket)
                broker.simulate_fill(order_id, fill_price)
                metrics["orders_filled"] += 1
                logger.debug(f"    -> Filled! Total fills: {metrics['orders_filled']}")

                # Give callbacks a chance to run
                await asyncio.sleep(0)

    def _print_candle_summary(
        self,
        candle_num: int,
        kline: Dict,
        candle: Dict,
        strategy,
        broker,
        metrics: Dict,
    ) -> None:
        """Print summary after each candle for debugging."""
        from src.strategies.buy_dip.position import PositionState
        from datetime import datetime

        timestamp = datetime.fromtimestamp(kline["timestamp"] / 1000)
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])

        print(f"\n{'='*80}")
        print(f"Candle #{candle_num} | {timestamp.strftime('%Y-%m-%d %H:%M')}")
        print(f"High: ${high:,.2f} | Low: ${low:,.2f} | Close: ${close:,.2f}")
        print(f"{'='*80}")

        # Budget info
        available = strategy._budget_manager.get_available_budget()
        locked = strategy._budget_manager.get_locked_budget()
        print(f"BUDGET: Available=${available:,.2f} | Locked=${locked:,.2f}")

        # Pending orders
        pending = broker.get_pending_orders()
        if pending:
            print(f"\nPENDING ORDERS ({len(pending)}):")
            for oid, order_data in pending.items():
                print(
                    f"  - {oid}: {order_data['side']} @ ${float(order_data['price']):,.2f}"
                )
        else:
            print(f"\nPENDING ORDERS: None")

        # Positions
        positions = list(strategy._positions.values())
        if positions:
            print(f"\nPOSITIONS ({len(positions)}):")
            for pos in positions:
                state_name = (
                    pos.state.name if hasattr(pos.state, "name") else str(pos.state)
                )
                print(f"\n  Position: {pos.position_id}")
                print(f"    State: {state_name}")
                if pos.top_price:
                    print(f"    Top: ${float(pos.top_price):,.2f}")
                if pos.confirmed_top:
                    print(f"    Confirmed Top: ${float(pos.confirmed_top):,.2f}")
                print(
                    f"    DCA Level: {pos.next_dca_level}/{len(pos.dca_distances_pct)}"
                )
                print(
                    f"    Buy Orders Filled: {len([o for o in pos.buy_orders if o.status == 'FILLED'])}"
                )
                if pos.total_invested > 0:
                    print(f"    Invested: ${float(pos.total_invested):,.2f}")
                    print(f"    Quantity: {float(pos.total_quantity):.6f}")
                    print(
                        f"    Avg Entry: ${float(pos.average_entry):,.2f}"
                        if pos.average_entry
                        else ""
                    )
                if pos.pending_order:
                    print(
                        f"    Pending: {pos.pending_order.order_id} @ ${float(pos.pending_order.price):,.2f}"
                    )
                if pos.sell_order:
                    print(f"    Sell Order: @ ${float(pos.sell_order.price):,.2f}")
        else:
            print(f"\nPOSITIONS: None")

        # Metrics
        print(f"\nMETRICS:")
        print(f"  Tops Detected: {metrics['tops_detected']}")
        print(f"  Orders Filled: {metrics['orders_filled']}")
        print(f"  Positions Completed: {metrics['positions_completed']}")

    def _calculate_max_drawdown(
        self, budget_history: List[Dict], initial_budget: Decimal
    ) -> float:
        """Calculate maximum drawdown percentage from budget history."""
        if not budget_history:
            return 0.0

        peak = float(initial_budget)
        max_dd = 0.0

        for entry in budget_history:
            total = entry["total"]
            if total > peak:
                peak = total

            drawdown = (peak - total) / peak * 100
            if drawdown > max_dd:
                max_dd = drawdown

        return max_dd

    async def optimize_parameters(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        initial_budget: Decimal,
        base_config: Dict,
        parameter_ranges: Dict[str, List],
        metric: str = "total_profit_pct",
    ) -> Tuple[Dict, List[BacktestResult]]:
        """Optimize strategy parameters using grid search.

        Args:
            symbol: Trading pair
            start_date: Start date
            end_date: End date
            initial_budget: Starting budget
            base_config: Base configuration
            parameter_ranges: Dict of parameter names to list of values to test
                Example: {
                    'dca_distances_pct': [
                        [1.0, 2.0, 3.0],
                        [1.5, 2.5, 3.5],
                        [1.618, 2.718, 3.142]
                    ],
                    'order_size_percentage': [1.0, 2.0, 3.0]
                }
            metric: Metric to optimize ('total_profit_pct', 'win_rate', etc.)

        Returns:
            Tuple of (best_config, all_results)
        """
        logger.info(f"Starting parameter optimization...")
        logger.info(f"Parameter ranges: {parameter_ranges}")

        results = []

        # Generate all combinations
        import itertools

        param_names = list(parameter_ranges.keys())
        param_values = list(parameter_ranges.values())

        combinations = list(itertools.product(*param_values))
        total_combos = len(combinations)

        logger.info(f"Testing {total_combos} parameter combinations...")

        for i, combo in enumerate(combinations):
            # Create config for this combination
            test_config = base_config.copy()
            for param_name, value in zip(param_names, combo):
                test_config[param_name] = value

            logger.info(f"\nTest {i+1}/{total_combos}: {dict(zip(param_names, combo))}")

            # Run backtest
            try:
                result = await self.run_backtest(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    initial_budget=initial_budget,
                    config=test_config,
                    use_cache=True,
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Backtest failed for config {test_config}: {e}")
                continue

        # Find best result
        if not results:
            raise ValueError("All backtests failed")

        best_result = max(results, key=lambda r: getattr(r, metric))
        best_config = {
            "dca_distances_pct": best_result.dca_distances_pct,
            "order_size_percentage": best_result.order_size_pct,
        }

        logger.info(f"\n{'='*60}")
        logger.info(f"OPTIMIZATION COMPLETE")
        logger.info(f"{'='*60}")
        logger.info(f"Best configuration: {best_config}")
        logger.info(f"Best {metric}: {getattr(best_result, metric)}")
        logger.info(f"Win rate: {best_result.win_rate:.1f}%")
        logger.info(
            f"Total profit: ${best_result.total_profit} ({best_result.total_profit_pct:.2f}%)"
        )

        return best_config, results


async def main():
    """Example usage of backtester."""
    from decimal import Decimal

    # Setup
    backtester = BuyDipBacktester()

    # Single backtest example
    result = await backtester.run_backtest(
        symbol="BTCUSDT",
        start_date=datetime(2024, 10, 1),
        end_date=datetime(2024, 10, 31),
        initial_budget=Decimal("10000"),
        config={
            "order_size_percentage": 2.0,
            "dca_distances_pct": [1.618, 2.718, 3.142],  # φ, e, π
            "min_consecutive_rising": 3,
            "min_total_gain_pct": 0.25,
        },
    )

    print(json.dumps(result.to_dict(), indent=2))

    # Parameter optimization example
    best_config, all_results = await backtester.optimize_parameters(
        symbol="BTCUSDT",
        start_date=datetime(2024, 10, 1),
        end_date=datetime(2024, 10, 31),
        initial_budget=Decimal("10000"),
        base_config={
            "min_consecutive_rising": 3,
            "min_total_gain_pct": 0.25,
        },
        parameter_ranges={
            "dca_distances_pct": [
                [1.0, 2.0, 3.0],
                [1.5, 2.5, 3.5],
                [1.618, 2.718, 3.142],  # φ, e, π
                [2.0, 3.0, 4.0],
            ],
            "order_size_percentage": [1.0, 1.5, 2.0, 2.5, 3.0],
        },
        metric="total_profit_pct",
    )

    print(f"\nBest configuration: {best_config}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    asyncio.run(main())
