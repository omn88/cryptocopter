import asyncio
from typing import List
from logging_config import StrategyLogger
from src.common.identifiers import (
    AccountUpdate,
    BinanceClient,
    KlineUpdate,
    OrderUpdate,
    PositionMode,
    SignalUpdate,
    State,
    StrategyConfig,
)
from src.df_handler import DfHandler
from src.gui.gui_handler import GuiHandlerSpot
from src.position_handler import PositionHandler


class CoinSniper:
    def __init__(
        self,
        client: BinanceClient,
        balance: float,
        config: StrategyConfig,
        gui_handler: GuiHandlerSpot,
        logger: StrategyLogger,
        df_handler,
    ):
        self.client = client
        self.config: StrategyConfig = config
        self.balance = balance
        self.gui_handler = gui_handler
        self.logger = logger
        self.df_handler: DfHandler = df_handler
        self.position_handler: PositionHandler = PositionHandler(
            client=client,
            strategy_logger=logger,
            config=config,
            gui_handler=gui_handler,
        )
        self.queue: asyncio.Queue = asyncio.Queue()

        # Initialize any other common attributes
        self.signal_update: SignalUpdate = SignalUpdate()
        self.order_update: OrderUpdate = OrderUpdate()
        self.kline_update: KlineUpdate = KlineUpdate()
        self.account_update: AccountUpdate = AccountUpdate(account_update={})
        self.state: State = State.FLAT
        self.mode = PositionMode.DCA
        self.states: List[State] = [State.LONG, State.SHORT]
        self.transitions = []
