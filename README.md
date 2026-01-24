# Cryptocopter

Advanced cryptocurrency spot trading system with DCA-based strategies, multi-exchange support (Binance & Kraken), portfolio management, and real-time execution.

## 🌟 Features

### Trading Strategies
- **Buy Dip Strategy**: DCA-based strategy that buys dips below detected market tops
  - Dynamic DCA configuration (any number of order levels)
  - Mathematical constant presets (φ, e, π)
  - Historical backtesting and parameter optimization
  - Comprehensive learning guide with exercises

### Core Capabilities
- **Live Trading**: Real-time execution via Binance Spot websocket
- **Portfolio Management**: Multi-symbol portfolio tracking and optimization
- **Position Recovery**: Automatic position reconciliation and error recovery
- **GUI Interface**: Kivy-based UI with configuration management
- **Database Persistence**: SQLite storage for positions, orders, and history
- **Comprehensive Testing**: 90+ test cases with extensive edge case coverage

## 🚀 Quick Start

### Prerequisites
```bash
Python 3.12+
Windows or Linux
Binance Spot API credentials
```

### Installation
```bash
# Clone repository
git clone https://github.com/omn88/cryptocopter.git
cd cryptocopter

# Create virtual environment
python -m venv windows_venv  # Windows
python3 -m venv linux_venv   # Linux

# Activate environment
windows_venv\Scripts\activate  # Windows
source linux_venv/bin/activate # Linux

# Install dependencies
pip install -r requirements/production.txt
pip install -r requirements/develop.txt  # For development
```

### Configuration
Create `config/api_keys.json`:
```json
{
  "binance_testnet": {
    "api_key": "your_testnet_key",
    "api_secret": "your_testnet_secret"
  }
}
```

### Run Application
```bash
python main.py
```

## 📊 Buy Dip Strategy

### Overview
The Buy Dip strategy identifies market tops and places multiple DCA (Dollar Cost Averaging) orders below the detected top. Each position uses independent budget allocation.

### Key Features
- **Dynamic DCA Levels**: Configure any number of order levels (not limited to 6)
- **Mathematical Constants**: Elegant presets using φ (phi), e, π
- **Historical Backtesting**: Test strategies on real Binance data
- **Parameter Optimization**: Grid search to find optimal DCA distances
- **Interactive GUI**: Configure DCA levels visually with live preview

### Quick Example
```python
from src.strategies.buy_dip import BuyDipStrategy, BuyDipConfig
from decimal import Decimal

# Configure strategy with 3 levels using mathematical constants
config = BuyDipConfig(
    dca_distances_pct=[1.618, 2.718, 3.142],  # φ, e, π
    budget_per_position=Decimal("300"),
    budget_per_dca_order=Decimal("100")
)

strategy = BuyDipStrategy(config=config)
```

### Backtesting
```python
from examples.backtest_buy_dip import run_single_backtest
import asyncio

# Run backtest on 3 months of data
asyncio.run(run_single_backtest())

# Or optimize parameters
from examples.backtest_buy_dip import run_parameter_optimization
asyncio.run(run_parameter_optimization())
```

See `examples/backtest_buy_dip.py` for comprehensive examples.

### Learning Resources
- **[Strategy Guide](docs/buy_dip/STRATEGY_GUIDE.md)**: Complete technical reference (895 lines)
- **[Learning Guide](docs/buy_dip/LEARNING_GUIDE.md)**: 4-level interactive tutorial with exercises
- **[Refactoring Summary](docs/buy_dip/REFACTORING_SUMMARY.md)**: Development journey

## 🛠️ Development

### Project Structure
```
src/
├── strategies/
│   └── buy_dip/           # Buy Dip strategy implementation
│       ├── strategy.py    # Main strategy logic
│       ├── config.py      # Configuration with dynamic DCA
│       ├── backtester.py  # Historical backtesting (550+ lines)
│       └── config_gui.py  # Dynamic configuration GUI
├── broker/                # Exchange integration
├── database/              # Position/order persistence
├── portfolio/             # Portfolio management
├── recovery/              # Position recovery system
└── websocket/             # Real-time data streams

tests/                     # 90+ test cases
docs/                      # Comprehensive documentation
examples/                  # Usage examples and backtests
```

### Running Tests
```bash
# All tests
pytest

# Specific test file
pytest tests/strategies/buy_dip/test_strategy.py

# With coverage
pytest --cov=src --cov-report=html
```

### Key Technologies
- **Binance Spot API**: Live trading and historical data
- **Kivy**: Cross-platform GUI framework
- **SQLite**: Database persistence
- **asyncio**: Async/await for concurrent operations
- **pytest**: Testing framework

## 📈 Backtesting System

The backtesting infrastructure allows you to:
1. **Download historical data** from Binance (15m candles)
2. **Simulate strategy execution** with realistic order fills
3. **Optimize parameters** across multiple configurations
4. **Compare strategies** with comprehensive metrics

### Metrics Tracked
- Total profit (absolute & percentage)
- Win rate
- Max drawdown
- Average holding time
- Order fill rates
- Top detection accuracy
- Risk metrics

### Example Results
```
📊 Performance Metrics:
  Total Profit:        $127.34 (+12.73%)
  Win Rate:            68.2%
  Max Drawdown:        -3.45%
  
🎯 Position Statistics:
  Positions Completed: 22
  Winning Positions:   15
  Avg Profit/Position: $5.79
```

## 🎨 GUI Configuration

Dynamic DCA configuration popup allows you to:
- Add/remove order levels on the fly
- Use mathematical constant presets
- Preview order prices for any top value
- Validate configuration before saving

```python
from src.strategies.buy_dip.config_gui import show_config_popup

def on_save(levels):
    print(f"New DCA levels: {levels}")

show_config_popup(
    initial_levels=[1.618, 2.718, 3.142],
    on_save=on_save
)
```

## 📝 Known Issues

1. **Historical Data**: Last row from Binance may be incomplete - always skip last candle
2. **Position Updates**: Position state updates after new klines need enhancement for short signals
3. **Order Fills**: Instant fills may not appear in user socket - requires additional verification

## 🤝 Contributing

This is a personal trading system. Feel free to fork and adapt for your own use.

## ⚠️ Disclaimer

This software is for educational purposes only. Trading cryptocurrencies carries significant risk. Always test on testnet before live trading. The authors are not responsible for any financial losses.

## 📄 License

Private project - All rights reserved

***

# Editing this README

When you're ready to make this README your own, just edit this file and use the handy template below (or feel free to structure it however you want - this is just a starting point!).  Thank you to [makeareadme.com](https://www.makeareadme.com/) for this template.

## Suggestions for a good README
Every project is different, so consider which of these sections apply to yours. The sections used in the template are suggestions for most open source projects. Also keep in mind that while a README can be too long and detailed, too long is better than too short. If you think your README is too long, consider utilizing another form of documentation rather than cutting out information.

## Name
Choose a self-explaining name for your project.

## Description
Let people know what your project can do specifically. Provide context and add a link to any reference visitors might be unfamiliar with. A list of Features or a Background subsection can also be added here. If there are alternatives to your project, this is a good place to list differentiating factors.

## Badges
On some READMEs, you may see small images that convey metadata, such as whether or not all the tests are passing for the project. You can use Shields to add some to your README. Many services also have instructions for adding a badge.

## Visuals
Depending on what you are making, it can be a good idea to include screenshots or even a video (you'll frequently see GIFs rather than actual videos). Tools like ttygif can help, but check out Asciinema for a more sophisticated method.

## Installation
Within a particular ecosystem, there may be a common way of installing things, such as using Yarn, NuGet, or Homebrew. However, consider the possibility that whoever is reading your README is a novice and would like more guidance. Listing specific steps helps remove ambiguity and gets people to using your project as quickly as possible. If it only runs in a specific context like a particular programming language version or operating system or has dependencies that have to be installed manually, also add a Requirements subsection.

## Usage
Use examples liberally, and show the expected output if you can. It's helpful to have inline the smallest example of usage that you can demonstrate, while providing links to more sophisticated examples if they are too long to reasonably include in the README.

## Support
Tell people where they can go to for help. It can be any combination of an issue tracker, a chat room, an email address, etc.

## Roadmap
If you have ideas for releases in the future, it is a good idea to list them in the README.

## Contributing
State if you are open to contributions and what your requirements are for accepting them.

For people who want to make changes to your project, it's helpful to have some documentation on how to get started. Perhaps there is a script that they should run or some environment variables that they need to set. Make these steps explicit. These instructions could also be useful to your future self.

You can also document commands to lint the code or run tests. These steps help to ensure high code quality and reduce the likelihood that the changes inadvertently break something. Having instructions for running tests is especially helpful if it requires external setup, such as starting a Selenium server for testing in a browser.

## Authors and acknowledgment
Show your appreciation to those who have contributed to the project.

## License
For open source projects, say how it is licensed.

## Project status
If you have run out of energy or time for your project, put a note at the top of the README saying that development has slowed down or stopped completely. Someone may choose to fork your project or volunteer to step in as a maintainer or owner, allowing your project to keep going. You can also make an explicit request for maintainers.
