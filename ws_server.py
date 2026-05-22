"""
DeFAI Gateway — WebSocket Real-Time Tracking Server
====================================================
Live streaming of Aerodrome pools, wallet activity, and new token launches.

Architecture:
  AI Agent → WebSocket → ws_server → Poll loop → Push updates
  
Channels:
  pools          — Top Aerodrome pools (TVL/APR changes, every 30s)
  wallet:<addr>  — Wallet incoming/outgoing txs (every 15s)
  tokens         — New token deployments (every 60s)

Protocol:
  Client sends:  {"subscribe": "pools"} or {"subscribe": "wallet:0x..."}
  Server sends:  {"channel": "pools", "type": "update", "data": [...]}
  Client sends:  {"unsubscribe": "pools"}
  Client sends:  {"list"} → list active subscriptions
  Client sends:  {"ping"} → pong
"""

import os, sys, json, time, asyncio, hashlib
from typing import Set, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import websockets
    import websockets.server
    import websockets.exceptions
except ImportError:
    print("[!] websockets not installed. Run: pip install websockets", file=sys.stderr)
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

WS_PORT = int(os.getenv("WS_PORT", "4021"))
AERODROME_API = os.getenv("AERODROME_API", "https://api.aerodrome.finance/api/v1")
BLOCKSCOUT_BASE = "https://base.blockscout.com/api/v2"
POLL_POOLS = int(os.getenv("WS_POLL_POOLS", "30"))     # seconds
POLL_WALLET = int(os.getenv("WS_POLL_WALLET", "15"))    # seconds
POLL_TOKENS = int(os.getenv("WS_POLL_TOKENS", "60"))    # seconds
MAX_CLIENTS = int(os.getenv("WS_MAX_CLIENTS", "100"))

# ═══════════════════════════════════════════════════════════════
# SUBSCRIPTION MANAGER
# ═══════════════════════════════════════════════════════════════

class SubscriptionManager:
    """Manages WebSocket client subscriptions to data channels.
    
    Each client (WebSocket connection) can subscribe to multiple channels.
    Each channel has a poll loop that broadcasts to all subscribed clients.
    """
    
    def __init__(self):
        # channel -> set of websocket connections
        self._channels: Dict[str, Set] = {
            "pools": set(),
            "tokens": set(),
        }
        # websocket -> set of channels
        self._clients: Dict[Any, Set[str]] = {}
        # Track last seen data for change detection
        self._last_pools = []
        self._last_tokens = []
        self._wallet_cache: Dict[str, list] = {}
    
    def subscribe(self, ws, channel: str) -> bool:
        """Subscribe a client to a channel. Returns True if valid."""
        if channel.startswith("wallet:"):
            addr = channel.split(":", 1)[1].strip().lower()
            if not addr.startswith("0x") or len(addr) != 42:
                return False
            if channel not in self._channels:
                self._channels[channel] = set()
                self._wallet_cache[addr] = []
        elif channel not in self._channels:
            return False
        
        self._channels[channel].add(ws)
        if ws not in self._clients:
            self._clients[ws] = set()
        self._clients[ws].add(channel)
        return True
    
    def unsubscribe(self, ws, channel: str = None):
        """Unsubscribe a client from a channel (or all if channel is None)."""
        if channel:
            if channel in self._channels:
                self._channels[channel].discard(ws)
            if ws in self._clients:
                self._clients[ws].discard(channel)
        else:
            # Unsubscribe from all
            for ch, clients in self._channels.items():
                clients.discard(ws)
            if ws in self._clients:
                self._clients[ws] = set()
    
    def remove_client(self, ws):
        """Remove a disconnected client from all channels."""
        for ch, clients in self._channels.items():
            clients.discard(ws)
        self._clients.pop(ws, None)
    
    def get_subscriptions(self, ws) -> list:
        """Get all channels a client is subscribed to."""
        return list(self._clients.get(ws, set()))
    
    async def broadcast(self, channel: str, data: dict):
        """Broadcast data to all clients subscribed to a channel."""
        if channel not in self._channels:
            return
        message = json.dumps({
            "channel": channel,
            "type": data.get("type", "update"),
            "data": data.get("data", data),
            "timestamp": int(time.time()),
        })
        dead_clients = set()
        for ws in self._channels[channel].copy():
            try:
                await ws.send(message)
            except (websockets.exceptions.ConnectionClosed, ConnectionError):
                dead_clients.add(ws)
        # Clean up dead connections
        for ws in dead_clients:
            self.remove_client(ws)

sub_mgr = SubscriptionManager()


# ═══════════════════════════════════════════════════════════════
# DATA FETCHERS
# ═══════════════════════════════════════════════════════════════

async def fetch_json(url: str, params: dict = None, retries: int = 2) -> dict:
    """Fetch JSON with retries."""
    import httpx
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params=params, headers={"User-Agent": "DeFAI-Gateway/2.4"})
                resp.raise_for_status()
                return resp.json()
        except Exception:
            if attempt < retries:
                await asyncio.sleep(1)
    return {"_failed": True}


async def fetch_pools() -> list:
    """Fetch top Aerodrome pools."""
    data = await fetch_json(f"{AERODROME_API}/pools")
    if isinstance(data, list):
        pools = []
        for p in data[:20]:
            pools.append({
                "name": p.get("name", "Unknown"),
                "address": p.get("address", ""),
                "tvl_usd": float(p.get("tvl", 0) or 0),
                "volume_24h": float(p.get("volume24h", 0) or 0),
                "apr": float(p.get("apr", 0) or 0),
                "timestamp": int(time.time()),
            })
        return pools
    return []


async def fetch_wallet_txs(address: str, limit: int = 5) -> list:
    """Fetch recent transactions for a wallet."""
    data = await fetch_json(f"{BLOCKSCOUT_BASE}/addresses/{address}/transactions", {"limit": limit, "sort": "desc"})
    if isinstance(data, dict):
        items = data.get("items", [])
        txs = []
        for tx in items[:limit]:
            txs.append({
                "hash": tx.get("hash", ""),
                "from": tx.get("from", {}).get("hash", ""),
                "to": tx.get("to", {}).get("hash", ""),
                "value_eth": float(tx.get("value", "0")) / 1e18 if tx.get("value") else 0,
                "method": tx.get("method", ""),
                "timestamp": tx.get("timestamp", ""),
                "status": tx.get("status", "pending"),
                "explorer": f"https://basescan.org/tx/{tx.get('hash', '')}",
            })
        return txs
    return []


async def fetch_new_tokens(limit: int = 10) -> list:
    """Fetch recently deployed tokens."""
    data = await fetch_json(f"{BLOCKSCOUT_BASE}/tokens", {"limit": limit})
    if isinstance(data, dict):
        items = data.get("items", [])
        tokens = []
        for t in items[:limit]:
            tokens.append({
                "name": t.get("name", "Unknown"),
                "symbol": t.get("symbol", "???"),
                "address": t.get("address", ""),
                "decimals": t.get("decimals", 18),
                "holders": t.get("holders", 0),
                "explorer": f"https://basescan.org/token/{t.get('address', '')}",
            })
        return tokens
    return []


# ═══════════════════════════════════════════════════════════════
# POLL LOOPS
# ═══════════════════════════════════════════════════════════════

async def poll_pools_loop():
    """Poll Aerodrome pools every N seconds, broadcast changes."""
    while True:
        try:
            if sub_mgr._channels["pools"]:
                pools = await fetch_pools()
                if pools:
                    # Check for significant changes
                    significant = []
                    for p in pools:
                        name = p["name"]
                        old = next((o for o in sub_mgr._last_pools if o["name"] == name), None)
                        if old:
                            tvl_change = abs(p["tvl_usd"] - old["tvl_usd"])
                            apr_change = abs(p["apr"] - old["apr"])
                            if tvl_change > 10000 or apr_change > 0.5:
                                p["change"] = {
                                    "tvl_delta": round(p["tvl_usd"] - old["tvl_usd"], 2),
                                    "apr_delta": round(p["apr"] - old["apr"], 2),
                                }
                                significant.append(p)
                        else:
                            significant.append(p)
                    
                    if significant:
                        await sub_mgr.broadcast("pools", {
                            "type": "pool_update",
                            "data": significant,
                        })
                    sub_mgr._last_pools = pools
        except Exception as e:
            print(f"[ws] poll_pools error: {e}", file=sys.stderr)
        await asyncio.sleep(POLL_POOLS)


async def poll_wallet_loop(channel: str, address: str):
    """Poll a wallet address for new transactions."""
    while True:
        try:
            if channel in sub_mgr._channels and sub_mgr._channels[channel]:
                txs = await fetch_wallet_txs(address)
                if txs:
                    cached = sub_mgr._wallet_cache.get(address, [])
                    cached_hashes = {tx["hash"] for tx in cached}
                    new_txs = [tx for tx in txs if tx["hash"] not in cached_hashes]
                    
                    if new_txs:
                        await sub_mgr.broadcast(channel, {
                            "type": "wallet_tx",
                            "data": new_txs,
                            "address": address,
                        })
                    sub_mgr._wallet_cache[address] = txs
        except Exception as e:
            print(f"[ws] poll_wallet({address}) error: {e}", file=sys.stderr)
        await asyncio.sleep(POLL_WALLET)


async def poll_tokens_loop():
    """Poll new tokens every N seconds."""
    while True:
        try:
            if sub_mgr._channels["tokens"]:
                tokens = await fetch_new_tokens()
                if tokens:
                    cached = sub_mgr._last_tokens
                    cached_addrs = {t["address"] for t in cached}
                    new_tokens = [t for t in tokens if t["address"] not in cached_addrs]
                    
                    if new_tokens:
                        await sub_mgr.broadcast("tokens", {
                            "type": "new_tokens",
                            "data": new_tokens,
                        })
                    sub_mgr._last_tokens = tokens
        except Exception as e:
            print(f"[ws] poll_tokens error: {e}", file=sys.stderr)
        await asyncio.sleep(POLL_TOKENS)


async def wallet_watchdog():
    """Monitor for new wallet subscriptions and start poll loops."""
    active_wallets = set()
    while True:
        current_wallets = set()
        for ch in list(sub_mgr._channels.keys()):
            if ch.startswith("wallet:"):
                current_wallets.add(ch)
        
        # Start poll loops for new wallets
        for ch in current_wallets - active_wallets:
            addr = ch.split(":", 1)[1]
            asyncio.create_task(poll_wallet_loop(ch, addr))
            print(f"[ws] Started wallet monitor: {addr}", file=sys.stderr)
        
        active_wallets = current_wallets
        await asyncio.sleep(5)


# ═══════════════════════════════════════════════════════════════
# WEBSOCKET HANDLER
# ═══════════════════════════════════════════════════════════════

async def handle_client(ws):
    """Handle a WebSocket client connection."""
    client_id = hashlib.md5(str(id(ws)).encode()).hexdigest()[:8]
    print(f"[ws] Client {client_id} connected", file=sys.stderr)
    
    # Send welcome message
    await ws.send(json.dumps({
        "type": "welcome",
        "version": "v2.4",
        "channels": ["pools", "wallet:<address>", "tokens"],
        "message": "Send {\"subscribe\": \"<channel>\"} to start receiving updates",
        "timestamp": int(time.time()),
    }))
    
    try:
        async for message in ws:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                await ws.send(json.dumps({"type": "error", "message": "Invalid JSON"}))
                continue
            
            if "subscribe" in data:
                channel = data["subscribe"]
                if sub_mgr.subscribe(ws, channel):
                    await ws.send(json.dumps({
                        "type": "subscribed",
                        "channel": channel,
                        "timestamp": int(time.time()),
                    }))
                    print(f"[ws] {client_id} subscribed to {channel}", file=sys.stderr)
                else:
                    await ws.send(json.dumps({
                        "type": "error",
                        "message": f"Invalid channel: {channel}. Use: pools, wallet:0x..., tokens",
                    }))
            
            elif "unsubscribe" in data:
                channel = data.get("unsubscribe")
                sub_mgr.unsubscribe(ws, channel)
                await ws.send(json.dumps({
                    "type": "unsubscribed",
                    "channel": channel or "all",
                    "timestamp": int(time.time()),
                }))
            
            elif "list" in data:
                subs = sub_mgr.get_subscriptions(ws)
                await ws.send(json.dumps({
                    "type": "subscriptions",
                    "channels": subs,
                    "timestamp": int(time.time()),
                }))
            
            elif "ping" in data:
                await ws.send(json.dumps({"type": "pong", "timestamp": int(time.time())}))
            
            else:
                await ws.send(json.dumps({"type": "error", "message": f"Unknown command: {list(data.keys())}"}))
    
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        sub_mgr.remove_client(ws)
        print(f"[ws] Client {client_id} disconnected", file=sys.stderr)


# ═══════════════════════════════════════════════════════════════
# MCP TOOLS (Add to Server)
# ═══════════════════════════════════════════════════════════════

WS_TOOL_DEFS = """# WebSocket MCP Tools (add to server.py)

@mcp.tool()
async def subscribe(
    channel: str,
    webhook_url: str = None,
    caller_address: str = None
) -> str:
    '''Subscribe to real-time data streams. PREMIUM tier.
    
    Channels:
      pools              — Live Aerodrome pool TVL/APR changes
      wallet:0x...       — Monitor wallet for new transactions
      tokens             — New token deployments on Base
    
    Args:
        channel: Channel name (e.g. 'pools', 'wallet:0x...', 'tokens')
        webhook_url: Optional webhook URL for push notifications
        caller_address: Your wallet (premium tier)
    '''
    import server
    import json
    gate = server.require_premium(caller_address)
    if gate: return gate
    
    valid_channels = ["pools", "tokens"]
    if channel.startswith("wallet:0x") and len(channel) == 47:  # wallet:0x + 40 hex
        valid_channels.append(channel)
    
    if channel not in valid_channels:
        return server.json_error(f"Invalid channel: {channel}")
    
    result = {
        "channel": channel,
        "status": "active",
        "ws_endpoint": f"ws://localhost:{WS_PORT}",
        "instructions": f"Connect via WebSocket to ws://localhost:{WS_PORT} and send {{\\"subscribe\\": \\"{channel}\\"}}",
    }
    
    if webhook_url:
        result["webhook_url"] = webhook_url
        result["poll_interval_seconds"] = {
            "pools": POLL_POOLS,
            "wallet": POLL_WALLET,
            "tokens": POLL_TOKENS,
        }.get(channel.split(":")[0], 30)
    
    return server.json_ok(result)

@mcp.tool()
async def get_ws_info(caller_address: str = None) -> str:
    '''Get WebSocket connection info and active channels. FREE tier.'''
    import server
    return server.json_ok({
        "ws_endpoint": f"ws://localhost:{WS_PORT}",
        "channels": ["pools", "wallet:<address>", "tokens"],
        "protocol": "Send JSON: {\"subscribe\": \"<channel>\"}",
        "poll_intervals_seconds": {
            "pools": POLL_POOLS,
            "wallet": POLL_WALLET,
            "tokens": POLL_TOKENS,
        },
        "active_subscriptions": len(sub_mgr._channels.get("pools", set())),
    })
"""


# ═══════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════

async def main():
    """Start the WebSocket server + background poll loops."""
    print(f"\n{'═'*60}", file=sys.stderr)
    print(f"  DeFAI Gateway — WebSocket Real-Time Server", file=sys.stderr)
    print(f"  Listening on ws://0.0.0.0:{WS_PORT}", file=sys.stderr)
    print(f"  Poll intervals: pools={POLL_POOLS}s, wallet={POLL_WALLET}s, tokens={POLL_TOKENS}s", file=sys.stderr)
    print(f"  Max clients: {MAX_CLIENTS}", file=sys.stderr)
    print(f"{'═'*60}\n", file=sys.stderr)
    
    # Start background poll loops
    asyncio.create_task(poll_pools_loop())
    asyncio.create_task(poll_tokens_loop())
    asyncio.create_task(wallet_watchdog())
    
    # Start WebSocket server
    async with websockets.server.serve(
        handle_client,
        "0.0.0.0",
        WS_PORT,
        max_size=2**20,  # 1MB max message
        compression=None,
    ):
        await asyncio.Future()  # Run forever


def run_ws_server():
    """Entry point for launching the WS server."""
    asyncio.run(main())


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="DeFAI Gateway WebSocket Server")
    parser.add_argument("--port", type=int, default=WS_PORT, help="WebSocket port")
    parser.add_argument("--pool-interval", type=int, default=POLL_POOLS, help="Pool poll interval (s)")
    parser.add_argument("--wallet-interval", type=int, default=POLL_WALLET, help="Wallet poll interval (s)")
    parser.add_argument("--token-interval", type=int, default=POLL_TOKENS, help="Token poll interval (s)")
    args = parser.parse_args()
    
    globals()["WS_PORT"] = args.port
    globals()["POLL_POOLS"] = args.pool_interval
    globals()["POLL_WALLET"] = args.wallet_interval
    globals()["POLL_TOKENS"] = args.token_interval
    
    run_ws_server()
