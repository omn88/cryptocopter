import asyncio
from typing import Optional, Union
from binance import BinanceSocketManager
from logging_config import StrategyLogger
from src.common.common import futures_get_balance
from src.common.identifiers import (
    BinanceClient,
    EventName,
    Event,
    SentinelUpdate,
    StrategyConfig,
)
from src.common.initialize_trading_environment import (
    change_margin_type,
    futures_prepare_producers,
    spot_prepare_producers,
)
from src.df_handler import DfHandler
from src.gui.gui_handler import GuiHandlerFutures, GuiHandlerSpot
from src.gui.identifiers import AccountData
from src.strategies.base import BaseStrategy
from src.strategies.coin_sniper import CoinSniper
from src.strategies.rsi_basic import RsiBasic
from src.workers import worker
from src.workers.trading_state_machine import TradingStateMachine

from src.strategies.rsi_extended import RsiExtended

from src.strategies.rsi_special import RsiSpecial

# logger = logging.getLogger("trading_system")

STRATEGY_MAP = {
    "Coin Sniper": CoinSniper,
    "RSI Basic": RsiBasic,
    "RSI Extended": RsiExtended,
    "RSI Special": RsiSpecial,
}


class TradingSystemFutures:
    def __init__(
        self,
        client: BinanceClient,
        gui_handler: GuiHandlerFutures,
        config: StrategyConfig,
        strategy_logger: StrategyLogger,
    ):
        self.client: BinanceClient = client
        self.config: StrategyConfig = config
        self.gui_handler: GuiHandlerFutures = gui_handler
        self.df_handler: DfHandler = DfHandler(
            client=client, config=config, logger=strategy_logger
        )
        self.strategy_logger: StrategyLogger = strategy_logger
        self.binance_socket_manager = BinanceSocketManager(client=client)
        self.stop_producers_event = asyncio.Event()
        self.balance = None
        self.state_machine: Optional[TradingStateMachine] = None
        self.strategy: Optional[BaseStrategy] = None

    async def initialize(self):
        await change_margin_type(
            client=self.client,
            symbol=self.config.symbol,
            margin_type=self.config.margin_type,
        )
        await self.client.futures_change_leverage(
            symbol=self.config.symbol, leverage=self.config.leverage
        )

        await self.df_handler.initialize()

        self.balance = await futures_get_balance(
            client=self.client, asset=self.config.asset
        )

        self.strategy = STRATEGY_MAP[self.config.name](
            client=self.client,
            balance=self.balance,
            df_handler=self.df_handler,
            config=self.config,
            gui_handler=self.gui_handler,
            logger=self.strategy_logger,
        )

        self.state_machine = TradingStateMachine(strategy=self.strategy)

        await self.gui_handler.main_ui_queue.put(AccountData(balance=self.balance))

        self.df_handler.df = self.df_handler.signals_from_features_generate(
            df=self.df_handler.df,
            conditions=self.df_handler.conditions,
            signals=self.df_handler.signals,
        )

    async def determine_start_position(self):
        await asyncio.sleep(5)
        await self.df_handler.futures_determine_start_position(
            queue=self.strategy.queue
        )

    async def prepare_worker(self, logger: StrategyLogger):
        # is this sleep needed?
        await asyncio.sleep(5)
        if self.state_machine:
            await worker.worker(state_machine=self.state_machine, logger=logger)

    async def start_trading(self):
        await asyncio.gather(
            *futures_prepare_producers(
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


class TradingSystemSpot:
    def __init__(
        self,
        system_id: str,
        client: BinanceClient,
        gui_handler: GuiHandlerSpot,
        config: StrategyConfig,
        strategy_logger: StrategyLogger,
    ):
        self.system_id = system_id
        self.client = client
        self.config = config
        self.gui_handler = gui_handler
        self.df_handler: DfHandler = DfHandler(
            client=client, config=config, logger=strategy_logger
        )
        self.strategy_logger = strategy_logger
        self.binance_socket_manager = BinanceSocketManager(client=client)
        self.stop_producers_event = asyncio.Event()
        self.balance = None
        self.state_machine: Optional[TradingStateMachine] = None
        self.strategy: Optional[BaseStrategy] = None

    async def initialize(self):
        # Strategy initialization
        self.strategy = STRATEGY_MAP[self.config.name](
            client=self.client,
            df_handler=self.df_handler,
            gui_handler=self.gui_handler,
            logger=self.strategy_logger,
            config=self.config,
            balance=self.balance,
        )

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
