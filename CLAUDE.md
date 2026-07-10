 Cryptocopter — Developer Guide

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

**WS v2:** public channels on `wss://ws.kraken.com/v2`, authenticated (token) channels on
`wss://ws-auth.kraken.com/v2` — two separate connections, not one shared URL. (Earlier revisions
of this doc listed a single URL; corrected in PR5 after confirming against Kraken's docs.)

- `ticker` channel (public): requires explicit per-symbol subscription (no all-tickers stream)
- `executions` channel (auth): order/fill updates, authenticated via token from GetWebSocketsToken
- `balances` channel (auth): account balance updates
- `instrument` channel (public): all instrument metadata on subscribe (useful at startup)

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

**4. "Dead-man switch" scope decision (PR5).**
Kraken has a real, separately-named "dead man's switch" feature (`cancelAllOrdersAfter`) that
auto-cancels all resting orders if the bot stops pinging it — an order-safety mechanism, distinct
from connection liveness. PR5 explicitly scoped "dead-man switch" as connection-watchdog only
(each socket's own recv loop reconnects on message silence); `cancelAllOrdersAfter` was **not**
implemented. If order safety on a dropped connection becomes a requirement, it needs its own PR —
don't assume it's covered by the existing reconnect logic.

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

`handle_user_message` (PR6) receives the full channel envelope
(`{"channel": "executions"|"balances", "type": "snapshot"|"update", "data": [...]}`) and iterates
`data`, building one `ExecutionReport` per entry via `create_execution_report()`. `order_type` and
`time_in_force` are upper-cased on the way in (Kraken sends `"limit"`/`"GTC"` lowercase-ish;
domain constants are `"LIMIT"`/`"GTC"`) — `hp_manager.py`'s FSM conditions compare
`execution_report.order_type == ORDER_TYPE_LIMIT` by exact string match, so skipping the
upper-case step would silently break every fill/cancel/expire transition.

## Kraken balances channel mapping

`create_account_position()` (PR6) maps each `balances` channel data entry to a `Balance`:
`asset` → `coin`, and `free`/`locked` are derived from `balance` (total) minus `hold_trade`
(amount held by open orders) — `free = balance - hold_trade`, `locked = hold_trade`. **Caveat:**
same as the `instrument` channel mapping in PR5 — this is based on Kraken's documented schema,
not verified against a live connection, since the test suite always mocks the WebSocket layer.
Smoke-test before relying on it in production; a wrong `hold_trade` mapping would silently
misreport available balance to `Portfolio`.

## "ALL"-ticker subscription gap (found during PR6, not fixed)

`Portfolio` (`portfolio.py`), `hpfront.py`, `asyncapp.py`, and `buy_dip/executor.py` all subscribe
to price updates with `symbol="ALL"`, relying on Binance's all-symbols ticker firehose to get a
`AllTickers` broadcast for every coin. Kraken has no all-symbols stream (see "No all-tickers
stream" above) — `BrokerSpot._signal_ws_subscribe` would call
`WebSocketManager.subscribe_ticker("ALL")`, sending an invalid `symbol: ["ALL"]` subscribe frame
to Kraken. This predates PR6 (it follows directly from the per-symbol subscription model decided
for PR5) but PR6 is where it became concrete, since `handle_ticker_message` is what used to
produce the `AllTickers` broadcast from Binance's all-symbols payload — there is no Kraken message
shape to build that broadcast from anymore, so PR6 removed the `AllTickers`/`ALL_TICKERS` path
from `handle_ticker_message` entirely rather than fake it. **Not fixed here** — needs its own PR:
most likely, `symbol="ALL"` price subscribers need to subscribe per-held-coin instead of the
literal string `"ALL"`. Until then, `Portfolio`/frontend live price updates for held coins do not
work against a real Kraken connection (account-position/balance updates are unaffected — the
`balances` channel is genuinely account-wide, no per-symbol issue there).

## Kraken AssetPairs → Symbol field mapping

| Symbol field | Kraken `AssetPairs` field |
|---|---|
| `precision` | derived from `lot_decimals` |
| `price_precision` | `pair_decimals` |
| `min_qty` | `ordermin` |
| `min_notional` | `costmin` |
| `price_filter` (tick size) | `tick_size` |

`Symbol.lot_size` and `Symbol.max_qty` were removed in PR4 — neither had a Kraken `AssetPairs`
equivalent, and grep confirmed nothing outside `symbol.py` ever read them.

`fetch_symbols()` prefers live WS data (`KrakenClient.get_asset_pairs_ws()`, a one-shot connect
→ subscribe to `instrument` → wait for the snapshot → disconnect) and falls back to REST
`KrakenClient.get_asset_pairs()` on any exception, including timeout or an empty result — landed
in PR5, per the "WS is primary, REST is fallback" migration direction. **Caveat:** the WS
instrument-channel field mapping (`qty_precision`→`lot_decimals`, `price_precision`→`pair_decimals`,
`qty_min`→`ordermin`, `cost_min`→`costmin`, `tick_size`/`price_increment`→`tick_size`) is based on
Kraken's documented schema and has not been verified against a live connection — this codebase's
test suite always mocks `KrakenClient`. Smoke-test `get_asset_pairs_ws()` against the real API
before relying on it in production; the REST fallback is the safety net if the mapping is wrong.

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
`Symbol.is_convert_only` is deleted too — it was only ever set by the now-deleted convert path.

PR7 also updated the quote-currency lists that mirror this routing decision, so a symbol ending
in PLN or BNB is no longer treated as parseable/tradeable anywhere: `Symbol.extract_coin_from_symbol`,
`KrakenClient._KNOWN_QUOTE_CURRENCIES` (`src/common/client.py`), and `StrategyExecutor.supported_quotes`
(`src/strategy_executor.py`) all dropped `PLN`/`BNB` and added `ETH`. `UsdPriceResolver.resolve_usd`
(`src/portfolio/usd_price_resolver.py`) was rewritten to mirror the exact same three-priority
routing (direct USDC → via BTC → via ETH → raise), replacing the old USDT-fallback/exotic-pair-loop
logic; its `get_all_tickers()` REST call is unchanged and still unimplemented on `KrakenClient`
(see the gaps list below — not this PR's scope).

**Not touched — pre-existing dead code, not wired to anything PR7 removed:** the GUI layer
(`src/gui/hp_manager/hp_data_manager.py`, `hp_position_updater.py`, `hp_state_calculator.py`,
`hpfront.py`) still has classification branches for an `hp_id` ending in `"_CONVERT"` and for
`symbol.is_convert_only`. Grepping for where a `"_CONVERT"`-suffixed `hp_id` is ever *assigned*
turned up nothing — `ConvertSellStrategy.build_positions()` never added that suffix, so this GUI
code was already unreachable before PR7 deleted the strategy that (didn't) feed it. Left in place
rather than expanded into GUI cleanup, since it was never live behavior to begin with.

## Migration PR plan

| PR | Branch | Status | Scope |
|---|---|---|---|
| 1 | `feature/kraken-ph1-constants-decoupling` | **MERGED** | `src/domain/constants.py`; replace all `binance.enums` imports in domain/strategies/tests |
| 2 | `feature/kraken-ph2-order-id-str` | **MERGED** | `Order.order_id: int → str`; DB schema `order_id TEXT`; `str(resp["orderId"])` in position files |
| 3 | `feature/kraken-ph3-client` | **MERGED** | `KrakenClient` class; XBT normalization; replace `binance.exceptions`; remove `python-binance` dep |
| 4 | `feature/kraken-ph4-symbol-fetching` | **MERGED** | Rewrite `fetch_symbols()` for Kraken `AssetPairs` |
| 5 | `feature/kraken-ph5-websocket` | **MERGED** | Kraken WS v2; per-symbol subscriptions; token auth + refresh; connection-silence watchdog; symbol metadata via `instrument` channel with REST `AssetPairs` fallback |
| 6 | `feature/kraken-ph6-message-handlers` | **MERGED** | Rewrite `message_handlers.py` for Kraken event schema |
| 7 | `feature/kraken-ph7-sell-factory` | IN REVIEW | Remove PLN/BNB/Convert; Kraken routing; update price resolver |

## KrakenClient gaps after PR3

PR3 only implements what PR3 itself needs — `create_order`, `cancel_order` — via
`kraken.spot.Trade` (python-kraken-sdk), wrapped in `asyncio.to_thread` since the SDK's REST
clients are synchronous. PR4 adds `get_asset_pairs()` via `kraken.spot.Market`, same pattern.
PR5 adds `get_ws_token()` (via `Trade`'s generic signed-`request()` method — the SDK has no
dedicated `GetWebSocketsToken` wrapper) and `get_asset_pairs_ws()` (one-shot raw-`websockets`
connection to the public `instrument` channel; see the caveat under "Kraken AssetPairs → Symbol
field mapping" above). The following Binance-only methods are **still not implemented** on
`KrakenClient` and will raise `AttributeError` if hit at runtime until their owning PR lands:

- `convert_request_quote` / `convert_accept_quote` (`hp_manager.py`) — deleted in PR7, not replaced
- `get_all_tickers` (`usd_price_resolver.py`), `get_orderbook_ticker` (GUI symbol picker),
  `get_account` (`portfolio.py` balance sync) — not owned by any PR in this table yet; needs a
  decision on which PR picks these up (likely folded into PR4 or a follow-up).
- `get_order` (used by `recovery/order_restorer.py`, `recovery/position_verifier.py`) — needs
  the same `order_status` + `cum_qty` status-normalization logic PR6 implemented as
  `_derive_order_status()` in `message_handlers.py`; that helper isn't reused here (recovery reads
  via REST, not the executions WS channel) but the same mapping rules apply. Still not
  implemented — not owned by any PR in this table yet.
- `close_connection` (`main.py` shutdown path) — not yet decided whether `KrakenClient` needs
  explicit cleanup at all, since `kraken.spot.Trade` is sync/requests-based. Not owned by any PR.

`WebSocketManager`'s old `_ws_api_request`/`ws_api` gap (listen-key-style user stream, python-binance's
WS-API pattern) no longer applies — PR5 replaced it outright with Kraken WS v2's two-connection,
token-in-subscribe-frame model (see "Kraken WS — key differences from Binance" above), so there
was nothing to implement on `KrakenClient` matching that old shape.

None of these are exercised by the test suite (client is always mocked), so `pytest` stays
green — but real recovery/portfolio/GUI runs against a live KrakenClient will fail on these
paths until the relevant PR lands. Each call site is marked with a `# type: ignore[attr-defined]`
plus a `TODO(PRn)` comment so `mypy` passes in CI without hiding unrelated errors in those files.

**`buy_dip` strategy was missed by the migration entirely.** `src/strategies/buy_dip/broker_adapter.py`
still calls `create_order`/`cancel_order` with the old python-binance kwargs (`order_type`,
`time_in_force`, `new_client_order_id`, `orig_client_order_id`), which don't exist on
`KrakenClient`'s signature at all — this isn't a deferred gap, it's a call site nobody updated.
It isn't mentioned anywhere in the architecture diagram or PR plan above. Marked with
`# type: ignore[call-arg]` / `# type: ignore[arg-type]` for now; needs its own fix, most likely
folded into whichever PR touches `buy_dip` next (none currently scheduled).

PR6 widens this gap: `buy_dip/executor.py`'s kline handling (`event.get("k", {})`, reading Binance
kline fields `o`/`h`/`l`/`c`/`v`/`t`/`T`/`x`) still expects the old Binance kline WS shape, but
`handle_kline_message` now forwards raw Kraken `ohlc` channel entries instead (fields like
`symbol`/`open`/`high`/`low`/`close`/`volume`/`interval_begin`/`interval` — no Binance-style `x`
"is candle closed" flag; Kraken's `ohlc` channel just streams continuous updates per open interval
and a consumer has to detect closes via `interval_begin` transitions). Also part of the
not-yet-scheduled `buy_dip` fix.

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
