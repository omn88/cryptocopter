"""Example script for backtesting Buy Dip strategy.

This script demonstrates:
1. Running a single backtest with specific parameters
2. Optimizing parameters across a range of values
3. Analyzing and visualizing results
"""

import asyncio
from decimal import Decimal
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.strategies.buy_dip.backtester import BuyDipBacktester, BacktestResult
from src.strategies.buy_dip.config import BuyDipConfig


async def run_single_backtest():
    """Run a single backtest with default parameters."""
    print("=" * 80)
    print("SINGLE BACKTEST - Buy Dip Strategy")
    print("=" * 80)

    # Configuration
    symbol = "BTCUSDT"
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 3, 31)  # 3 months
    initial_budget = Decimal("1000")

    # Strategy config (using mathematical constants)
    config = BuyDipConfig(
        dca_distances_pct=[1.618, 2.718, 3.142],  # φ, e, π
        budget_per_position=Decimal("300"),
        budget_per_dca_order=Decimal("50"),
    )

    print(f"\nSymbol: {symbol}")
    print(f"Period: {start_date.date()} to {end_date.date()}")
    print(f"Initial Budget: ${initial_budget:,.2f}")
    print(f"DCA Levels: {config.dca_distances_pct}")
    print(f"Budget per Position: ${config.budget_per_position}")
    print(f"Budget per Order: ${config.budget_per_dca_order}")
    print("\nRunning backtest...")

    # Run backtest
    backtester = BuyDipBacktester()
    result = await backtester.run_backtest(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        initial_budget=initial_budget,
        config=config,
    )

    # Print results
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)

    print(f"\n📊 Performance Metrics:")
    print(
        f"  Total Profit:        ${result.total_profit:,.2f} ({result.total_profit_pct:+.2f}%)"
    )
    print(f"  Final Budget:        ${result.final_budget:,.2f}")
    print(f"  Win Rate:            {result.win_rate:.1f}%")
    print(f"  Max Drawdown:        {result.max_drawdown_pct:.2f}%")

    print(f"\n🎯 Position Statistics:")
    print(f"  Positions Opened:    {result.positions_opened}")
    print(f"  Positions Completed: {result.positions_completed}")
    print(f"  Winning Positions:   {result.winning_positions}")
    print(f"  Avg Profit/Position: ${result.avg_profit_per_position:,.2f}")
    print(
        f"  Avg Holding Time:    {result.avg_holding_time_minutes:.0f} minutes ({result.avg_holding_time_minutes/60:.1f} hours)"
    )

    print(f"\n📋 Order Statistics:")
    print(f"  Total Orders:        {result.total_orders_placed}")
    print(f"  Orders Filled:       {result.total_orders_filled}")
    print(f"  Fill Rate:           {result.order_fill_rate:.1f}%")
    print(f"  Avg Fills/Position:  {result.avg_fills_per_position:.1f}")

    print(f"\n🔍 Top Detection:")
    print(f"  Tops Detected:       {result.tops_detected}")
    print(f"  Tops Confirmed:      {result.tops_confirmed}")
    print(f"  Tops Invalidated:    {result.tops_invalidated}")
    print(f"  Confirmation Rate:   {result.top_confirmation_rate:.1f}%")

    print(f"\n📈 Price Range:")
    print(f"  Highest Price:       ${result.highest_price:,.2f}")
    print(f"  Lowest Price:        ${result.lowest_price:,.2f}")
    print(
        f"  Price Range:         {((result.highest_price - result.lowest_price) / result.lowest_price * 100):.1f}%"
    )

    return result


async def run_parameter_optimization():
    """Optimize DCA distance parameters."""
    print("\n" + "=" * 80)
    print("PARAMETER OPTIMIZATION")
    print("=" * 80)

    # Configuration
    symbol = "BTCUSDT"
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 2, 29)  # 2 months (faster)
    initial_budget = Decimal("1000")

    # Base config
    base_config = BuyDipConfig(
        dca_distances_pct=[1.0, 2.0, 3.0],  # Will be overridden
        budget_per_position=Decimal("300"),
        budget_per_dca_order=Decimal("50"),
    )

    # Parameter ranges to test
    param_ranges = {
        "dca_level_1": [0.5, 1.0, 1.5, 2.0],
        "dca_level_2": [2.0, 2.5, 3.0, 3.5],
        "dca_level_3": [3.0, 4.0, 5.0, 6.0],
    }

    print(f"\nSymbol: {symbol}")
    print(f"Period: {start_date.date()} to {end_date.date()}")
    print(f"Initial Budget: ${initial_budget:,.2f}")
    print(f"\nParameter Ranges:")
    for param, values in param_ranges.items():
        print(f"  {param}: {values}")

    total_combinations = 1
    for values in param_ranges.values():
        total_combinations *= len(values)

    print(f"\nTotal Combinations: {total_combinations}")
    print("\nRunning optimization...")

    # Run optimization
    backtester = BuyDipBacktester()
    results = await backtester.optimize_parameters(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        initial_budget=initial_budget,
        base_config=base_config,
        param_ranges=param_ranges,
        optimization_metric="total_profit_pct",
    )

    # Print top 10 results
    print("\n" + "=" * 80)
    print("TOP 10 CONFIGURATIONS")
    print("=" * 80)

    for i, (params, result) in enumerate(results[:10], start=1):
        dca_levels = [
            params["dca_level_1"],
            params["dca_level_2"],
            params["dca_level_3"],
        ]

        print(f"\n#{i}")
        print(f"  DCA Levels: {dca_levels}")
        print(
            f"  Profit: ${result.total_profit:,.2f} ({result.total_profit_pct:+.2f}%)"
        )
        print(f"  Win Rate: {result.win_rate:.1f}%")
        print(
            f"  Positions: {result.positions_completed} completed, {result.winning_positions} winning"
        )
        print(f"  Drawdown: {result.max_drawdown_pct:.2f}%")

    # Best configuration
    best_params, best_result = results[0]
    best_dca_levels = [
        best_params["dca_level_1"],
        best_params["dca_level_2"],
        best_params["dca_level_3"],
    ]

    print("\n" + "=" * 80)
    print("🏆 BEST CONFIGURATION")
    print("=" * 80)
    print(f"\nDCA Levels: {best_dca_levels}")
    print(
        f"Profit: ${best_result.total_profit:,.2f} ({best_result.total_profit_pct:+.2f}%)"
    )
    print(f"Win Rate: {best_result.win_rate:.1f}%")
    print(f"Max Drawdown: {best_result.max_drawdown_pct:.2f}%")
    print(f"Avg Profit per Position: ${best_result.avg_profit_per_position:,.2f}")

    return results


async def compare_configurations():
    """Compare different DCA configurations."""
    print("\n" + "=" * 80)
    print("CONFIGURATION COMPARISON")
    print("=" * 80)

    # Test parameters
    symbol = "BTCUSDT"
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 2, 29)
    initial_budget = Decimal("1000")

    # Configurations to compare
    configurations = [
        ("Elegant (φ, e, π)", [1.618, 2.718, 3.142]),
        ("Simple (1, 2, 3)", [1.0, 2.0, 3.0]),
        ("Fibonacci", [1.618, 2.618, 4.236]),
        ("Wide Spread", [1.0, 3.0, 5.0]),
        ("Tight Spread", [0.5, 1.0, 1.5]),
        ("6 Levels", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
    ]

    print(f"\nSymbol: {symbol}")
    print(f"Period: {start_date.date()} to {end_date.date()}")
    print(f"Initial Budget: ${initial_budget:,.2f}")
    print(f"\nTesting {len(configurations)} configurations...")

    backtester = BuyDipBacktester()
    results = []

    for name, dca_levels in configurations:
        print(f"\n  Testing: {name} - {dca_levels}")

        config = BuyDipConfig(
            dca_distances_pct=dca_levels,
            budget_per_position=Decimal("300"),
            budget_per_dca_order=Decimal("50"),
        )

        result = await backtester.run_backtest(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            initial_budget=initial_budget,
            config=config,
        )

        results.append((name, dca_levels, result))

    # Print comparison table
    print("\n" + "=" * 80)
    print("COMPARISON TABLE")
    print("=" * 80)

    print(
        f"\n{'Configuration':<25} {'Profit %':<12} {'Win Rate':<12} {'Positions':<12} {'Drawdown'}"
    )
    print("-" * 80)

    for name, levels, result in results:
        print(
            f"{name:<25} {result.total_profit_pct:>10.2f}% {result.win_rate:>10.1f}% "
            f"{result.positions_completed:>10} {result.max_drawdown_pct:>10.2f}%"
        )

    # Find best by different metrics
    print("\n" + "=" * 80)
    print("BEST BY METRIC")
    print("=" * 80)

    best_profit = max(results, key=lambda x: x[2].total_profit_pct)
    best_winrate = max(results, key=lambda x: x[2].win_rate)
    best_drawdown = min(results, key=lambda x: x[2].max_drawdown_pct)

    print(f"\n💰 Best Profit: {best_profit[0]}")
    print(f"   Levels: {best_profit[1]}")
    print(f"   Profit: {best_profit[2].total_profit_pct:+.2f}%")

    print(f"\n🎯 Best Win Rate: {best_winrate[0]}")
    print(f"   Levels: {best_winrate[1]}")
    print(f"   Win Rate: {best_winrate[2].win_rate:.1f}%")

    print(f"\n🛡️ Best Drawdown: {best_drawdown[0]}")
    print(f"   Levels: {best_drawdown[1]}")
    print(f"   Max Drawdown: {best_drawdown[2].max_drawdown_pct:.2f}%")

    return results


async def main():
    """Run all examples."""
    print(
        """
╔═══════════════════════════════════════════════════════════════════════════════╗
║                    BUY DIP STRATEGY - BACKTESTING EXAMPLES                    ║
╚═══════════════════════════════════════════════════════════════════════════════╝
    """
    )

    # Run examples
    try:
        # 1. Single backtest
        await run_single_backtest()

        # 2. Parameter optimization
        await run_parameter_optimization()

        # 3. Configuration comparison
        await compare_configurations()

    except KeyboardInterrupt:
        print("\n\n❌ Interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback

        traceback.print_exc()

    print("\n" + "=" * 80)
    print("✅ Examples complete!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
