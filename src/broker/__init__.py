"""Broker module for Binance spot trading with WebSocket integration.

This module provides a clean interface for interacting with Binance spot markets,
handling real-time data streams, and managing trading operations.

Main Components:
- BrokerSpot: Main broker class for trading operations and subscription management
- WebSocketManager: Handles WebSocket connections, health monitoring, and recovery
- Message Handlers: Process incoming WebSocket messages (user data and ticker streams)

Usage:
    from src.broker import BrokerSpot
    from src.common.client import KrakenClient

    broker = BrokerSpot(client=client)
    broker.setup_subscriptions(hp_id="strategy1", symbol="BTCUSDC",
                              additional_symbols=None, worker_queue=queue)
"""

from src.broker.spot import BrokerSpot

__all__ = ["BrokerSpot"]
