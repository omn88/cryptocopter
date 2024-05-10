import asyncio
from typing import Optional
from binance import BinanceSocketManager
from logging_config import StrategyLogger
from src.common.identifiers.common import (
    BinanceClient,
    Event,
    EventName,
    SentinelUpdate,
)
from src.common.identifiers.spot import StrategyConfig
from src.common.initialize_trading_environment import spot_prepare_producers
from src.df_handler.spot import DfHandler
from src.gui.gui_handler.spot import GuiHandler
from src.strategies.base import BaseStrategy
from src.strategies.futures.rsi_basic import RsiBasic
from src.strategies.spot.base import BaseSpotStrategy
from src.workers import worker
from src.workers.trading_state_machine import TradingStateMachine

from src.strategies.futures.rsi_extended import RsiExtended

from src.strategies.futures.rsi_special import RsiSpecial

# logger = logging.getLogger("trading_system")

STRATEGY_MAP = {
    "Coin Sniper": BaseSpotStrategy,
    "RSI Basic": RsiBasic,
    "RSI Extended": RsiExtended,
    "RSI Special": RsiSpecial,
}


class TradingSystem:
    def __init__(
        self,
        system_id: str,
        client: BinanceClient,
        gui_handler: GuiHandler,
        config: StrategyConfig,
        strategy_logger: StrategyLogger,
    ):
        self.system_id = system_id
        self.client = client
        self.config = config
        self.gui_handler = gui_handler
        self.df_handler: DfHandler = DfHandler(client=client, logger=strategy_logger)
        self.strategy_logger = strategy_logger
        self.binance_socket_manager = BinanceSocketManager(client=client)
        self.stop_producers_event = asyncio.Event()
        self.balance = None
        self.state_machine: Optional[TradingStateMachine] = None
        self.strategy: Optional[BaseStrategy] = None

    async def initialize(self):
        # Strategy initialization
        self.strategy = BaseSpotStrategy(
            client=self.client,
            df_handler=self.df_handler,
            gui_handler=self.gui_handler,
            logger=self.strategy_logger,
            config=self.config,
            balance=self.balance,
        )

        await self.strategy.initialize()

        # Trading State Machine initialization
        self.state_machine = TradingStateMachine(strategy=self.strategy)

    async def prepare_worker(self, logger: StrategyLogger):
        # is this sleep needed?
        await asyncio.sleep(5)
        if self.state_machine:
            await worker.worker(state_machine=self.state_machine, logger=logger)

    async def start_trading(self):
        await asyncio.gather(
            *spot_prepare_producers(
                socket_manager=self.binance_socket_manager,
                stop_event=self.stop_producers_event,
                queue=self.strategy.queue,
                symbol=self.config.symbol,
            ),
            asyncio.create_task(self.prepare_worker(logger=self.strategy_logger)),
            return_exceptions=True,
        )

    async def stop(self):
        # This method stops the trading. You'll have to implement this based on how your strategy can be stopped.
        # It might involve cancelling the tasks that were started in `start`.
        self.strategy_logger.info("Trading system STOP initiated properly")
        await self.strategy.queue.put(
            Event(EventName.SENTINEL, content=SentinelUpdate(sentinel="sentinel"))
        )
        await asyncio.sleep(5)
        self.stop_producers_event.set()
        self.strategy_logger.info("Sentinel should be send.")
