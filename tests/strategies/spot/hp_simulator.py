import asyncio
import logging
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_CANCELED,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_FILLED,
)
from src.common.symbol_info import SymbolInfo
from src.gui.hpfront import HpFront
from src.identifiers.common import Mode, PositionSide
from src.identifiers.spot import (
    Event,
    EventName,
    ExecutionReport,
    HPBuyConfig,
    HPBuyData,
    HPSellConfig,
    HPSellData,
    State,
    StateInfo,
    TickerUpdate,
)
from src.strategies.hp_manager import HpStrategy
from src.strategy_executor import StrategyExecutor
from tests.spot import get_new_orders
from tests.strategies.spot.hp_manager_helpers import wait_for_condition

logger = logging.getLogger("hp_simulator")


class HPSimulator:
    def __init__(self, front: HpFront, back: StrategyExecutor):
        self.front = front
        self.back = back

    def new_price(self, price: float):
        ticker_event = Event(
            name=EventName.TICKER, content=TickerUpdate(last_price=price)
        )
        self.back.strategies["1000"].worker_queue.put_nowait(ticker_event)
        logger.info("Put event to the worker: %s", ticker_event)

    def simulate_buy_position(
        self,
        symbol: str,
        mode: Mode = Mode.DCA,
        budget: float = 1000,
        price_low: float = 1000,
        price_high: float = 1400,
        order_trigger: float = 1.0,
    ):
        hp = HPBuyData(
            HPBuyConfig(
                hp_id="0",
                symbol_info=SymbolInfo(symbol=symbol, precision=2, price_precision=2),
                price_low=price_low,
                price_high=price_high,
                order_trigger=order_trigger,
                budget=budget,
                mode=mode,
            ),
            state_info=StateInfo(),
        )

        self.front.config_queue.put_nowait(hp)
        logger.info("HP Buy Data added to the queue: %s", hp)

    async def assert_default_buy_position(self):
        await wait_for_condition(condition_func=lambda: len(self.back.strategies) == 1)
        assert not self.back.config_queue.qsize()
        assert len(self.back.strategies) == 1
        strategy = self.back.strategies["1000"]

        assert isinstance(strategy, HpStrategy)
        assert strategy.state == State.NEW
        assert len(strategy.buy.orders) == 3

        await wait_for_condition(
            condition_func=lambda: not self.front.active_records_buy
        )
        await wait_for_condition(condition_func=lambda: self.front.idle_records_buy)

    async def move_to_position_active_buy(self):
        # Open position and send orders
        strategy = self.back.strategies["1000"]
        strategy.client.create_order.side_effect = get_new_orders(
            orders=strategy.buy.orders
        )
        self.new_price(price=1410)

        # Assert new opened position data
        await wait_for_condition(condition_func=lambda: strategy.state == State.BUYING)
        await wait_for_condition(condition_func=lambda: self.front.active_records_buy)
        await wait_for_condition(condition_func=lambda: not self.front.idle_records_buy)
        assert strategy.buy.data.state_info.state == State.NEW
        assert all(order.order_id for order in strategy.buy.orders)
        assert all(order.status == ORDER_STATUS_NEW for order in strategy.buy.orders)

        logger.info("Active records: %s", self.front.active_records_buy)
        logger.info("Idle records: %s", self.front.idle_records_buy)

    async def cancel_buy_position_untouched(self):
        strategy = self.back.strategies["1000"]
        strategy.buy.data.state_info.stagnation_counter = (
            strategy.buy.data.state_info.stagnation_limit
        )

        strategy.buy.data.state_info.generate_next_monitor_time()

        assert strategy.calculate_trigger_cancel_orders_price_buy() == 1428.0
        self.new_price(price=1428)

        await wait_for_condition(
            condition_func=lambda: all(
                order.status == ORDER_STATUS_CANCELED for order in strategy.buy.orders
            )
        )

        assert len(strategy.buy.orders) == 3
        assert strategy.buy.data.state_info.state == State.NEW
        assert strategy.state == State.NEW

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == State.NEW.value
        )

        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["asset"] == "BTC"
        assert item["buy_price"] == "0.0"
        assert item["quantity"] == "0.0"
        assert item["quantity_usdt"] == "0.0"
        assert item["sell_price"] == "0.0"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "NEW"

    async def simulate_partial_fill(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
            order_id=445860,
            last_executed_quantity=0.12,
            last_executed_price=1400,
            cumulative_filled_quantity=0.12,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Orders: %s", strategy.buy.orders)
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[0].status
            == ORDER_STATUS_PARTIALLY_FILLED
        )
        assert strategy.buy.orders[1].status == ORDER_STATUS_NEW
        assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == str(exc_report.last_executed_quantity)
        )

        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["asset"] == "BTC"
        assert item["buy_price"] == "1400.0"
        assert item["quantity"] == "0.12"
        assert item["quantity_usdt"] == "168.0"
        assert item["sell_price"] == "0.0"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BUYING"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_first_buy_order_fill(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=445860,
            last_executed_quantity=0.24,
            last_executed_price=1400,
            cumulative_filled_quantity=0.24,
            price=1400.0,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Orders: %s", strategy.buy.orders)
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[0].status == ORDER_STATUS_FILLED
        )
        assert strategy.buy.orders[1].status == ORDER_STATUS_NEW
        assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == str(exc_report.last_executed_quantity)
        )

        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["asset"] == "BTC"
        assert item["buy_price"] == "1400.0"
        assert item["quantity"] == "0.24"
        assert item["quantity_usdt"] == "336.0"
        assert item["sell_price"] == "0.0"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BUYING"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_second_buy_order_fill(
        self, sell_price: str = "0.0"
    ) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=445861,
            last_executed_quantity=0.28,
            last_executed_price=1200,
            cumulative_filled_quantity=0.28,
            price=1200,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Orders: %s", strategy.buy.orders)
        assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[1].status == ORDER_STATUS_FILLED
        )
        assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

        realized_quantity = str(
            strategy.buy.orders[0].realized_quantity
            + strategy.buy.orders[1].realized_quantity
        )
        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == realized_quantity
        )

        logger.info(
            "a: %s, b: %s", self.front.hp_list_data[0]["quantity"], realized_quantity
        )

        assert len(self.front.hp_list_data) == 1
        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["asset"] == "BTC"
        assert item["buy_price"] == "1292.31"
        assert item["quantity"] == "0.52"
        assert item["quantity_usdt"] == "672.0"
        assert item["sell_price"] == sell_price
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BUYING"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_third_buy_order_fill(
        self, sell_price: str = "0.0"
    ) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=445862,
            last_executed_quantity=0.33,
            last_executed_price=1000,
            cumulative_filled_quantity=0.33,
            price=1000,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Orders: %s", strategy.buy.orders)
        assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
        assert strategy.buy.orders[1].status == ORDER_STATUS_FILLED
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[2].status == ORDER_STATUS_FILLED
        )

        realized_quantity = str(
            round(sum(order.realized_quantity for order in strategy.buy.orders), 2)
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == realized_quantity
        )

        assert len(self.front.hp_list_data) == 1
        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["asset"] == "BTC"
        assert item["buy_price"] == "1178.82"
        assert item["quantity"] == "0.85"
        assert item["quantity_usdt"] == "1002.0"
        assert item["sell_price"] == sell_price
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BOUGHT"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_bought_position(self):
        # Get default buy position
        self.simulate_buy_position(symbol="BTCUSDC")
        await self.assert_default_buy_position()

        await self.move_to_position_active_buy()

        # Simulate first order fill
        await self.simulate_first_buy_order_fill()
        await self.simulate_second_buy_order_fill()
        await self.simulate_third_buy_order_fill()

    async def setup_sell_position(
        self,
        hp_id: str,
        symbol: str,
        quantity: float,
        buy_price: float,
        sell_price: float,
        end_currency: str,
        asset: str,
    ):
        sell_config = HPSellData(
            config=HPSellConfig(
                hp_id=hp_id,
                asset=asset,
                buy_price=buy_price,
                sell_price=sell_price,
                quantity=quantity,
                end_currency=end_currency,
                symbol_info=SymbolInfo(symbol=symbol, precision=2, price_precision=2),
            ),
            state_info=StateInfo(side=PositionSide.SHORT),
        )
        self.front.config_queue.put_nowait(sell_config)
        logger.info("Sell config added to the queue: %s", sell_config.config)

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["sell_price"] == "4200.0"
        )

        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["asset"] == "BTC"
        assert item["buy_price"] == "1178.82"
        assert item["quantity"] == "0.85"
        assert item["quantity_usdt"] == "1002.0"
        assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BOUGHT"

        await wait_for_condition(
            condition_func=lambda: self.back.strategies["1000"].sell.orders
        )

    async def send_sell_orders_for_bought_position(self):
        strategy = self.back.strategies["1000"]
        logger.info("Sell orders: %s", strategy.sell.orders)
        strategy.client.create_order.side_effect = get_new_orders(strategy.sell.orders)
        self.new_price(price=4156)

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "SELLING"
        )

        item = self.front.hp_list_data[0]

        assert item["hp_id"] == "1000"
        assert item["asset"] == "BTC"
        assert item["buy_price"] == "1178.82"
        assert item["quantity"] == "0.85"
        assert item["quantity_usdt"] == "1002.0"
        assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "SELLING"

        await wait_for_condition(
            condition_func=lambda: strategy.sell.orders[0].status == ORDER_STATUS_NEW
        )
        assert strategy.sell.orders[0].quantity == 0.85
        assert strategy.sell.orders[0].realized_quantity == 0.0

        active_sell_item = self.front.active_records_sell[0]

        assert active_sell_item["hp_id"] == "1000"
        assert active_sell_item["symbol"] == "BTCUSDC"
        assert active_sell_item["buy_price"] == "1178.82"
        assert active_sell_item["quantity"] == "0.85"
        assert active_sell_item["end_currency"] == "USDC"
        assert (
            active_sell_item["sell_price"] == "4200.0"
        ), f"Item sell price: {item['sell_price']}"
        assert active_sell_item["stagnation"] == "0/8"
        assert active_sell_item["side"] == "SELL"
        assert active_sell_item["completeness"] == "0.0"

    async def cancel_unfilled_sell_position(self):
        strategy = self.back.strategies["1000"]
        strategy.sell.data.state_info.stagnation_counter = (
            strategy.sell.data.state_info.stagnation_limit
        )
        self.new_price(3864)
        assert len(strategy.sell.orders) == 1

        await wait_for_condition(
            condition_func=lambda: strategy.sell.orders[0].status
            == ORDER_STATUS_CANCELED
        )

        assert strategy.sell.orders[0].quantity == 0.85
        assert strategy.sell.orders[0].realized_quantity == 0.0

        assert strategy.sell.data.state_info.state == State.NEW
        assert strategy.state == State.BOUGHT

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "BOUGHT"
        )

        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["asset"] == "BTC"
        assert item["buy_price"] == "1178.82"
        assert item["quantity"] == "0.85"
        assert item["quantity_usdt"] == "1002.0"
        assert item["sell_price"] == "4200.0"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BOUGHT"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def simulate_sell_order_partial_fill(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
            order_id=5617834,
            last_executed_quantity=0.42,
            last_executed_price=4200,
            cumulative_filled_quantity=0.42,
            price=4200.0,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING
        logger.info(
            "Orders..................................................: %s",
            strategy.sell.orders,
        )
        await wait_for_condition(
            condition_func=lambda: strategy.sell.orders[0].status
            == ORDER_STATUS_PARTIALLY_FILLED
        )
        await asyncio.sleep(1)
        logger.info("Value....... %s", self.front.hp_list_data[0]["quantity"])

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == str(exc_report.last_executed_quantity)
        )

        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["asset"] == "BTC"
        assert item["buy_price"] == "1178.82"
        assert item["quantity"] == "0.425"
        assert item["quantity_usdt"] == "501.0"
        assert item["sell_price"] == "4200.0"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "SELLING"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_sell_order_fill(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=5617834,
            last_executed_quantity=0.85,
            last_executed_price=4200,
            cumulative_filled_quantity=0.85,
            price=4200.0,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING
        logger.info("Orders: %s", strategy.sell.orders)
        await wait_for_condition(
            condition_func=lambda: strategy.sell.orders[0].status == ORDER_STATUS_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == str(exc_report.last_executed_quantity)
        )

        item = self.front.hp_list_data[0]
        logger.info("Iteeeeeeeeeeem: %s", item)

        assert item["hp_id"] == "1000"
        assert item["asset"] == "BTC"
        assert item["buy_price"] == "1178.82"
        assert item["quantity"] == "0.0", f"Item quantity: {item['quantity']}"
        assert item["quantity_usdt"] == "0.0"
        assert item["sell_price"] == "4200.0"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "SOLD"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy
