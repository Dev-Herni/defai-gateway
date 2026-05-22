"""Tests for DeFAI Gateway WebSocket Real-Time Tracking — v2.4"""

import json
import sys
import os
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def sub_mgr():
    """Fresh SubscriptionManager for each test."""
    from ws_server import SubscriptionManager
    return SubscriptionManager()


@pytest.fixture
def mock_ws():
    """Mock WebSocket connection."""
    ws = AsyncMock()
    ws.send = AsyncMock()
    ws.recv = AsyncMock()
    return ws


# ═══════════════════════════════════════════════════════════════
# SUBSCRIPTION MANAGER TESTS
# ═══════════════════════════════════════════════════════════════

class TestSubscriptionManager:
    def test_subscribe_pools(self, sub_mgr, mock_ws):
        assert sub_mgr.subscribe(mock_ws, "pools") is True
        assert mock_ws in sub_mgr._channels["pools"]

    def test_subscribe_tokens(self, sub_mgr, mock_ws):
        assert sub_mgr.subscribe(mock_ws, "tokens") is True
        assert mock_ws in sub_mgr._channels["tokens"]

    def test_subscribe_wallet_valid(self, sub_mgr, mock_ws):
        assert sub_mgr.subscribe(mock_ws, "wallet:0x1234567890abcdef1234567890abcdef12345678") is True

    def test_subscribe_wallet_invalid(self, sub_mgr, mock_ws):
        assert sub_mgr.subscribe(mock_ws, "wallet:0xshort") is False

    def test_subscribe_unknown_channel(self, sub_mgr, mock_ws):
        assert sub_mgr.subscribe(mock_ws, "nonexistent") is False

    def test_unsubscribe_specific(self, sub_mgr, mock_ws):
        sub_mgr.subscribe(mock_ws, "pools")
        sub_mgr.subscribe(mock_ws, "tokens")
        sub_mgr.unsubscribe(mock_ws, "pools")
        assert mock_ws not in sub_mgr._channels["pools"]
        assert mock_ws in sub_mgr._channels["tokens"]

    def test_unsubscribe_all(self, sub_mgr, mock_ws):
        sub_mgr.subscribe(mock_ws, "pools")
        sub_mgr.subscribe(mock_ws, "tokens")
        sub_mgr.unsubscribe(mock_ws)
        assert mock_ws not in sub_mgr._channels["pools"]
        assert mock_ws not in sub_mgr._channels["tokens"]

    def test_remove_client(self, sub_mgr, mock_ws):
        sub_mgr.subscribe(mock_ws, "pools")
        sub_mgr.remove_client(mock_ws)
        assert mock_ws not in sub_mgr._channels["pools"]

    def test_get_subscriptions(self, sub_mgr, mock_ws):
        sub_mgr.subscribe(mock_ws, "pools")
        sub_mgr.subscribe(mock_ws, "tokens")
        subs = sub_mgr.get_subscriptions(mock_ws)
        assert "pools" in subs
        assert "tokens" in subs
        assert len(subs) == 2

    def test_get_subscriptions_empty(self, sub_mgr, mock_ws):
        subs = sub_mgr.get_subscriptions(mock_ws)
        assert subs == []

    def test_multiple_clients_same_channel(self, sub_mgr):
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        sub_mgr.subscribe(ws1, "pools")
        sub_mgr.subscribe(ws2, "pools")
        assert len(sub_mgr._channels["pools"]) == 2

    def test_wallet_channel_created_on_first_sub(self, sub_mgr, mock_ws):
        ch = "wallet:0x1234567890abcdef1234567890abcdef12345678"
        sub_mgr.subscribe(mock_ws, ch)
        assert ch in sub_mgr._channels

    def test_wallet_cache_initialized(self, sub_mgr, mock_ws):
        addr = "0x1234567890abcdef1234567890abcdef12345678"
        ch = f"wallet:{addr}"
        sub_mgr.subscribe(mock_ws, ch)
        assert addr in sub_mgr._wallet_cache
        assert sub_mgr._wallet_cache[addr] == []


# ═══════════════════════════════════════════════════════════════
# BROADCAST TESTS
# ═══════════════════════════════════════════════════════════════

class TestBroadcast:
    @pytest.mark.asyncio
    async def test_broadcast_to_subscribed(self, sub_mgr):
        ws = AsyncMock()
        ws.send = AsyncMock()
        sub_mgr.subscribe(ws, "pools")
        
        await sub_mgr.broadcast("pools", {"type": "test", "data": [{"name": "AERO/WETH"}]})
        
        ws.send.assert_called_once()
        sent = json.loads(ws.send.call_args[0][0])
        assert sent["channel"] == "pools"
        assert sent["type"] == "test"

    @pytest.mark.asyncio
    async def test_broadcast_no_subscribers(self, sub_mgr):
        ws = AsyncMock()
        ws.send = AsyncMock()
        
        await sub_mgr.broadcast("pools", {"type": "test"})
        
        ws.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_broadcast_to_wallet_channel(self, sub_mgr):
        ws = AsyncMock()
        ws.send = AsyncMock()
        ch = "wallet:0x1234567890abcdef1234567890abcdef12345678"
        sub_mgr.subscribe(ws, ch)
        
        await sub_mgr.broadcast(ch, {"type": "wallet_tx", "data": [{"hash": "0xtest"}]})
        
        ws.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_dead_client_cleaned_up(self, sub_mgr):
        ws = AsyncMock()
        ws.send = AsyncMock(side_effect=ConnectionError("dead"))
        sub_mgr.subscribe(ws, "pools")
        
        await sub_mgr.broadcast("pools", {"type": "test"})
        
        assert ws not in sub_mgr._channels["pools"]


# ═══════════════════════════════════════════════════════════════
# CONFIG TESTS
# ═══════════════════════════════════════════════════════════════

class TestWSConfig:
    def test_defaults(self):
        import ws_server
        assert ws_server.WS_PORT == 4021
        assert ws_server.MAX_CLIENTS >= 10
        assert ws_server.POLL_POOLS >= 5
        assert ws_server.POLL_WALLET >= 5
        assert ws_server.POLL_TOKENS >= 5

    def test_channels_initialized(self):
        from ws_server import sub_mgr
        assert "pools" in sub_mgr._channels
        assert "tokens" in sub_mgr._channels
