import asyncio
import logging
from constants import LEVERAGE, SYMBOL, ASSET, INTERVAL
from src.common.common import (
    futures_get_balance,
    create_async_client,
    create_socket_manager,
    create_async_queue,
    register_signal_handlers,
    change_margin_type,
    prepare_producers,
    prepare_workers,
    get_futures_historical_data,
    insert_to_pandas,
)
from src.common.identifiers import State
from src.common.orders import order_quantity_list_prepare, Position
from src.strategies.rsi_special import SpecialStrategy
import warnings
import os
import shutil
import logging_config  # noinspection PyUnresolvedReferences

warnings.simplefilter(action="ignore", category=FutureWarning)


logger = logging.getLogger("main")


async def main():

    logger.info(
        "RSI Based Futures: Start. Initial parameters: symbol %s, asset %s, interval %s",
        SYMBOL,
        ASSET,
        INTERVAL,
    )
    loop = asyncio.get_event_loop()

    client = await create_async_client()
    bsm = await create_socket_manager(client=client)
    queue = await create_async_queue()
    balance = await futures_get_balance(client=client, asset=ASSET)
    position = Position()

    register_signal_handlers(
        loop=loop, client=client, position=position, balance=balance
    )

    await change_margin_type(client=client)
    await client.futures_change_leverage(symbol=SYMBOL, leverage=LEVERAGE)

    raw_data = await get_futures_historical_data(
        client=client,
        interval=INTERVAL,
        lookback="4320",  # 44000 is approximately one month
    )
    df = insert_to_pandas(data=raw_data)

    # Strategy returns trading state machine
    tsm = SpecialStrategy(
        client=client,
        balance=balance,
        order_quantity_list=order_quantity_list_prepare(),
        queue=queue,
        df=df,
        position=position,
        raw_data=raw_data,
    )
    tsm.signals_from_features_generate()
    tsm.df["position"] = State.FLAT
    await tsm.determine_start_position()

    await asyncio.gather(
        *prepare_producers(bsm=bsm, df=df, interval=INTERVAL, queue=queue),
        *prepare_workers(
            tsm=tsm,
            queue=queue,
        ),
        return_exceptions=True,
    )

    # shutil.copyfile(f"{os.getcwd()}/artifacts/info.log", f"{artifacts_dir}/info.log")
    # shutil.copyfile(
    #     f"{os.getcwd()}/artifacts/list_of_orders.txt",
    #     f"{artifacts_dir}/list_of_orders.txt",
    # )


if __name__ == "__main__":

    # artifacts_dir = create_directory_with_timestamp()

    try:
        asyncio.run(main())
    except asyncio.exceptions.CancelledError:
        logging.info("Strategy cancelled")
