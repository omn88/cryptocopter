import logging
from typing import Optional
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_CANCELED,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_FILLED,
)
from src.common.symbol_info import SymbolInfo
from src.gui.hpfront import HpFront
from src.identifiers import (
    Event,
    EventName,
    ExecutionReport,
    HPBuyConfig,
    HPBuyData,
    HPSellConfig,
    HPSellData,
    Order,
    State,
    StateInfo,
    TickerUpdate,
    Mode,
    PositionSide,
)
from src.database.models import PositionStatus, PositionType, TradeType
from src.strategies.hp_manager import HpStrategy
from src.strategy_executor import StrategyExecutor
from tests.spot import get_new_orders
from tests.strategies.spot.hp_manager_helpers import wait_for_condition

logger = logging.getLogger("hp_simulator")


class HPSimulator:
    def __init__(self, front: HpFront, back: StrategyExecutor):
        self.front = front
        self.back = back

    def new_price(self, price: float, symbol: str = "BTCUSDC"):
        ticker_event = Event(
            name=EventName.TICKER, content=TickerUpdate(last_price=price, symbol=symbol)
        )
        self.back.strategies["1000"].worker_queue.put_nowait(ticker_event)
        logger.info("Put event to the worker: %s", ticker_event)

    def simulate_buy_position(
        self,
        symbol: str,
        mode: Mode = Mode.DCA,
        budget: float = 1000.0,
        price_low: float = 1000.0,
        price_high: float = 1400.0,
        order_trigger: float = 1.0,
        hp_id: str = "0",
        coin: str = "BTC",
    ):
        hp = HPBuyData(
            HPBuyConfig(
                hp_id=hp_id,
                symbol_info=SymbolInfo(symbol=symbol, precision=2, price_precision=2),
                price_low=price_low,
                price_high=price_high,
                order_trigger=order_trigger,
                budget=budget,
                mode=mode,
                coin=coin,
            ),
            state_info=StateInfo(),
        )

        self.front.config_queue.put_nowait(hp)
        logger.info("HP Buy Data added to the queue: %s", hp)

    async def assert_default_buy_position(self):
        logger.info(
            "=== ASSERTING DEFAULT BUY POSITION === len self back stragies: %s",
            len(self.back.strategies),
        )
        await wait_for_condition(condition_func=lambda: len(self.back.strategies) == 1)
        await wait_for_condition(
            condition_func=lambda: not self.back.config_queue.qsize()
        )
        assert len(self.back.strategies) == 1
        strategy = self.back.strategies["1000"]

        assert isinstance(strategy, HpStrategy)
        assert strategy.state == State.NEW, strategy.state
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
        self.new_price(price=1410.0, symbol="BTCUSDC")

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

        assert strategy.buy.orders_cancel_price == 1428.0
        self.new_price(price=1428.0, symbol="BTCUSDC")

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
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1400.0"
        assert item["quantity"] == "0.0"
        assert item["quantity_usd"] == "0.0"
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
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1400.0"
        assert item["quantity"] == "0.12"
        assert item["quantity_usd"] == "168.0"
        assert item["sell_price"] == "0.0"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BUYING"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_partial_fill_with_sell_price(self) -> HpStrategy:
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
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1400.0"
        assert item["quantity"] == "0.12"
        assert item["quantity_usd"] == "168.0"
        assert item["sell_price"] == "4200.0"
        assert item["expected_return"] == "336.0"
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
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1400.0"
        assert item["quantity"] == "0.24"
        assert item["quantity_usd"] == "336.0"
        assert item["sell_price"] == "0.0"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BUYING"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_second_buy_order_fill(self) -> HpStrategy:
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
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1292.31"
        assert item["quantity"] == "0.52"
        assert item["quantity_usd"] == "672.0"
        assert item["sell_price"] == "0.0", item["sell_price"]
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BUYING"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_third_buy_order_fill(self) -> HpStrategy:
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
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1178.82"
        assert item["quantity"] == "0.85"
        assert item["quantity_usd"] == "1002.0"
        assert item["sell_price"] == "0.0"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BOUGHT"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_second_buy_order_fill_with_sell_price(self) -> HpStrategy:
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
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1292.31"
        assert item["quantity"] == "0.52"
        assert item["quantity_usd"] == "672.0"
        assert item["sell_price"] == "4200.0", item["sell_price"]
        assert item["expected_return"] == "1512.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BUYING"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_third_buy_order_fill_with_sell_price(self) -> HpStrategy:
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
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1178.82"
        assert item["quantity"] == "0.85"
        assert item["quantity_usd"] == "1002.0"
        assert item["sell_price"] == "4200.0"
        assert item["expected_return"] == "2568.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BOUGHT"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_bought_position(self, symbol="BTCUSDC"):
        # Assumes position is already created and in default state
        self.simulate_buy_position(symbol=symbol)
        await self.assert_default_buy_position()
        await self.move_to_position_active_buy()
        # Simulate all three buy order fills
        strategy = await self.simulate_first_buy_order_fill()
        strategy = await self.simulate_second_buy_order_fill()
        strategy = await self.simulate_third_buy_order_fill()
        return strategy

    async def setup_sell_position(
        self,
        hp_id: str,
        symbol: str,
        quantity: float,
        buy_price: float,
        sell_price: float,
        end_currency: str,
        coin: str,
        trade_type: Optional[TradeType] = None,
    ):
        sell_config = HPSellData(
            config=HPSellConfig(
                hp_id=hp_id,
                coin=coin,
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
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1178.82", item["buy_price"]
        assert item["quantity"] == "0.85"
        assert item["quantity_usd"] == "1002.0"
        assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
        assert (
            item["expected_return"] == "2568.0"
        ), f"Item ER: {item['expected_return']}"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BOUGHT"

        await wait_for_condition(
            condition_func=lambda: self.back.strategies[
                "1000"
            ].sell.current_position.sell_order
        )

    async def send_sell_order_for_bought_position(self):
        strategy = self.back.strategies["1000"]
        logger.info("Sell order: %s", strategy.sell.current_position.sell_order)
        strategy.client.create_order.side_effect = get_new_orders(
            [strategy.sell.current_position.sell_order]
        )
        self.new_price(price=4156.0, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "SELLING"
        )

        item = self.front.hp_list_data[0]

        assert item["hp_id"] == "1000"
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1178.82"
        assert item["quantity"] == "0.85"
        assert item["quantity_usd"] == "1002.0"
        assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
        assert item["expected_return"] == "2568.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "SELLING"

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_NEW
        )
        assert strategy.sell.current_position.sell_order.quantity == 0.85
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.0

        active_sell_item = self.front.active_records_sell[0]

        assert active_sell_item["hp_id"] == "1000"
        assert active_sell_item["symbol"] == "BTCUSDC"
        assert active_sell_item["buy_price"] == "1178.82"
        assert active_sell_item["quantity"] == "0.85"
        assert active_sell_item["end_currency"] == "USDC"
        assert (
            active_sell_item["sell_price"] == "4200.0"
        ), f"Item sell price: {item['sell_price']}"
        assert active_sell_item["side"] == "SELL"
        assert active_sell_item["completeness"] == "0.0"

    async def cancel_unfilled_sell_position(self):
        strategy = self.back.strategies["1000"]
        self.new_price(3864, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_CANCELED
        )

        assert strategy.sell.current_position.sell_order.quantity == 0.85
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.0

        assert strategy.sell.current_position.state_info.state == State.NEW
        assert strategy.state == State.BOUGHT

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "BOUGHT"
        )

        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1178.82"
        assert item["quantity"] == "0.85"
        assert item["quantity_usd"] == "1002.0"
        assert item["sell_price"] == "4200.0"
        assert item["expected_return"] == "2568.0"
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
            order_id=12345,
            last_executed_quantity=0.42,
            last_executed_price=4200,
            cumulative_filled_quantity=0.42,
            price=4200.0,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_PARTIALLY_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"] == "0.43"
        )

        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1178.82"
        assert item["quantity"] == "0.43"
        assert item["quantity_usd"] == "506.89", item["quantity_usd"]
        assert item["sell_price"] == "4200.0"
        assert item["expected_return"] == "2568.0"
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
            order_id=12345,
            last_executed_quantity=0.85,
            last_executed_price=4200,
            cumulative_filled_quantity=0.85,
            price=4200.0,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING
        logger.info("Sell order: %s", strategy.sell.current_position.sell_order)
        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"] == "0.0"
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "SOLD"
        )

        item = self.front.hp_list_data[0]
        logger.info("Iteeeeeeeeeeem: %s", item)

        assert item["hp_id"] == "1000"
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1178.82"
        assert item["quantity"] == "0.0", f"Item quantity: {item['quantity']}"
        assert item["quantity_usd"] == "0.0"
        assert item["sell_price"] == "4200.0", item["sell_price"]
        assert item["expected_return"] == "2568.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "SOLD", f"State: {item['state']}"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def cancel_partially_sold_position(self):
        strategy = self.back.strategies["1000"]
        self.new_price(3864, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_CANCELED
        )

        assert strategy.sell.current_position.sell_order.quantity == 0.85
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.42

        assert strategy.sell.current_position.state_info.state == State.PARTIALLY_SOLD
        assert strategy.state == State.PARTIALLY_SOLD

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PARTIALLY_SOLD"
        )

        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1178.82"
        assert item["quantity"] == "0.43"
        assert item["quantity_usd"] == "506.89", item["quantity_usd"]
        assert item["sell_price"] == "4200.0"
        assert item["expected_return"] == "2568.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "PARTIALLY_SOLD"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def resend_sell_order_for_partially_sold_position(self):
        strategy = self.back.strategies["1000"]
        logger.info("Sell orders: %s", strategy.sell.current_position.sell_order)
        strategy.client.create_order.side_effect = get_new_orders(
            [strategy.sell.current_position.sell_order]
        )
        self.new_price(price=4156.0, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "SELLING"
        )

        item = self.front.hp_list_data[0]

        assert item["hp_id"] == "1000"
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1178.82"
        assert item["quantity"] == "0.43"
        assert item["quantity_usd"] == "506.89", item["quantity_usd"]
        assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
        assert item["expected_return"] == "2568.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "SELLING"

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_NEW
        )
        assert strategy.sell.current_position.sell_order.quantity == 0.85
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.42

        active_sell_item = self.front.active_records_sell[0]

        assert active_sell_item["hp_id"] == "1000"
        assert active_sell_item["symbol"] == "BTCUSDC"
        assert active_sell_item["buy_price"] == "1178.82"
        assert active_sell_item["quantity"] == "0.85"
        assert active_sell_item["end_currency"] == "USDC"
        assert (
            active_sell_item["sell_price"] == "4200.0"
        ), f"Item sell price: {item['sell_price']}"
        assert active_sell_item["side"] == "SELL"
        assert active_sell_item["completeness"] == "0.49", active_sell_item[
            "completeness"
        ]

    async def send_sell_order_for_part_bought_position(self):
        strategy = self.back.strategies["1000"]
        logger.info("Sell orders: %s", strategy.sell.current_position.sell_order)
        strategy.client.create_order.side_effect = get_new_orders(
            [strategy.sell.current_position.sell_order]
        )
        self.new_price(price=4156, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"] == "SELLING"
        )

        item = self.front.hp_list_data[0]

        assert item["hp_id"] == "1000"
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1400.0", f"Item buy price: {item['buy_price']}"
        assert item["quantity"] == "0.24", f"Item quantity: {item['quantity']}"
        assert item["quantity_usd"] == "336.0"
        assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
        assert item["expected_return"] == "672.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "SELLING"

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_NEW
        )
        assert strategy.sell.current_position.sell_order.quantity == 0.24
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.0

        active_sell_item = self.front.active_records_sell[0]

        assert active_sell_item["hp_id"] == "1000"
        assert active_sell_item["symbol"] == "BTCUSDC"
        assert active_sell_item["buy_price"] == "1400.0"
        assert active_sell_item["quantity"] == "0.24"
        assert active_sell_item["end_currency"] == "USDC"
        assert (
            active_sell_item["sell_price"] == "4200.0"
        ), f"Item sell price: {item['sell_price']}"
        assert active_sell_item["side"] == "SELL"
        assert active_sell_item["completeness"] == "0.0"

    async def setup_sell_position_after_first_buy_order_filled(
        self,
        hp_id: str,
        symbol: str,
        quantity: float,
        buy_price: float,
        sell_price: float,
        end_currency: str,
        coin: str,
    ):
        sell_config = HPSellData(
            config=HPSellConfig(
                hp_id=hp_id,
                coin=coin,
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
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1400.0", item["buy_price"]
        assert item["quantity"] == "0.24"
        assert item["quantity_usd"] == "336.0"
        assert item["sell_price"] == "4200.0", f"Item sell price: {item['sell_price']}"
        assert item["expected_return"] == "672.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "PARTIALLY_BOUGHT"

        await wait_for_condition(
            condition_func=lambda: self.back.strategies[
                "1000"
            ].sell.current_position.sell_order
        )

    async def cancel_buy_position_after_first_order_filled(self):
        strategy = self.back.strategies["1000"]

        assert strategy.buy.orders_cancel_price == 1428.0
        self.new_price(price=1428.0, symbol="BTCUSDC")

        assert len(strategy.buy.orders) == 3

        assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED

        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[1].status
            == ORDER_STATUS_CANCELED
        )
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[2].status
            == ORDER_STATUS_CANCELED
        )

        assert strategy.buy.orders[0].realized_quantity == 0.24
        assert strategy.buy.orders[1].realized_quantity == 0.0
        assert strategy.buy.orders[2].realized_quantity == 0.0

        assert strategy.buy.data.state_info.state == State.PARTIALLY_BOUGHT
        assert strategy.state == State.PARTIALLY_BOUGHT

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PARTIALLY_BOUGHT"
        )

        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1400.0"
        assert item["quantity"] == "0.24"
        assert item["quantity_usd"] == "336.0"
        assert item["sell_price"] == "0.0"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "PARTIALLY_BOUGHT"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def cancel_unfilled_sell_position_from_part_filled_buy(self):
        strategy = self.back.strategies["1000"]
        self.new_price(3864, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_CANCELED
        )

        assert strategy.sell.current_position.sell_order.quantity == 0.24
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.0

        assert strategy.sell.current_position.state_info.state == State.NEW
        assert strategy.state == State.PARTIALLY_BOUGHT

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PARTIALLY_BOUGHT"
        )

        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1400.0"
        assert item["quantity"] == "0.24"
        assert item["quantity_usd"] == "336.0"
        assert item["sell_price"] == "4200.0"
        assert item["expected_return"] == "672.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "PARTIALLY_BOUGHT"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def simulate_sell_order_partial_fill_from_part_bought(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
            order_id=12345,
            last_executed_quantity=0.14,
            last_executed_price=4200,
            cumulative_filled_quantity=0.14,
            price=4200.0,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_PARTIALLY_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"] == "0.1"
        )

        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1400.0"
        assert item["quantity"] == "0.1"
        assert item["quantity_usd"] == "140.0", item["quantity_usd"]
        assert item["sell_price"] == "4200.0"
        assert item["expected_return"] == "672.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "SELLING"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def cancel_sell_position_filled_partially(self):
        strategy = self.back.strategies["1000"]
        self.new_price(3864, symbol="BTCUSDC")

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_CANCELED
        )

        assert strategy.sell.current_position.sell_order.quantity == 0.24
        assert strategy.sell.current_position.sell_order.realized_quantity == 0.14

        assert strategy.sell.current_position.state_info.state == State.PARTIALLY_SOLD
        assert strategy.state == State.PART_SOLD_PART_BOUGHT

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PART_SOLD_PART_BOUGHT"
        )

        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1400.0"
        assert item["quantity"] == "0.1", item["quantity"]
        assert item["quantity_usd"] == "140.0"
        assert item["sell_price"] == "4200.0"
        assert item["expected_return"] == "672.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "PART_SOLD_PART_BOUGHT"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def simulate_second_buy_order_partial_fill(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
            order_id=445861,
            last_executed_quantity=0.14,
            last_executed_price=1200,
            cumulative_filled_quantity=0.14,
            price=1200,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.BUYING
        logger.info("Orders: %s", strategy.buy.orders)
        assert strategy.buy.orders[0].status == ORDER_STATUS_FILLED
        await wait_for_condition(
            condition_func=lambda: strategy.buy.orders[1].status
            == ORDER_STATUS_PARTIALLY_FILLED
        )
        assert strategy.buy.orders[2].status == ORDER_STATUS_NEW

        realized_quantity = str(
            strategy.buy.orders[0].realized_quantity
            + strategy.buy.orders[1].realized_quantity
            - strategy.sell.current_position.sell_order.realized_quantity
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
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1326.32"
        assert item["quantity"] == "0.24"
        assert item["quantity_usd"] == "318.32"
        assert item["sell_price"] == "4200.0", item["sell_price"]
        assert item["expected_return"] == "1092.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BUYING"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def cancel_buy_position_filled_partially_sold_partially(self):
        strategy = self.back.strategies["1000"]

        assert strategy.buy.orders_cancel_price == 1224.0
        strategy.ticker_update = TickerUpdate(last_price=1428.0)
        assert (
            strategy.conditions_for_cancelling_partially_sold_and_bought_orders_buy_position()
        )

        await strategy.process_ticker()  # type: ignore[attr-defined]

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["state"]
            == "PART_SOLD_PART_BOUGHT"
        )

        hp_list = self.front.hp_list_data

        assert len(hp_list) == 1
        item = hp_list[0]
        assert item["hp_id"] == "1000"
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1326.32"
        assert item["quantity"] == "0.24"
        assert item["quantity_usd"] == "318.32"
        assert item["sell_price"] == "4200.0"
        assert item["expected_return"] == "1092.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "PART_SOLD_PART_BOUGHT", item["state"]

    async def simulate_second_buy_order_fill_after_selling_half_of_first_order(
        self,
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
            - strategy.sell.current_position.sell_order.realized_quantity
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
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1292.31"
        assert item["quantity"] == "0.38"
        assert item["quantity_usd"] == "491.08"
        assert item["sell_price"] == "4200.0", item["sell_price"]
        assert item["expected_return"] == "1512.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BUYING"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_third_buy_order_fill_after_selling_half_of_first_order(
        self,
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
            round(
                (
                    sum(order.realized_quantity for order in strategy.buy.orders)
                    - strategy.sell.current_position.sell_order.realized_quantity
                ),
                2,
            )
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == realized_quantity
        )

        assert len(self.front.hp_list_data) == 1
        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1178.82"
        assert item["quantity"] == "0.71"
        assert item["quantity_usd"] == "836.96"
        assert item["sell_price"] == "4200.0"
        assert item["expected_return"] == "2568.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "PARTIALLY_SOLD"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_sell_order_fill_from_part_bought(self) -> HpStrategy:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=12345,
            last_executed_quantity=0.24,
            last_executed_price=4200,
            cumulative_filled_quantity=0.24,
            price=4200.0,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"] == "0.0"
        )

        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1400.0"
        assert item["quantity"] == "0.0", item["quantity"]
        assert item["quantity_usd"] == "0.0", item["quantity_usd"]
        assert item["sell_price"] == "4200.0"
        assert item["expected_return"] == "672.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "SOLD_PART_BOUGHT", item["state"]

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_second_buy_order_fill_after_selling_first_order(
        self,
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
            - strategy.sell.current_position.sell_order.realized_quantity
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
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1292.31"
        assert item["quantity"] == "0.28"
        assert item["quantity_usd"] == "361.85"
        assert item["sell_price"] == "4200.0", item["sell_price"]
        assert item["expected_return"] == "1512.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BUYING"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def simulate_third_buy_order_fill_after_selling_first_order(
        self,
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
            round(
                (
                    sum(order.realized_quantity for order in strategy.buy.orders)
                    - strategy.sell.current_position.sell_order.realized_quantity
                ),
                2,
            )
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[0]["quantity"]
            == realized_quantity
        )

        assert len(self.front.hp_list_data) == 1
        item = self.front.hp_list_data[0]
        assert item["hp_id"] == "1000"
        assert item["coin"] == "BTCUSD"
        assert item["buy_price"] == "1178.82"
        assert item["quantity"] == "0.61"
        assert item["quantity_usd"] == "719.08"
        assert item["sell_price"] == "4200.0"
        assert item["expected_return"] == "2568.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "PARTIALLY_SOLD"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        return strategy

    async def open_first_sell_position_from_two_hop_trade(self):
        assert len(self.back.strategies) == 0

        coin = "AXL"

        sell_config = HPSellData(
            config=HPSellConfig(
                hp_id="",
                coin=coin,
                buy_price=0.2928,
                sell_price=1.14,
                quantity=1000.0,
                end_currency="PLN",
                symbol_info=self.back.symbols_info[f"{coin}USDT"],
            ),
            state_info=StateInfo(side=PositionSide.SHORT),
        )
        self.front.config_queue.put_nowait(sell_config)
        logger.info("Sell config added to the queue: %s", sell_config.config)

        await wait_for_condition(
            condition_func=lambda: len(self.front.hp_list_data) == 3
        )
        strategy = self.back.strategies["1000"]
        assert isinstance(strategy, HpStrategy)

        assert len(strategy.sell.sell_strategy) == 2
        assert strategy.sell.sell_strategy[0].symbol == f"{coin}BTC"
        assert (
            strategy.sell.sell_strategy[1].symbol
            == f"BTC{sell_config.config.end_currency}"
        )

        logger.info("Orig SELL DATA: %s", strategy.sell.original_position)
        assert strategy.sell.original_position.config.coin == coin

        assert self.front.hp_list_data[0]["state"] == State.BOUGHT.value
        assert self.front.hp_list_data[0]["coin"] == f"{coin}USD"
        assert self.front.hp_list_data[0]["hp_id"] == "1000"
        assert (
            self.front.hp_list_data[0]["buy_price"] == "0.2928"
        ), self.front.hp_list_data[0]["buy_price"]
        assert self.front.hp_list_data[0]["quantity"] == "1000.0"
        assert self.front.hp_list_data[0]["quantity_usd"] == "292.8"
        assert self.front.hp_list_data[0]["sell_price"] == "1.14"

        logger.info("HP LIST: %s", self.front.hp_list_data)
        assert (
            self.front.hp_list_data[0]["expected_return"] == "847.2"
        ), f"ER: {self.front.hp_list_data[0]['expected_return']}"
        assert self.front.hp_list_data[0]["current_price"] == "0.0"
        assert self.front.hp_list_data[0]["net"] == "0.0"

        sell_order = strategy.sell.current_position.sell_order

        assert sell_order.quantity == 1000
        assert sell_order.price == 0.00000356
        assert sell_order.realized_quantity == 0.0
        assert sell_order.order_id == 0

        assert strategy.state == State.BOUGHT

        await wait_for_condition(
            condition_func=lambda: not self.front.active_records_sell
        )
        await wait_for_condition(condition_func=lambda: self.front.idle_records_sell)

    async def send_orders_for_first_position_from_two_hop_trade(self):
        # Open position and send orders
        strategy = self.back.strategies["1000"]
        strategy.client.create_order.side_effect = get_new_orders(
            orders=[strategy.sell.current_position.sell_order]
        )
        self.new_price(price=1.14, symbol="AXLUSDT")

        sell_order = strategy.sell.current_position.sell_order

        # Assert new opened position data
        await wait_for_condition(condition_func=lambda: strategy.state == State.SELLING)
        await wait_for_condition(condition_func=lambda: self.front.active_records_sell)
        logger.info("idle records sell: %s", self.front.idle_records_sell)
        await wait_for_condition(
            condition_func=lambda: not self.front.idle_records_sell
        )

        assert strategy.sell.current_position.state_info.state == State.NEW
        assert sell_order.order_id == 12345
        assert sell_order.status == ORDER_STATUS_NEW
        assert sell_order.quantity == 1000
        assert sell_order.price == 0.00000356
        assert sell_order.realized_quantity == 0.0
        logger.info("Active records: %s", self.front.active_records_sell)
        logger.info("Idle records: %s", self.front.idle_records_sell)

    async def simulate_sell_order_partial_fill_in_first_hop(self):
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
            order_id=12345,
            last_executed_quantity=500,
            last_executed_price=0.00000365,
            cumulative_filled_quantity=500,
            price=0.00000365,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_PARTIALLY_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[1]["quantity"] == "500.0"
        )

        item = self.front.hp_list_data[1]
        assert item["hp_id"] == "1000a"
        assert item["coin"] == "AXLBTC"
        assert item["buy_price"] == "0.00000092", f"buy price: {item['buy_price']}"
        assert item["quantity"] == "500.0"
        assert item["quantity_usd"] == "45.75"
        assert item["sell_price"] == "0.00000356", f"Sell price: {item['sell_price']}"
        assert item["expected_return"] == "0.002645"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "SELLING"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def simulate_sell_order_fill_in_first_hop(self) -> None:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=12345,
            last_executed_quantity=1000,
            last_executed_price=0.00000365,
            cumulative_filled_quantity=1000,
            price=0.00000365,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[2]["coin"] == "BTCPLN"
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[2]["quantity"] == "0.00356"
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[2]["buy_price"] == "320000.0"
        )

        item = self.front.hp_list_data[2]
        assert item["hp_id"] == "1000b"
        assert item["coin"] == "BTCPLN"
        assert item["quantity"] == "0.00356", f"quantity to: {item['quantity']}"
        assert item["buy_price"] == "320000.0", f"buy price to: {item['buy_price']}"
        assert item["quantity_usd"] == "1139.2"
        assert item["sell_price"] == "320000.0"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "BOUGHT"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def open_second_sell_position_from_two_hop_trade(self):
        strategy = self.back.strategies["1000"]

        # Mock sending the sell order
        strategy.client.create_order.side_effect = get_new_orders(
            orders=[strategy.sell.current_position.sell_order]
        )

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.config.symbol_info.symbol
            == "BTCPLN"
        )
        sell_order = strategy.sell.current_position.sell_order

        assert sell_order.quantity == 0.00356
        assert sell_order.price == 320000.0
        assert sell_order.realized_quantity == 0.0
        assert sell_order.order_id == 12345
        await wait_for_condition(condition_func=lambda: strategy.state == State.SELLING)
        assert strategy.state == State.SELLING, f"State to: {strategy.state}"

        await wait_for_condition(
            condition_func=lambda: not self.front.idle_records_sell
        )
        await wait_for_condition(condition_func=lambda: self.front.active_records_sell)
        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[2]["state"]
            == State.SELLING.value
        )
        assert (
            self.front.hp_list_data[2]["coin"]
            == f"{strategy.sell.current_position.config.coin}PLN"
        )
        assert self.front.hp_list_data[2]["hp_id"] == "1000b"
        assert self.front.hp_list_data[2]["buy_price"] == "320000.0"
        assert self.front.hp_list_data[2]["quantity"] == "0.00356"
        assert self.front.hp_list_data[2]["quantity_usd"] == "1139.2"
        assert self.front.hp_list_data[2]["sell_price"] == "320000.0"
        assert self.front.hp_list_data[2]["expected_return"] == "0.0"
        assert self.front.hp_list_data[2]["current_price"] == "0.0"
        assert self.front.hp_list_data[2]["net"] == "0.0"
        assert self.front.hp_list_data[2]["state"] == "SELLING"

    async def simulate_sell_order_partial_fill_in_second_hop(self):
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_PARTIALLY_FILLED,
            order_id=12345,
            last_executed_quantity=0.00178,
            last_executed_price=320000.0,
            cumulative_filled_quantity=0.00178,
            price=320000.0,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING

        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_PARTIALLY_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[2]["quantity"] == "0.00178"
        )

        item = self.front.hp_list_data[2]
        assert item["hp_id"] == "1000b"
        assert item["coin"] == "BTCPLN"
        assert item["buy_price"] == "320000.0", f"buy price: {item['buy_price']}"
        assert item["quantity"] == "0.00178"
        assert item["quantity_usd"] == "569.6"
        assert item["sell_price"] == "320000.0", f"Sell price: {item['sell_price']}"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "SELLING"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

    async def simulate_sell_order_fill_in_second_hop(self) -> None:
        strategy = self.back.strategies["1000"]

        exc_report = ExecutionReport(
            order_type=ORDER_TYPE_LIMIT,
            current_order_status=ORDER_STATUS_FILLED,
            order_id=12345,
            last_executed_quantity=0.00356,
            last_executed_price=320000.0,
            cumulative_filled_quantity=0.00356,
            price=320000.0,
        )
        strategy.worker_queue.put_nowait(Event(EventName.EXECUTION_REPORT, exc_report))
        logger.info("Put event to the worker: %s", exc_report)

        assert strategy.state == State.SELLING

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[2]["coin"] == "BTCPLN"
        )
        assert isinstance(
            strategy.sell.current_position.sell_order, Order
        ), f"..... it is: {type(strategy.sell.current_position.sell_order)}"
        logger.info("DUPA")
        await wait_for_condition(
            condition_func=lambda: strategy.sell.current_position.sell_order.status
            == ORDER_STATUS_FILLED
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[2]["quantity"] == "0.0"
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[2]["buy_price"] == "320000.0"
        )

        await wait_for_condition(
            condition_func=lambda: self.front.hp_list_data[2]["state"] == "SOLD"
        )

        item = self.front.hp_list_data[2]
        assert item["hp_id"] == "1000b"
        assert item["coin"] == "BTCPLN", item["coin"]
        assert item["quantity"] == "0.0", f"quantity to: {item['quantity']}"
        assert item["buy_price"] == "320000.0", f"buy price to: {item['buy_price']}"
        assert item["quantity_usd"] == "0.0"
        assert item["sell_price"] == "320000.0"
        assert item["expected_return"] == "0.0"
        assert item["current_price"] == "0.0"
        assert item["net"] == "0.0"
        assert item["net_percent"] == "0.0"
        assert item["state"] == "SOLD"

        logger.info("HP List after the update: %s", self.front.hp_list_data)

        main_item = self.front.hp_list_data[0]
        first_leg = self.front.hp_list_data[1]
        second_leg = self.front.hp_list_data[2]

        await wait_for_condition(condition_func=lambda: main_item["state"] == "SOLD")
        assert main_item["state"] == "SOLD"
        assert first_leg["state"] == "SOLD"
        assert second_leg["state"] == "SOLD"

    # The assert_application_db_state_match method has been moved to CrashRecoveryHelper for centralized use in tests.
