# Cryptocopter

[![CI](https://github.com/omn88/cryptocopter/actions/workflows/ci.yml/badge.svg)](https://github.com/omn88/cryptocopter/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

An async Python trading bot for Binance spot markets. It runs two independent DCA strategies, persists all position state to SQLite, recovers cleanly from crashes, and exposes a Kivy desktop GUI for configuration and monitoring.

> **Warning — real money risk.** Always verify the bot works correctly on the Binance testnet before pointing it at a live account. The author provides no warranty. Use at your own risk.

---

## Strategies

### HP Manager (Hold & Profit)

User-configured buy/sell ladder. You specify a coin, a buy trigger price, and a budget; the bot places the buy order, tracks partial fills, and then executes a sell once the position is filled — automatically choosing the best sell route.

**Lifecycle (state machine via `transitions`):**

```
NEW → BUYING → PARTIALLY_BOUGHT / BOUGHT → READY_TO_SELL → SELLING → PARTIALLY_SOLD / SOLD → CLOSED
```

**Sell strategies** (selected automatically based on available trading pairs):

| Type | Mechanism | Example |
|---|---|---|
| `Direct` | Single limit order | AXL → USDC (AXLUSDC pair) |
| `Convert` | Binance Convert API | BTC → USDT (atomic conversion) |
| `Multihop` | Two-leg limit orders | AXL → BTC → USDC |

### Buy Dip

Automatic candle-pattern-driven DCA buyer. The strategy watches for a rising candle sequence (N consecutive candles with higher highs, or a cumulative gain % threshold), marks the detected top, then places multiple buy orders at configurable distances below it.

**DCA level defaults** (mathematical constants):

| Level | Distance | Constant |
|---|---|---|
| 1 | 1.618% | φ (golden ratio) |
| 2 | 2.718% | e (Euler's number) |
| 3 | 3.142% | π (pi) |

---

## Architecture

```
main.py  (asyncio.run → Kivy async_run)
│
├── StrategyExecutor          # HP Manager orchestrator; one HpStrategy per position
│   └── RecoveryService       # Restores in-flight positions on restart
│       ├── PositionVerifier  # Reconciles DB state with Binance exchange
│       ├── OrderRestorer     # Re-fetches order status from exchange
│       ├── PositionConverter # DB model → domain objects
│       └── MultihopRecoveryHandler
│
├── BuyDipExecutor            # Buy Dip orchestrator
│
├── BrokerSpot                # Unified Binance interface
│   └── WebSocketManager      # Ticker / user-data / kline streams; auto-reconnect
│
├── PortfolioManager          # Multi-symbol inventory and USD valuation
│
└── Database (aiosqlite)      # Persistent store — single connection, async
```

**Single event loop.** Kivy's `async_run()` integrates with Python's asyncio loop so all components share one loop with no cross-thread coordination.

**Queue-based communication:**

| Queue | Direction | Content |
|---|---|---|
| `worker_queue` | Broker → Executors | Tickers, execution reports, kline events |
| `ui_queue` | Executors → GUI | Position state updates |
| `config_queue` | GUI → Executors | New / updated position configs |
| `portfolio_ui_queue` | HP Manager → Portfolio UI | Trade completion events |

---

## Setup

### Prerequisites

- Python 3.12+
- Binance Spot API credentials (testnet or live)

### Install

```bash
git clone https://github.com/omn88/cryptocopter.git
cd cryptocopter

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -e .[dev]
```

### Configure

Create `config/.env`:

```
API_KEY=your_binance_api_key
API_SECRET=your_binance_api_secret
```

When the file is absent (CI, tests) both values default to empty strings — imports never raise.

**Required API permissions:** Enable *Spot & Margin Trading* on the API key. Withdrawal permission is not needed and should be left disabled.

**Testnet:** Binance provides a [Spot Testnet](https://testnet.binance.vision/) with paper-money credentials. Use it to validate the bot before switching to a live key.

The bot stores all position state in `trading.db` (SQLite, created automatically in the working directory). Back up this file before wiping it — it's the only source of truth for in-flight positions.

### Run

```bash
python main.py
```

This opens the Kivy GUI (1200 × 640), connects to Binance WebSocket streams, and restores any in-flight positions from the database.

---

## Testing

```bash
# Fast suite (no DB fixtures)
pytest -m "not db"

# Full suite including crash-recovery tests
pytest

# With coverage
pytest --cov=src --cov-report=html
```

321 tests across unit, integration, E2E (simulator-based), and recovery-path scenarios.

**Key test infrastructure:**

- `HPSimulator` / `BuyDipSimulator` — full-stack simulators that drive strategies through Binance mock responses without a real network connection
- `wait_for_condition` — async poller used instead of `asyncio.sleep` in E2E tests for reliable state assertions
- `db` marker — flags heavy crash-recovery tests that spin up real SQLite databases; run separately when needed

---

## Project Structure

```
src/
├── config.py                     # Single config entry point (reads config/.env)
├── strategy_executor.py          # HP Manager executor
├── broker/                       # BrokerSpot + WebSocketManager
├── common/                       # Symbol formatting, helpers
├── database/                     # aiosqlite persistence layer
├── domain/                       # Core domain objects
│   ├── orders.py                 # Order, ExecutionReport
│   ├── positions.py              # HPBuy, HPSell, HPBuyConfig, HPSellConfig
│   ├── events.py                 # Portfolio event DTOs
│   ├── inventory.py              # InventoryItem
│   └── enums.py                  # State, SellType, PositionSide, …
├── gui/                          # Kivy UI (hp_manager, buy_dip tabs)
├── portfolio/                    # PortfolioManager, InventoryManager
├── recovery/                     # RecoveryService and helpers
└── strategies/
    ├── hp_manager/               # HpStrategy, HPPositionBuy/Sell, sell strategies
    └── buy_dip/                  # BuyDipStrategy, candle detection, DCA logic

tests/
├── conftest.py                   # Shared fixtures (mock client, test DB)
├── common/                       # Symbol, helpers unit tests
├── portfolio/                    # Inventory E2E, portfolio event tests
├── recovery/                     # Recovery path tests
└── strategies/
    ├── hp/                       # HP Manager unit + E2E + recovery DB tests
    └── buy_dip/                  # Buy Dip unit + E2E tests

config/
└── .env                          # API credentials (not committed)

examples/
└── backtest_buy_dip.py           # Backtest runner and parameter grid search
```

---

## CI

GitHub Actions runs three jobs on every push:

| Job | Tool | What it checks |
|---|---|---|
| Formatting | `black --check` | Code style |
| Linting | `mypy` + `pylint` | Type errors, code quality (threshold 8.0) |
| Tests | `pytest --cov` | Full test suite + coverage report artifact |

---

## Known Limitations

- **Binance-only.** The broker layer wraps `python-binance` directly; no exchange abstraction exists.
- **Spot only.** Futures and margin trading are not supported.
- **Single account.** No multi-account or sub-account support.
- **Windows / Linux.** Tested on both; macOS not validated (Kivy SDL2 dependency may require extra setup).
- `websockets` is pinned to 13.1 due to a `python-binance` incompatibility with 14+.

