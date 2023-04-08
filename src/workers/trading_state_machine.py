import asyncio
from typing import List, Union, Optional
import binance
import pandas
from transitions.extensions.asyncio import AsyncMachine
import logging
from src.features.features import State, Signal
from src.orders import Position, PositionMode
from src.producers.producers import SignalUpdate, OrderUpdate
from src.workers.handle_order import position_liquidation, target_reached

logger = logging.getLogger("state_actions")


class TradingStateMachine:
    def __init__(self, client, queue, position, df, balance, order_quantity_list):
        self.client: binance.AsyncClient = client
        self.queue: asyncio.Queue = queue
        self.position: Position = position
        self.position_old: Optional[Position] = None
        self.df: pandas.DataFrame = df
        self.balance: float = balance
        self.order_quantity_list = order_quantity_list
        self.state: State = State.FLAT
        self.signal_update: Optional[SignalUpdate] = None
        self.order_update: Optional[OrderUpdate] = None
        self.mode: PositionMode = PositionMode.DCA
        self.states: List[State] = [self.state]
        self.transitions = [
            {
                "trigger": "process_signal",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_skipping_same_signal",
                "after": "skip_signal",
            },
            {
                "trigger": "process_signal",
                "source": "*",
                "dest": State.FLAT,
                "conditions": "conditions_for_liquidation",
                "before": "handle_liquidation",
                "after": "enter_flat",
            },
            {
                "trigger": "process_signal",
                "source": "*",
                "dest": State.FLAT,
                "conditions": "conditions_for_target_reached",
                "before": "handle_target_reached",
                "after": "enter_flat",
            },
        ]

        self.machine = AsyncMachine(
            model=self,
            states=self.states,
            transitions=self.transitions,
            initial=self.state,
            send_event=True,
            queued=True,
        )

    def add_states_and_transitions(self, new_states, new_transitions):
        self.states.extend(new_states)
        self.transitions.extend(new_transitions)
        self.machine = AsyncMachine(
            model=self,
            states=self.states,
            transitions=self.transitions,
            initial=State.FLAT,
            send_event=True,
            queued=True,
        )

    def conditions_for_skipping_same_signal(self) -> bool:
        return self.state == self.signal_update.signal

    def update_position_in_df(self, update: Union[Signal, State]):
        self.df.at[self.df.index[-1], "position"] = update

    def skip_signal(self) -> None:
        logger.info("Skipping signal: %s", self.signal_update.signal)
        self.update_position_in_df(update=self.state)

    async def handle_liquidation(self):
        self.position, self.df, self.balance = await position_liquidation(
            client=self.client,
            position=self.position,
            order_update=self.order_update,
            df=self.df,
            balance=self.balance,
        )

    async def enter_flat(self):
        self.position = Position()

    async def handle_target_reached(self):
        self.position, self.df, self.balance = await target_reached(
            client=self.client,
            position=self.position,
            order_update=self.order_update,
            df=self.df,
            balance=self.balance,
        )

    async def process_signal(self, signal_update, position):
        await self.machine.trigger(
            "process_signal",
            signal_update=signal_update,
            position=position,
        )
