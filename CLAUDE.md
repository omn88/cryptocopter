# Cryptocopter — Developer Guide

## Project overview

Async Python trading bot with a Kivy GUI. Uses aiosqlite for persistence, the `transitions`
library for FSM-driven strategy logic, and raw `websockets` for exchange connectivity.

**Current status:** Migrating from Binance to Kraken (MiCa regulation blocks Binance in Poland).

## Running the app

```bash
python main.py
```

Config lives in `config/.env` (API_KEY, API_SECRET).

## Running tests

```bash
# Fast suite (excludes slow DB/recovery tests)
.venv/bin/pytest tests/ -x -q -m "not db"

# Full suite including DB tests
.venv/bin/pytest tests/ -x -q
```

## Linting / formatting

Black is enforced in CI. **Always run before committing:**

```bash
.venv/bin/black src/ tests/
```

Pre-commit hooks: `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`,
`check-added-large-files`, `black`.

## Architecture

```
main.py
  └── AsyncApp (Kivy)
        ├── BrokerSpot          — WS subscriptions, message routing
        │     └── WebSocketManager — WS connectivity, health, reconnects
        ├── StrategyExecutor    — creates/recovers HpStrategy instances
        │     └── HpStrategy    — FSM per trading position (transitions lib)
        │           ├── HPPositionBuy  — places/cancels buy orders
        │           └── HPPositionSell — places/cancels sell orders
        ├── RecoveryService     — restores positions from DB after crash
        ├── Portfolio           — inventory tracking
        └── UsdPriceResolver    — resolves coin prices to USDC
```

Key data flow:
1. WS ticker → `handle_ticker_message` → `TickerUpdate` → `HpStrategy.worker_queue`
2. WS executions → `handle_user_message` → `ExecutionReport` → `HpStrategy.worker_queue`
3. Strategy FSM processes events and calls `client.create_order` / `client.cancel_order`

## Domain constants

**Never import from `binance.enums` or any exchange SDK in domain/strategy code.**
Use `src/domain/constants.py` instead:

```python
from src.domain.constants import (
    ORDER_STATUS_NEW, ORDER_STATUS_FILLED, ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_CANCELED, ORDER_STATUS_EXPIRED, ORDER_STATUS_OPEN,
    ORDER_TYPE_LIMIT, ORDER_TYPE_MARKET, TIME_IN_FORCE_GTC,
)
```

`ORDER_STATUS_OPEN` is Kraken-specific (`"open"` covers both NEW and PARTIALLY_FILLED).
Distinguish partial fill by checking `cum_qty > 0` in the message handler.

## Kraken migration — decisions

| Decision | Answer |
|---|---|
| Quote currency | USDC |
| Coins with no Kraken pair | Skip — handle deposit/withdrawal manually |
| XBT/BTC naming | Normalize at adapter boundary (BTC internally, XBT only in KrakenClient) |
| Python library | python-kraken-sdk |
| Order ID type | `str` (was `int`) — Kraken txids are strings like `"OB5VMB-B4U2U-DJD7WS"` |
| Architecture | Rip and replace (no abstraction layer) |
| PLN pairs | Removed — Kraken has no PLN pairs |
| Convert API fallback | Removed — no Kraken equivalent; skip unsupported coins |
| WS subscription model | Per-symbol dynamic (subscribe/unsubscribe as strategies start/stop) |
| ORM | Later — separate concern, do not mix with exchange migration |

## Kraken API reference

**REST base:** `https://api.kraken.com/0/`

| Method | Endpoint | Used for |
|---|---|---|
| POST | `/0/private/AddOrder` | Place limit order |
| POST | `/0/private/CancelOrder` | Cancel order |
| GET | `/0/public/AssetPairs` | Symbol metadata (replaces `get_exchange_info`) |
| GET | `/0/public/Ticker` | Price snapshot (replaces `get_all_tickers`) |
| POST | `/0/private/GetWebSocketsToken` | One-time WS auth token (15 min expiry) |

**WS v2:** `wss://ws.kraken.com/v2`

- `ticker` channel: requires explicit per-symbol subscription (no all-tickers stream)
- `executions` channel: order/fill updates, authenticated via token from GetWebSocketsToken
- `balances` channel: account balance updates
- `instrument` channel: all instrument metadata on subscribe (useful at startup)

## Kraken WS — key differences from Binance

**1. No all-tickers stream.**
Binance had `!miniTicker@arr`. Kraken requires per-symbol:
```json
{"method": "subscribe", "params": {"channel": "ticker", "symbol": ["BTC/USDC"]}}
```
`BrokerSpot.subscribe()` must signal `WebSocketManager` to add/remove per-symbol subscriptions.
Use a `{symbol → subscriber_count}` reference counter.

**2. Token auth for user stream.**
Binance used a REST-created listen key renewed every 60 min. Kraken uses a one-time token obtained
via `POST /0/private/GetWebSocketsToken`, valid 15 min, passed in the WS subscribe message.
Need a token refresh loop inside `WebSocketManager`.

**3. `"open"` status is ambiguous.**
Kraken sends `"open"` for both NEW and PARTIALLY_FILLED orders. Detect partial fill:
`exec_type == "trade"` AND `order_status == "open"` AND `cum_qty > 0`.

## Kraken execution report field mapping

| ExecutionReport field | Kraken WS field |
|---|---|
| `symbol` | `symbol` (normalize XBT→BTC) |
| `order_id` | `order_id` (string txid) |
| `side` | `side` (`"buy"` → `"BUY"`) |
| `current_order_status` | derived: `order_status` + `cum_qty` logic (see above) |
| `current_execution_type` | `exec_type` (`"pending"`, `"trade"`, `"canceled"`, `"expired"`) |
| `last_executed_quantity` | `last_qty` |
| `last_executed_price` | `last_price` |
| `cumulative_filled_quantity` | `cum_qty` |
| `commission_amount` | `fees[0].asset_qty` |
| `commission_asset` | `fees[0].asset` |

## Kraken AssetPairs → Symbol field mapping

| Symbol field | Kraken `AssetPairs` field |
|---|---|
| `precision` | derived from `lot_decimals` |
| `price_precision` | `pair_decimals` |
| `min_qty` | `ordermin` |
| `min_notional` | `costmin` |
| `price_filter` (tick size) | `tick_size` |

## XBT normalization rule

`KrakenClient` owns all XBT↔BTC translation. No other file should know about XBT:

```python
def _to_kraken_symbol(self, internal: str) -> str:
    # "BTCUSDC" → "XBT/USDC"
    ...

def _from_kraken_symbol(self, kraken: str) -> str:
    # "XBT/USDC" → "BTCUSDC"
    ...
```

## New sell path routing (Kraken)

Replaces the old PLN / BNB / Convert logic. Priority order for `end_currency = USDC`:

1. **Direct:** `{coin}/USDC` pair exists → `DirectSellStrategy`
2. **Via BTC:** `{coin}/BTC` + `BTC/USDC` both exist → `MultihopSellStrategy`
3. **Via ETH:** `{coin}/ETH` + `ETH/USDC` both exist → `MultihopSellStrategy`
4. **No path found:** raise `ValueError` — coin has no Kraken pair, handle manually

`ConvertSellStrategy` is deleted. `SellType.CONVERT` and `TradeType.CONVERT` are deleted.

## Migration PR plan

| PR | Branch | Status | Scope |
|---|---|---|---|
| 1 | `feature/kraken-ph1-constants-decoupling` | **MERGED** | `src/domain/constants.py`; replace all `binance.enums` imports in domain/strategies/tests |
| 2 | `feature/kraken-ph2-order-id-str` | **MERGED** | `Order.order_id: int → str`; DB schema `order_id TEXT`; `str(resp["orderId"])` in position files |
| 3 | `feature/kraken-ph3-client` | IN REVIEW | `KrakenClient` class; XBT normalization; replace `binance.exceptions`; remove `python-binance` dep |
| 4 | `feature/kraken-ph4-symbol-fetching` | TODO | Rewrite `fetch_symbols()` for Kraken `AssetPairs` |
| 5 | `feature/kraken-ph5-websocket` | TODO | Kraken WS v2; per-symbol subscriptions; token auth + refresh; dead-man switch |
| 6 | `feature/kraken-ph6-message-handlers` | TODO | Rewrite `message_handlers.py` for Kraken event schema |
| 7 | `feature/kraken-ph7-sell-factory` | TODO | Remove PLN/BNB/Convert; Kraken routing; update price resolver |

## KrakenClient gaps after PR3

PR3 only implements what PR3 itself needs — `create_order`, `cancel_order` — via
`kraken.spot.Trade` (python-kraken-sdk), wrapped in `asyncio.to_thread` since the SDK's REST
clients are synchronous. The following Binance-only methods are **not yet implemented** on
`KrakenClient` and will raise `AttributeError` if hit at runtime until their owning PR lands:

- `get_exchange_info` (`src/common/symbol.py: fetch_symbols`) — PR4
- `convert_request_quote` / `convert_accept_quote` (`hp_manager.py`) — deleted in PR7, not replaced
- `get_all_tickers` (`usd_price_resolver.py`), `get_orderbook_ticker` (GUI symbol picker),
  `get_account` (`portfolio.py` balance sync) — not owned by any PR in this table yet; needs a
  decision on which PR picks these up (likely folded into PR4 or a follow-up).
- `get_order` (used by `recovery/order_restorer.py`, `recovery/position_verifier.py`) — needs
  the same `ORDER_STATUS_OPEN` + `cum_qty` status-normalization logic as PR6's message handler
  rewrite, so it's deferred there rather than duplicated ad hoc in PR3.

None of these are exercised by the test suite (client is always mocked), so `pytest` stays
green — but real recovery/portfolio/GUI runs against a live KrakenClient will fail on these
paths until the relevant PR lands.

## ORM discussion (deferred)

Currently uses raw `aiosqlite` with hand-written SQL. SQLAlchemy (with `AsyncSession` + Alembic
for migrations) would add type safety and reduce boilerplate. Since the DB has never been in
production, this is a clean-slate opportunity. Decision: revisit **after** the Kraken migration is
complete — do not mix the two changes.

## Interview context

This Binance→Kraken migration is the technical case study for the SDET interview at Kraken (2026-07-14).
Key talking points:

- **WS architecture redesign:** Binance's one-stream model vs Kraken's per-symbol subscription model,
  and why the latter is actually cleaner (no filtering thousands of irrelevant ticker prices)
- **Adapter boundary:** XBT normalization is isolated in `KrakenClient`; nothing else knows about it
- **Exchange-agnostic domain:** `src/domain/constants.py` decouples strategy logic from any SDK
- **Incremental migration:** 7 focused PRs, each independently testable, nothing broken in between
