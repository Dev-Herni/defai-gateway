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

## 🛠️ Tools (14 Total)

| # | Tool | Description | Tier |
|---|------|-------------|------|
| 1 | `get_balance` | ETH + ERC-20 token balances | 🆓 Free |
| 2 | `get_token_info` | Token name, symbol, decimals, supply | 🆓 Free |
| 3 | `get_gas_price` | Live Base gas in gwei | 🆓 Free |
| 4 | `get_pools` | Top Aerodrome liquidity pools (3 data sources) | ⭐ Premium |
| 5 | `analyze_wallet` | Full wallet breakdown + portfolio | ⭐ Premium |
| 6 | `track_new_tokens` | Scan for new token deployments (3-tier fallback) | ⭐ Premium |
| 7 | `get_swap_quote` | Live swap quote with price impact + route info | 🔒 $GATE |
| 8 | `build_swap_transaction` | Full EIP-1559 swap tx (nonce, gas, chainId) | 🔒 $GATE |
| 9 | `build_approve_transaction` | Token approval tx for Aerodrome Router | 🆓 Free |
| 10 | `check_allowance` | Check current allowance before swapping | 🆓 Free |
| 11 | `monitor_price` | Price check + target comparison (limit-order style) | ⭐ Premium |
| 12 | `get_token_price` | Live price in USD (CoinGecko) | ⭐ Premium |
| 13 | `get_recent_transactions` | Recent wallet activity (Blockscout) | ⭐ Premium |
| 14 | `get_payment_status` | Your tier + remaining free calls | ⭐ Premium |

---

## 🏗️ Architecture

```
AI Agent → MCP Protocol → DeFAI Gateway ──┬── Base RPC (on-chain)
                                           ├── Blockscout API (transactions)
                                           ├── Aerodrome API (pools)
                                           ├── CoinGecko API (prices)
                                           └── Clanker API (new tokens)
```

**Key design decisions:**
- **Read-only by default** — no private keys needed for 9/10 tools
- **Stateless** — no database, no storage, no user data
- **Payment gating** built-in — free tier, premium, token-gated
- **Layered API fallbacks** — always returns data even if upstream APIs fail

---

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
- **Open source** — 100% auditable, 616 lines
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

### ✅ v2.2 (current)
- 14 tools: + swap execution system (quote + EIP-1559 tx + approval + allowance + price monitoring)
- Multi-hop routing (direct → via WETH → via USDC)
- `exact_in` and `exact_out` swap types
- EIP-1559 transaction builder with nonce, gas, chainId, deadline
- Token approval system (free tier)
- Price monitoring with target comparison (limit-order style)
- Aerodrome Router ABI integration (full)

### 🔜 v2.3 — Next Sprint
- [ ] **x402 Payments** — AI agents pay per API call in USDC
- [ ] **WebSocket real-time tracking** — live pool updates
- [ ] **Limit orders** via Aerodrome
- [ ] **Solana support** — cross-chain MCP
- [ ] **Interactive demo on landing page** — try it in your browser

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
