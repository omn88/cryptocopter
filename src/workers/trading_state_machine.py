import logging
from transitions.extensions.asyncio import AsyncMachine


logger = logging.getLogger("trading_state_machine")


class TradingStateMachine:
    def __init__(self, strategy):
        self.strategy = strategy
        self.machine = AsyncMachine(
            model=self.strategy,
            states=strategy.states,
            transitions=strategy.transitions,
            initial=strategy.state,
            send_event=True,
            queued=True,
        )
