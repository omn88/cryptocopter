from logging_config import StrategyLogger
from src.common.identifiers.spot import EventName, Event, SignalUpdate, TickerUpdate
from src.strategies.futures.base import BaseFuturesStrategy
from src.strategies.spot.hp_manager import HpManager
from src.common.identifiers.common import AccountUpdate, OrderUpdate
from src.workers.trading_state_machine import TradingStateMachine


async def worker(state_machine: TradingStateMachine, logger: StrategyLogger):
    while True:
        logger.info(
            "-------------------------------------POSITION-----------------------------------------"
        )
        if state_machine.strategy.queue.qsize() == 0:
            logger.info("Awaiting new Event...")

        event = await state_machine.strategy.queue.get()
        assert isinstance(event, Event)

        if EventName.TICKER == event.name:
            assert isinstance(event.content, TickerUpdate)
            assert isinstance(state_machine.strategy, HpManager)
            state_machine.strategy.ticker_update = event.content

            logger.info(
                "Last price for %s: %s, Order trigger price: %s",
                state_machine.strategy.ticker_update.symbol,
                state_machine.strategy.ticker_update.last_price,
                state_machine.strategy.trigger_orders_price,
            )

            await state_machine.strategy.process_ticker()  # type: ignore

        elif EventName.ORDER == event.name:
            logger.info("Entering order event: %s", event)
            assert isinstance(event.content, OrderUpdate)
            state_machine.strategy.order_update = event.content
            await state_machine.strategy.process_order()  # type: ignore

        elif EventName.ACCOUNT == event.name:
            logger.info("Entering account event: %s", event)
            assert isinstance(event.content, AccountUpdate)
            state_machine.strategy.account_update = event.content
            await state_machine.strategy.process_account()  # type: ignore

        elif EventName.SIGNAL == event.name:
            logger.info("Entering signal event: %s", event)
            assert isinstance(event.content, SignalUpdate)
            state_machine.strategy.signal_update = event.content
            await state_machine.strategy.process_signal()  # type: ignore

            assert isinstance(state_machine.strategy, BaseFuturesStrategy)

            logger.info(
                "Last %s rows from main df: %s",
                5,
                state_machine.strategy.df_handler.df.tail(5).to_string(),
            )

        elif EventName.SENTINEL == event.name:
            logger.info("Entering sentinel event -> Exiting worker")

            await state_machine.strategy.position_handler.cancel_position()
            return

        state_machine.strategy.queue.task_done()
