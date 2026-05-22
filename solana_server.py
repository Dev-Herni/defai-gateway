"""
DeFAI Gateway — Solana Chain Support
=====================================
Cross-chain MCP: Base + Solana in one server.

Architecture:
  AI Agent → MCP → DeFAI Gateway ──┬── Base RPC (EVM)
                                    └── Solana RPC (JSON-RPC, no solana-py dep)

Tools (prefixed with sol_ for Solana):
  sol_get_balance        — SOL + SPL token balances
  sol_get_token_info     — Token metadata (name, supply, decimals)
  sol_get_recent_txs     — Recent transaction history
  sol_get_gas_price      — Current Solana fee (lamports per sig)

Multi-Chain Detection:
  Address starts with "0x"  → Base chain
  Address is base58 (43-44 chars) → Solana chain
"""

import os, json, sys, time, hashlib, base58
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

SOLANA_RPC = os.getenv("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
SOLANA_RPC_FALLBACK = os.getenv("SOLANA_RPC_FALLBACK", "https://solana-api.projectserum.com")

# Token registry (well-known Solana tokens)
SOL_TOKENS = {
    "SOL": "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "RAY": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
    "SRM": "SRMuApVNdxXokk5GT7XD5cUUgXMBCoAz2LHeuAoKWRt",
    "JUP": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "PYTH": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
}

# ═══════════════════════════════════════════════════════════════
# HTTP CLIENT
# ═══════════════════════════════════════════════════════════════

import httpx

async def sol_rpc_call(method: str, params: list = None, retries: int = 2) -> dict:
    """Make a JSON-RPC call to Solana.
    
    Returns {"result": ...} on success, or {"error": ...} on failure.
    """
    if params is None:
        params = []
    
    payload = {
        "jsonrpc": "2.0",
        "id": int(time.time() * 1000) % 1000000,
        "method": method,
        "params": params,
    }
    
    last_error = None
    for rpc_url in [SOLANA_RPC, SOLANA_RPC_FALLBACK]:
        for attempt in range(retries + 1):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        rpc_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    if resp.status_code == 429:
                        await asyncio.sleep(1)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    
                    if "error" in data:
                        return {"error": data["error"].get("message", str(data["error"]))}
                    return {"result": data.get("result")}
            except Exception as e:
                last_error = str(e)
                if attempt < retries:
                    await asyncio.sleep(1)
    
    return {"error": f"All RPC endpoints failed: {last_error}"}


import asyncio

# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def is_solana_address(addr: str) -> bool:
    """Check if an address looks like a Solana address (base58, 32-44 chars)."""
    if not addr or addr.startswith("0x"):
        return False
    # Solana addresses are base58, 32-44 chars
    if len(addr) < 32 or len(addr) > 44:
        return False
    # Check it's valid base58
    try:
        base58.b58decode(addr)
        return True
    except:
        return False

def is_evm_address(addr: str) -> bool:
    """Check if an address looks like an EVM address (0x + 40 hex)."""
    return addr.startswith("0x") and len(addr) == 42

def detect_chain(address: str) -> str:
    """Auto-detect which chain an address belongs to."""
    if is_evm_address(address):
        return "base"
    if is_solana_address(address):
        return "solana"
    return "unknown"

def lamports_to_sol(lamports: int) -> float:
    """Convert lamports to SOL."""
    return lamports / 1_000_000_000

def format_token_amount(amount: int, decimals: int = 9) -> float:
    """Format token amount with decimals."""
    return amount / (10 ** decimals)

def sol_json_ok(data: dict) -> str:
    """Format Solana response with status."""
    data["_status"] = "ok"
    data["chain"] = "solana"
    return json.dumps(data, indent=2)

def sol_json_error(message: str, code: str = "error") -> str:
    return json.dumps({"_status": code, "error": message, "chain": "solana"}, indent=2)

# ═══════════════════════════════════════════════════════════════
# TOOL IMPLEMENTATIONS (callable from server.py)
# ═══════════════════════════════════════════════════════════════

async def sol_get_balance(address: str) -> str:
    """Get SOL and SPL token balances for a Solana wallet.
    
    Args:
        address: Solana wallet address (base58)
    """
    try:
        # 1. SOL balance
        sol_result = await sol_rpc_call("getBalance", [address])
        if "error" in sol_result:
            return sol_json_error(sol_result["error"])
        
        lamports = sol_result["result"].get("value", 0) if isinstance(sol_result.get("result"), dict) else 0
        sol_balance = lamports_to_sol(lamports)
        
        result = {
            "address": address,
            "balance_sol": round(sol_balance, 6),
            "balance_lamports": lamports,
        }
        
        # 2. SPL token balances
        tokens_result = await sol_rpc_call("getTokenAccountsByOwner", [
            address,
            {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
            {"encoding": "jsonParsed"},
        ])
        
        if "result" in tokens_result:
            token_accounts = []
            for account in tokens_result["result"].get("value", []):
                try:
                    parsed = account["account"]["data"]["parsed"]["info"]
                    mint = parsed.get("mint", "")
                    token_amount = parsed.get("tokenAmount", {})
                    balance = format_token_amount(
                        int(token_amount.get("amount", "0")),
                        token_amount.get("decimals", 0)
                    )
                    if balance > 0:
                        # Look up symbol from registry
                        symbol = "SPL"
                        for sym, addr in SOL_TOKENS.items():
                            if addr == mint:
                                symbol = sym
                                break
                        
                        token_accounts.append({
                            "mint": mint,
                            "symbol": symbol,
                            "balance": round(balance, 6),
                            "decimals": token_amount.get("decimals", 0),
                        })
                except:
                    continue
            
            result["tokens"] = token_accounts
        
        # 3. USD estimate
        try:
            from server import fetch_json
            # Use Jupiter API for SOL price
            price_data = await fetch_json(
                "https://api.coingecko.com/api/v3/simple/price",
                {"ids": "solana", "vs_currencies": "usd"}
            )
            sol_usd = price_data.get("solana", {}).get("usd", 0)
            if sol_usd:
                result["total_usd_estimate"] = round(sol_balance * sol_usd, 2)
        except:
            result["total_usd_estimate"] = "N/A"
        
        return sol_json_ok(result)
    
    except Exception as e:
        return sol_json_error(str(e))


async def sol_get_token_info(mint_address: str) -> str:
    """Get token metadata for a Solana SPL token.
    
    Args:
        mint_address: SPL token mint address (base58)
    """
    try:
        # Get token supply
        supply_result = await sol_rpc_call("getTokenSupply", [mint_address])
        if "error" in supply_result:
            return sol_json_error(supply_result["error"])
        
        supply_info = supply_result.get("result", {}).get("value", {})
        supply = supply_info.get("amount", "0")
        decimals = supply_info.get("decimals", 0)
        
        # Get token metadata (name/symbol from registry)
        symbol = "SPL"
        name = "Unknown"
        for sym, addr in SOL_TOKENS.items():
            if addr == mint_address:
                symbol = sym
                name = sym
                break
        
        return sol_json_ok({
            "mint": mint_address,
            "name": name,
            "symbol": symbol,
            "decimals": decimals,
            "total_supply": format_token_amount(int(supply), decimals) if supply.isdigit() else supply,
            "explorer": f"https://solscan.io/token/{mint_address}",
        })
    
    except Exception as e:
        return sol_json_error(str(e))


async def sol_get_recent_txs(address: str, limit: int = 5) -> str:
    """Get recent transactions for a Solana wallet.
    
    Args:
        address: Solana wallet address
        limit: Max transactions (default 5, max 25)
    """
    try:
        limit = min(max(limit, 1), 25)
        
        result = await sol_rpc_call("getSignaturesForAddress", [
            address,
            {"limit": limit}
        ])
        
        if "error" in result:
            return sol_json_error(result["error"])
        
        sigs = result.get("result", [])
        txs = []
        for sig in sigs:
            txs.append({
                "signature": sig.get("signature", ""),
                "slot": sig.get("slot", 0),
                "block_time": sig.get("blockTime", 0),
                "confirmation_status": sig.get("confirmationStatus", "unknown"),
                "explorer": f"https://solscan.io/tx/{sig.get('signature', '')}",
            })
        
        return sol_json_ok({
            "address": address,
            "recent_transactions": txs,
            "count": len(txs),
        })
    
    except Exception as e:
        return sol_json_error(str(e))


async def sol_get_gas_price() -> str:
    """Get current Solana fee (lamports per signature)."""
    try:
        # Get recent blockhash (includes fee)
        result = await sol_rpc_call("getRecentBlockhash")
        if "error" in result:
            return sol_json_error(result["error"])
        
        fee_calculator = result["result"].get("value", {}).get("feeCalculator", {})
        lamports_per_sig = fee_calculator.get("lamportsPerSignature", 5000)
        
        return sol_json_ok({
            "lamports_per_signature": lamports_per_sig,
            "sol_per_signature": round(lamports_to_sol(lamports_per_sig), 10),
            "estimated_tx_cost_sol": round(lamports_to_sol(lamports_per_sig), 10),  # Simple tx = 1 sig
            "estimated_tx_cost_usd": "Check with get_token_price SOL for USD estimate",
        })
    
    except Exception as e:
        return sol_json_error(str(e))


async def sol_analyze_wallet(address: str) -> str:
    """Full Solana wallet analysis.
    
    Args:
        address: Solana wallet address
    """
    if not is_solana_address(address):
        return sol_json_error("Invalid Solana address format")
    
    # Gather all data in parallel
    balance_task = sol_get_balance(address)
    txs_task = sol_get_recent_txs(address, 5)
    
    balance_result = await balance_task
    txs_result = await txs_task
    
    balance_data = json.loads(balance_result)
    txs_data = json.loads(txs_result)
    
    return sol_json_ok({
        "address": address,
        "balance": balance_data.get("balance_sol", "N/A"),
        "balance_lamports": balance_data.get("balance_lamports", 0),
        "tokens": balance_data.get("tokens", []),
        "total_usd_estimate": balance_data.get("total_usd_estimate", "N/A"),
        "recent_txs": txs_data.get("recent_transactions", []),
        "explorer": f"https://solscan.io/account/{address}",
    })
