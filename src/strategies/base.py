import asyncio
from typing import List
from logging_config import StrategyLogger
from src.common.identifiers.futures import (
    AccountUpdate,
    SignalUpdate,
    OrderUpdate,
    KlineUpdate,
    BinanceClient,
    StrategyConfig,
    TickerUpdate,
)
from src.df_handler import DfHandler


class BaseStrategy:
    def __init__(
        self,
        client: BinanceClient,
        config: StrategyConfig,
        logger: StrategyLogger,
        df_handler: DfHandler,
        balance: float,
    ):
        self.client = client
        self.config = config
        self.logger = logger
        self.df_handler = df_handler
        self.balance = balance
        self.queue: asyncio.Queue = asyncio.Queue()

        # Initialize any other common attributes
        self.signal_update: SignalUpdate = SignalUpdate()
        self.order_update: OrderUpdate = OrderUpdate()
        self.kline_update: KlineUpdate = KlineUpdate()
        self.ticker_update: TickerUpdate = TickerUpdate()
        self.account_update: AccountUpdate = AccountUpdate(account_update={})
        self.transitions: List = []
