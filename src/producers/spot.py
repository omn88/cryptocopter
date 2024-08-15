import asyncio
import logging

from binance import BinanceSocketManager
from src.common.identifiers.spot import (
    AccountPosition,
    Balance,
    EventName,
    Event,
    ExecutionReport,
    TickerUpdate,
)
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import PriceData

logger = logging.getLogger("spot_producers")


async def spot_user_socket(
    socket_manager: BinanceSocketManager,
    queue: asyncio.Queue,
    stop_event: asyncio.Event,
    symbol_info: SymbolInfo,
):
    reconnect_attempts = 10  # Number of times to attempt reconnection

    while not stop_event.is_set():
        try:
            socket = socket_manager.user_socket()  # Initialize the WebSocket connection
            async with socket:
                logger.info("Spot user socket connected.")
                while not stop_event.is_set():
                    try:
                        msg = await asyncio.wait_for(socket.recv(), timeout=1.0)
                        logger.debug("[Event]: %s", msg)
                        event_type = msg.get("e")
                        symbol = msg.get("s")
                        if (
                            event_type == EventName.EXECUTION_REPORT.value
                            and symbol == symbol_info.symbol
                        ):
                            await handle_execution_report(msg, queue)
                        if (
                            event_type == EventName.ACCOUNT_POSITION.value
                            and symbol == symbol_info.symbol
                        ):
                            await handle_outbound_account_position(msg, queue)
                    except asyncio.TimeoutError:
                        continue
        except ConnectionResetError as e:
            logger.error("Connection was reset: %s. Reconnecting...", e)
            for attempt in range(reconnect_attempts):
                if stop_event.is_set():
                    return  # Exit if stop_event is set

                await asyncio.sleep(2**attempt)  # Exponential backoff
                logger.info("Reconnecting attempt %d...", attempt + 1)
                break  # Break out of the retry loop to re-establish the connection

        except Exception as e:
            logger.error("Unexpected error: %s", e)
            break


async def handle_execution_report(msg, queue):
    report = ExecutionReport(
        symbol=msg["s"],
        client_order_id=msg["c"],
        side=msg["S"],
        order_type=msg["o"],
        time_in_force=msg["f"],
        quantity=float(msg["q"]),
        price=float(msg["p"]),
        stop_price=float(msg["P"]),
        iceberg_quantity=float(msg["F"]),
        order_list_id=msg["g"],
        original_client_order_id=msg["C"],
        current_execution_type=msg["x"],
        current_order_status=msg["X"],
        order_reject_reason=msg["r"],
        order_id=int(msg["i"]),
        last_executed_quantity=float(msg["l"]),
        cumulative_filled_quantity=float(msg["z"]),
        last_executed_price=float(msg["L"]),
        commission_amount=float(msg["n"]) if msg["n"] else None,
        commission_asset=msg["N"],
        transaction_time=msg["T"],
        trade_id=msg["t"],
        ignore_1=msg["I"],
        is_order_working=msg["w"],
        is_trade_maker_side=msg["m"],
        ignore_2=msg["M"],
        order_creation_time=msg["O"],
        cumulative_quote_asset_transacted_quantity=float(msg["Z"]),
        last_quote_asset_transacted_quantity=float(msg["Y"]),
        quote_order_quantity=float(msg["Q"]),
        working_time=msg["W"],
        self_trade_prevention_mode=msg["V"],
    )
    await queue.put(
        Event(
            name=EventName.EXECUTION_REPORT,
            content=report,
        )
    )
    logger.info("Execution report added to the queue: %s", report)


async def handle_outbound_account_position(msg, queue):
    balances = [
        Balance(asset=b["a"], free=float(b["f"]), locked=float(b["l"]))
        for b in msg["B"]
    ]
    account_position = AccountPosition(
        event_time=msg["E"], last_update_time=msg["u"], balances=balances
    )
    await queue.put(
        Event(
            name=EventName.ACCOUNT_POSITION,
            content=account_position,
        )
    )
    logger.info("Account position added to the queue: %s", account_position)


async def spot_ticker_socket(
    socket_manager: BinanceSocketManager,
    queue: asyncio.Queue,
    ui_queue: asyncio.Queue,
    symbol_info: SymbolInfo,
    stop_event: asyncio.Event,
):
    reconnect_attempts = 10  # Number of times to attempt reconnection

    while not stop_event.is_set():
        try:
            socket = socket_manager.symbol_ticker_socket(
                symbol=symbol_info.symbol
            )  # Initialize the WebSocket connection
            async with socket:
                logger.info("Spot ticker socket connected.")
                while not stop_event.is_set():
                    try:
                        msg = await asyncio.wait_for(socket.recv(), timeout=1.0)
                        logger.debug("[Event]: %s", msg)
                        await queue.put(
                            Event(
                                name=EventName.TICKER,
                                content=TickerUpdate(
                                    symbol=str(msg["s"]),
                                    last_price=symbol_info.adjust_price(
                                        float(msg["c"])
                                    ),
                                    best_bid_price=symbol_info.adjust_price(
                                        float(msg.get("b", "0"))
                                    ),
                                    best_ask_price=symbol_info.adjust_price(
                                        float(msg.get("a", "0"))
                                    ),
                                    high_price=symbol_info.adjust_price(
                                        float(msg.get("h", "0"))
                                    ),
                                    low_price=symbol_info.adjust_price(
                                        float(msg.get("l", "0"))
                                    ),
                                    volume=float(msg["v"]),
                                ),
                            )
                        )
                        await ui_queue.put(
                            PriceData(
                                symbol=msg["s"],
                                price=symbol_info.adjust_price(float(msg["c"])),
                            )
                        )
                    except asyncio.TimeoutError:
                        continue

        except ConnectionResetError as e:
            logger.error("Connection was reset: %s. Reconnecting...", e)
            for attempt in range(reconnect_attempts):
                if stop_event.is_set():
                    return  # Exit if stop_event is set

                await asyncio.sleep(2**attempt)  # Exponential backoff
                logger.info("Reconnecting attempt %d...", attempt + 1)
                break  # Break out of the retry loop to re-establish the connection

        except Exception as e:
            logger.error("Unexpected error: %s", e)
            break
