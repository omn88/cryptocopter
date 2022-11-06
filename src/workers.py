import asyncio
import json
import logging

import binance

import lib
import pandas
import features
import producers

logger = logging.getLogger("worker")


async def signal_handle(df: pandas.DataFrame, signal: features.Signals):

    if signal == features.Signals.FLAT:
        if df.position == features.Signals.FLAT:
            logger.info(
                "Current position is: %s and signal: %s. Duuu Nateng"
                % (df.position, signal)
            )
        if df.position == features.Signals.LONG:
            df.at[df.index, "position"] = signal
            logger.info(
                "Current position is: %s and signal: %s. Change to FLAT"
                % (df.position, signal)
            )
        if df.position == features.Signals.LONG_20:
            df.at[df.index, "position"] = signal
            logger.info(
                "Current position is: %s and signal: %s. Change to FLAT"
                % (df.position, signal)
            )
        if df.position == features.Signals.SHORT:
            df.at[df.index, "position"] = signal
            logger.info(
                "Current position is: %s and signal: %s. Change to FLAT"
                % (df.position, signal)
            )
        if df.position == features.Signals.SHORT_80:
            df.at[df.index, "position"] = signal
            logger.info(
                "Current position is: %s and signal: %s. Change to FLAT"
                % (df.position, signal)
            )

    elif signal == features.Signals.LONG:
        if df.position == features.Signals.FLAT:
            logger.info(
                "Current position is: %s and signal: %s. Open Long!"
                % (df.position, signal)
            )

        if df.position == features.Signals.LONG:
            df.at[df.index, "position"] = signal
            logger.info(
                "Current position is: %s and signal: %s. Change to FLAT"
                % (df.position, signal)
            )
        if df.position == features.Signals.LONG_20:
            df.at[df.index, "position"] = signal
            logger.info(
                "Current position is: %s and signal: %s. Change to FLAT"
                % (df.position, signal)
            )
        if df.position == features.Signals.SHORT:
            df.at[df.index, "position"] = signal
            logger.info(
                "Current position is: %s and signal: %s. Change to FLAT"
                % (df.position, signal)
            )
        if df.position == features.Signals.SHORT_80:
            df.at[df.index, "position"] = signal
            logger.info(
                "Current position is: %s and signal: %s. Change to FLAT"
                % (df.position, signal)
            )


async def user_socket_data_handle():
    pass


async def worker(
    df: pandas.DataFrame,
    queue: asyncio.Queue,
    client: binance.AsyncClient,
    symbol: str,
    interval: str,
):
    while True:
        # Get a "work item" out of the queue.
        task = await queue.get()

        # logger.info(f"New task: {task}")
        if isinstance(task, producers.Event):
            logger.info(task)
            if producers.EventName.Kline == task.name:
                temp_df = await lib.get_futures_historical_data(
                    client=client,
                    symbol=symbol,
                    interval=interval,
                    lookback="3360",  # 44000 is approximately one month
                )
                temp_df = features.signals_from_features_generate(df=temp_df)
                logger.info("Kline event last row: %s" % df.iloc[-1])
                logger.info("Temp DF last row: %s" % temp_df.iloc[-1])
                df_length = len(df)
                df = df.append(temp_df.iloc[-1])
                logger.info("Kline event after append: %s" % df.iloc[-1])

                assert len(df) == df_length + 1

                # if df.iloc[-1, 'signal'] != 0:
                #     await signal_handle(df.iloc[-1])
            elif producers.EventName.User == producers.Event.name:
                await user_socket_data_handle()
        elif isinstance(task, features.Signals):
            logger.info(task)
            await signal_handle(df, task)

        # if isinstance(task, features.Signals):
        #     logger.info("Wlazl do srodka, nie jest signalsem")
        #     task = json.loads(task)
        #
        #     assert task['e'] == 'continuous_kline'
        #     if task['e'] == 'continuous_kline':
        #         temp_df = await lib.get_futures_historical_data(
        #             client=client,
        #             symbol=symbol,
        #             interval=interval,
        #             lookback="3360",  # 44000 is approximately one month
        #         )
        #         temp_df = features.signals_from_features_generate(df=df)
        #         logger.info(f'Before append {df.iloc[-1]}')
        #         df = df.append(temp_df.tail(1))
        #         logger.info(f'After append {df.iloc[-1]}')
        # else:
        #     match task:
        #         case features.Signals.LONG:
        #             pass
        #         case features.Signals.LONG_20:
        #             pass
        #         case features.Signals.SHORT:
        #             pass
        #         case features.Signals.SHORT_80:
        #             pass
        #         case features.Signals.FLAT:
        #             pass

        # Notify the queue that the "work item" has been processed.
        queue.task_done()
