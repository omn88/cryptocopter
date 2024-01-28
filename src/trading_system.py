import asyncio
from typing import Optional
from binance import BinanceSocketManager
from logging_config import StrategyLogger
from src.common.common import (
    futures_get_balance,
    get_futures_historical_data,
    insert_to_pandas,
    rsi_indicator_apply,
)
from src.common.identifiers import (
    BinanceClient,
    EventName,
    Event,
    SentinelUpdate,
    StrategyConfig,
)
from src.common.initialize_trading_environment import (
    determine_start_position,
    prepare_producers,
)
from src.gui.gui_handler import GuiHandler
from src.gui.identifiers import AccountData
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
        gui_handler: GuiHandler,
        config: StrategyConfig,
        strategy_logger: StrategyLogger,
    ):
        self.client: BinanceClient = client
        self.config: StrategyConfig = config
        self.gui_handler: GuiHandler = gui_handler
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
            client=self.client,
            interval=self.config.interval,
            lookback="4320",
            symbol=self.config.symbol,
        )
        self.df = insert_to_pandas(data=self.raw_data)
        self.df = rsi_indicator_apply(df=self.df)

        self.balance = await futures_get_balance(
            client=self.client, asset=self.config.asset
        )

        self.strategy = STRATEGY_MAP[self.config.name](
            client=self.client,
            balance=self.balance,
            df=self.df,
            raw_data=self.raw_data,
            config=self.config,
            gui_handler=self.gui_handler,
            logger=self.strategy_logger,
        )

        self.state_machine = TradingStateMachine(strategy=self.strategy)

        await self.gui_handler.main_ui_queue.put(AccountData(balance=self.balance))

        self.df = self.strategy.signals_from_features_generate(
            df=self.df,
            conditions=self.strategy.conditions,
            signals=self.strategy.signals,
        )

    async def determine_start_position(self):
        await asyncio.sleep(5)
        await determine_start_position(df=self.df, queue=self.strategy.queue)

    async def prepare_worker(self, logger: StrategyLogger):
        await asyncio.sleep(5)
        if self.state_machine:
            await worker.worker(state_machine=self.state_machine, logger=logger)

    async def start_trading(self):
        await asyncio.gather(
            *prepare_producers(
                socket_manager=self.binance_socket_manager,
                stop_event=self.stop_producers_event,
                interval=self.config.interval,
                queue=self.strategy.queue,
                gui_handler=self.gui_handler,
                symbol=self.config.symbol,
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
        await self.gui_handler.main_ui_queue.put(
            Event(
                EventName.SENTINEL,
                content={
                    "strategy_name": self.config.name,
                    "symbol": self.config.symbol,
                },
            )
        )
        await asyncio.sleep(5)
        self.stop_producers_event.set()
        self.strategy_logger.info("Sentinel should be send.")
