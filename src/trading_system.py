import asyncio
import logging
from typing import Optional
from binance import BinanceSocketManager
from logging_config import StrategyLogger
from src.common.common import (
    futures_get_balance,
    get_futures_historical_data,
    insert_to_pandas,
    rsi_indicator_apply,
)
from src.common.constants import ASSET, INTERVAL
from src.common.identifiers import (
    BinanceClient,
    Position,
    EventName,
    Event,
    SentinelUpdate,
)
from src.common.initialize_trading_environment import (
    determine_start_position,
    prepare_producers,
)
from src.common.orders import order_quantity_list_prepare
from src.gui.identifiers import AccountData
from src.order_handler import OrderHandler
from src.strategies.base import BaseStrategy
from src.strategies.rsi_basic import RsiBasic
from src.workers import worker
from src.workers.trading_state_machine import TradingStateMachine

from src.strategies.rsi_extended import RsiExtended
from src.strategies.rsi_special import RsiSpecial

# logger = logging.getLogger("trading_system")

STRATEGY_MAP = {
    "RSI Basic": RsiBasic,
    "RSI Extended": RsiExtended,
    "RSI Special": RsiSpecial,
}


class TradingSystem:
    def __init__(
        self,
        client: BinanceClient,
        strategy_name: str,
        symbol: str,
        number_of_orders: int,
        main_ui_queue: asyncio.Queue,
        strategy_logger: StrategyLogger,
    ):
        self.client: BinanceClient = client
        self.strategy_name: str = strategy_name
        self.symbol = symbol
        self.number_of_orders = number_of_orders
        self.main_ui_queue: asyncio.Queue = main_ui_queue
        self.strategy_logger: StrategyLogger = strategy_logger
        self.binance_socket_manager = BinanceSocketManager(client=client)
        self.stop_producers_event = asyncio.Event()
        self.balance = None
        self.raw_data = None
        self.df = None
        self.state_machine: Optional[TradingStateMachine] = None
        self.strategy: Optional[BaseStrategy] = None

    async def initialize(self):
        # await change_margin_type(client=self.client, symbol=self.symbol)
        # await self.client.futures_change_leverage(symbol=self.symbol, leverage=LEVERAGE)

        # Fetch and process historical data
        self.raw_data = await get_futures_historical_data(
            client=self.client, interval=INTERVAL, lookback="4320", symbol=self.symbol
        )
        self.df = insert_to_pandas(data=self.raw_data)
        self.df = rsi_indicator_apply(df=self.df)

        self.balance = await futures_get_balance(client=self.client, asset=ASSET)

        self.strategy = STRATEGY_MAP[self.strategy_name](
            client=self.client,
            balance=self.balance,
            order_quantity_list=order_quantity_list_prepare(
                number_of_orders=self.number_of_orders
            ),
            df=self.df,
            raw_data=self.raw_data,
            symbol=self.symbol,
            strategy_name=self.strategy_name,
            number_of_orders=self.number_of_orders,
            main_ui_queue=self.main_ui_queue,
            logger=self.strategy_logger,
        )

        self.state_machine = TradingStateMachine(strategy=self.strategy)

        await self.main_ui_queue.put(AccountData(balance=self.balance))

        self.df = self.strategy.signals_from_features_generate(
            df=self.df,
            conditions=self.strategy.conditions,
            signals=self.strategy.signals,
        )

    async def determine_start_position(self):
        await asyncio.sleep(5)
        await determine_start_position(df=self.df, queue=self.strategy.queue)

    async def prepare_worker(self, logger: logging.Logger):
        await asyncio.sleep(5)
        if self.state_machine:
            await worker.worker(state_machine=self.state_machine, logger=logger)

    async def start_trading(self):
        await asyncio.gather(
            *prepare_producers(
                socket_manager=self.binance_socket_manager,
                stop_event=self.stop_producers_event,
                interval=INTERVAL,
                queue=self.strategy.queue,
                ui_queue=self.strategy.ui_queue,
                symbol=self.symbol,
                main_ui_queue=self.main_ui_queue,
            ),
            asyncio.create_task(self.prepare_worker(logger=self.strategy_logger)),
            asyncio.create_task(self.determine_start_position()),
            return_exceptions=True,
        )

    async def stop(self):
        # This method stops the trading. You'll have to implement this based on how your strategy can be stopped.
        # It might involve cancelling the tasks that were started in `start`.
        self.strategy_logger.info("Trading system STOP initiated properly")
        await self.strategy.queue.put(
            Event(EventName.SENTINEL, content=SentinelUpdate(sentinel="sentinel"))
        )
        await self.main_ui_queue.put(
            Event(
                EventName.SENTINEL,
                content={"strategy_name": self.strategy_name, "symbol": self.symbol},
            )
        )
        await asyncio.sleep(5)
        self.stop_producers_event.set()
        self.strategy_logger.info("Sentinel should be send.")
