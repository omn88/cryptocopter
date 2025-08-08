import asyncio
import logging
import os
import queue
import threading
import time  # Add time import for WebSocket error handling
from typing import Dict, List, Optional
from decouple import Config, RepositoryEnv
from binance.enums import (
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_NEW,
)
from src.common.common import generate_hp_id
from src.database import TradingDatabase
from src.identifiers import (
    CoinBalance,
    Event,
    EventName,
    ExecutionReport,
    HPBuyConfig,
    HPBuyData,
    HPSellConfig,
    HPSellData,
    Order,
    RemoveRecord,
    SellPosition,
    SellType,
    State,
    StateInfo,
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
    UiState,
    BinanceClient,
    PositionSide,
    HPSellPositionCreated,
    HPSellPositionCompleted,
    HPBuyPositionFilled,
    HPPositionCancelled,
)
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import (
    HPClose,
    HPGuiDataBuy,
    HPGuiDataSell,
    HPUpdate,
)
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.position_buy import HPPositionBuy
from src.position_sell import HPPositionSell
from src.strategies.hp_manager import HpStrategy
from src.broker import BrokerSpot
from src.database.recovery_service import RecoveryService
from src.database.exceptions import RecoveryError


# Specify the path to the .env file
DOTENV_FILE = "config/.env"
if os.path.exists(DOTENV_FILE):
    config_env = Config(RepositoryEnv(DOTENV_FILE))
else:
    print("Warning: .env file not found! Using default values.")
    config_env = {
        "API_KEY": "key",
        "API_SECRET": "secret",
    }


logger = logging.getLogger("strategy_executor")


class StrategyExecutor:
    def __init__(
        self,
        db: TradingDatabase,
        broker: BrokerSpot,
        symbols_info: Dict[str, SymbolInfo],
        ui_queue: queue.Queue,
        balances: Dict[str, CoinBalance],
        price_resolver: UsdPriceResolver,
        portfolio_ui_queue: Optional[queue.Queue] = None,
        test_mode: bool = False,
    ):
        logger.info("StrategyExecutor.__init__ called with test_mode=%s", test_mode)
        self.client: Optional[BinanceClient] = None
        self.db = db
        self.broker = broker
        self.ui_queue = ui_queue
        self.portfolio_ui_queue = (
            portfolio_ui_queue  # Queue for sending HP events to portfolio
        )
        self.config_queue: queue.Queue = queue.Queue()
        self.strategies: Dict[str, HpStrategy] = {}
        self.recovery_service: Optional[RecoveryService] = None
        self.symbols_info = symbols_info
        self.balances = balances
        self.supported_quotes = ["USDC", "PLN", "BTC", "BNB", "USDT"]
        self.test_mode = test_mode  # Add a test_mode parameter
        self.price_resolver = price_resolver

        # WebSocket error handling attributes
        self._websocket_error_count = 0
        self._last_websocket_error_time = 0
        self._websocket_error_suppression_time = 600  # 10 minutes
        self.loop = None
        self.stop_event = threading.Event()
        logger.info("Starting StrategyExecutor thread")
        self.thread = threading.Thread(target=self.start_loop)
        self.thread.start()
        logger.info("StrategyExecutor thread started")

    def start_loop(self):
        """Starts the asyncio loop in a new thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.run())

    async def run(self) -> None:
        logger.info("Strategy executor ready to retrieve the first config")
        logger.info(
            "Test mode: %s, Client available: %s",
            self.test_mode,
            self.client is not None,
        )
        if self.test_mode:
            logger.info(
                "Test mode - using injected client, crash recovery will be triggered manually when client is assigned"
            )
        else:
            self.client = BinanceClient(
                api_key=config_env("API_KEY"), api_secret=config_env("API_SECRET")
            )
            logger.info("Production client initialized")
            # Always run crash recovery after client is available (will be no-op if database is empty)
            logger.info(
                "About to start crash recovery, client available: %s",
                self.client is not None,
            )
            await self.recover_positions_from_crash()

        # Set up WebSocket error handling (for both test and real mode)
        if hasattr(self.broker, "set_error_handler"):
            self.broker.set_error_handler(self._handle_websocket_error)

        while not self.stop_event.is_set():
            try:
                strategy_data = self.config_queue.get_nowait()
                logger.info("New config for strategy executor: %s", strategy_data)
                if isinstance(strategy_data, HPBuyData):
                    asyncio.create_task(self.setup_buy_position(new_hp=strategy_data))
                if isinstance(strategy_data, HPSellData):
                    sell_strategy = self.determine_sell_strategy(
                        config=strategy_data.config
                    )
                    logger.info("Sell strategy determined: %s", sell_strategy)
                    # Patch: Set symbol_info if convert-only or USDC
                    if sell_strategy[0].is_convert_only or sell_strategy[
                        0
                    ].symbol.endswith("USDC"):
                        strategy_data.config.symbol_info = sell_strategy[0]
                    sell_position = SellPosition(
                        sell_order=Order(quantity=0),
                        config=strategy_data.config,
                        state_info=strategy_data.state_info,
                    )
                    if not strategy_data.config.hp_id:
                        await self.setup_sell_position_with_new_hp(
                            strategy_data=sell_position, sell_strategy=sell_strategy
                        )
                        await self.db.upsert_sell_price_level(
                            data=sell_position, strategy_state=State.BOUGHT
                        )
                    else:
                        await self.setup_sell_position(
                            strategy_data=sell_position, sell_strategy=sell_strategy
                        )

                if isinstance(strategy_data, RemoveRecord):
                    await self.remove_record(
                        hp_id=strategy_data.hp_id, side=strategy_data.side
                    )
                if isinstance(strategy_data, HPClose):
                    await self.close_position(close_data=strategy_data)

            except queue.Empty:
                await asyncio.sleep(0.1)

    def _restore_current_sell_position_for_multihop(self, strategy: HpStrategy):
        """
        If this is a two-hop sell, and the first leg is FILLED, advance current_position to the second leg.
        """
        sell_positions = strategy.sell.sell_positions
        if sell_positions and len(sell_positions) == 2:
            first_leg = sell_positions[0]
            second_leg = sell_positions[1]
            if first_leg.sell_order.status == ORDER_STATUS_FILLED:
                # Advance current_position to the second leg
                strategy.sell.current_position = second_leg
                logger.info(
                    "[Recovery] Advanced current_position to second leg after first leg FILLED: %s",
                    second_leg.config.hp_id,
                )

    async def _restore_all_child_sell_positions_for_multihop(
        self, strategy: HpStrategy
    ):
        """
        For two-hop sells, after recovery, restore both child sell positions (e.g., hp_id ending with 'a' and 'b') from DB.
        Set their orders and state, and set current_position to the correct child based on the status of the child positions in the DB.
        """
        sell_positions = strategy.sell.sell_positions
        if not (sell_positions and len(sell_positions) == 2):
            return

        # Restore each child sell position's order from DB (as before)
        for pos in sell_positions:
            orders = await self.db.fetch_orders_for_price_level(
                hp_id=pos.config.hp_id, side=PositionSide.SHORT.value
            )
            if orders:
                order_dict = orders[0]
                pos.sell_order.order_id = order_dict["order_id"]
                pos.sell_order.quantity = order_dict["quantity"]
                pos.sell_order.precision = pos.config.symbol_info.precision
                pos.sell_order.price_precision = pos.config.symbol_info.price_precision
                pos.sell_order.price = order_dict["price"]
                pos.sell_order.quantity_stable = order_dict["quantity_stable"]
                pos.sell_order.realized_quantity = order_dict["realized_quantity"]
                pos.sell_order.status = order_dict["status"]
                logger.info(
                    "[Recovery] Patched sell order for child %s: %s",
                    pos.config.hp_id,
                    pos.sell_order,
                )
            else:
                logger.info(
                    "[Recovery] No sell orders found in DB for child %s",
                    pos.config.hp_id,
                )

        # Set current_position based on child leg order status
        first_leg = sell_positions[0]
        second_leg = sell_positions[1]
        first_status = first_leg.sell_order.status
        second_status = second_leg.sell_order.status

        if first_status == ORDER_STATUS_FILLED:
            strategy.sell.current_position = second_leg
            logger.info(
                "[Recovery] Set current_position to second leg after first leg FILLED: %s",
                second_leg.config.hp_id,
            )
        elif first_status in [ORDER_STATUS_NEW, "PARTIALLY_FILLED", "SUBMITTED"]:
            strategy.sell.current_position = first_leg
            logger.info(
                "[Recovery] Set current_position to first leg (open): %s",
                first_leg.config.hp_id,
            )
        elif second_status in [ORDER_STATUS_NEW, "PARTIALLY_FILLED", "SUBMITTED"]:
            strategy.sell.current_position = second_leg
            logger.info(
                "[Recovery] Set current_position to second leg (open): %s",
                second_leg.config.hp_id,
            )
        else:
            # Fallback: set to 'b' if present
            for pos in sell_positions:
                if pos.config.hp_id.endswith("b"):
                    strategy.sell.current_position = pos
                    logger.info(
                        "[Recovery] Fallback: Set current_position to child leg 'b': %s",
                        pos.config.hp_id,
                    )
                    break

    def _send_hp_event_to_portfolio(self, event_name: EventName, event_data):
        """Send HP events to portfolio for quantity management."""
        if self.portfolio_ui_queue is None:
            logger.debug("No portfolio UI queue available, skipping HP event")
            return

        try:
            event = Event(name=event_name, content=event_data)
            self.portfolio_ui_queue.put_nowait(event)
            logger.info(f"Sent HP event to portfolio: {event_name.value}")
        except Exception as e:
            logger.error(f"Failed to send HP event to portfolio: {e}")

    async def _handle_websocket_error(self, error_msg):
        """Handle WebSocket errors, especially keepalive timeouts and unrecoverable failures."""
        current_time = time.time()

        # Check for unrecoverable errors
        unrecoverable_types = [
            "BinanceWebsocketUnableToConnect",
            "BinanceWebsocketClosed",
            "ConnectionClosedError",
        ]
        unrecoverable_msgs = [
            "Max reconnections",
            "timed out during opening handshake",
            "Cannot connect to host",
            "Temporary failure in name resolution",
            "getaddrinfo failed",
        ]

        is_unrecoverable = False
        if isinstance(error_msg, dict):
            error_type = error_msg.get("type", "")
            error_message = error_msg.get("m", "")
            if any(t in error_type for t in unrecoverable_types) or any(
                m in error_message for m in unrecoverable_msgs
            ):
                is_unrecoverable = True

        # If unrecoverable, restart websocket client with infinite retry
        if is_unrecoverable:
            logger.error(
                "Unrecoverable websocket error detected: %s. Restarting BinanceClient and resubscribing all strategies.",
                error_msg,
            )
            retry_count = 0
            while True:
                try:
                    # Stop current client if exists
                    logger.info("Attempting to restart BinanceClient...")
                    if self.client:
                        try:
                            await self.client.close_connection()
                        except Exception as e:
                            logger.warning("Error closing client: %s", e)
                        self.client = None
                    # Recreate client
                    logger.info("Recreating BinanceClient...")
                    if self.test_mode:
                        logger.info(
                            "Test mode - using injected client, crash recovery will be triggered manually when client is assigned"
                        )
                    else:
                        self.client = BinanceClient(
                            api_key=config_env("API_KEY"),
                            api_secret=config_env("API_SECRET"),
                        )
                    logger.info("BinanceClient restarted successfully.")
                    # Resubscribe all strategies
                    await self._resubscribe_all_strategies()
                    logger.info("Resubscription after restart complete.")
                    break
                except Exception as e:
                    retry_count += 1
                    logger.error(
                        "Websocket restart attempt #%d failed: %s. Retrying in %d seconds...",
                        retry_count,
                        e,
                        min(30, 2**retry_count),
                    )
                    await asyncio.sleep(min(30, 2**retry_count))
            return

        # Check if this is a keepalive timeout error (legacy logic)
        if isinstance(error_msg, dict):
            error_type = error_msg.get("type", "")
            error_message = error_msg.get("m", "")
            if (
                "keepalive ping timeout" in error_message
                or "ConnectionClosedError" in error_type
            ):
                # Suppress frequent logging of the same error
                if (
                    current_time - self._last_websocket_error_time
                    > self._websocket_error_suppression_time
                ):
                    logger.warning(
                        "WebSocket keepalive timeout detected. This is a known issue with "
                        "python-binance + Python 3.12. Connection will auto-reconnect."
                    )
                    self._last_websocket_error_time = current_time
                    self._websocket_error_count = 1
                else:
                    self._websocket_error_count += 1
                if self._websocket_error_count > 20:
                    logger.warning(
                        "Excessive WebSocket reconnections detected (%d errors), will resubscribe all streams",
                        self._websocket_error_count,
                    )
                    await self._resubscribe_all_strategies()
                    self._websocket_error_count = 0
                return

        # Handle other WebSocket errors normally
        logger.error("WebSocket error: %s", error_msg)

    async def _resubscribe_all_strategies(self):
        """Resubscribe all active strategies after excessive reconnections"""
        logger.info("Resubscribing all active strategy WebSocket streams...")

        for strategy_id, strategy in self.strategies.items():
            try:
                worker_queue = strategy.worker_queue

                # Unsubscribe first
                self.broker.unsubscribe(system_id=str(strategy_id))

                # Wait a bit
                await asyncio.sleep(1)

                # Resubscribe to user data stream
                self.broker.subscribe(
                    system_id=str(strategy_id),
                    subscription_info=SubscriptionInfo(
                        data_type=SubscriptionType.USER,
                        symbol=strategy.buy.data.config.symbol_info.symbol,
                        target=SubscriptionTarget.BACKEND,
                        queue=worker_queue,
                    ),
                )

                # Resubscribe to price stream
                self.broker.subscribe(
                    system_id=str(strategy_id),
                    subscription_info=SubscriptionInfo(
                        data_type=SubscriptionType.PRICE,
                        symbol=strategy.buy.data.config.symbol_info.symbol,
                        target=SubscriptionTarget.BACKEND,
                        queue=worker_queue,
                    ),
                )
                logger.debug("Resubscribed streams for strategy %s", strategy_id)

            except Exception as e:
                logger.error("Failed to resubscribe strategy %s: %s", strategy_id, e)

        logger.info("Finished resubscribing all strategies")

    def determine_sell_strategy(self, config: HPSellConfig) -> List[SymbolInfo]:
        delisted_coins = {
            "USDT",
            "FDUSD",
            "TUSD",
            "USDP",
            "DAI",
            "AEUR",
            "UST",
            "USTC",
            "PAXG",
        }

        strategy = []
        coin = config.coin
        end_currency = config.end_currency

        if end_currency == "PLN":
            # Priority 1: Direct pair to PLN
            if f"{coin}PLN" in self.symbols_info:
                strategy.append(self.symbols_info[f"{coin}PLN"])
                return strategy

            # Priority 2: coinUSDC + USDCPLN
            if f"{coin}USDC" in self.symbols_info and "USDCPLN" in self.symbols_info:
                strategy.append(self.symbols_info[f"{coin}USDC"])
                strategy.append(self.symbols_info["USDCPLN"])
                return strategy

            # Priority 3: coinBTC + BTCPLN
            if (
                coin not in delisted_coins
                and f"{coin}BTC" in self.symbols_info
                and "BTCPLN" in self.symbols_info
            ):
                strategy.append(self.symbols_info[f"{coin}BTC"])
                strategy.append(self.symbols_info["BTCPLN"])
                return strategy

            # Priority 4: coinBNB + BNBPLN
            if (
                coin not in delisted_coins
                and f"{coin}BNB" in self.symbols_info
                and "BNBPLN" in self.symbols_info
            ):
                strategy.append(self.symbols_info[f"{coin}BNB"])
                strategy.append(self.symbols_info["BNBPLN"])
                return strategy

            # Priority 5: Converting
            symbol_info = self.symbols_info[f"{coin}USDT"]
            symbol_info.is_convert_only = True
            strategy.append(symbol_info)
            return strategy

        if end_currency == "USDC":
            # Priority 1: coinUSDC
            if f"{coin}USDC" in self.symbols_info:
                strategy.append(self.symbols_info[f"{coin}USDC"])
                return strategy

            # Priority 2: coinBTC + BTCUSDC
            if (
                coin not in delisted_coins
                and f"{coin}BTC" in self.symbols_info
                and "BTCUSDC" in self.symbols_info
            ):
                strategy.append(self.symbols_info[f"{coin}BTC"])
                strategy.append(self.symbols_info["BTCUSDC"])
                return strategy

            # Priority 3: Exotic coinXYZ + XYZUSDC
            if coin not in delisted_coins:
                for pair in self.symbols_info:
                    if pair.startswith(coin):
                        quote = pair.replace(coin, "")
                        if quote in delisted_coins:
                            continue
                        if f"{quote}USDC" in self.symbols_info:
                            strategy.append(self.symbols_info[pair])
                            strategy.append(self.symbols_info[f"{quote}USDC"])
                            return strategy

            # Priority 4: Converting
            symbol_info = self.symbols_info[f"{coin}USDT"]
            symbol_info.is_convert_only = True
            strategy.append(symbol_info)
            return strategy
        return []

    def stop(self):
        logger.info("Stopping strategy executor, stop event SET.")
        self.stop_event.set()

        if self.client:
            try:
                asyncio.run(self.client.close_connection())
            except RuntimeError:
                logger.warning("No running event loop, skipping async close.")

        logger.info("Client connection closed.")
        self.thread.join()
        logger.info("Strategy executor thread finished")

    async def close_position(self, close_data: HPClose):
        self.broker.unsubscribe(system_id=close_data.config.hp_id)
        strategy = self.strategies[close_data.config.hp_id]

        strategy.stop_event.set()

    async def setup_buy_position(
        self,
        new_hp: HPBuyData,
        is_restoration: bool = False,
    ) -> None:
        logger.info(
            "setup_buy_position called: hp_id=%s, is_restoration=%s",
            new_hp.config.hp_id,
            is_restoration,
        )

        # For restoration, preserve existing HP ID; for new positions, generate new one
        if not is_restoration:
            logger.info("Setting up new position with config: %s", new_hp.config)

            new_hp.config.hp_id = generate_hp_id(hp_list=list(self.strategies.keys()))
            new_hp.state_info.generate_open_time()
        else:
            logger.info("Restoration mode: preserving HP ID %s", new_hp.config.hp_id)

        logger.info("Client check: %s", self.client is not None)
        assert self.client is not None
        worker_queue: queue.Queue = queue.Queue()

        logger.info("Self balances: %s", self.balances)

        logger.info("Creating HpStrategy for HP %s", new_hp.config.hp_id)
        strategy = HpStrategy(
            client=self.client,
            ui_queue=self.ui_queue,
            balance=self.balances["USDC"].total,
            db=self.db,
            worker_queue=worker_queue,
            config_queue=self.config_queue,
            buy_position=HPPositionBuy(
                client=self.client,
                data=new_hp,
                db=self.db,
            ),
            sell_position=HPPositionSell(
                client=self.client,
                original_position=SellPosition(
                    config=HPSellConfig(
                        hp_id=new_hp.config.hp_id,
                        symbol_info=new_hp.config.symbol_info,
                        coin=new_hp.config.coin,
                    ),
                    state_info=StateInfo(side=PositionSide.SHORT),
                    sell_order=Order(quantity=0.0),
                ),
                db=self.db,
                sell_strategy=[],
                price_resolver=self.price_resolver,
                broker=self.broker,
                worker_queue=worker_queue,
            ),
            portfolio_event_callback=self._send_hp_event_to_portfolio,  # Pass callback for portfolio events
        )

        assert isinstance(strategy.buy.data.config, HPBuyConfig)
        logger.info("HpStrategy created successfully for HP %s", new_hp.config.hp_id)

        # Handle order preparation: restore from DB for restoration mode, create new for normal mode
        if is_restoration:
            # Restore existing buy orders from database instead of creating new ones
            strategy.buy.orders = await self.restore_buy_orders(
                buy_position=strategy.buy, worker_queue=worker_queue
            )

            # --- Patch: recalculate state from orders after restoration ---
            logger.info("[Recovery][Buy] Orders for completeness calculation:")
            for idx, order in enumerate(strategy.buy.orders):
                logger.info(
                    "[Recovery][Buy] Order %d: status=%s, quantity=%s, realized_quantity=%s",
                    idx,
                    order.status,
                    order.quantity,
                    order.realized_quantity,
                )

            all_filled = all(
                order.status == ORDER_STATUS_FILLED for order in strategy.buy.orders
            )
            part_bought = any(
                order.realized_quantity > 0 for order in strategy.buy.orders
            )

            # Detailed completeness calculation logging
            total_realized = sum(
                order.realized_quantity for order in strategy.buy.orders
            )
            total_quantity = sum(order.quantity for order in strategy.buy.orders)
            logger.info(
                "[Recovery][Buy] total_realized_quantity=%s, total_order_quantity=%s",
                total_realized,
                total_quantity,
            )
            if total_quantity > 0:
                completeness = total_realized / total_quantity
            else:
                completeness = 0.0
            logger.info("[Recovery][Buy] Calculated completeness=%s", completeness)

            # Default state logic

            strategy.buy.data.state_info.state = (
                State.BOUGHT
                if all_filled
                else State.NEW if not part_bought else State.PARTIALLY_BOUGHT
            )

            # --- Restore sell position state and orders if they exist in DB ---
            logger.info(
                "[Recovery] Checking for sell orders for HP %s", new_hp.config.hp_id
            )
            sell_orders = await self.db.fetch_orders_for_price_level(
                hp_id=new_hp.config.hp_id, side=PositionSide.SHORT.value
            )
            logger.info(
                "[Recovery] fetch_orders_for_price_level returned: %s", sell_orders
            )
            if sell_orders:
                logger.info(
                    "[Recovery] Found %d sell orders for HP %s",
                    len(sell_orders),
                    new_hp.config.hp_id,
                )
                db_order = sell_orders[0]
                logger.info(
                    "[Recovery] Restoring sell order fields from DB: %s", db_order
                )
                strategy.sell.current_position.sell_order.order_id = db_order[
                    "order_id"
                ]
                strategy.sell.current_position.sell_order.quantity = db_order[
                    "quantity"
                ]
                strategy.sell.current_position.sell_order.precision = (
                    strategy.sell.current_position.config.symbol_info.precision
                )
                strategy.sell.current_position.sell_order.price_precision = (
                    strategy.sell.current_position.config.symbol_info.price_precision
                )
                strategy.sell.current_position.sell_order.price = db_order["price"]
                strategy.sell.current_position.sell_order.quantity_stable = db_order[
                    "quantity_stable"
                ]
                strategy.sell.current_position.sell_order.realized_quantity = db_order[
                    "realized_quantity"
                ]
                strategy.sell.current_position.sell_order.status = db_order["status"]
                logger.info(
                    "[Recovery] Patched sell order for HP %s: %s",
                    new_hp.config.hp_id,
                    strategy.sell.current_position.sell_order,
                )
            else:
                logger.info(
                    "[Recovery] No sell orders found in DB for HP %s",
                    new_hp.config.hp_id,
                )

            # Restore strategy execution state from database (for main state)
            strategy_state_str = await self._get_strategy_state_from_db(
                new_hp.config.hp_id
            )
            strategy.state = State(strategy_state_str)

            logger.info("strategy.state restored from DB: %s", strategy.state)
        else:
            # Create new orders for normal setup
            strategy.buy.prepare_orders()
            strategy.buy.data.state_info.generate_open_time()

        self.strategies[new_hp.config.hp_id] = strategy

        self.send_buy_position_to_ui(
            config=new_hp.config,
            state_info=new_hp.state_info,
            state=strategy.state,
            buy_orders=strategy.buy.orders,
        )

        self.broker.subscribe(
            system_id=str(new_hp.config.hp_id),
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.USER,
                symbol=new_hp.config.symbol_info.symbol,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )
        self.broker.subscribe(
            system_id=str(new_hp.config.hp_id),
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol=new_hp.config.symbol_info.symbol,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )

        await self.db.upsert_buy_price_level(
            data=strategy.buy.data, strategy_state=strategy.state
        )

        strategy.worker_task = asyncio.create_task(strategy.worker())
        logger.info("System with ID %s initialized.", new_hp.config.hp_id)

    def send_buy_position_to_ui(
        self,
        config: HPBuyConfig,
        state_info: StateInfo,
        state: State,
        buy_orders: List[Order],
    ):
        total_quant = sum(order.realized_quantity for order in buy_orders)
        self.ui_queue.put_nowait(
            HPGuiDataBuy(
                data=HPBuyData(config=config, state_info=state_info),
                hp_update=HPUpdate(
                    hp_id=config.hp_id,
                    coin=config.coin,
                    symbol_info=config.symbol_info,
                    state=state,
                    buy_price=config.price_high,
                    quantity=float(total_quant) if total_quant else None,
                ),
            )
        )

    def send_sell_position_to_ui(
        self, config: HPSellConfig, state_info: StateInfo, state: State
    ):
        expected_return = None
        if config.buy_price is not None and config.sell_price is not None:
            expected_return = config.symbol_info.adjust_price(
                (config.sell_price - config.buy_price) * config.quantity
            )
        quantity_usd = config.symbol_info.adjust_price(
            config.quantity * config.buy_price
        )
        self.ui_queue.put_nowait(
            HPGuiDataSell(
                data=HPSellData(config=config, state_info=state_info),
                hp_update=HPUpdate(
                    hp_id=config.hp_id,
                    buy_price=config.buy_price,
                    sell_price=config.sell_price,
                    coin=config.coin,
                    symbol_info=config.symbol_info,
                    state=state,
                    quantity=config.quantity,
                    quantity_usd=quantity_usd,
                    expected_return=expected_return,
                ),
            )
        )

    async def setup_sell_position(
        self, strategy_data: SellPosition, sell_strategy: List[SymbolInfo]
    ) -> None:
        logger.info(
            "Setting up sell position for existing HP: %s", strategy_data.config.hp_id
        )
        strategy: HpStrategy = self.strategies[strategy_data.config.hp_id]
        assert self.client
        if strategy_data.state_info.state == State.NEW:
            strategy.sell = HPPositionSell(
                client=self.client,
                original_position=SellPosition(
                    config=strategy_data.config,
                    state_info=strategy_data.state_info,
                    sell_order=Order(quantity=strategy_data.config.quantity),
                ),
                db=self.db,
                sell_strategy=sell_strategy,
                price_resolver=self.price_resolver,
                broker=self.broker,
                worker_queue=strategy.worker_queue,
            )
            logger.info(
                "Current position in standard setup sell: %s",
                strategy.sell.current_position,
            )
        if strategy_data.state_info.state == State.CLOSED:
            logger.info("Closing sell position")
            if strategy.state == State.SELLING:
                await strategy.sell.cancel_position()
            strategy.sell.current_position.config.sell_price = (
                strategy_data.config.sell_price
            )
            strategy.sell.current_position.state_info.ui_state = UiState.CLOSED

        await self.db.upsert_sell_price_level(
            data=strategy.sell.current_position, strategy_state=strategy.state
        )
        self.send_sell_position_to_ui(
            config=strategy.sell.current_position.config,
            state_info=strategy.sell.current_position.state_info,
            state=strategy.state,
        )
        logger.debug("Sell position setup exit")

    async def setup_sell_position_with_new_hp(
        self,
        strategy_data: SellPosition,
        sell_strategy: List[SymbolInfo],
        is_restoration: bool = False,
    ) -> (
        None
    ):  # For restoration, preserve existing HP ID; for new positions, generate new one
        if not is_restoration:
            parent_hp_id = generate_hp_id(hp_list=list(self.strategies.keys()))
            strategy_data.config.hp_id = parent_hp_id
        else:
            parent_hp_id = strategy_data.config.hp_id
        logger.info(
            "Setting up NEW SELL position with config: %s", strategy_data.config
        )

        assert self.client is not None
        worker_queue: queue.Queue = queue.Queue()

        strategy = HpStrategy(
            client=self.client,
            ui_queue=self.ui_queue,
            buy_position=HPPositionBuy(
                client=self.client,
                data=HPBuyData(
                    config=HPBuyConfig(
                        hp_id=parent_hp_id,
                        symbol_info=strategy_data.config.symbol_info,
                        coin=strategy_data.config.coin,
                    ),
                    state_info=StateInfo(ui_state=UiState.CLOSED, state=State.BOUGHT),
                ),
                db=self.db,
            ),
            sell_position=HPPositionSell(
                client=self.client,
                original_position=SellPosition(
                    config=strategy_data.config,
                    state_info=strategy_data.state_info,
                    sell_order=Order(quantity=strategy_data.config.quantity),
                    sell_type=(
                        SellType.TWOHOPS
                        if len(sell_strategy) == 2
                        else (
                            SellType.CONVERT
                            if sell_strategy[0].is_convert_only
                            else SellType.DIRECT
                        )
                    ),
                ),
                db=self.db,
                sell_strategy=sell_strategy,
                price_resolver=self.price_resolver,
                broker=self.broker,
                worker_queue=worker_queue,
            ),
            balance=self.balances["USDC"].total,
            db=self.db,
            worker_queue=worker_queue,
            config_queue=self.config_queue,
            initial_state=State.BOUGHT,
            portfolio_event_callback=self._send_hp_event_to_portfolio,  # Pass callback for portfolio events
        )

        config = strategy.sell.current_position.config

        # Handle restoration vs new position setup
        if is_restoration:
            logger.info(
                "[Recovery] Entering sell position restoration for HP %s", parent_hp_id
            )
            # Restore existing sell orders from database
            sell_order = await self.restore_sell_orders(
                sell_config=strategy.sell.current_position.config,
                worker_queue=worker_queue,
            )
            logger.info("[Recovery] restore_sell_orders() returned: %s", sell_order)
            if sell_order:
                logger.info(
                    "[Recovery] Assigning restored sell order to in-memory: %s",
                    sell_order,
                )
                strategy.sell.current_position.sell_order = sell_order
                logger.info(
                    "[Recovery] In-memory sell order after assignment: %s",
                    strategy.sell.current_position.sell_order,
                )
            else:
                logger.info(
                    "[Recovery] No sell orders found in DB for HP %s", parent_hp_id
                )

            # --- Restore buy position state and orders if they exist in DB ---
            # Check if there are buy orders for this hp_id
            buy_orders = await self.db.fetch_orders_for_price_level(
                hp_id=parent_hp_id, side=PositionSide.LONG.value
            )
            logger.info(
                "[Recovery] fetch_orders_for_price_level(BUY) returned: %s", buy_orders
            )
            if buy_orders:
                # Use the existing restore_buy_orders logic to populate strategy.buy.orders
                strategy.buy.orders = await self.restore_buy_orders(
                    buy_position=strategy.buy, worker_queue=worker_queue
                )
                logger.info(
                    "[Recovery] In-memory buy orders after restore: %s",
                    strategy.buy.orders,
                )
                strategy_state_str = await self._get_strategy_state_from_db(
                    parent_hp_id
                )
                logger.info("[Recovery] Strategy state from DB: %s", strategy_state_str)
                strategy.state = State(strategy_state_str)

                # Set buy state based on actual buy order statuses
                all_filled = all(
                    o.status == ORDER_STATUS_FILLED for o in strategy.buy.orders
                )
                all_new = all(o.status == ORDER_STATUS_NEW for o in strategy.buy.orders)

                if all_filled:
                    strategy.buy.data.state_info.state = State.BOUGHT
                elif all_new:
                    strategy.buy.data.state_info.state = State.NEW
                elif any(o.realized_quantity > 0 for o in strategy.buy.orders):
                    strategy.buy.data.state_info.state = State.PARTIALLY_BOUGHT
                else:
                    strategy.buy.data.state_info.state = State.CLOSED

            logger.info(
                "Before restoration, current_position: %s",
                strategy.sell.current_position,
            )
            # --- Patch: For two-hop sells, advance current_position to second leg if first leg is FILLED ---
            self._restore_current_sell_position_for_multihop(strategy)
            # logger.info("After restoration, current_position: %s", strategy.sell.current_position)
            # # --- General: For two-hop sells, restore both child legs and set current_position appropriately ---
            await self._restore_all_child_sell_positions_for_multihop(strategy)

        else:
            # Generate new timestamp for new positions
            strategy.sell.current_position.state_info.generate_open_time()

        logger.info("Current position: %s", strategy.sell.current_position)

        self.strategies[parent_hp_id] = strategy

        assert config.symbol_info.symbol.endswith(
            tuple(self.supported_quotes)
        ), f"Symbol must end with one of {self.supported_quotes}"
        self.send_sell_position_to_ui(
            config=strategy.sell.original_position.config,
            state_info=strategy.sell.original_position.state_info,
            state=strategy.state,
        )

        for position in strategy.sell.sell_positions:
            self.send_sell_position_to_ui(
                config=position.config,
                state_info=position.state_info,
                state=strategy.state,
            )
        self.broker.subscribe(
            system_id=str(parent_hp_id),
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.USER,
                symbol=config.symbol_info.symbol,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )
        for symbol_info in sell_strategy:
            self.broker.subscribe(
                system_id=str(parent_hp_id),
                subscription_info=SubscriptionInfo(
                    data_type=SubscriptionType.PRICE,
                    symbol=symbol_info.symbol,
                    target=SubscriptionTarget.BACKEND,
                    queue=worker_queue,
                ),
            )

        await self.db.upsert_sell_price_level(
            data=strategy.sell.current_position, strategy_state=strategy.state
        )

        # Send HP sell position created event to portfolio for quantity locking
        if not is_restoration:  # Only send for new positions, not restored ones
            hp_sell_created = HPSellPositionCreated(
                hp_id=parent_hp_id,
                coin=config.coin,
                quantity=config.quantity,
                buy_price=config.buy_price,  # Use buy price from config
                sell_price=config.sell_price,  # Use sell price from config
                end_currency=config.end_currency,  # Use end currency from config
            )
            self._send_hp_event_to_portfolio(
                EventName.HP_SELL_POSITION_CREATED, hp_sell_created
            )

        strategy.worker_task = asyncio.create_task(strategy.worker())
        logger.info("System with ID %s initialized.", parent_hp_id)

    async def remove_record(self, hp_id: str, side: PositionSide) -> None:
        logger.info(
            "Entering remove record, id: %s to system: %s", hp_id, self.strategies
        )

        if hp_id not in self.strategies:
            logger.info("HP %s NOT in running strategies", hp_id)
            return

        strategy: HpStrategy = self.strategies[hp_id]
        logger.info("Found strategy with hp id: %s, side to remove: %s", hp_id, side)
        buy = strategy.buy
        sell = strategy.sell

        if (
            side == PositionSide.LONG
            and sell.current_position.state_info.state == State.NEW
            and buy.data.state_info.state == State.NEW
        ):
            logger.info("Entered trading system removal!")
            self.broker.unsubscribe(system_id=hp_id)
            strategy.state = State.CLOSED
            buy.data.state_info.state = State.CLOSED
            if buy.orders:
                buy.orders = await buy.cancel_remaining_limit_orders(
                    symbol=buy.data.config.symbol_info.symbol,
                    orders=buy.orders,
                )
                for order in buy.orders:
                    if order.status == ORDER_STATUS_CANCELED:
                        await self.db.upsert_order(
                            order=order,
                            hp_id=hp_id,
                            side=side,
                        )
                buy.data.state_info.get_completeness(buy.orders)

            await self.db.upsert_buy_price_level(data=buy.data)

            buy.data.state_info.ui_state = UiState.CLOSED

            self.send_buy_position_to_ui(
                config=strategy.buy.data.config,
                state_info=strategy.buy.data.state_info,
                state=strategy.state,
                buy_orders=strategy.buy.orders,
            )

            logger.info("Removed strategy %s.", hp_id)
            return

        if (
            side == PositionSide.LONG
            and buy.data.state_info.state == State.PARTIALLY_BOUGHT
        ):
            if strategy.state == State.BUYING:
                buy.orders = await buy.cancel_remaining_limit_orders(
                    symbol=buy.data.config.symbol_info.symbol,
                    orders=buy.orders,
                )
                strategy.state = buy.data.state_info.state
                for order in buy.orders:
                    if order.status == ORDER_STATUS_CANCELED:
                        await self.db.upsert_order(
                            order=order, hp_id=buy.data.config.hp_id, side=side
                        )
            buy.data.state_info.state = State.CLOSED
            buy.data.state_info.ui_state = UiState.CLOSED
            buy.data.state_info.completeness = sum(
                order.realized_quantity for order in buy.orders
            ) / sum(order.quantity for order in buy.orders)
            self.send_buy_position_to_ui(
                config=strategy.buy.data.config,
                state_info=strategy.buy.data.state_info,
                state=strategy.state,
                buy_orders=strategy.buy.orders,
            )

            await self.db.upsert_buy_price_level(data=buy.data)

        if side == PositionSide.SHORT:
            if strategy.state == State.SELLING:
                sell_rlzd_qty = (
                    strategy.sell.current_position.sell_order.realized_quantity
                )
                sell_order_qty = strategy.sell.current_position.sell_order.quantity
                fully_bought = all(
                    order.status == ORDER_STATUS_FILLED for order in strategy.buy.orders
                )
                await sell.cancel_remaining_order()
                strategy.state = (
                    State.PARTIALLY_BOUGHT
                    if not fully_bought
                    else (
                        State.BOUGHT
                        if fully_bought and not sell_rlzd_qty
                        else (
                            State.PARTIALLY_SOLD
                            if (
                                fully_bought
                                and sell_order_qty
                                and sell_rlzd_qty != sell_order_qty
                            )
                            else (
                                State.PART_SOLD_PART_BOUGHT
                                if (
                                    not fully_bought
                                    and sell_order_qty
                                    and sell_rlzd_qty != sell_order_qty
                                )
                                else State.SOLD
                            )
                        )
                    )
                )

                # Send HP sell position completed event to portfolio when fully sold
                if strategy.state == State.SOLD:
                    # Calculate the end currency received (typically USDC for the amount received)
                    end_currency_received = (
                        sell.current_position.sell_order.realized_quantity
                        * sell.current_position.config.sell_price
                    )

                    hp_sell_completed = HPSellPositionCompleted(
                        hp_id=hp_id,
                        coin=sell.current_position.config.coin,
                        quantity_sold=sell.current_position.sell_order.realized_quantity,
                        buy_price=sell.current_position.config.buy_price,  # Add missing buy price
                        sell_price=sell.current_position.config.sell_price,  # Add missing sell price
                        end_currency="USDC",  # Usually selling to USDC
                        end_currency_received=end_currency_received,
                    )
                    self._send_hp_event_to_portfolio(
                        EventName.HP_SELL_POSITION_COMPLETED, hp_sell_completed
                    )

                # if sell.current_position.sell_order.status == ORDER_STATUS_CANCELED:
                #     self.db.upsert_order(
                #         order=sell.current_position.sell_order, hp_id=hp_id, side=side
                #     )
            sell.current_position.config.sell_price = 0.0
            if sell.current_position.config.is_child:
                sell.original_position.config.sell_price = 0.0
                self.send_sell_position_to_ui(
                    config=strategy.sell.original_position.config,
                    state_info=strategy.sell.original_position.state_info,
                    state=strategy.state,
                )
            sell.current_position.state_info.ui_state = UiState.CLOSED
            sell.current_position.state_info.get_completeness(
                sell.current_position.sell_order
            )
            self.send_sell_position_to_ui(
                config=strategy.sell.current_position.config,
                state_info=strategy.sell.current_position.state_info,
                state=strategy.state,
            )
            await self.db.upsert_sell_price_level(
                data=sell.current_position, strategy_state=strategy.state
            )

    async def recover_positions_from_crash(self) -> None:
        """
        Recover all active trading positions from database after system crash/restart.

        This is the main crash recovery method that:
        1. Uses TradingDatabase to get active positions
        2. Verifies them with the exchange via RecoveryService
        3. Calls setup_buy_position and setup_sell_position_with_new_hp to restore them
        """
        logger.info("Starting crash recovery process...")
        logger.info(
            "Recovery debug: test_mode=%s, client=%s",
            self.test_mode,
            type(self.client).__name__ if self.client else None,
        )

        try:
            # Ensure client is available for recovery
            if not self.client:
                logger.error(
                    "No client available for crash recovery (test_mode=%s)",
                    self.test_mode,
                )
                if self.test_mode:
                    logger.error(
                        "In test mode but client was not assigned before recovery started"
                    )
                return

            logger.info("Client is available, proceeding with crash recovery")

            # Create recovery service with the same database instance
            self.recovery_service = RecoveryService(
                symbols_info=self.symbols_info, client=self.client, database=self.db
            )
            logger.info("Recovery service created successfully")

            # Recover all positions and convert them to trading objects
            logger.info("Calling recovery_service.recover_all_positions()")
            (
                buy_positions,
                sell_positions,
            ) = await self.recovery_service.recover_all_positions()

            logger.info(
                "Crash recovery found %d buy positions and %d sell positions",
                len(buy_positions),
                len(sell_positions),
            )

            # Restore buy positions using dedicated restore method (preserves HP IDs and state)
            for i, buy_data in enumerate(buy_positions):
                logger.info(
                    "Restoring buy position %d/%d: %s",
                    i + 1,
                    len(buy_positions),
                    buy_data.config.hp_id,
                )
                await self.restore_buy_position(buy_data=buy_data)
                logger.info(
                    "Successfully restored buy position %s", buy_data.config.hp_id
                )

            # Restore sell positions using dedicated restore method (preserves HP IDs and state)
            for i, sell_data in enumerate(sell_positions):
                logger.info(
                    "Restoring sell position %d/%d: %s",
                    i + 1,
                    len(sell_positions),
                    sell_data.config.hp_id,
                )
                await self.restore_sell_position(sell_data=sell_data)
                logger.info(
                    "Successfully restored sell position %s", sell_data.config.hp_id
                )

            logger.info(
                "Crash recovery completed successfully. Total strategies now: %d",
                len(self.strategies),
            )

        except RecoveryError as e:
            logger.error("Crash recovery failed: %s", e)
            # Don't raise - let the system continue with empty state
        except Exception as e:
            logger.error("Unexpected error during crash recovery: %s", e, exc_info=True)
            # Don't raise - let the system continue with empty state

    async def restore_buy_position(self, buy_data: HPBuyData) -> None:
        """
        Restore a buy position from crash recovery with its existing HP ID and state.
        Uses the normal setup process but with restoration flag to preserve state.
        """
        logger.info("Restoring buy position: %s", buy_data.config.hp_id)
        logger.info(
            "Buy position details: symbol=%s, coin=%s, budget=%s",
            buy_data.config.symbol_info.symbol,
            buy_data.config.coin,
            buy_data.config.budget,
        )

        try:
            # Use the normal setup process but in restoration mode
            await self.setup_buy_position(new_hp=buy_data, is_restoration=True)
            logger.info("Buy position %s restored successfully", buy_data.config.hp_id)
        except Exception as e:
            logger.error(
                "Failed to restore buy position %s: %s",
                buy_data.config.hp_id,
                e,
                exc_info=True,
            )
            raise

    async def restore_sell_position(self, sell_data: HPSellData) -> None:
        """
        Restore a sell position from crash recovery with its existing HP ID and state.
        Uses the normal setup process but with restoration flag to preserve state.
        """
        logger.info("Restoring sell position: %s", sell_data.config.hp_id)

        # Convert HPSellData to SellPosition format expected by setup method
        sell_position = SellPosition(
            config=sell_data.config,
            state_info=sell_data.state_info,
            sell_order=Order(quantity=sell_data.config.quantity),
        )

        # Determine sell strategy for this position
        sell_strategy = self.determine_sell_strategy(config=sell_data.config)

        # Use the normal setup process but in restoration mode
        await self.setup_sell_position_with_new_hp(
            strategy_data=sell_position,
            sell_strategy=sell_strategy,
            is_restoration=True,
        )

        logger.info("Sell position %s restored successfully", sell_data.config.hp_id)

    async def restore_buy_orders(
        self, buy_position: HPPositionBuy, worker_queue: queue.Queue
    ) -> List[Order]:
        assert self.client
        buy_config = buy_position.data.config  # Restore orders for buy position

        # Use the dedicated method to fetch all orders for this HP and side
        orders = await self.db.fetch_orders_for_price_level(
            hp_id=buy_config.hp_id, side=PositionSide.LONG.value
        )

        logger.info("Orders for HP: %s, %s", buy_config.hp_id, orders)
        if not orders:
            buy_position.prepare_orders()
            return buy_position.orders

        # Group orders by price level (price, quantity)
        from collections import defaultdict

        grouped_orders = defaultdict(list)
        for order_dict in orders:
            key = (order_dict["price"], order_dict["quantity"])
            grouped_orders[key].append(order_dict)

        restored_orders: List[Order] = []
        for (price, quantity), order_dicts in grouped_orders.items():
            # Aggregate realized_quantity from all orders for this price level
            total_realized = sum(o["realized_quantity"] for o in order_dicts)
            # Find the latest open order (not FILLED or CANCELED), else the latest order
            open_orders = [
                o
                for o in order_dicts
                if o["status"] not in [ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED]
            ]
            if open_orders:
                # Use the latest open order (by order_id or timestamp if available)
                latest_order = max(open_orders, key=lambda o: o.get("order_id", 0))
            else:
                # Use the latest order overall
                latest_order = max(order_dicts, key=lambda o: o.get("order_id", 0))

            trading_order = Order(
                order_id=latest_order["order_id"],
                quantity=latest_order["quantity"],
                precision=buy_config.symbol_info.precision,
                price_precision=buy_config.symbol_info.price_precision,
                price=latest_order["price"],
                quantity_stable=latest_order["quantity_stable"],
                realized_quantity=total_realized,
                status=latest_order["status"],
            )
            restored_orders.append(trading_order)

        logger.info("Buy orders restored from DB (aggregated): %s.", restored_orders)

        # Confirm buy position state with the exchange for open orders
        for order in restored_orders:
            if order.status not in [ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED]:
                # Retrieve the latest order information from the API
                resp = await self.client.get_order(
                    symbol=buy_config.symbol_info.symbol,
                    orderId=order.order_id,
                )
                latest_status = resp["status"]
                latest_realized_quantity = float(resp["executedQty"])

                # Check if status or realized quantity has changed
                status_changed = latest_status != order.status
                quantity_changed = latest_realized_quantity != order.realized_quantity

                if status_changed or quantity_changed:
                    ex_report = ExecutionReport(
                        symbol=buy_config.symbol_info.symbol,
                        quantity=order.quantity,
                        price=order.price,
                        current_order_status=latest_status,
                        order_id=order.order_id,
                        cumulative_filled_quantity=latest_realized_quantity,
                    )
                    worker_queue.put_nowait(
                        Event(
                            name=EventName.EXECUTION_REPORT,
                            content=ex_report,
                        )
                    )
                    logger.info(
                        "Order %s has been modified, execution report send: %s",
                        order.order_id,
                        ex_report,
                    )
                else:
                    logger.info("No changes detected for order %s.", order.order_id)

        return restored_orders

    async def restore_sell_orders(
        self, sell_config: HPSellConfig, worker_queue: queue.Queue
    ) -> Optional[Order]:
        assert self.client  # Restore orders for sell position

        # Use the dedicated method to fetch orders for this HP and side
        orders = await self.db.fetch_orders_for_price_level(
            hp_id=sell_config.hp_id,
            side=PositionSide.SHORT.value,
        )

        if not orders:
            logger.info("No sell orders found in DB")
            return None

        if len(orders) == 2:
            for order in orders:
                if order["status"] == ORDER_STATUS_NEW:
                    current_order = order
                    break
        if len(orders) == 1:
            current_order = orders[0]

        # Convert order dictionaries to trading Order objects
        # Only restore orders that are not filled or canceled
        logger.info(
            "Restoring order %s with status %s",
            current_order["order_id"],
            current_order["status"],
        )
        trading_order = Order(
            order_id=current_order["order_id"],
            quantity=current_order["quantity"],
            precision=sell_config.symbol_info.precision,
            price_precision=sell_config.symbol_info.price_precision,
            price=current_order["price"],
            quantity_stable=current_order["quantity_stable"],
            realized_quantity=current_order["realized_quantity"],
            status=current_order["status"],
        )

        logger.info("Sell orders restored from DB: %s.", trading_order)

        if current_order["status"] not in [ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED]:
            # Retrieve the latest order information from the API
            resp = await self.client.get_order(
                symbol=sell_config.symbol_info.symbol,
                orderId=current_order["order_id"],
            )
            latest_status = resp["status"]
            latest_realized_quantity = float(resp["executedQty"])

            # Check if status or realized quantity has changed
            status_changed = latest_status != current_order["status"]
            quantity_changed = (
                latest_realized_quantity != current_order["realized_quantity"]
            )

            if status_changed or quantity_changed:
                # Send a message to the appropriate queue

                ex_report = ExecutionReport(
                    symbol=sell_config.symbol_info.symbol,
                    quantity=current_order["quantity"],
                    price=current_order["price"],
                    current_order_status=latest_status,
                    order_id=current_order["order_id"],
                    cumulative_filled_quantity=latest_realized_quantity,
                )
                worker_queue.put_nowait(
                    Event(
                        name=EventName.EXECUTION_REPORT,
                        content=ex_report,
                    )
                )
                logger.info(
                    "Order %s has been modified, execution report send: %s",
                    current_order["order_id"],
                    ex_report,
                )
            else:
                logger.info(
                    "No changes detected for order %s.", current_order["order_id"]
                )
        return trading_order

    async def _get_strategy_state_from_db(self, hp_id: str) -> Optional[str]:
        """
        Get the strategy execution state for a given HP ID from the database.

        Args:
            hp_id: The HP ID to query for

        Returns:
            The strategy_state string from the database, or None if not found
        """
        try:
            async with self.db.get_connection() as conn:
                cursor = await conn.execute(
                    "SELECT strategy_state FROM positions WHERE hp_id = ? LIMIT 1",
                    (hp_id,),
                )
                row = await cursor.fetchone()
                if row:
                    return row["strategy_state"]
                else:
                    logger.warning("No strategy state found for HP ID: %s", hp_id)
                    return None
        except Exception as e:
            logger.error("Failed to get strategy state for HP %s: %s", hp_id, e)
            return None
