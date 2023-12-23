import asyncio

from src.common.common import (
    futures_get_balance,
    get_futures_historical_data,
    insert_to_pandas,
    rsi_indicator_apply,
)
from src.common.constants import ASSET, LEVERAGE, INTERVAL
from src.common.identifiers import Position, EventName, Event, SentinelUpdate
from src.common.initialize_trading_environment import (
    create_async_queue,
    change_margin_type,
    prepare_producers,
    prepare_workers,
    create_socket_manager,
)
from src.common.orders import order_quantity_list_prepare
from src.gui.identifiers import AccountData
from src.strategies.rsi_basic import BasicStrategy
from src.strategies.rsi_extended import ExtendedStrategy
from src.strategies.rsi_special import SpecialStrategy
import logging

logger = logging.getLogger("trading_system")

STRATEGY_MAP = {
    "RSI Basic": BasicStrategy,
    "RSI Extended": ExtendedStrategy,
    "RSI Special": SpecialStrategy,
}


class TradingSystem:
    def __init__(self, client, ui_queue, strategy_name, symbol, main_ui_queue):
        self.client = client
        self.binance_socket_manager = None
        self.queue = None
        self.ui_queue = ui_queue
        self.balance = None
        self.raw_data = None
        self.df = None
        self.position = None
        self.strategy = None
        self.strategy_name = strategy_name
        self.symbol = symbol
        self.main_ui_queue = main_ui_queue

    async def initialize(self):
        # Initialize queue, balance, position
        self.binance_socket_manager = await create_socket_manager(client=self.client)
        self.queue = create_async_queue()
        self.balance = await futures_get_balance(client=self.client, asset=ASSET)
        await self.ui_queue.put(AccountData(balance=self.balance))
        logger.info("Send account data: %s", self.balance)

        # Change margin type and leverage
        await change_margin_type(client=self.client, symbol=self.symbol)
        # await self.client.futures_change_leverage(symbol=self.symbol, leverage=LEVERAGE)

        # Fetch and process historical data
        self.raw_data = await get_futures_historical_data(
            client=self.client, interval=INTERVAL, lookback="4320", symbol=self.symbol
        )
        self.df = insert_to_pandas(data=self.raw_data)
        logger.info("DF: %s", self.df)
        self.df = rsi_indicator_apply(df=self.df)

    async def start_trading(self):
        # Prepare producers and workers, then start them
        self.position = Position()

        StrategyClass = STRATEGY_MAP[self.strategy_name]
        self.strategy = StrategyClass(
            client=self.client,
            queue=self.queue,
            balance=self.balance,
            order_quantity_list=order_quantity_list_prepare(),
            df=self.df,
            position=self.position,
            raw_data=self.raw_data,
            ui_queue=self.ui_queue,
            symbol=self.symbol,
            strategy_name=self.strategy_name,
            main_ui_queue=self.main_ui_queue,
        )

        await asyncio.gather(
            *prepare_producers(
                bsm=self.binance_socket_manager,
                df=self.df,
                interval=INTERVAL,
                queue=self.queue,
                tsm=self.strategy,
                ui_queue=self.ui_queue,
                symbol=self.symbol,
            ),
            *prepare_workers(tsm=self.strategy, queue=self.queue, symbol=self.symbol),
            return_exceptions=True,
        )

    async def stop(self):
        # This method stops the trading. You'll have to implement this based on how your strategy can be stopped.
        # It might involve cancelling the tasks that were started in `start`.
        logger.info("Trading system STOP initiated properly")
        await self.queue.put(
            Event(EventName.SENTINEL, content=SentinelUpdate(sentinel="sentinel"))
        )
        await self.main_ui_queue.put(
            Event(
                EventName.SENTINEL,
                content={"strategy_name": self.strategy_name, "symbol": self.symbol},
            )
        )
        logger.info("Sentinel should be send.")
