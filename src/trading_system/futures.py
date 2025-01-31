import asyncio
from typing import Optional
from binance import BinanceSocketManager
from transitions.extensions.asyncio import AsyncMachine
from logging_config import StrategyLogger
from src.common.common import futures_get_balance
from src.common.identifiers.common import (
    BinanceClient,
    SentinelUpdate,
)
from src.common.identifiers.futures import Event, EventName, StrategyConfig
from src.common.initialize_trading_environment import (
    change_margin_type,
    futures_prepare_producers,
)
from src.df_handler.futures import DfHandler
from src.gui.hpmanager import HpFront
from src.gui.gui_handler.futures import GuiHandler
from src.gui.identifiers.futures import AccountData
from src.strategies.futures.base import BaseFuturesStrategy
from src.strategies.futures.rsi_basic import RsiBasic
from src.workers import worker_futures
from src.strategies.futures.rsi_extended import RsiExtended
from src.strategies.futures.rsi_special import RsiSpecial

# logger = logging.getLogger("trading_system")

STRATEGY_MAP = {
    "HP Manager": HpFront,
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
        self.df_handler: DfHandler = DfHandler(
            client=client, config=config, logger=strategy_logger
        )
        self.strategy_logger: StrategyLogger = strategy_logger
        self.binance_socket_manager = BinanceSocketManager(client=client)
        self.stop_producers_event = asyncio.Event()
        self.balance = None
        self.state_machine: Optional[AsyncMachine] = None
        self.strategy: Optional[BaseFuturesStrategy] = None

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

        # Trading State Machine initialization
        self.state_machine = AsyncMachine(
            model=self.strategy,
            states=self.strategy.states,
            transitions=self.strategy.transitions,
            initial=self.strategy.state,
            send_event=True,
            queued=True,
        )

        await self.gui_handler.main_ui_queue.put(AccountData(balance=self.balance))

        self.df_handler.df = self.df_handler.signals_from_features_generate(
            df=self.df_handler.df,
            conditions=self.df_handler.conditions,
            signals=self.df_handler.signals,
        )

    async def determine_start_position(self):
        await asyncio.sleep(5)
        await self.df_handler.determine_start_position(queue=self.strategy.queue)

    async def prepare_worker(self, logger: StrategyLogger):
        # is this sleep needed?
        await asyncio.sleep(5)
        if self.state_machine:
            await worker_futures.worker(state_machine=self.state_machine, logger=logger)

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
