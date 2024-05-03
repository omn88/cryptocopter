import asyncio
from binance import BinanceSocketManager

from src.common.identifiers.futures import AccountUpdate, OrderUpdate, TickerUpdate


class TickerDataPublisher:
    def __init__(self, socket_manager: BinanceSocketManager):
        self.socket_manager = socket_manager
        self.subscribers = {}
        self.stop_event = asyncio.Event()

    def subscribe(self, symbol, subscriber):
        if symbol not in self.subscribers:
            self.subscribers[symbol] = []
        self.subscribers[symbol].append(subscriber)

    def unsubscribe(self, symbol, subscriber):
        if symbol in self.subscribers:
            self.subscribers[symbol].remove(subscriber)

    async def run(self):
        socket = self.socket_manager.symbol_ticker_socket(symbol="all")
        async with socket:
            while not self.stop_event.is_set():
                try:
                    msg = await asyncio.wait_for(socket.recv(), timeout=1.0)
                    if msg.get("e") == "24hrTicker":
                        symbol = msg["s"]
                        ticker_event = TickerUpdate(
                            symbol=symbol,
                            last_price=round(float(msg["c"]), 1),
                            best_bid_price=round(float(msg["b"]), 1),
                            best_ask_price=round(float(msg["a"]), 1),
                            high_price=round(float(msg["h"]), 1),
                            low_price=round(float(msg["l"]), 1),
                            volume=float(msg["v"]),
                        )
                        for subscriber in self.subscribers.get(symbol, []):
                            asyncio.create_task(subscriber.notify(ticker_event))
                except asyncio.TimeoutError:
                    continue

    def stop(self):
        self.stop_event.set()


async def spot_user_socket(
    socket_manager: BinanceSocketManager,
    queue: asyncio.Queue,
    stop_event: asyncio.Event,
):
    socket = socket_manager.user_socket()  # This should be the spot user socket
    async with socket:
        logger.info("Spot user socket connected.")
        while not stop_event.is_set():
            try:
                msg = await asyncio.wait_for(socket.recv(), timeout=1.0)
                logger.info("From spot user: %s", msg)
                if msg["e"] == "ACCOUNT_UPDATE":
                    await queue.put(
                        Event(
                            name=EventName.ACCOUNT,
                            content=AccountUpdate(account_update=msg),
                        )
                    )
                elif msg["e"] == "ORDER_TRADE_UPDATE":
                    order_info = msg["o"]
                    await queue.put(
                        Event(
                            name=EventName.ORDER,
                            content=OrderUpdate(
                                symbol=order_info["s"],
                                price=round(float(order_info["p"]), 1),
                                average_price=round(float(order_info["ap"]), 1),
                                quantity=round(float(order_info["z"]), 3),
                                status=order_info["X"],
                                order_id=int(order_info["i"]),
                                order_type=order_info["o"],
                                last_filled_quantity=round(float(order_info["l"]), 3),
                                realized_quantity=round(float(order_info["z"]), 3),
                            ),
                        )
                    )
                else:
                    logger.info("Unhandled message type: %s", msg)
            except asyncio.TimeoutError:
                continue


async def spot_ticker_socket(
    socket_manager: BinanceSocketManager,
    queue: asyncio.Queue,
    symbol: str,
    stop_event: asyncio.Event,
):
    logger.info("Entering spot ticker socket")
    socket = socket_manager.symbol_ticker_socket(symbol=symbol)
    async with socket:
        logger.info("Spot ticker socket connected.")
        while not stop_event.is_set():
            try:
                msg = await asyncio.wait_for(socket.recv(), timeout=1.0)
                await queue.put(
                    Event(
                        name=EventName.TICKER,
                        content=TickerUpdate(
                            last_price=round(float(msg["c"]), 1),  # Last price
                            best_bid_price=round(
                                float(msg.get("b", "0")), 1
                            ),  # Best bid price, with safe default if 'b' is absent
                            best_ask_price=round(
                                float(msg.get("a", "0")), 1
                            ),  # Best ask price, with safe default if 'a' is absent
                            high_price=round(
                                float(msg["h"]), 1
                            ),  # High price of the day
                            low_price=round(float(msg["l"]), 1),  # Low price of the day
                            volume=float(msg["v"]),  # Total traded base asset volume
                        ),
                    )
                )

            except asyncio.TimeoutError:
                continue
