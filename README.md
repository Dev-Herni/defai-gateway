# DeFAI Gateway MCP Server 🤖⛓️

**The first production-ready MCP server connecting AI Agents to Base Chain DeFi.**

[![MCP](https://img.shields.io/badge/MCP-Server-00D4FF)](https://modelcontextprotocol.io)
[![Base](https://img.shields.io/badge/Chain-Base-0052FF)](https://base.org)
[![CI](https://github.com/Dev-Herni/defai-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/Dev-Herni/defai-gateway/actions)
[![License](https://img.shields.io/badge/License-MIT-4ADE80)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-FFD43B)](https://python.org)

---

## 🌟 What is DeFAI Gateway?

DeFAI Gateway gives any AI agent **full read + limited execute access to Base Chain DeFi**. 
Check balances, analyze wallets, track liquidity pools, discover new tokens, and prepare swaps — all through natural language.

**Why build this?** AI agents are the new UI. Every DeFi protocol will be accessed through agents.
DeFAI Gateway is the infrastructure layer that makes it possible.

---

## 🔌 Quick Start

```bash
pip install -r requirements.txt
python server.py
```

**1 line. That's it.** Your AI agent now has access to Base Chain.

---

## 🛠️ Tools (21 Total) + x402 Payment Gateway + WebSocket Tracking + Solana

| # | Tool | Description | Tier | Chain |
|---|------|-------------|------|-------|
| 1 | `get_balance` | ETH + ERC-20 token balances | 🆓 Free | Base |
| 2 | `get_token_info` | Token name, symbol, decimals, supply | 🆓 Free | Base |
| 3 | `get_gas_price` | Live Base gas in gwei | 🆓 Free | Base |
| 4 | `get_pools` | Top Aerodrome liquidity pools (3 data sources) | ⭐ Premium | Base |
| 5 | `analyze_wallet` | Full wallet breakdown + portfolio | ⭐ Premium | Base |
| 6 | `track_new_tokens` | Scan for new token deployments (3-tier fallback) | ⭐ Premium | Base |
| 7 | `get_swap_quote` | Live swap quote with price impact + route info | 🔒 $GATE | Base |
| 8 | `build_swap_transaction` | Full EIP-1559 swap tx (nonce, gas, chainId) | 🔒 $GATE | Base |
| 9 | `build_approve_transaction` | Token approval tx for Aerodrome Router | 🆓 Free | Base |
| 10 | `check_allowance` | Check current allowance before swapping | 🆓 Free | Base |
| 11 | `monitor_price` | Price check + target comparison (limit-order style) | ⭐ Premium | Base |
| 12 | `get_token_price` | Live price in USD (CoinGecko) | ⭐ Premium | Base |
| 13 | `get_recent_transactions` | Recent wallet activity (Blockscout) | ⭐ Premium | Base |
| 14 | `get_payment_status` | Your tier + remaining free calls | ⭐ Premium | Base |
| 15 | `subscribe` | Subscribe to real-time WebSocket streams | ⭐ Premium | Base |
| 16 | `get_ws_info` | WebSocket connection info + active channels | 🆓 Free | Base |
| 17 | `sol_get_balance` | SOL + SPL token balances for Solana wallets | 🆓 Free | Solana |
| 18 | `sol_get_token_info` | Solana SPL token metadata (supply, decimals) | 🆓 Free | Solana |
| 19 | `sol_get_recent_txs` | Recent transaction history on Solana | 🆓 Free | Solana |
| 20 | `sol_get_gas_price` | Current Solana fee (lamports per signature) | 🆓 Free | Solana |
| 21 | `sol_analyze_wallet` | Full Solana wallet analysis + portfolio | ⭐ Premium | Solana |

---

## 💰 x402 Payment Gateway (New in v2.3)

**AI Agents pay per API call in USDC on Base Chain.**

The x402 standard lets AI agents make HTTP calls with embedded USDC micropayments.

### How it works

```
1. Agent sends USDC to FEE_WALLET on Base
2. Agent calls POST /deposit with tx_hash
3. Server verifies on-chain → adds credit balance
4. Agent calls POST /mcp with tool + args
5. Server deducts ~$0.001 per call from credit
6. Response returned normally
```

### Start the x402 server

```bash
python x402_server.py --port 4020 --fee-wallet 0xYourWallet
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/mcp` | POST | Call any MCP tool (requires x402 header or credit) |
| `/deposit` | POST | Verify USDC tx and add credits |
| `/status` | GET | Check credit balance and usage |
| `/pricing` | GET | Get pricing table + curl example |
| `/health` | GET | Server health check |

### Pricing

| Feature | Cost |
|---------|------|
| Free tier | 10 calls/day (no payment needed) |
| Per call | ~$0.001 USDC |
| Minimum deposit | $0.01 USDC |
| $GATE holders | Unlimited (no per-call fee) |

---

## 🏗️ Architecture

```
AI Agent ──┬── MCP (stdio) ──→ DeFAI Gateway ──┬── Base RPC (on-chain)
           │          21 Tools (Base + Solana)  ├── Solana RPC (JSON-RPC)
           │                                    ├── Blockscout API (transactions)
           │                                    ├── Aerodrome API (pools)
           │                                    ├── CoinGecko API (prices)
           │                                    ├── Jupiter API (Solana prices)
           │                                    └── Clanker API (new tokens)
           │
           ├── HTTP (x402) ──→ x402 Payment Gateway ──┬── USDC verification (on-chain)
           │                                           ├── Credit ledger
           │                                           ├── /mcp (forward to MCP)
           │                                           ├── /deposit (add credits)
           │                                           ├── /status (check balance)
           │                                           └── /pricing (per-call costs)
           │
           └── WebSocket ──→ Real-Time Tracking ──┬── Pools (30s)
                                                   ├── Wallet (15s)
                                                   └── Tokens (60s)
```

**Key design decisions:**
- **Read-only by default** — no private keys needed for 9/10 tools
- **Stateless** — no database, no storage, no user data
- **Payment gating** built-in — free tier, premium, token-gated
- **Layered API fallbacks** — always returns data even if upstream APIs fail

---

## 📡 WebSocket Real-Time Tracking (New in v2.4)

**Live streaming of pools, wallets, and tokens via WebSocket.**

No polling needed — subscribe to a channel and receive push updates.

### Quick Start

```bash
# Terminal 1: Start WebSocket server
python ws_server.py --port 4021

# Terminal 2: Connect with any WebSocket client
python -c "
import asyncio, websockets
async def main():
    async with websockets.connect('ws://localhost:4021') as ws:
        await ws.send('{\"subscribe\": \"pools\"}')
        async for msg in ws:
            print(msg)
asyncio.run(main())
"
```

### Channels

| Channel | Data | Interval | Example |
|---------|------|----------|---------|
| `pools` | Aerodrome pool TVL/APR changes | 30s | `{"subscribe": "pools"}` |
| `wallet:0x...` | New wallet transactions | 15s | `{"subscribe": "wallet:0xYourAddress"}` |
| `tokens` | New token deployments | 60s | `{"subscribe": "tokens"}` |

### Protocol

All messages are JSON. Server pushes updates with timestamp and change deltas.

```json
// Server → Client update
{"channel": "pools", "type": "pool_update", "data": [...], "timestamp": 1712345678}

// Change detection (only pushes when TVL/APR changes)
{"channel": "pools", "type": "pool_update", "data": [{
  "name": "AERO/WETH", "tvl_usd": 48200000, "apr": 14.8,
  "change": {"tvl_delta": 250000, "apr_delta": 0.3}
}]}
```

### Run modes

```bash
# Standalone
python ws_server.py --port 4021

# Via server.py
python server.py --ws
```

---

## 🌐 Solana Cross-Chain Support (New in v2.5)

**One server. Two chains. Auto-detect.** DeFAI Gateway now routes to **Base** or **Solana** based on the address format.

| Input | Detected Chain |
|-------|---------------|
| `0x...` (42 hex chars) | **Base** (EVM) |
| `base58...` (32-44 chars) | **Solana** |

### Solana Tools

| Tool | What it does |
|------|-------------|
| `sol_get_balance` | SOL balance + all SPL token balances |
| `sol_get_token_info` | Token metadata (name, supply, decimals) |
| `sol_get_recent_txs` | Recent transaction history with Solscan links |
| `sol_get_gas_price` | Current fee in lamports per signature |
| `sol_analyze_wallet` | Full portfolio: balance + tokens + recent txs |

### Supported Tokens

SOL, USDC, USDT, RAY, SRM, JUP, BONK, PYTH, WIF + any SPL token by mint address.

### Architecture

```text
AI Agent → MCP ──→ DeFAI Gateway ──┬── Base RPC (EVM)
                                    ├── Solana RPC (JSON-RPC)
                                    ├── Jupiter API (prices)
                                    └── Auto-Detect: 0x→Base, base58→Solana
```

## 🔄 Swap Flow (AI Agent Example)

A complete swap from USDC → AERO:

```
1. check_allowance("USDC", "0xYourWallet") 
   → Needs approval? Yes → 
   
2. build_approve_transaction("USDC", caller_address="0xYourWallet")
   → Sign tx in wallet → Wait for confirmation →
   
3. get_swap_quote("USDC", "AERO", 100, caller_address="0xYourWallet")
   → Expected: 850.5 AERO, Route: direct, Price Impact: 0.02%
   
4. build_swap_transaction("USDC", "AERO", 100, slippage=0.5, caller_address="0xYourWallet")
   → Full EIP-1559 tx with nonce, gas, chainId → Sign + send in wallet
```

**AI agents execute this autonomously:** The agent builds the tx, the user signs with their wallet, the agent tracks the result.

## 💰 Pricing

| Tier | Operations | Price | What you get |
|------|-----------|-------|-------------|
| **Free** | 1,000/mo | **$0** | Balances, tokens, gas prices |
| **Pro** | 10,000/mo | **$19.99/mo** | All tools + analytics + tracking |
| **Enterprise** | Unlimited | **$99/mo** | Dedicated RPC, custom integrations |

Or **hold $GATE** for unlimited access + swap execution + revenue share.

💳 Pay with SOL, ETH (Base), USDC, or credit card.

---

## 🔐 Security

- **Server NEVER touches your private key** — all swap data is unsigned
- **Open source** — 100% auditable, ~800 lines
- **No data stored** — queries go directly to public RPC + APIs
- **Rate limited** to prevent abuse

---

## 🗺️ Roadmap

### ✅ v1 (launched)
- 6 core tools: balances, tokens, gas, pools, analytics, tracking
- Payment gating (free/premium/$GATE)

### ✅ v2 (current)
- 10 tools: + token price, recent txs, payment status, swap prep
- Blockscout integration (no API key needed)
- Aerodrome v2 API fallback
- Retry logic + structured error handling
- CI/CD with GitHub Actions
- Tests (20 test cases)
- Docker multi-stage build
- Smithery.yaml for Smithery deployment

### ✅ v2.2
- 14 tools: + swap execution system (quote + EIP-1559 tx + approval + allowance + price monitoring)
- Multi-hop routing (direct → via WETH → via USDC)
- `exact_in` and `exact_out` swap types
- EIP-1559 transaction builder with nonce, gas, chainId, deadline
- Token approval system (free tier)
- Price monitoring with target comparison (limit-order style)
- Aerodrome Router ABI integration (full)

### ✅ v2.4
- **WebSocket Real-Time Tracking** — live streaming of pools, wallets, and tokens
- 16 tools: + subscribe, get_ws_info
- 3 channels: pools (30s), wallet (15s), tokens (60s)
- Change detection — only pushes when data changes (TVL delta, APR delta)
- Auto-cleanup of dead WebSocket connections
- Standalone: `python ws_server.py` or integrated: `python server.py --ws`
- 18 WebSocket tests (63 total across test suite)
- x402 Payment Gateway — AI agents pay per API call in USDC on Base

### ✅ v2.5 (current)
- **Solana Cross-Chain Support** — 5 Solana tools (tools 17-21)
- `sol_get_balance` — SOL + SPL token balances
- `sol_get_token_info` — Token metadata (supply, decimals, explorer)
- `sol_get_recent_txs` — Recent transaction history
- `sol_get_gas_price` — Current fee in lamports per signature
- `sol_analyze_wallet` — Full portfolio + recent activity
- Multi-chain auto-detect — `0x` → Base, `base58` → Solana
- Token registry (9 well-known SPL tokens)
- 19 Solana-specific tests (82 total across test suite)

### 🔜 v2.6 — Next Sprint
- [ ] **Limit orders** via Aerodrome
- [ ] **Solana swap execution** — Jupiter integration
- [ ] **Interactive demo on landing page** — try it in your browser
- [ ] **Multi-wallet support** — manage multiple addresses

---

## 🔌 Integration Examples

### Claude Desktop

```json
{
  "mcpServers": {
    "defai-gateway": {
      "command": "python",
      "args": ["/path/to/server.py"],
      "env": {
        "RPC_URL": "https://mainnet.base.org"
      }
    }
  }
}
```

### VS Code (Continue extension)

1. Open VS Code → Continue extension
2. Go to MCP Server settings
3. Add:
```json
{
  "mcpServers": {
    "defai-gateway": {
      "command": "python",
      "args": ["/path/to/server.py"]
    }
  }
}
```

### Docker

```bash
docker build -t defai-gateway .
docker run --rm defai-gateway python server.py --http 8080
```

### Hermes Agent

```bash
# In hermes config.yaml
tools:
  mcp_servers:
    - name: "defai-gateway"
      command: "python"
      args: ["/home/henri/defai-gateway/server.py"]
```

---

## ⚙️ Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `RPC_URL` | `https://mainnet.base.org` | Base RPC endpoint |
| `SOLANA_RPC` | `https://api.mainnet-beta.solana.com` | Solana RPC endpoint |
| `SOLANA_RPC_FALLBACK` | `https://solana-api.projectserum.com` | Solana fallback RPC |
| `GATE_TOKEN` | `""` | $GATE token address for gating |
| `FEE_WALLET` | `0x000...` | Fee collection wallet |
| `FEE_BPS` | `5` | Fee basis points (0.05%) |
| `DAILY_FREE_CALLS` | `10` | Free calls per wallet per day |

---

## 🧪 Development

```bash
# Run tests
pip install pytest pytest-asyncio
pytest tests/ -v

# Run with HTTP (SSE) mode
python server.py --http 8080

# Run in x402 mode
python server.py --x402 4020
```

---

## 📬 Contact & Support

- **Email:** hermes-business@agentmail.to
- **GitHub Issues:** [Report a bug](https://github.com/Dev-Herni/defai-gateway/issues)
- **Token:** $GATE — ask about $GATE at your favorite DEX

---

## 📜 License

MIT — free to use, modify, and distribute. Built on Base.

*Part of the [DeFAI ecosystem](https://dev-herni.github.io/defai-gateway-site/) · Powered by Hermes Agent*
