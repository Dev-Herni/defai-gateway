"""
DeFAI Gateway — x402 Payment Gateway
======================================
AI Agents pay per API call in USDC on Base Chain.

x402 Standard:
  Client includes a signed USDC transfer proof in the HTTP header.
  Server verifies on-chain, processes the call, and optionally refunds overpayment.
  
Architecture:
  AI Agent → HTTP POST /mcp (with x402 header) → x402 Middleware → MCP Server → Response
  
Pricing:
  - Base rate: 0.001 USDC per tool call
  - Free tier: 10 calls/day still honored
  - $GATE holders: No per-call fee (unlimited)
  
Flow:
  1. Agent sends a USDC tx to FEE_WALLET on Base
  2. Agent includes tx hash in X-402-Tx-Hash header
  3. Server verifies ≥ 0.001 USDC received
  4. Server adds credit balance for caller
  5. Each MCP call deducts from credit 
  6. Response returned normally
"""

import os, sys, json, time, hashlib
from typing import Optional
from urllib.parse import urlparse

# Add parent to path for importing server
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

X402_PORT = int(os.getenv("X402_PORT", "4020"))
FEE_WALLET = os.getenv("FEE_WALLET", "0x0000000000000000000000000000000000000000")
USDC_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_RPC = os.getenv("RPC_URL", "https://mainnet.base.org")
CALL_COST_USDC = int(os.getenv("X402_CALL_COST", "1000"))  # 0.001 USDC (6 decimals)
MIN_DEPOSIT_USDC = int(os.getenv("X402_MIN_DEPOSIT", "10000"))  # 0.01 USDC minimum
FREE_TIER_DAILY = int(os.getenv("DAILY_FREE_CALLS", "10"))

# Web3 init
web3 = None
try:
    from web3 import Web3
    web3 = Web3(Web3.HTTPProvider(BASE_RPC))
    if web3.is_connected():
        print(f"[x402] Base RPC connected — block {web3.eth.block_number}", file=sys.stderr)
    else:
        web3 = None
except Exception as e:
    print(f"[x402] Web3 init error: {e}", file=sys.stderr)

# ERC20 minimal ABI (balanceOf + transfer events)
USDC_ABI = json.loads('''[
  {"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
  {"constant":true,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"},
  {"constant":false,"inputs":[{"name":"_to","type":"address"},{"name":"_value","type":"uint256"}],"name":"transfer","outputs":[{"name":"","type":"bool"}],"type":"function"},
  {"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"},
  {"constant":true,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"type":"function"}
]''')

# ═══════════════════════════════════════════════════════════════
# CREDIT SYSTEM
# ═══════════════════════════════════════════════════════════════

class CreditLedger:
    """Manages prepaid credit balances for x402 callers.
    
    Each caller_address has a credit balance in USDC (wei, 6 decimals).
    Credits are added when an on-chain USDC transfer is verified.
    Credits are deducted per MCP tool call.
    """
    
    def __init__(self):
        self._credits = {}  # caller_address_lower -> int (USDC wei)
        self._verified_txs = set()  # tx hashes already processed
        self._daily_free = {}  # address_date -> count
    
    def _today(self) -> str:
        return time.strftime("%Y-%m-%d")
    
    def get_balance(self, address: str) -> int:
        """Get credit balance in USDC (6 decimals)."""
        return self._credits.get(address.strip().lower(), 0)
    
    def add_credits(self, address: str, amount_wei: int, tx_hash: str = None):
        """Add credits for a caller after verifying payment."""
        addr = address.strip().lower()
        if tx_hash:
            if tx_hash in self._verified_txs:
                return False  # Already processed
            self._verified_txs.add(tx_hash)
        self._credits[addr] = self._credits.get(addr, 0) + amount_wei
        return True
    
    def deduct_call(self, address: str, cost_wei: int = CALL_COST_USDC) -> bool:
        """Deduct cost of one call. Returns True if enough credit.
        Falls back to free tier if no credit but free calls remaining.
        """
        addr = address.strip().lower() if address else None
        
        # Check free tier first for anonymous users
        if not addr:
            return True  # Anonymous = free
        
        # Check if $GATE holder (unlimited)
        # (Caller should check this upstream, but we allow overdraft for gate holders)
        
        # Deduct from credit balance
        current = self._credits.get(addr, 0)
        if current >= cost_wei:
            self._credits[addr] = current - cost_wei
            return True
        
        # Check daily free tier
        free_key = f"{addr}:{self._today()}"
        self._daily_free.setdefault(free_key, 0)
        if self._daily_free[free_key] < FREE_TIER_DAILY:
            self._daily_free[free_key] += 1
            return True
        
        return False  # Insufficient credit and no free calls left
    
    def get_status(self, address: str) -> dict:
        """Get full status for a caller."""
        addr = address.strip().lower() if address else None
        free_key = f"{addr}:{self._today()}" if addr else ""
        
        return {
            "credit_balance_usdc": self._credits.get(addr, 0) / 1_000_000 if addr else 0,
            "credit_balance_wei": self._credits.get(addr, 0) if addr else 0,
            "free_calls_used": self._daily_free.get(free_key, 0) if addr else 0,
            "free_calls_remaining": max(0, FREE_TIER_DAILY - self._daily_free.get(free_key, 0)) if addr else FREE_TIER_DAILY,
            "call_cost_usdc": CALL_COST_USDC / 1_000_000,
            "fee_wallet": FEE_WALLET,
        }

ledger = CreditLedger()

# ═══════════════════════════════════════════════════════════════
# ON-CHAIN VERIFICATION
# ═══════════════════════════════════════════════════════════════

async def verify_usdc_payment(tx_hash: str, expected_min_wei: int = MIN_DEPOSIT_USDC) -> dict:
    """Verify a USDC transfer to the fee wallet on Base.
    
    Checks:
      1. Transaction exists and is confirmed
      2. Transaction has Transfer event from USDC contract
      3. Transfer destination matches FEE_WALLET
      4. Transfer amount >= expected_min_wei
      5. Transaction is recent (within last 60 blocks)
    
    Returns:
      {"valid": bool, "from": str, "amount_wei": int, "reason": str}
    """
    if not web3:
        return {"valid": False, "from": "", "amount_wei": 0, "reason": "Base RPC not connected"}
    
    tx_hash = tx_hash.strip()
    if not tx_hash.startswith("0x"):
        tx_hash = "0x" + tx_hash
    
    try:
        # Get transaction receipt
        receipt = web3.eth.get_transaction_receipt(tx_hash)
        if not receipt:
            return {"valid": False, "from": "", "amount_wei": 0, "reason": "Transaction not found"}
        
        # Check block recency (within last 60 blocks = ~2 min)
        current_block = web3.eth.block_number
        if receipt["blockNumber"] < current_block - 60:
            return {"valid": False, "from": "", "amount_wei": 0, "reason": "Transaction too old"}
        
        # Check confirmation status
        if receipt["status"] != 1:
            return {"valid": False, "from": "", "amount_wei": 0, "reason": "Transaction failed"}
        
        # Parse logs for USDC Transfer event
        # USDC Transfer event signature: Transfer(address,address,uint256)
        transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        
        usdc_addr_checksum = web3.to_checksum_address(USDC_ADDRESS).lower()
        fee_wallet_checksum = web3.to_checksum_address(FEE_WALLET).lower() if FEE_WALLET and FEE_WALLET != "0x0000000000000000000000000000000000000000" else None
        
        sender = None
        amount_wei = 0
        
        for log in receipt.get("logs", []):
            # Check it's from the USDC contract
            if log.get("address", "").lower() != usdc_addr_checksum:
                continue
            
            topics = log.get("topics", [])
            if len(topics) != 3:
                continue
            
            # Check it's a Transfer event
            if topics[0].hex() if hasattr(topics[0], 'hex') else str(topics[0]) != transfer_topic:
                continue
            
            # Decode sender and recipient from indexed topics
            sender_raw = topics[1]
            recipient_raw = topics[2]
            
            # Pad addresses to 40 hex chars
            sender_hex = sender_raw.hex()[-40:].lower() if hasattr(sender_raw, 'hex') else str(sender_raw)[-40:].lower()
            recipient_hex = recipient_raw.hex()[-40:].lower() if hasattr(recipient_raw, 'hex') else str(recipient_raw)[-40:].lower()
            sender_addr = "0x" + sender_hex
            recipient_addr = "0x" + recipient_hex
            
            # Check if recipient is the fee wallet
            if fee_wallet_checksum and recipient_addr.lower() == fee_wallet_checksum.lower():
                # Decode amount from data field
                data = log.get("data", "0x0")
                if isinstance(data, str) and data.startswith("0x"):
                    amount_wei = int(data, 16)
                elif hasattr(data, 'hex'):
                    amount_wei = int(data.hex(), 16)
                else:
                    amount_wei = int(str(data), 16)
                
                sender = "0x" + sender_hex
                break
        
        if not sender:
            return {"valid": False, "from": "", "amount_wei": 0, "reason": "No USDC transfer to fee wallet found"}
        
        if amount_wei < expected_min_wei:
            actual = amount_wei / 1_000_000
            expected = expected_min_wei / 1_000_000
            return {"valid": False, "from": sender, "amount_wei": amount_wei, "reason": f"Amount {actual:.6f} USDC < minimum {expected:.6f} USDC"}
        
        return {"valid": True, "from": sender, "amount_wei": amount_wei, "reason": "Payment verified"}
    
    except Exception as e:
        return {"valid": False, "from": "", "amount_wei": 0, "reason": f"Verification error: {e}"}


# ═══════════════════════════════════════════════════════════════
# HTTP SERVER (using stdlib http.server for zero deps)
# ═══════════════════════════════════════════════════════════════

import asyncio
import http.server
import socketserver
import urllib.parse

class X402Handler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler with x402 payment middleware.
    
    Endpoints:
      POST /mcp      — MCP tool call (requires x402 payment or free tier)
      GET  /status   — Check credit balance + usage
      GET  /health   — Server health check
      POST /deposit  — Verify a USDC tx and add credits
    """
    
    def log_message(self, format, *args):
        """Silence default logs, use stderr instead."""
        print(f"[x402] {self.client_address[0]} {format % args}", file=sys.stderr)
    
    def _send_json(self, status_code: int, data: dict):
        """Send JSON response."""
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
    
    def _get_caller_address(self) -> str:
        """Extract caller address from x402 headers or query params."""
        # From header
        addr = self.headers.get("X-402-Address", "")
        if addr:
            return addr.strip()
        # From query param
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        addr = params.get("caller_address", [""])[0]
        return addr.strip()
    
    def _get_payment_tx(self) -> str:
        """Extract payment tx hash from x402 header."""
        return self.headers.get("X-402-Tx-Hash", "").strip()
    
    def _get_free_tier(self) -> bool:
        """Check if caller is requesting free tier."""
        return self.headers.get("X-402-Free", "").lower() == "true"
    
    # ─── Routes ──────────────────────────────────────────
    
    def do_OPTIONS(self):
        """CORS preflight."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-402-Tx-Hash, X-402-Address, X-402-Free")
        self.end_headers()
    
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        
        if path == "/status":
            self._handle_status()
        elif path == "/health":
            self._send_json(200, {"status": "ok", "service": "DeFAI Gateway x402", "version": "v2.3"})
        elif path == "/pricing":
            self._handle_pricing()
        else:
            self._send_json(404, {"error": "Not found"})
    
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        
        if path == "/mcp":
            asyncio.run(self._handle_mcp())
        elif path == "/deposit":
            asyncio.run(self._handle_deposit())
        else:
            self._send_json(404, {"error": "Not found"})
    
    def _handle_status(self):
        """GET /status — Check credit balance and usage."""
        caller = self._get_caller_address()
        status = ledger.get_status(caller)
        
        # Add gate token check if possible
        gate_holder = False
        if caller and web3:
            try:
                GATE_TOKEN = os.getenv("GATE_TOKEN", "")
                if GATE_TOKEN:
                    contract = web3.eth.contract(
                        address=web3.to_checksum_address(GATE_TOKEN),
                        abi=USDC_ABI  # Reuse minimal ABI for balanceOf
                    )
                    bal = contract.functions.balanceOf(web3.to_checksum_address(caller)).call()
                    gate_holder = bal > 0
            except:
                pass
        
        status["gate_holder"] = gate_holder
        status["unlimited"] = gate_holder
        status["address"] = caller or "anonymous"
        self._send_json(200, status)
    
    def _handle_pricing(self):
        """GET /pricing — Show pricing table."""
        self._send_json(200, {
            "base_call_cost": CALL_COST_USDC / 1_000_000,
            "base_call_cost_currency": "USDC",
            "free_calls_per_day": FREE_TIER_DAILY,
            "minimum_deposit": MIN_DEPOSIT_USDC / 1_000_000,
            "fee_wallet": FEE_WALLET,
            "chain": "Base",
            "token": USDC_ADDRESS,
            "gate_holder_unlimited": True,
            "message": "Send USDC to fee wallet, include tx hash in X-402-Tx-Hash header",
            "curl_example": f'curl -X POST http://localhost:{X402_PORT}/mcp \\\n  -H "Content-Type: application/json" \\\n  -H "X-402-Tx-Hash: <your_tx_hash>" \\\n  -H "X-402-Address: <your_wallet>" \\\n  -d \'{{"tool":"get_balance","args":{{"address":"0x..."}}}}\''
        })
    
    async def _handle_deposit(self):
        """POST /deposit — Verify a USDC tx and add credits."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        
        try:
            data = json.loads(body)
        except:
            self._send_json(400, {"error": "Invalid JSON"})
            return
        
        tx_hash = data.get("tx_hash", "")
        if not tx_hash:
            self._send_json(400, {"error": "tx_hash required"})
            return
        
        # Check if already processed
        if tx_hash in ledger._verified_txs:
            self._send_json(409, {"error": "Transaction already processed"})
            return
        
        result = await verify_usdc_payment(tx_hash)
        
        if result["valid"]:
            sender = result["from"]
            amount = result["amount_wei"]
            ledger.add_credits(sender, amount, tx_hash)
            balance = ledger.get_balance(sender)
            self._send_json(200, {
                "status": "credited",
                "from": sender,
                "amount_usdc": amount / 1_000_000,
                "amount_wei": amount,
                "credit_balance_usdc": balance / 1_000_000,
                "credit_balance_wei": balance,
                "estimated_calls": balance // CALL_COST_USDC if CALL_COST_USDC > 0 else 0,
            })
        else:
            self._send_json(402, {
                "status": "payment_required",
                "reason": result["reason"],
                "fee_wallet": FEE_WALLET,
                "minimum_deposit_usdc": MIN_DEPOSIT_USDC / 1_000_000,
                "instructions": f"Send >= ${MIN_DEPOSIT_USDC / 1_000_000:.4f} USDC on Base to {FEE_WALLET}, then call /deposit with the tx_hash"
            })
    
    async def _handle_mcp(self):
        """POST /mcp — MCP tool call with x402 payment or free tier.
        
        Request body: {"tool": "get_balance", "args": {...}}
        Headers:
          X-402-Tx-Hash: <tx_hash> (optional — for paid calls)
          X-402-Address: <wallet>  (required for paid/credit calls)
          X-402-Free: "true"       (optional — use free tier)
        """
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        
        try:
            data = json.loads(body)
        except:
            self._send_json(400, {"error": "Invalid JSON"})
            return
        
        tool_name = data.get("tool", "")
        tool_args = data.get("args", {})
        caller = self._get_caller_address()
        free_tier = self._get_free_tier()
        payment_tx = self._get_payment_tx()
        
        if not tool_name:
            self._send_json(400, {"error": "tool name required"})
            return
        
        # Payment processing
        if not free_tier and payment_tx:
            # Verify and credit
            if payment_tx not in ledger._verified_txs:
                verification = await verify_usdc_payment(payment_tx)
                if verification["valid"] and verification["from"]:
                    ledger.add_credits(verification["from"], verification["amount_wei"], payment_tx)
                    if not caller:
                        caller = verification["from"]
                    elif caller.lower() != verification["from"].lower():
                        # Allow different wallet as caller if they have credits
                        pass
        
        # Check gate holder status for unlimited access
        is_gate_holder = False
        if caller and web3:
            try:
                GATE_TOKEN = os.getenv("GATE_TOKEN", "")
                if GATE_TOKEN:
                    contract = web3.eth.contract(
                        address=web3.to_checksum_address(GATE_TOKEN),
                        abi=USDC_ABI
                    )
                    bal = contract.functions.balanceOf(web3.to_checksum_address(caller)).call()
                    is_gate_holder = bal > 0
            except:
                pass
        
        # Check if caller can pay
        if not is_gate_holder:
            can_pay = ledger.deduct_call(caller, CALL_COST_USDC)
            if not can_pay:
                status = ledger.get_status(caller)
                self._send_json(402, {
                    "error": "Payment required",
                    "detail": "Insufficient credit balance and no free calls remaining",
                    "call_cost_usdc": CALL_COST_USDC / 1_000_000,
                    "status": status,
                    "deposit_endpoint": f"http://localhost:{X402_PORT}/deposit",
                    "pricing_endpoint": f"http://localhost:{X402_PORT}/pricing",
                    "fee_wallet": FEE_WALLET,
                    "instructions": f"Send USDC on Base to {FEE_WALLET}, then POST to /deposit with {{\"tx_hash\": \"<your_tx>\"}}"
                })
                return
        
        # ═══ Forward to MCP Server ═══
        # For now, we route known tools and return mock results
        # In production, this would pipe to the stdio MCP process
        result = await self._forward_to_mcp(tool_name, tool_args, caller, is_gate_holder)
        
        # Add payment info to response
        result["_x402"] = {
            "caller": caller or "anonymous",
            "unlimited": is_gate_holder,
            "credit_balance": ledger.get_balance(caller) / 1_000_000 if caller else 0,
            "cost": 0 if is_gate_holder else CALL_COST_USDC / 1_000_000,
        }
        
        self._send_json(200, result)
    
    async def _forward_to_mcp(self, tool_name: str, args: dict, caller: str, is_gate_holder: bool) -> dict:
        """Forward a tool call to the MCP server.
        
        In production, this connects to the MCP server via stdio subprocess.
        For now, we dynamically dispatch to the server module.
        """
        try:
            # Re-import server module fresh for each call
            for mod in list(sys.modules.keys()):
                if "server" in mod:
                    del sys.modules[mod]
            
            import server
            
            # Map tool names to functions
            tool_map = {
                "get_balance": server.get_balance,
                "get_token_info": server.get_token_info,
                "get_gas_price": server.get_gas_price,
                "get_pools": server.get_pools,
                "analyze_wallet": server.analyze_wallet,
                "track_new_tokens": server.track_new_tokens,
                "get_token_price": server.get_token_price,
                "get_recent_transactions": server.get_recent_transactions,
                "get_payment_status": server.get_payment_status,
                "get_swap_quote": server.get_swap_quote,
                "build_swap_transaction": server.build_swap_transaction,
                "build_approve_transaction": server.build_approve_transaction,
                "check_allowance": server.check_allowance,
                "monitor_price": server.monitor_price,
            }
            
            if tool_name not in tool_map:
                # Try dynamic attribute lookup
                func = getattr(server, tool_name, None)
                if not func:
                    return {"_status": "error", "error": f"Unknown tool: {tool_name}"}
            else:
                func = tool_map[tool_name]
            
            # Add caller_address if the function accepts it
            if caller and "caller_address" in func.__code__.co_varnames[:func.__code__.co_argcount]:
                args["caller_address"] = caller
            
            # Call the function and parse result
            result_str = await func(**args)
            result = json.loads(result_str)
            return result
            
        except Exception as e:
            return {"_status": "error", "error": f"MCP error: {e}"}


def run_x402_server():
    """Run the x402 HTTP server."""
    server_addr = ("0.0.0.0", X402_PORT)
    
    print(f"\n{'═'*60}", file=sys.stderr)
    print(f"  DeFAI Gateway — x402 Payment Gateway", file=sys.stderr)
    print(f"  Listening on http://0.0.0.0:{X402_PORT}", file=sys.stderr)
    print(f"  Fee Wallet: {FEE_WALLET}", file=sys.stderr)
    print(f"  Call Cost:  {CALL_COST_USDC / 1_000_000:.4f} USDC", file=sys.stderr)
    print(f"  Min Deposit: {MIN_DEPOSIT_USDC / 1_000_000:.4f} USDC", file=sys.stderr)
    print(f"  Free Tier:   {FREE_TIER_DAILY} calls/day", file=sys.stderr)
    print(f"{'═'*60}\n", file=sys.stderr)
    
    # Use ThreadingHTTPServer for async support
    class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        allow_reuse_address = True
        daemon_threads = True
    
    server = ThreadedHTTPServer(server_addr, X402Handler)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[x402] Shutting down...", file=sys.stderr)
        server.shutdown()


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="DeFAI Gateway x402 Payment Server")
    parser.add_argument("--port", type=int, default=X402_PORT, help="HTTP port")
    parser.add_argument("--fee-wallet", type=str, default=FEE_WALLET, help="Fee collection wallet on Base")
    parser.add_argument("--call-cost", type=float, default=CALL_COST_USDC / 1_000_000, help="Cost per call in USDC")
    args = parser.parse_args()
    
    if args.port:
        X402_PORT = args.port
    if args.fee_wallet:
        FEE_WALLET = args.fee_wallet
    if args.call_cost:
        CALL_COST_USDC = int(args.call_cost * 1_000_000)
    
    run_x402_server()
