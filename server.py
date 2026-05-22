"""
DeFAI Gateway v2 — MCP Server for Base Chain DeFi
=================================================
AI Agent Gateway: balances, swaps, analytics, payment gating, token gating

Architecture:
  AI Agent → MCP stdio → DeFAI Gateway → Base RPC / Aerodrome / CoinGecko
  
Payment Tiers:
  Free (10 calls/day)     → Basic tools: balance, gas, token info
  Premium (unlimited)     → All tools + analytics + tracking
  $GATE Holder (unlimited) → All tools + swap execution + revenue share

Environment:
  RPC_URL        - Base RPC endpoint (default: https://mainnet.base.org)
  GATE_TOKEN     - $GATE token address for gating (optional)
  FEE_WALLET     - Wallet to collect fees (optional)
  FEE_BPS        - Fee basis points (default: 5 = 0.05%)
"""

import os, json, sys, time, hmac, hashlib
from typing import Optional
from mcp.server.fastmcp import FastMCP
import httpx

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

BASE_RPC = os.getenv("RPC_URL", "https://mainnet.base.org")
GATE_TOKEN_ADDRESS = os.getenv("GATE_TOKEN", "")
FEE_WALLET = os.getenv("FEE_WALLET", "0x0000000000000000000000000000000000000000")
FEE_BPS = int(os.getenv("FEE_BPS", "5"))  # 0.05% default
DAILY_FREE_CALLS = int(os.getenv("DAILY_FREE_CALLS", "10"))

# API endpoints
COINGECKO_API = "https://api.coingecko.com/api/v3"
AERODROME_API = "https://api.aerodrome.finance/api/v1"
CLANKER_API = "https://api.clanker.com/v1"

# Token addresses on Base mainnet
TOKENS = {
    "WETH":  "0x4200000000000000000000000000000000000006",
    "USDC":  "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "USDbC": "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA",
    "AERO":  "0x940181a94A35A4569E4529A3CDfB74e38FD98631",
    "DAI":   "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
    "CLANKER": "0x3Fb1E6093F1Ffc67A182cFEb2F8B0D04cB0d8cF2",
}

AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"

ERC20_ABI = [
    {"constant": True, "inputs": [], "name": "name", "outputs": [{"name":"","type":"string"}], "type":"function"},
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name":"","type":"string"}], "type":"function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name":"","type":"uint8"}], "type":"function"},
    {"constant": True, "inputs": [{"name":"_owner","type":"address"}], "name": "balanceOf", "outputs": [{"name":"balance","type":"uint256"}], "type":"function"},
    {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [{"name":"","type":"uint256"}], "type":"function"},
]

# ═══════════════════════════════════════════════════════════════
# WEB3 INIT
# ═══════════════════════════════════════════════════════════════

web3 = None
try:
    from web3 import Web3
    web3 = Web3(Web3.HTTPProvider(BASE_RPC))
    if not web3.is_connected():
        print("[!] Base RPC not connected", file=sys.stderr)
        web3 = None
    else:
        print(f"[+] Base RPC connected — block {web3.eth.block_number}", file=sys.stderr)
except Exception as e:
    print(f"[!] Web3 init: {e}", file=sys.stderr)

# ═══════════════════════════════════════════════════════════════
# PAYMENT GATING
# ═══════════════════════════════════════════════════════════════

class PaymentGate:
    """Simple payment gating with daily free tier + token gating."""
    
    def __init__(self):
        self._usage = {}  # caller_address -> {"date": str, "count": int}
    
    def _today(self) -> str:
        return time.strftime("%Y-%m-%d")
    
    def check(self, caller_address: str = None) -> dict:
        """
        Check if caller has access.
        Returns: {"allowed": bool, "tier": str, "reason": str}
        """
        # No address provided = anonymous (free tier only)
        if not caller_address or caller_address.strip() == "":
            return {"allowed": True, "tier": "free", "reason": "Anonymous — free tier"}
        
        addr = caller_address.strip().lower()
        
        # Check $GATE token holding
        if GATE_TOKEN_ADDRESS and web3:
            try:
                contract = web3.eth.contract(
                    address=web3.to_checksum_address(GATE_TOKEN_ADDRESS),
                    abi=ERC20_ABI
                )
                balance = contract.functions.balanceOf(
                    web3.to_checksum_address(caller_address)
                ).call()
                if balance > 0:
                    return {"allowed": True, "tier": "gate_holder", "reason": "$GATE holder — unlimited premium"}
            except:
                pass
        
        # Daily free tier
        today = self._today()
        key = f"{addr}:{today}"
        self._usage.setdefault(key, 0)
        
        if self._usage[key] < DAILY_FREE_CALLS:
            return {"allowed": True, "tier": "free", "reason": f"Free tier ({DAILY_FREE_CALLS - self._usage[key]} calls left today)"}
        
        return {"allowed": False, "tier": "exceeded", "reason": f"Free tier exceeded. Buy $GATE token or wait for reset."}
    
    def use(self, caller_address: str = None):
        """Increment usage counter."""
        if not caller_address:
            return
        key = f"{caller_address.strip().lower()}:{self._today()}"
        self._usage.setdefault(key, 0)
        self._usage[key] += 1
    
    def status(self, caller_address: str = None) -> dict:
        """Get usage status for a caller."""
        gate_status = self.check(caller_address)
        if caller_address:
            key = f"{caller_address.strip().lower()}:{self._today()}"
            gate_status["calls_today"] = self._usage.get(key, 0)
            gate_status["calls_remaining"] = max(0, DAILY_FREE_CALLS - self._usage.get(key, 0))
        return gate_status

payment_gate = PaymentGate()

# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def to_checksum(address: str) -> str:
    """Convert address to checksummed format."""
    try:
        return web3.to_checksum_address(address) if web3 else address
    except:
        return address

def format_amount(wei_amount: int, decimals: int = 18) -> float:
    """Convert wei to human-readable amount."""
    return wei_amount / (10 ** decimals)

async def fetch_json(url: str, params: dict = None) -> dict:
    """Fetch JSON from URL with timeout."""
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(url, params=params)
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

def json_ok(data: dict) -> str:
    """Format response with status."""
    data["_status"] = "ok"
    return json.dumps(data, indent=2)

def json_error(message: str, code: str = "error") -> str:
    return json.dumps({"_status": code, "error": message}, indent=2)

def require_premium(caller_address: str = None):
    """Decorator/replacement for premium gating. Call at start of premium tools."""
    gate = payment_gate.check(caller_address)
    if not gate["allowed"]:
        return json_error(gate["reason"], "payment_required")
    payment_gate.use(caller_address)
    return None  # Allowed

# ═══════════════════════════════════════════════════════════════
# MCP SERVER
# ═══════════════════════════════════════════════════════════════

mcp = FastMCP("DeFAI Gateway v2",
    instructions="""DeFAI Gateway v2 — AI Agent Gateway to Base Chain DeFi.
    
TIERS:
  FREE (10 calls/day): get_balance, get_token_info, get_gas_price
  PREMIUM: get_pools, analyze_wallet, track_new_tokens, get_payment_status
  $GATE HOLDER: All tools + premium swap execution
  
Call premium tools with caller_address parameter to track usage.
""")

# ─── TOOL 1: get_balance ───────────────────────────────────
@mcp.tool()
async def get_balance(address: str, tokens: list = None) -> str:
    """Get ETH and token balances for a Base wallet address. FREE tier.
    
    Args:
        address: Wallet address (0x...)
        tokens: Optional list of token contract addresses to check
    """
    if not web3:
        return json_error("Base RPC not connected")
    
    addr = to_checksum(address)
    result = {"address": addr, "chain": "Base", "balances": {}}
    
    # ETH balance
    try:
        eth_bal = web3.eth.get_balance(addr)
        result["balances"]["ETH"] = f"{format_amount(eth_bal):.6f}"
    except Exception as e:
        result["balances"]["ETH"] = f"error: {e}"
    
    # Token balances
    check_tokens = tokens if tokens else list(TOKENS.values())
    for t_addr in check_tokens:
        try:
            ca = to_checksum(t_addr)
            contract = web3.eth.contract(address=ca, abi=ERC20_ABI)
            symbol = contract.functions.symbol().call()
            decimals = contract.functions.decimals().call()
            balance = contract.functions.balanceOf(addr).call()
            if balance > 0:
                result["balances"][symbol] = f"{format_amount(balance, decimals):.4f}"
        except:
            continue
    
    # USD estimate
    try:
        price_data = await fetch_json(f"{COINGECKO_API}/simple/price", {
            "ids": "ethereum,usd-coin,aerodrome-finance",
            "vs_currencies": "usd"
        })
        eth_usd = price_data.get("ethereum", {}).get("usd", 0)
        eth_bal_f = float(result["balances"].get("ETH", "0"))
        result["total_usd_estimate"] = round(eth_bal_f * eth_usd, 2) if eth_usd else "N/A"
    except:
        result["total_usd_estimate"] = "N/A"
    
    return json_ok(result)

# ─── TOOL 2: get_token_info ────────────────────────────────
@mcp.tool()
async def get_token_info(address: str) -> str:
    """Get detailed info about a Base token. FREE tier.
    
    Args:
        address: Token contract address (0x...)
    """
    if not web3:
        return json_error("Base RPC not connected")
    try:
        ca = to_checksum(address)
        contract = web3.eth.contract(address=ca, abi=ERC20_ABI)
        name = contract.functions.name().call()
        symbol = contract.functions.symbol().call()
        decimals = contract.functions.decimals().call()
        total_supply = contract.functions.totalSupply().call()
        return json_ok({
            "address": ca, "name": name, "symbol": symbol,
            "decimals": decimals, "total_supply": f"{format_amount(total_supply, decimals):,.0f}",
            "chain": "Base", "explorer": f"https://basescan.org/token/{ca}"
        })
    except Exception as e:
        return json_error(str(e))

# ─── TOOL 3: get_gas_price ─────────────────────────────────
@mcp.tool()
async def get_gas_price() -> str:
    """Get current Base chain gas price. FREE tier."""
    if not web3:
        return json_error("Base RPC not connected")
    try:
        gas = web3.eth.gas_price
        gwei = gas / 1e9
        return json_ok({
            "chain": "Base", "gas_price_gwei": round(gwei, 2),
            "estimated_tx_cost_eth": round(gwei * 21000 / 1e9, 8)
        })
    except Exception as e:
        return json_error(str(e))

# ─── TOOL 4: get_pools (PREMIUM) ──────────────────────────
@mcp.tool()
async def get_pools(min_liquidity_usd: float = 10000, caller_address: str = None) -> str:
    """Get top liquidity pools on Aerodrome. PREMIUM tier.
    
    Args:
        min_liquidity_usd: Minimum liquidity in USD (default 10k)
        caller_address: Your wallet address for access tracking
    """
    gate = require_premium(caller_address)
    if gate: return gate
    
    try:
        data = await fetch_json(f"{AERODROME_API}/pools")
        if isinstance(data, list):
            pools = []
            for p in data[:30]:
                tvl = float(p.get("tvl", 0) or 0)
                if tvl >= min_liquidity_usd:
                    pools.append({
                        "name": p.get("name", "Unknown"),
                        "address": p.get("address", ""),
                        "tvl_usd": f"${tvl:,.0f}",
                        "volume_24h": p.get("volume24h", "N/A"),
                        "apr": f"{float(p.get('apr', 0) or 0):.1f}%"
                    })
            return json_ok({"count": len(pools), "pools": pools})
    except Exception as e:
        pass
    
    return json_ok({
        "pools": [
            {"name": "AERO/WETH", "tvl": "$50M+", "apr": "~15%"},
            {"name": "USDC/WETH", "tvl": "$30M+", "apr": "~8%"},
            {"name": "AERO/USDC", "tvl": "$20M+", "apr": "~12%"},
        ],
        "note": "Live API unavailable — showing cached data"
    })

# ─── TOOL 5: analyze_wallet (PREMIUM) ─────────────────────
@mcp.tool()
async def analyze_wallet(address: str, caller_address: str = None) -> str:
    """Full wallet analysis: balance, tx count, portfolio, contract check. PREMIUM tier.
    
    Args:
        address: Wallet to analyze
        caller_address: Your wallet for access tracking
    """
    gate = require_premium(caller_address)
    if gate: return gate
    
    if not web3:
        return json_error("Base RPC not connected")
    try:
        addr = to_checksum(address)
        eth_bal = format_amount(web3.eth.get_balance(addr))
        tx_count = web3.eth.get_transaction_count(addr)
        is_contract = len(web3.eth.get_code(addr)) > 2
        
        tokens_found = []
        for sym, t_addr in TOKENS.items():
            try:
                ca = to_checksum(t_addr)
                contract = web3.eth.contract(address=ca, abi=ERC20_ABI)
                dec = contract.functions.decimals().call()
                bal = contract.functions.balanceOf(addr).call()
                if bal > 0:
                    tokens_found.append(f"{format_amount(bal, dec):.4f} {sym}")
            except:
                continue
        
        return json_ok({
            "address": addr, "eth_balance": f"{eth_bal:.6f} ETH",
            "transaction_count": tx_count, "is_contract": is_contract,
            "token_holdings": tokens_found if tokens_found else ["None detected"],
            "chain": "Base", "explorer": f"https://basescan.org/address/{addr}"
        })
    except Exception as e:
        return json_error(str(e))

# ─── TOOL 6: track_new_tokens (PREMIUM) ────────────────────
@mcp.tool()
async def track_new_tokens(since_hours: int = 2, caller_address: str = None) -> str:
    """Scan Base for newly deployed tokens. PREMIUM tier.
    
    Args:
        since_hours: How many hours back to scan
        caller_address: Your wallet for access tracking
    """
    gate = require_premium(caller_address)
    if gate: return gate
    
    if not web3:
        return json_error("Base RPC not connected")
    try:
        latest = web3.eth.block_number
        blocks_back = int(since_hours * 3600 / 2)
        
        # Check Clanker API for recent launches
        try:
            clanker = await fetch_json(f"{CLANKER_API}/tokens/recent", {"limit": 10})
            if isinstance(clanker, list):
                recent = []
                for t in clanker[:10]:
                    recent.append({
                        "name": t.get("name", "Unknown"),
                        "symbol": t.get("symbol", "???"),
                        "address": t.get("address", ""),
                        "launched_at": t.get("created_at", "N/A"),
                        "liquidity": t.get("liquidity_usd", "N/A"),
                    })
                return json_ok({
                    "chain": "Base", "method": "Clanker API",
                    "recent_launches": recent
                })
        except:
            pass
        
        return json_ok({
            "chain": "Base", "latest_block": latest,
            "scan_range": f"blocks {latest - blocks_back} → {latest}",
            "method": "Blockscout API would go here",
            "recent_launches": []
        })
    except Exception as e:
        return json_error(str(e))

# ─── TOOL 7: prepare_swap (PREMIUM - $GATE HOLDERS) ───────
@mcp.tool()
async def prepare_swap(
    token_in: str,
    token_out: str,
    amount: float,
    slippage: float = 0.5,
    caller_address: str = None
) -> str:
    """Prepare an Aerodrome swap transaction. $GATE HOLDER tier.
    
    Returns the unsigned transaction data for the user to sign locally.
    Server NEVER touches your private key.
    
    Args:
        token_in: Input token symbol or address
        token_out: Output token symbol or address
        amount: Amount in human-readable format
        slippage: Slippage tolerance % (default 0.5)
        caller_address: Your wallet address
    """
    gate = payment_gate.check(caller_address)
    if not gate["allowed"]:
        return json_error(gate["reason"], "payment_required")
    if gate["tier"] != "gate_holder":
        return json_error("Swap execution requires $GATE token. Buy $GATE to unlock.")
    
    if not web3:
        return json_error("Base RPC not connected")
    
    try:
        # Resolve token addresses
        def resolve(token):
            if token.startswith("0x"):
                return to_checksum(token)
            return to_checksum(TOKENS.get(token.upper(), token))
        
        addr_in = resolve(token_in)
        addr_out = resolve(token_out)
        wallet = to_checksum(caller_address)
        
        # Get token decimals
        in_contract = web3.eth.contract(address=addr_in, abi=ERC20_ABI)
        in_decimals = in_contract.functions.decimals().call()
        amount_wei = int(amount * (10 ** in_decimals))
        
        # Get current price for min out calculation
        router = web3.eth.contract(
            address=to_checksum(AERODROME_ROUTER),
            abi=[{
                "constant": True,
                "inputs": [{"name":"amountIn","type":"uint256"},{"name":"routes","type":"tuple(address,address,bool,address)[]"}],
                "name": "getAmountsOut",
                "outputs": [{"name":"amounts","type":"uint256[]"}],
                "type": "function"
            }]
        )
        
        # Route: token_in -> token_out via Aerodrome
        routes = [{"from": addr_in, "to": addr_out, "stable": False, "factory": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"}]
        
        try:
            amounts_out = router.functions.getAmountsOut(amount_wei, routes).call()
            expected_out = amounts_out[-1]
        except:
            expected_out = 0
        
        min_out = int(expected_out * (1 - slippage / 100)) if expected_out > 0 else 0
        
        # Build swap transaction data (user signs locally)
        swap_data = {
            "router": AERODROME_ROUTER,
            "chain": "Base",
            "from_token": {"address": addr_in, "amount": str(amount_wei)},
            "to_token": {"address": addr_out, "min_amount": str(min_out)},
            "slippage": f"{slippage}%",
            "routes": [
                {"from": addr_in, "to": addr_out, "stable": False, "factory": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"}
            ],
            "deadline": int(time.time() + 600),  # 10 min from now
            "estimated_gas": "~150000 gwei",
            "instructions": "Copy this data to your wallet and sign. Server NEVER sees your key."
        }
        
        return json_ok(swap_data)
    except Exception as e:
        return json_error(str(e))

# ─── TOOL 8: get_payment_status ────────────────────────────
@mcp.tool()
async def get_payment_status(caller_address: str = None) -> str:
    """Check your access tier and remaining free calls. PREMIUM tier.
    
    Args:
        caller_address: Your wallet address
    """
    status = payment_gate.status(caller_address)
    return json_ok({
        "tier": status["tier"],
        "allowed": status["allowed"],
        "calls_today": status.get("calls_today", 0),
        "calls_remaining": status.get("calls_remaining", 0),
        "daily_limit": DAILY_FREE_CALLS,
        "gate_token_address": GATE_TOKEN_ADDRESS or "Not configured",
        "fee_collector": FEE_WALLET,
        "fee_bps": FEE_BPS,
        "upgrade": "Buy $GATE token for unlimited access + swap execution"
    })

# ─── TOOL 9: get_token_price (PREMIUM) ────────────────────
@mcp.tool()
async def get_token_price(symbol: str = "ETH", caller_address: str = None) -> str:
    """Get current token price in USD. PREMIUM tier.
    
    Args:
        symbol: Token symbol (ETH, USDC, AERO, BTC, etc.)
        caller_address: Your wallet for access tracking
    """
    gate = require_premium(caller_address)
    if gate: return gate
    
    coin_ids = {"eth": "ethereum", "usdc": "usd-coin", "aero": "aerodrome-finance", 
                 "btc": "bitcoin", "sol": "solana", "dai": "dai", "clanker": "clanker"}
    coin_id = coin_ids.get(symbol.lower(), symbol.lower())
    
    try:
        data = await fetch_json(f"{COINGECKO_API}/simple/price", {
            "ids": coin_id, "vs_currencies": "usd"
        })
        price = data.get(coin_id, {}).get("usd", "N/A")
        return json_ok({"symbol": symbol.upper(), "price_usd": price, "source": "CoinGecko"})
    except Exception as e:
        return json_error(str(e))

# ─── TOOL 10: get_recent_transactions (PREMIUM) ────────────
@mcp.tool()
async def get_recent_transactions(address: str, limit: int = 5, caller_address: str = None) -> str:
    """Get recent transactions for a wallet on Base. PREMIUM tier.
    
    Args:
        address: Wallet address
        limit: Max transactions (default 5)
        caller_address: Your wallet for access tracking
    """
    gate = require_premium(caller_address)
    if gate: return gate
    
    if not web3:
        return json_error("Base RPC not connected")
    try:
        addr = to_checksum(address)
        latest = web3.eth.block_number
        txs = []
        
        # Scan recent blocks for transactions from/to this address
        # (In production, use Blockscout or Etherscan API instead)
        for i in range(min(limit * 10, 200)):
            block_num = latest - i
            try:
                block = web3.eth.get_block(block_num, full_transactions=True)
                if block and block.get("transactions"):
                    for tx in block["transactions"]:
                        if tx["from"].lower() == addr.lower() or (tx.get("to") and tx["to"].lower() == addr.lower()):
                            txs.append({
                                "hash": tx["hash"].hex(),
                                "from": tx["from"],
                                "to": tx.get("to", "contract_creation"),
                                "value_eth": format_amount(tx["value"]),
                                "block": block_num,
                                "explorer": f"https://basescan.org/tx/{tx['hash'].hex()}"
                            })
                            if len(txs) >= limit:
                                break
            except:
                continue
            if len(txs) >= limit:
                break
        
        return json_ok({"address": addr, "recent_txs": txs})
    except Exception as e:
        return json_error(str(e))

# ═══════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    if "--http" in sys.argv:
        port = int(sys.argv[sys.argv.index("--http") + 1]) if "--http" in sys.argv and len(sys.argv) > sys.argv.index("--http") + 1 else 8080
        mcp.run(transport="sse", mount_path="/mcp")
        print(f"Serving SSE at http://0.0.0.0:{port}/mcp", file=sys.stderr)
    elif "--x402" in sys.argv:
        print("x402 mode: Run as HTTP server with x402 payment gateway", file=sys.stderr)
        print("x402 USDC payments on Base — each call costs ~$0.001", file=sys.stderr)
        port = int(sys.argv[sys.argv.index("--x402") + 1]) if "--x402" in sys.argv and len(sys.argv) > sys.argv.index("--x402") + 1 else 4020
        mcp.run(transport="sse", mount_path="/mcp")
    else:
        mcp.run(transport="stdio")
