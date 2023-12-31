import asyncio
import logging
from binance import BinanceSocketManager
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
    change_margin_type,
    prepare_producers,
    prepare_workers,
)
from src.common.orders import order_quantity_list_prepare
from src.gui.identifiers import AccountData
from src.strategies.rsi_basic import BasicStrategy
from src.strategies.rsi_extended import ExtendedStrategy
from src.strategies.rsi_special import SpecialStrategy

logger = logging.getLogger("trading_system")

STRATEGY_MAP = {
    "RSI Basic": BasicStrategy,
    "RSI Extended": ExtendedStrategy,
    "RSI Special": SpecialStrategy,
}


class TradingSystem:
    def __init__(
        self,
        client: BinanceClient,
        ui_queue: asyncio.Queue,
        strategy_name: str,
        symbol: str,
        main_ui_queue: asyncio.Queue,
    ):
        self.client: BinanceClient = client
        self.ui_queue: asyncio.Queue = ui_queue
        self.strategy_name = strategy_name
        self.symbol = symbol
        self.main_ui_queue: asyncio.Queue = main_ui_queue
        self.binance_socket_manager = BinanceSocketManager(client=client)
        self.queue: asyncio.Queue = asyncio.Queue()
        self.position = Position()
        self.balance = None
        self.raw_data = None
        self.df = None
        self.strategy = None

    async def initialize(self):
        self.balance = await futures_get_balance(client=self.client, asset=ASSET)
        await self.main_ui_queue.put(AccountData(balance=self.balance))

        # await change_margin_type(client=self.client, symbol=self.symbol)
        # await self.client.futures_change_leverage(symbol=self.symbol, leverage=LEVERAGE)

        # Fetch and process historical data
        self.raw_data = await get_futures_historical_data(
            client=self.client, interval=INTERVAL, lookback="4320", symbol=self.symbol
        )
        self.df = insert_to_pandas(data=self.raw_data)
        self.df = rsi_indicator_apply(df=self.df)

        self.strategy = STRATEGY_MAP[self.strategy_name](
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

    async def start_trading(self):
        await asyncio.gather(
            *prepare_producers(
                bsm=self.binance_socket_manager,
                df=self.df,
                interval=INTERVAL,
                queue=self.queue,
                tsm=self.strategy,
                ui_queue=self.ui_queue,
                symbol=self.symbol,
                main_ui_queue=self.main_ui_queue,
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
