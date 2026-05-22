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

## 🛠️ Tools (10 Total)

| # | Tool | Description | Tier | Use Case |
|---|------|-------------|------|----------|
| 1 | `get_balance` | ETH + ERC-20 token balances | 🆓 Free | "What's in my wallet?" |
| 2 | `get_token_info` | Token name, symbol, decimals, supply | 🆓 Free | "Is this token legit?" |
| 3 | `get_gas_price` | Live Base gas in gwei | 🆓 Free | "Should I trade now?" |
| 4 | `get_pools` | Top Aerodrome liquidity pools | ⭐ Premium | "Where's the yield?" |
| 5 | `analyze_wallet` | Full wallet breakdown + portfolio | ⭐ Premium | "Who is this whale?" |
| 6 | `track_new_tokens` | Scan for new token deployments (3 sources) | ⭐ Premium | "What launched today?" |
| 7 | `get_token_price` | Live price in USD (CoinGecko) | ⭐ Premium | "What's AERO worth?" |
| 8 | `get_recent_transactions` | Recent wallet activity (Blockscout) | ⭐ Premium | "What has this wallet been doing?" |
| 9 | `get_payment_status` | Your tier + remaining free calls | ⭐ Premium | "What's my usage?" |
| 10 | `prepare_swap` | Prepare Aerodrome swap tx (unsigned) | 🔒 $GATE | "Swap 100 USDC for AERO" |

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

### 🔜 v2.2 — Next Sprint
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
