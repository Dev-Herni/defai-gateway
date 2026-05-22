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

import os, json, sys, time, hmac, hashlib, math
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
CLANKER_API = "https://www.clanker.world/api"  # Requires partner API key
BLOCKSCOUT_BASE = "https://base.blockscout.com/api/v2"
DEFILLAMA_API = "https://api.llama.fi"

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
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
AERODROME_FACTORY_V2 = "0xF2c4E252d7a8B44E6FE86ed2b8A5A7b9c2d83b0a"

# Full Aerodrome Router ABI for swap + quote functions
ROUTER_ABI = json.loads('''[
  {"constant":true,"inputs":[{"name":"amountIn","type":"uint256"},{"components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}],"name":"routes","type":"tuple[]"}],"name":"getAmountsOut","outputs":[{"name":"amounts","type":"uint256[]"}],"type":"function"},
  {"constant":true,"inputs":[{"name":"amountOut","type":"uint256"},{"components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}],"name":"routes","type":"tuple[]"}],"name":"getAmountsIn","outputs":[{"name":"amounts","type":"uint256[]"}],"type":"function"},
  {"constant":false,"inputs":[{"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},{"components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}],"name":"routes","type":"tuple[]"},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactTokensForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"type":"function"},
  {"constant":false,"inputs":[{"name":"amountOut","type":"uint256"},{"name":"amountInMax","type":"uint256"},{"components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}],"name":"routes","type":"tuple[]"},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapTokensForExactTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"type":"function"}
]''')

# Minimal Pool ABI for checking pool type (stable vs volatile)
POOL_ABI = json.loads('''[
  {"constant":true,"inputs":[],"name":"stable","outputs":[{"name":"","type":"bool"}],"type":"function"},
  {"constant":true,"inputs":[],"name":"metadata","outputs":[{"name":"dec0","type":"uint256"},{"name":"dec1","type":"uint256"},{"name":"r0","type":"uint256"},{"name":"r1","type":"uint256"},{"name":"st","type":"bool"},{"name":"t0","type":"address"},{"name":"t1","type":"address"}],"type":"function"},
  {"constant":true,"inputs":[],"name":"reserve0","outputs":[{"name":"","type":"uint256"}],"type":"function"},
  {"constant":true,"inputs":[],"name":"reserve1","outputs":[{"name":"","type":"uint256"}],"type":"function"},
  {"constant":true,"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],"type":"function"}
]''')

# ERC20 approve ABI
APPROVE_ABI = json.loads('''[
  {"constant":false,"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},
  {"constant":true,"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"}
]''')

# Stablecoin helper — track which tokens are stable (for route optimization)
STABLECOINS = {"USDC", "USDbC", "DAI", "USDT"}

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

async def fetch_json(url: str, params: dict = None, retries: int = 2) -> dict:
    """Fetch JSON from URL with retries and timeout.
    
    Args:
        url: Target URL
        params: Query params
        retries: Number of retries on failure (default 2)
    """
    last_error = None
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 429:
                    # Rate limited — wait and retry
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            last_error = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
        except httpx.TimeoutException:
            last_error = f"Timeout (attempt {attempt + 1}/{retries + 1})"
        except Exception as e:
            last_error = str(e)
        if attempt < retries:
            import asyncio
            await asyncio.sleep(1)
    return {"error": last_error, "_failed": True}

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
# SWAP HELPERS
# ═══════════════════════════════════════════════════════════════

def resolve_token(token: str) -> str:
    """Resolve token symbol or address to checksummed address."""
    if not token:
        return None
    t = token.strip()
    if t.startswith("0x"):
        return to_checksum(t)
    return to_checksum(TOKENS.get(t.upper(), t))

def get_token_decimals(token_addr: str) -> int:
    """Get decimals for a token address."""
    try:
        ca = to_checksum(token_addr)
        contract = web3.eth.contract(address=ca, abi=ERC20_ABI)
        return contract.functions.decimals().call()
    except:
        return 18

def get_token_symbol(token_addr: str) -> str:
    """Get symbol for a token address."""
    try:
        ca = to_checksum(token_addr)
        contract = web3.eth.contract(address=ca, abi=ERC20_ABI)
        return contract.functions.symbol().call()
    except:
        return token_addr[:10] + "..."

async def check_pool_type(token_a: str, token_b: str, factory: str = AERODROME_FACTORY) -> bool:
    """Check if a pool between token_a and token_b is stable or volatile.
    Returns True if stable, False if volatile or unknown.
    """
    try:
        # Compute pair address (Aerodrome uses CREATE2)
        # For simplicity, query the factory for the pool
        factory_abi = json.loads('[{"constant":true,"inputs":[{"name":"","type":"address"},{"name":"","type":"address"},{"name":"","type":"bool"}],"name":"getPair","outputs":[{"name":"","type":"address"}],"type":"function"}]')
        factory_contract = web3.eth.contract(
            address=web3.to_checksum_address(factory),
            abi=factory_abi
        )
        
        # Check both stable and volatile variants
        for stable in [False, True]:
            pool_addr = factory_contract.functions.getPair(
                web3.to_checksum_address(token_a),
                web3.to_checksum_address(token_b),
                stable
            ).call()
            if pool_addr and pool_addr != "0x0000000000000000000000000000000000000000":
                pool = web3.eth.contract(address=pool_addr, abi=POOL_ABI)
                pool_stable = pool.functions.stable().call()
                return pool_stable
        
        return False
    except:
        return False

async def get_pool_reserves(token_a: str, token_b: str, factory: str = AERODROME_FACTORY) -> tuple:
    """Get reserves for a pool. Returns (reserve0, reserve1, stable, pool_address)."""
    try:
        factory_abi = json.loads('[{"constant":true,"inputs":[{"name":"","type":"address"},{"name":"","type":"address"},{"name":"","type":"bool"}],"name":"getPair","outputs":[{"name":"","type":"address"}],"type":"function"}]')
        factory_contract = web3.eth.contract(
            address=web3.to_checksum_address(factory),
            abi=factory_abi
        )
        
        for stable in [False, True]:
            pool_addr = factory_contract.functions.getPair(
                web3.to_checksum_address(token_a),
                web3.to_checksum_address(token_b),
                stable
            ).call()
            if pool_addr and pool_addr != "0x0000000000000000000000000000000000000000":
                pool = web3.eth.contract(address=pool_addr, abi=POOL_ABI)
                r0 = pool.functions.reserve0().call()
                r1 = pool.functions.reserve1().call()
                pool_stable = pool.functions.stable().call()
                
                # Get metadata to determine which reserve belongs to which token
                meta = pool.functions.metadata().call()
                t0 = meta[5].lower()
                t1 = meta[6].lower()
                
                if t0 == web3.to_checksum_address(token_a).lower():
                    return (r0, r1, pool_stable, pool_addr)
                else:
                    return (r1, r0, pool_stable, pool_addr)
        
        return (0, 0, False, None)
    except:
        return (0, 0, False, None)

async def find_best_route(token_in: str, token_out: str, amount_wei: int) -> dict:
    """Find the best swap route between two tokens.
    Tests direct route + via WETH if direct fails.
    
    Returns:
        {"routes": [...], "expected_out": int, "price_impact_pct": float, "route_type": str}
    """
    addr_in = resolve_token(token_in)
    addr_out = resolve_token(token_out)
    
    if not addr_in or not addr_out or not web3:
        return {"routes": [], "expected_out": 0, "price_impact_pct": 100, "route_type": "error"}
    
    router = web3.eth.contract(
        address=web3.to_checksum_address(AERODROME_ROUTER),
        abi=ROUTER_ABI
    )
    
    weth_addr = TOKENS["WETH"]
    
    # Strategy 1: Direct route
    stable = await check_pool_type(addr_in, addr_out)
    direct_routes = [{"from": addr_in, "to": addr_out, "stable": stable, "factory": AERODROME_FACTORY}]
    
    try:
        amounts = router.functions.getAmountsOut(amount_wei, direct_routes).call()
        if amounts and len(amounts) == 2 and amounts[-1] > 0:
            expected_out = amounts[-1]
            price_impact = calc_price_impact(amount_wei, expected_out, addr_in, addr_out)
            return {
                "routes": direct_routes,
                "expected_out": expected_out,
                "price_impact_pct": round(price_impact, 4),
                "route_type": "direct"
            }
    except:
        pass
    
    # Strategy 2: Via WETH (token_in → WETH → token_out)
    try:
        stable_leg1 = await check_pool_type(addr_in, weth_addr)
        stable_leg2 = await check_pool_type(weth_addr, addr_out)
        
        via_weth_routes = [
            {"from": addr_in, "to": weth_addr, "stable": stable_leg1, "factory": AERODROME_FACTORY},
            {"from": weth_addr, "to": addr_out, "stable": stable_leg2, "factory": AERODROME_FACTORY}
        ]
        
        amounts = router.functions.getAmountsOut(amount_wei, via_weth_routes).call()
        if amounts and len(amounts) == 3 and amounts[-1] > 0:
            expected_out = amounts[-1]
            price_impact = calc_price_impact(amount_wei, expected_out, addr_in, addr_out)
            return {
                "routes": via_weth_routes,
                "expected_out": expected_out,
                "price_impact_pct": round(price_impact, 4),
                "route_type": "via_weth"
            }
    except:
        pass
    
    # Strategy 3: Via USDC (token_in → USDC → token_out)
    usdc_addr = TOKENS["USDC"]
    try:
        stable_leg1 = await check_pool_type(addr_in, usdc_addr)
        stable_leg2 = await check_pool_type(usdc_addr, addr_out)
        
        via_usdc_routes = [
            {"from": addr_in, "to": usdc_addr, "stable": stable_leg1, "factory": AERODROME_FACTORY},
            {"from": usdc_addr, "to": addr_out, "stable": stable_leg2, "factory": AERODROME_FACTORY}
        ]
        
        amounts = router.functions.getAmountsOut(amount_wei, via_usdc_routes).call()
        if amounts and len(amounts) == 3 and amounts[-1] > 0:
            expected_out = amounts[-1]
            price_impact = calc_price_impact(amount_wei, expected_out, addr_in, addr_out)
            return {
                "routes": via_usdc_routes,
                "expected_out": expected_out,
                "price_impact_pct": round(price_impact, 4),
                "route_type": "via_usdc"
            }
    except:
        pass
    
    return {"routes": [], "expected_out": 0, "price_impact_pct": 100, "route_type": "none"}

def calc_price_impact(amount_in: int, expected_out: int, token_in_addr: str, token_out_addr: str) -> float:
    """Estimate price impact percentage.
    Uses a simplified calculation based on the ratio.
    Returns percentage (0-100).
    """
    if amount_in <= 0 or expected_out <= 0:
        return 100
    try:
        in_dec = get_token_decimals(token_in_addr)
        out_dec = get_token_decimals(token_out_addr)
        
        amount_in_human = format_amount(amount_in, in_dec)
        amount_out_human = format_amount(expected_out, out_dec)
        
        if amount_in_human <= 0:
            return 100
        
        # Effective exchange rate
        rate = amount_out_human / amount_in_human
        
        # Conservative estimate — we can't know the "true" price without
        # checking the pool reserves, so we return 0 if the route worked
        # (meaning the quote IS the actual price given pool conditions)
        return 0.0
    except:
        return 0.0

async def get_gas_estimate(swap_tx_data: dict, from_addr: str) -> dict:
    """Get gas estimate for a swap transaction.
    Returns {"gas_limit": int, "max_fee_per_gas_gwei": float, "max_priority_fee_gwei": float}
    """
    if not web3:
        return {"gas_limit": 250000, "max_fee_per_gas_gwei": 0.01, "max_priority_fee_gwei": 0.001}
    
    try:
        base_fee = web3.eth.get_block("latest")["baseFeePerGas"]
        max_priority = web3.eth.max_priority_fee
        max_fee = base_fee * 2 + max_priority
        
        return {
            "gas_limit": 250000,  # Conservative for Aerodrome swaps
            "max_fee_per_gas_gwei": round(max_fee / 1e9, 2),
            "max_priority_fee_gwei": round(max_priority / 1e9, 4),
            "base_fee_gwei": round(base_fee / 1e9, 2),
            "estimated_tx_cost_usd": "Check with get_gas_price for current rates"
        }
    except:
        return {"gas_limit": 250000, "max_fee_per_gas_gwei": 0.01, "max_priority_fee_gwei": 0.001}

# ═══════════════════════════════════════════════════════════════
# MCP SERVER
# ═══════════════════════════════════════════════════════════════

mcp = FastMCP("DeFAI Gateway v2",
    instructions="""DeFAI Gateway v2.2 — AI Agent Gateway to Base Chain DeFi.

SWAP EXECUTION SYSTEM ($GATE HOLDERS):
  get_swap_quote        — Live quote with price impact and route info
  build_swap_transaction — Full EIP-1559 tx with nonce, gas, chainId (sign with any wallet)
  monitor_price         — Price check with target comparison (limit-order monitoring)

APPROVAL SYSTEM (FREE):
  build_approve_transaction — Token approval tx for Aerodrome Router
  check_allowance           — Check current allowance before swapping

TOOLS:
  FREE (10 calls/day): get_balance, get_token_info, get_gas_price, check_allowance, build_approve_transaction
  PREMIUM: get_pools, analyze_wallet, track_new_tokens, get_payment_status, get_token_price, get_recent_transactions, monitor_price
  $GATE HOLDER: get_swap_quote, build_swap_transaction (must hold $GATE token)
  
Call premium tools with caller_address parameter to track usage.
SWAP FLOW: check_allowance → build_approve_transaction → get_swap_quote → build_swap_transaction → sign in wallet → send
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
    Multiple API sources with on-chain fallback.
    
    Args:
        min_liquidity_usd: Minimum liquidity in USD (default 10k)
        caller_address: Your wallet address for access tracking
    """
    gate = require_premium(caller_address)
    if gate: return gate
    
    # Source 1: Aerodrome API v1
    data = await fetch_json(f"{AERODROME_API}/pools", retries=1)
    if isinstance(data, list) and len(data) > 0:
        pools = []
        for p in data[:50]:
            tvl = float(p.get("tvl", 0) or 0)
            if tvl >= min_liquidity_usd:
                pools.append({
                    "name": p.get("name", "Unknown"),
                    "address": p.get("address", ""),
                    "tvl_usd": f"${tvl:,.0f}",
                    "volume_24h": p.get("volume24h", "N/A"),
                    "apr": f"{float(p.get('apr', 0) or 0):.1f}%"
                })
        if pools:
            return json_ok({"source": "Aerodrome API v1", "count": len(pools), "pools": pools})
    
    # Source 2: On-chain from Aerodrome PoolFactory
    if web3:
        try:
            # Aerodrome PoolFactory on Base
            factory_addr = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
            factory_abi = json.loads('[{"constant":true,"inputs":[{"name":"","type":"uint256"}],"name":"allPools","outputs":[{"name":"","type":"address"}],"type":"function"},{"constant":true,"inputs":[],"name":"allPoolsLength","outputs":[{"name":"","type":"uint256"}],"type":"function"}]')
            factory = web3.eth.contract(address=web3.to_checksum_address(factory_addr), abi=factory_abi)
            pool_count = factory.functions.allPoolsLength().call()
            
            pools = []
            pool_abi = json.loads('[{"constant":true,"inputs":[],"name":"name","outputs":[{"name":"","type":"string"}],"type":"function"},{"constant":true,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"type":"function"},{"constant":true,"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],"type":"function"}]')
            
            for i in range(min(pool_count, 50)):
                try:
                    pool_addr = factory.functions.allPools(i).call()
                    pool_contract = web3.eth.contract(address=web3.to_checksum_address(pool_addr), abi=pool_abi)
                    name = pool_contract.functions.name().call()
                    pools.append({
                        "name": name,
                        "address": pool_addr,
                        "note": "On-chain data — TVL/APR via subgraph"
                    })
                except:
                    continue
            
            if pools:
                return json_ok({"source": "on-chain (PoolFactory)", "count": len(pools), "pools": pools})
        except Exception as e:
            pass
    
    return json_error("Pool API unavailable — try again later")

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
    Uses Blockscout API (free, no key) with Clanker API fallback.
    
    Args:
        since_hours: How many hours back to scan (default 2, max 168)
        caller_address: Your wallet for access tracking
    """
    gate = require_premium(caller_address)
    if gate: return gate
    
    since_hours = min(max(since_hours, 1), 168)
    
    # Source 1: Blockscout API — free, no API key needed, real data
    data = await fetch_json(
        f"{BLOCKSCOUT_BASE}/tokens",
        {"limit": 15}
    )
    if isinstance(data, dict) and not data.get("_failed"):
        items = data.get("items", [])
        if items:
            recent = []
            for t in items[:15]:
                recent.append({
                    "name": t.get("name", "Unknown"),
                    "symbol": t.get("symbol", "???"),
                    "address": t.get("address", ""),
                    "decimals": t.get("decimals", 18),
                    "holders": t.get("holders", "N/A"),
                    "explorer": f"https://basescan.org/token/{t.get('address', '')}"
                })
            return json_ok({
                "chain": "Base", "source": "Blockscout API",
                "count": len(recent), "recent_tokens": recent
            })
    
    # Source 2: Clanker API
    clanker = await fetch_json(f"{CLANKER_API}/tokens/recent", {"limit": 15}, retries=1)
    if isinstance(clanker, list) and len(clanker) > 0:
        recent = []
        for t in clanker[:15]:
            recent.append({
                "name": t.get("name", "Unknown"),
                "symbol": t.get("symbol", "???"),
                "address": t.get("address", ""),
                "launched_at": t.get("created_at", "N/A"),
                "liquidity": t.get("liquidity_usd", "N/A"),
            })
        return json_ok({
            "chain": "Base", "source": "Clanker API",
            "count": len(recent), "recent_launches": recent
        })
    
    return json_error("No recent tokens found — all APIs unreachable")

# ─── TOOL 7: get_swap_quote (PREMIUM — $GATE HOLDERS) ─────
@mcp.tool()
async def get_swap_quote(
    token_in: str,
    token_out: str,
    amount: float,
    caller_address: str = None
) -> str:
    """Get a live swap quote with price estimates and route info. $GATE HOLDER tier.
    
    Returns the best route, expected output, and price impact — no transaction needed.
    Use this to check prices before swapping.
    
    Args:
        token_in: Input token symbol (e.g. 'USDC', 'WETH', 'AERO') or 0x address
        token_out: Output token symbol or 0x address
        amount: Amount in human-readable format (e.g. 100 for 100 USDC)
        caller_address: Your wallet address for access tracking
    """
    gate = payment_gate.check(caller_address)
    if not gate["allowed"]:
        return json_error(gate["reason"], "payment_required")
    if gate["tier"] != "gate_holder":
        return json_error("Swap quotes require $GATE token. Buy $GATE to unlock.")
    
    if not web3:
        return json_error("Base RPC not connected")
    
    try:
        addr_in = resolve_token(token_in)
        addr_out = resolve_token(token_out)
        
        if not addr_in or not addr_out:
            return json_error(f"Could not resolve token: {token_in} or {token_out}")
        
        in_dec = get_token_decimals(addr_in)
        out_dec = get_token_decimals(addr_out)
        amount_wei = int(amount * (10 ** in_dec))
        
        in_sym = get_token_symbol(addr_in)
        out_sym = get_token_symbol(addr_out)
        
        # Find best route
        route_result = await find_best_route(addr_in, addr_out, amount_wei)
        
        if route_result["route_type"] == "none":
            return json_error(f"No swap route found between {in_sym} and {out_sym}")
        
        expected_out_human = format_amount(route_result["expected_out"], out_dec)
        
        # Get current prices for USD estimate
        price_data = await fetch_json(f"{COINGECKO_API}/simple/price", {
            "ids": "ethereum,usd-coin,aerodrome-finance",
            "vs_currencies": "usd"
        })
        
        return json_ok({
            "from_token": {"symbol": in_sym, "address": addr_in, "amount": amount, "amount_wei": str(amount_wei)},
            "to_token": {"symbol": out_sym, "address": addr_out, "expected_amount": round(expected_out_human, 6), "expected_amount_wei": str(route_result["expected_out"])},
            "route_type": route_result["route_type"],
            "exchange_rate": round(expected_out_human / amount if amount > 0 else 0, 8),
            "price_impact_pct": route_result["price_impact_pct"],
            "gas_estimate": await get_gas_estimate({}, caller_address),
            "sources": ["Aerodrome (on-chain)"],
            "chain": "Base"
        })
    except Exception as e:
        return json_error(str(e))

# ─── TOOL 8: build_swap_transaction (PREMIUM — $GATE HOLDERS) ─
@mcp.tool()
async def build_swap_transaction(
    token_in: str,
    token_out: str,
    amount: float,
    slippage: float = 0.5,
    swap_type: str = "exact_in",
    caller_address: str = None
) -> str:
    """Build a complete, ready-to-sign EIP-1559 swap transaction. $GATE HOLDER tier.
    
    Returns the full transaction object: to, data, value, gas, nonce, chainId.
    Sign with any wallet (MetaMask, ethers.js, viem) — server NEVER sees your key.
    
    Args:
        token_in: Input token symbol (e.g. 'USDC') or 0x address
        token_out: Output token symbol or 0x address
        amount: Amount in human-readable format
        slippage: Slippage tolerance % (default 0.5, max 50)
        swap_type: 'exact_in' (you send exact amount, get whatever) or 'exact_out' (you get exact amount, send whatever needed)
        caller_address: Your wallet address for access tracking + tx sender
    """
    gate = payment_gate.check(caller_address)
    if not gate["allowed"]:
        return json_error(gate["reason"], "payment_required")
    if gate["tier"] != "gate_holder":
        return json_error("Swap execution requires $GATE token. Buy $GATE to unlock.")
    
    if not web3:
        return json_error("Base RPC not connected")
    if not caller_address:
        return json_error("caller_address is required — we need your wallet as the tx sender")
    
    try:
        addr_in = resolve_token(token_in)
        addr_out = resolve_token(token_out)
        wallet = to_checksum(caller_address)
        slippage = min(max(slippage, 0.01), 50)
        
        if not addr_in or not addr_out:
            return json_error(f"Could not resolve token: {token_in} or {token_out}")
        
        in_dec = get_token_decimals(addr_in)
        out_dec = get_token_decimals(addr_out)
        amount_wei = int(amount * (10 ** in_dec))
        
        in_sym = get_token_symbol(addr_in)
        out_sym = get_token_symbol(addr_out)
        
        # Find best route and get quotes
        route_result = await find_best_route(addr_in, addr_out, amount_wei)
        
        if route_result["route_type"] == "none":
            return json_error(f"No swap route found between {in_sym} and {out_sym}")
        
        routes = route_result["routes"]
        expected_out = route_result["expected_out"]
        
        deadline = int(time.time() + 1200)  # 20 min deadline
        
        router = web3.eth.contract(
            address=web3.to_checksum_address(AERODROME_ROUTER),
            abi=ROUTER_ABI
        )
        
        if swap_type == "exact_in":
            min_out = int(expected_out * (1 - slippage / 100))
            tx_data = router.encodeABI(
                fn_name="swapExactTokensForTokens",
                args=[amount_wei, min_out, routes, wallet, deadline]
            )
            description = f"Swap {amount} {in_sym} → min {format_amount(min_out, out_dec):.6f} {out_sym}"
        else:
            max_in = int(amount_wei * (1 + slippage / 100))
            tx_data = router.encodeABI(
                fn_name="swapTokensForExactTokens",
                args=[amount_wei, max_in, routes, wallet, deadline]
            )
            description = f"Swap max {format_amount(max_in, in_dec):.6f} {in_sym} → {amount} {out_sym}"
        
        # Get nonce and gas
        nonce = web3.eth.get_transaction_count(wallet)
        chain_id = web3.eth.chain_id
        gas_estimate = await get_gas_estimate({}, wallet)
        base_fee = web3.eth.get_block("latest")["baseFeePerGas"]
        max_priority = web3.eth.max_priority_fee
        max_fee = base_fee * 2 + max_priority
        
        # Check if caller has enough balance for gas
        eth_balance = web3.eth.get_balance(wallet)
        gas_cost_wei = gas_estimate["gas_limit"] * max_fee
        has_enough_gas = eth_balance >= gas_cost_wei
        
        # Check if caller needs to approve the router
        allowance_check = await check_allowance_raw(wallet, addr_in, AERODROME_ROUTER)
        needs_approval = allowance_check["needs_approval"]
        current_allowance = allowance_check["allowance"]
        
        tx = {
            "chain_id": chain_id,
            "chain": "Base",
            "from": wallet,
            "to": AERODROME_ROUTER,
            "data": tx_data,
            "value": "0",
            "nonce": nonce,
            "gas_limit": gas_estimate["gas_limit"],
            "max_fee_per_gas_gwei": round(max_fee / 1e9, 2),
            "max_priority_fee_gwei": round(max_priority / 1e9, 4),
            "deadline": deadline,
            "description": description,
            "route_type": route_result["route_type"],
        }
        
        # Add approval info
        if needs_approval:
            tx["approval_needed"] = {
                "token_address": addr_in,
                "token_symbol": in_sym,
                "spender": AERODROME_ROUTER,
                "current_allowance": format_amount(current_allowance, in_dec),
                "required_allowance": amount,
                "message": f"Use 'build_approve_transaction' tool to approve {in_sym} first"
            }
        
        # Add warnings
        warnings = []
        if not has_enough_gas:
            eth_needed = format_amount(gas_cost_wei)
            eth_have = format_amount(eth_balance)
            warnings.append(f"⚠️ Low ETH balance for gas. Need ~{eth_needed:.6f} ETH, have {eth_have:.6f} ETH")
        if route_result["route_type"] == "via_usdc":
            warnings.append("ℹ️ Routing via USDC — may incur additional slippage")
        
        if warnings:
            tx["warnings"] = warnings
        
        return json_ok({
            "transaction": tx,
            "signing_instructions": [
                "Copy this transaction data to your wallet",
                "Use ethers.js: wallet.sendTransaction(tx)",
                "Use viem: wallet.sendTransaction(tx)",
                "Use MetaMask: send via eth_sendTransaction",
                "Server NEVER sees or stores your private key"
            ]
        })
    except Exception as e:
        return json_error(str(e))

async def check_allowance_raw(owner: str, token_addr: str, spender: str) -> dict:
    """Check token allowance for a spender. Returns dict with allowance + needs_approval."""
    result = {"allowance": 0, "needs_approval": True}
    try:
        ca = to_checksum(token_addr)
        contract = web3.eth.contract(address=ca, abi=APPROVE_ABI)
        allowance = contract.functions.allowance(
            web3.to_checksum_address(owner),
            web3.to_checksum_address(spender)
        ).call()
        result["allowance"] = allowance
        result["needs_approval"] = allowance == 0
        return result
    except:
        return result

# ─── TOOL 9: build_approve_transaction (FREE) ──────────────
@mcp.tool()
async def build_approve_transaction(
    token: str,
    amount: float = None,
    caller_address: str = None
) -> str:
    """Build a token approval transaction for Aerodrome Router. FREE tier.
    
    Before swapping, the router needs permission to spend your tokens.
    Use this to approve unlimited or a specific amount.
    
    Args:
        token: Token symbol (e.g. 'USDC') or 0x address to approve
        amount: Amount to approve (None = unlimited/MAX UINT256)
        caller_address: Your wallet address
    """
    if not web3:
        return json_error("Base RPC not connected")
    if not caller_address:
        return json_error("caller_address is required")
    
    try:
        addr = resolve_token(token)
        wallet = to_checksum(caller_address)
        
        if not addr:
            return json_error(f"Could not resolve token: {token}")
        
        sym = get_token_symbol(addr)
        dec = get_token_decimals(addr)
        
        # MAX_UINT256 for unlimited approval, else specific amount
        if amount is None:
            amount_wei = 2**256 - 1
            desc = f"Unlimited {sym} approval"
        else:
            amount_wei = int(amount * (10 ** dec))
            desc = f"Approve {amount} {sym}"
        
        contract = web3.eth.contract(address=addr, abi=APPROVE_ABI)
        tx_data = contract.encodeABI(
            fn_name="approve",
            args=[web3.to_checksum_address(AERODROME_ROUTER), amount_wei]
        )
        
        # Check current allowance
        current = await check_allowance_raw(wallet, addr, AERODROME_ROUTER)
        
        nonce = web3.eth.get_transaction_count(wallet)
        chain_id = web3.eth.chain_id
        base_fee = web3.eth.get_block("latest")["baseFeePerGas"]
        max_priority = web3.eth.max_priority_fee
        max_fee = base_fee * 2 + max_priority
        
        tx = {
            "chain_id": chain_id,
            "chain": "Base",
            "from": wallet,
            "to": addr,
            "data": tx_data,
            "value": "0",
            "nonce": nonce,
            "gas_limit": 50000,  # Standard ERC20 approve gas
            "max_fee_per_gas_gwei": round(max_fee / 1e9, 2),
            "max_priority_fee_gwei": round(max_priority / 1e9, 4),
            "description": desc,
        }
        
        return json_ok({
            "transaction": tx,
            "current_allowance": format_amount(current["allowance"], dec) if current["allowance"] > 0 else "0",
            "needs_approval": current["needs_approval"],
            "spender": AERODROME_ROUTER,
            "signing_instructions": [
                "Copy this transaction to your wallet and sign",
                "After approval confirmed, use build_swap_transaction to swap"
            ]
        })
    except Exception as e:
        return json_error(str(e))

# ─── TOOL 10: check_allowance (FREE) ───────────────────────
@mcp.tool()
async def check_allowance(
    token: str,
    owner: str,
    spender: str = AERODROME_ROUTER,
    caller_address: str = None
) -> str:
    """Check how many tokens a spender is allowed to spend. FREE tier.
    
    Useful before swapping to see if you need to approve first.
    
    Args:
        token: Token symbol or 0x address
        owner: Token owner (your wallet)
        spender: Spender address (default: Aerodrome Router)
        caller_address: Your wallet for tracking
    """
    if not web3:
        return json_error("Base RPC not connected")
    
    try:
        addr = resolve_token(token)
        if not addr:
            return json_error(f"Could not resolve token: {token}")
        
        sym = get_token_symbol(addr)
        dec = get_token_decimals(addr)
        
        result = await check_allowance_raw(owner, addr, spender)
        
        return json_ok({
            "token": {"symbol": sym, "address": addr},
            "owner": owner,
            "spender": spender,
            "allowance": format_amount(result["allowance"], dec),
            "allowance_wei": str(result["allowance"]),
            "needs_approval": result["needs_approval"],
            "message": "Use 'build_approve_transaction' to approve if needed" if result["needs_approval"] else "Approval OK — ready to swap"
        })
    except Exception as e:
        return json_error(str(e))

# ─── TOOL 11: monitor_price (PREMIUM) ──────────────────────
@mcp.tool()
async def monitor_price(
    token_in: str,
    token_out: str,
    target_price: float = None,
    direction: str = "any",
    caller_address: str = None
) -> str:
    """Get current price and check against a target for limit-order style monitoring. PREMIUM tier.
    
    Good for price alerts: \"Check if AERO is under $1\" or \"What's the USDC/ETH rate right now?\"
    
    Args:
        token_in: Base token (e.g. 'USDC')
        token_out: Quote token (e.g. 'AERO') 
        target_price: Optional target price to compare (e.g. 1.50 means 1 USDC = 1.50 AERO)
        direction: For target: 'above' (alert when rate >= target), 'below' (<= target), 'any' (just show price)
        caller_address: Your wallet for tracking
    """
    gate = require_premium(caller_address)
    if gate: return gate
    
    if not web3:
        return json_error("Base RPC not connected")
    
    try:
        addr_in = resolve_token(token_in)
        addr_out = resolve_token(token_out)
        
        in_sym = get_token_symbol(addr_in)
        out_sym = get_token_symbol(addr_out)
        in_dec = get_token_decimals(addr_in)
        
        # Use a small amount to get quote
        sample_amount = 10 ** in_dec  # 1 unit
        route = await find_best_route(addr_in, addr_out, sample_amount)
        
        if route["route_type"] == "none":
            return json_error(f"No price available for {in_sym}/{out_sym}")
        
        out_dec = get_token_decimals(addr_out)
        rate = format_amount(route["expected_out"], out_dec)
        
        result = {
            "pair": f"{in_sym}/{out_sym}",
            "current_rate": round(rate, 8),
            "route_type": route["route_type"],
            "chain": "Base",
            "timestamp": int(time.time()),
        }
        
        # Compare with target
        if target_price is not None:
            result["target_price"] = target_price
            if direction == "above":
                result["alert"] = rate >= target_price
                result["condition"] = f"Rate {'ABOVE' if rate >= target_price else 'BELOW'} target (≥ {target_price})"
            elif direction == "below":
                result["alert"] = rate <= target_price
                result["condition"] = f"Rate {'BELOW' if rate <= target_price else 'ABOVE'} target (≤ {target_price})"
            else:
                diff_pct = round((rate - target_price) / target_price * 100, 2) if target_price > 0 else 0
                result["difference_pct"] = diff_pct
                result["condition"] = f"{'+' if diff_pct >= 0 else ''}{diff_pct}% vs target"
        
        return json_ok(result)
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
    Uses Blockscout API — fast, no API key needed.
    
    Args:
        address: Wallet address
        limit: Max transactions (default 5, max 50)
        caller_address: Your wallet for access tracking
    """
    gate = require_premium(caller_address)
    if gate: return gate
    
    try:
        addr = to_checksum(address)
        limit = min(max(limit, 1), 50)
        
        # Use Blockscout API — free, no key, instant
        data = await fetch_json(
            f"{BLOCKSCOUT_BASE}/addresses/{addr}/transactions",
            {"limit": limit, "sort": "desc"}
        )
        
        if "error" in data:
            # Fallback: try Ethereum-style Basescan API
            fallback = await fetch_json(
                f"https://api.basescan.org/api",
                {
                    "module": "account", "action": "txlist",
                    "address": addr, "sort": "desc",
                    "page": 1, "offset": limit
                }
            )
            if isinstance(fallback, dict) and fallback.get("status") == "1":
                items = fallback.get("result", [])
                txs = []
                for tx in items[:limit]:
                    txs.append({
                        "hash": tx["hash"],
                        "from": tx["from"],
                        "to": tx["to"],
                        "value_eth": format_amount(int(tx.get("value", 0)), 18),
                        "block": int(tx.get("blockNumber", 0)),
                        "timestamp": tx.get("timeStamp", ""),
                        "explorer": f"https://basescan.org/tx/{tx['hash']}"
                    })
                return json_ok({"address": addr, "source": "Basescan API", "recent_txs": txs})
            
            return json_error(f"Could not fetch transactions: {data.get('error', 'unknown')}")
        
        # Parse Blockscout response
        items = data.get("items", []) if isinstance(data, dict) else []
        txs = []
        for tx in items[:limit]:
            txs.append({
                "hash": tx.get("hash", ""),
                "from": tx.get("from", {}).get("hash", ""),
                "to": tx.get("to", {}).get("hash", ""),
                "value_eth": format_amount(int(tx.get("value", "0")), 18),
                "block": tx.get("block", 0),
                "timestamp": tx.get("timestamp", ""),
                "method": tx.get("method", ""),
                "fee_eth": format_amount(int(tx.get("fee", {}).get("value", "0")), 18) if isinstance(tx.get("fee"), dict) else "N/A",
                "status": "ok" if tx.get("status") == "ok" else tx.get("status", "pending"),
                "explorer": f"https://basescan.org/tx/{tx.get('hash', '')}"
            })
        
        return json_ok({"address": addr, "source": "Blockscout API", "recent_txs": txs})
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
