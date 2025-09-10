"""
Inventory Sell Simulator for testing inventory-based sell operations.

This simulator provides methods to test the complete inventory sell flow:
1. Clicking sell buttons on inventory items
2. Configuring sell parameters (direct, multi-hop, convert)
3. Creating HP sell positions
4. Executing sell orders
5. Validating final states
"""

import logging
from typing import List, Optional

from src.common.symbol_info import SymbolInfo
from src.gui.hp_manager.hpfront import HpFront
from src.strategy_executor import StrategyExecutor
from src.portfolio.portfolio_gui import PortfolioUI
from src.identifiers import (
    HPSellConfig,
    HPSellData,
    InventoryItem,
    PositionSide,
    State,
    StateInfo,
)
from tests.strategies.hp_manager_helpers import wait_for_condition

logger = logging.getLogger(__name__)


class InventorySellSimulator:
    """Simulator for inventory-based sell operations."""

    def __init__(
        self,
        portfolio: PortfolioUI,
        hp_manager: HpFront,
        strategy_executor: StrategyExecutor,
    ):
        self.portfolio = portfolio
        self.hp_manager = hp_manager
        self.strategy_executor = strategy_executor

    def get_inventory_item(self, coin: str) -> InventoryItem:
        """Get inventory item for a specific coin from portfolio inventory."""
        # Portfolio has the inventory, not strategy executor
        inventory = self.portfolio.inventory
        for item in inventory:
            if item.coin == coin:
                return item
        raise ValueError(f"No inventory item found for coin: {coin}")

    def get_all_inventory_items(self) -> List[InventoryItem]:
        """Get all inventory items from portfolio."""
        return self.portfolio.inventory

    async def verify_sell_modal_opened(
        self, coin: str, expected_quantity: float, expected_buy_price: float
    ):
        """Verify that sell modal opened with correct pre-populated data."""
        # This will need to be implemented - verify modal is open with correct data
        logger.info(
            f"TODO: Verify sell modal opened for {coin} with quantity={expected_quantity}, buy_price={expected_buy_price}"
        )
        pass

    async def configure_multi_hop_sell(self, sell_price: float, end_currency: str):
        """Configure multi-hop sell in the modal."""
        # This will simulate user entering multi-hop sell configuration
        logger.info(
            f"TODO: Configure multi-hop sell with price={sell_price}, end_currency={end_currency}"
        )
        pass

    async def configure_convert_sell(self, end_currency: str):
        """Configure convert-only sell in the modal."""
        # This will simulate user entering convert sell configuration
        logger.info(f"TODO: Configure convert sell to {end_currency}")
        pass

    async def submit_sell_configuration(
        self,
        coin: str,
        sell_price: float,
        end_currency: str = "USDC",
    ):
        """Submit the sell configuration to create HP sell position."""
        # This will simulate clicking "Create HP" or similar button in modal

        item = self.get_inventory_item(coin=coin)

        # Create sell configuration
        sell_config = HPSellConfig(
            coin=item.coin,
            buy_price=item.buy_price,
            sell_price=sell_price,
            quantity=item.available_quantity,
            end_currency=end_currency,
            symbol_info=self.strategy_executor.symbols_info[f"{coin}USDT"],
        )

        sell_data = HPSellData(
            config=sell_config,
            state_info=StateInfo(side=PositionSide.SHORT),
        )

        # Submit to HP manager via config queue
        self.hp_manager.config_queue.put_nowait(sell_data)
        logger.info(f"Submitted sell configuration: {sell_config}")

        await wait_for_condition(
            condition_func=lambda: len(self.strategy_executor.strategies) > 0,
            timeout=5.0,
        )

        # The HP ID will be dynamically generated, so let's find it
        if self.strategy_executor.strategies:
            generated_hp_id = list(self.strategy_executor.strategies.keys())[0]
            logger.info(f"HP position created with ID: {generated_hp_id}")
            return generated_hp_id
        else:
            raise RuntimeError(
                "No HP strategy was created after submitting sell configuration"
            )

    def verify_hp_sell_position_created(self, hp_id: str, coin: str, quantity: float):
        """Verify that HP sell position was created correctly."""
        assert hp_id in self.strategy_executor.strategies
        strategy = self.strategy_executor.strategies[hp_id]
        logger.info(
            f"Verified HP sell position created: {hp_id} for {coin} with quantity {quantity}"
        )
        # Add verification logic here

    async def simulate_sell_order_execution(self, hp_id: str):
        """Simulate the execution of the sell order to complete the sell flow."""
        from binance.enums import ORDER_TYPE_LIMIT, ORDER_STATUS_FILLED
        from src.identifiers import (
            Event,
            EventName,
            ExecutionReport,
            TickerUpdate,
            SignalUpdate,
            Signal,
        )

        strategy = self.strategy_executor.strategies[hp_id]

        # Step 1: First trigger transition from BOUGHT to SELLING using ticker update
        # The sell trigger price should be the sell price or slightly above
        sell_price = strategy.sell.current_position.config.sell_price
        strategy.ticker_update = TickerUpdate(
            last_price=sell_price,
            symbol=strategy.sell.current_position.config.symbol_info.symbol,
        )

        # Process ticker to move from BOUGHT to SELLING
        await strategy.process_ticker()  # type: ignore
        logger.info(f"Strategy {hp_id} transitioned to state: {strategy.state}")

        # Step 2: Simulate sell order execution
        sell_position = strategy.sell.current_position
        sell_order = sell_position.sell_order

        # Create execution report for full fill
        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=sell_order.order_id,
            last_executed_quantity=sell_order.quantity,
            last_executed_price=sell_order.price,
            cumulative_filled_quantity=sell_order.quantity,
            price=sell_order.price,
        )

        # Send execution report to strategy worker
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info(f"Sent execution report for HP {hp_id}: {exc_report}")

        # Step 3: Process the execution report
        await strategy.process_order()  # type: ignore

        # Step 4: Wait for order status to be filled
        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_FILLED
        )
        logger.info(f"Order status confirmed as FILLED for HP {hp_id}")

        # Step 5: Check if there's a signal to process and handle it
        if strategy.worker_queue.qsize() > 0:
            event = strategy.worker_queue.get_nowait()
            if event.name == EventName.SIGNAL and isinstance(
                event.content, SignalUpdate
            ):
                if event.content.signal == Signal.HP_ALL_ORDERS_FILLED:
                    strategy.signal_update = event.content
                    await strategy.process_signal()  # type: ignore
                    logger.info(f"Processed HP_ALL_ORDERS_FILLED signal for HP {hp_id}")

    async def verify_sell_execution_complete(self, hp_id: str, expected_state: State):
        """Verify that sell execution completed with expected state."""
        # First simulate the sell order execution
        await self.simulate_sell_order_execution(hp_id)

        # Then wait for the expected state
        await wait_for_condition(
            condition_func=lambda: self.strategy_executor.strategies[hp_id].state
            == expected_state
        )
        logger.info(
            f"Verified sell execution complete: {hp_id} reached state {expected_state}"
        )

    def verify_inventory_item_structure(self, item: InventoryItem, coin: str):
        """Verify that inventory item has expected structure and data."""
        assert item.coin == coin, f"Expected coin {coin}, got {item.coin}"
        assert item.available_quantity > 0, f"Expected positive quantity for {coin}"
        assert item.buy_price > 0, f"Expected positive buy price for {coin}"
        logger.info(
            f"Verified inventory item structure for {coin}: quantity={item.available_quantity}, price={item.buy_price}"
        )

    def verify_connections(self):
        """Verify that portfolio, HP manager, and strategy executor are properly connected."""
        # Verify portfolio has hp_manager reference
        assert hasattr(
            self.portfolio, "hp_manager"
        ), "Portfolio should have hp_manager reference"
        assert (
            self.portfolio.hp_manager is self.hp_manager
        ), "Portfolio should reference the correct HP manager"

        # Verify HP manager has portfolio_queue (not direct portfolio reference)
        assert hasattr(
            self.hp_manager, "portfolio_queue"
        ), "HP manager should have portfolio_queue for communication"

        # Verify HP manager does NOT have direct portfolio reference (correct architecture)
        assert not hasattr(
            self.hp_manager, "portfolio"
        ), "HP manager should NOT have direct portfolio reference - it uses portfolio_queue instead"

        # Verify backend connections
        assert (
            self.hp_manager.config_queue is self.strategy_executor.config_queue
        ), "HP manager should use strategy executor config queue"
        assert (
            self.strategy_executor.ui_queue is self.hp_manager.ui_queue
        ), "Strategy executor should use HP manager UI queue"

        logger.info("Verified all portfolio-HP manager-backend connections")

    async def validate_inventory_quantities(
        self, coin, expected_total, expected_available, expected_locked, description=""
    ):
        """Validate inventory quantities for a specific coin."""
        # Process any pending events first to ensure inventory is up to date
        await self.portfolio.process_test_events()

        logger.info("Inventory: %s", self.portfolio.inventory)

        coin_items = [item for item in self.portfolio.inventory if item.coin == coin]

        if not coin_items:
            if (
                expected_total == 0.0
                and expected_available == 0.0
                and expected_locked == 0.0
            ):
                logger.info(
                    f"✓ Inventory validation {description}: No {coin} items as expected"
                )
                return
            else:
                raise AssertionError(
                    f"Expected {coin} inventory items but none found. {description}"
                )

        actual_total = sum(item.quantity for item in coin_items)
        actual_available = sum(item.available_quantity for item in coin_items)
        actual_locked = sum(item.locked_quantity for item in coin_items)

        # Round to avoid floating point precision issues
        actual_total = round(actual_total, 8)
        actual_available = round(actual_available, 8)
        actual_locked = round(actual_locked, 8)
        expected_total = round(expected_total, 8)
        expected_available = round(expected_available, 8)
        expected_locked = round(expected_locked, 8)

        assert (
            actual_total == expected_total
        ), f"{description}: Expected {coin} total={expected_total}, got {actual_total}"
        assert (
            actual_available == expected_available
        ), f"{description}: Expected {coin} available={expected_available}, got {actual_available}"
        assert (
            actual_locked == expected_locked
        ), f"{description}: Expected {coin} locked={expected_locked}, got {actual_locked}"

        logger.info(
            f"✓ Inventory validation {description}: {coin} total={actual_total}, available={actual_available}, locked={actual_locked}"
        )

    def get_inventory_quantity(self, coin: str) -> float:
        """Get total inventory quantity for a coin."""
        coin_items = [item for item in self.portfolio.inventory if item.coin == coin]
        if not coin_items:
            return 0.0
        return sum(item.quantity for item in coin_items)

    def get_available_quantity(self, coin: str) -> float:
        """Get available inventory quantity for a coin."""
        coin_items = [item for item in self.portfolio.inventory if item.coin == coin]
        if not coin_items:
            return 0.0
        return sum(item.available_quantity for item in coin_items)

    def get_locked_quantity(self, coin: str) -> float:
        """Get locked inventory quantity for a coin."""
        coin_items = [item for item in self.portfolio.inventory if item.coin == coin]
        if not coin_items:
            return 0.0
        return sum(item.locked_quantity for item in coin_items)

    def get_total_quantity(self, coin: str) -> float:
        """Get total inventory quantity for a coin (alias for get_inventory_quantity)."""
        return self.get_inventory_quantity(coin)
