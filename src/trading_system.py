import asyncio

from src.common.common import (
    futures_get_balance,
    get_futures_historical_data,
    insert_to_pandas,
    rsi_indicator_apply,
)
from src.common.constants import ASSET, SYMBOL, LEVERAGE, INTERVAL
from src.common.identifiers import Position
from src.common.initialize_trading_environment import (
    create_async_client,
    create_async_queue,
    change_margin_type,
    prepare_producers,
    prepare_workers,
    create_socket_manager,
)
from src.common.orders import order_quantity_list_prepare
from src.strategies.rsi_basic import BasicStrategy
from src.strategies.rsi_extended import ExtendedStrategy
from src.strategies.rsi_special import SpecialStrategy
import logging

logger = logging.getLogger("trading_system")

STRATEGY_MAP = {
    "RSI_Basic": BasicStrategy,
    "RSI_Extended": ExtendedStrategy,
}


class TradingSystem:
    def __init__(self, ui_queue):
        self.client = None
        self.binance_socket_manager = None
        self.queue = None
        self.ui_queue: asyncio.Queue = ui_queue
        self.balance = None
        self.raw_data = None
        self.df = None
        self.position = None
        self.strategy = None
        self.strategy_name = None

    async def initialize(self):
        # Initialize client, queue, balance, position
        self.client = await create_async_client()
        self.binance_socket_manager = await create_socket_manager(client=self.client)
        self.queue = create_async_queue()
        self.balance = await futures_get_balance(client=self.client, asset=ASSET)
        await self.ui_queue.put("UpdateBalance")

        # Register signal handlers
        # loop = asyncio.get_event_loop()
        # register_signal_handlers(
        #     loop=loop, client=self.client, position=self.position, balance=self.balance
        # )

        # Change margin type and leverage
        await change_margin_type(client=self.client)
        await self.client.futures_change_leverage(symbol=SYMBOL, leverage=LEVERAGE)

        # Fetch and process historical data
        self.raw_data = await get_futures_historical_data(
            client=self.client, interval=INTERVAL, lookback="4320"
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
        )

        await asyncio.gather(
            *prepare_producers(
                bsm=self.binance_socket_manager,
                df=self.df,
                interval=INTERVAL,
                queue=self.queue,
                tsm=self.strategy,
            ),
            *prepare_workers(tsm=self.strategy, queue=self.queue),
            return_exceptions=True,
        )

    async def stop(self):
        # This method stops the trading. You'll have to implement this based on how your strategy can be stopped.
        # It might involve cancelling the tasks that were started in `start`.
        pass  # TODO: implement this
