# DeFAI Gateway MCP Server 🤖⛓️

**The first production-ready MCP server connecting AI Agents to Base Chain DeFi.**

[![MCP](https://img.shields.io/badge/MCP-Server-00D4FF)](https://modelcontextprotocol.io)
[![Base](https://img.shields.io/badge/Chain-Base-0052FF)](https://base.org)
[![License](https://img.shields.io/badge/License-MIT-4ADE80)](LICENSE)

---

## 🚀 Quick Start

```bash
pip install -r requirements.txt
python server.py
```

That's it. Your AI agent now has access to Base Chain.

## 🛠️ Tools

| Tool | Description | Tier | Use Case |
|------|-------------|------|----------|
| `get_balance` | ETH + token balances | 🆓 Free | Portfolio check |
| `get_token_info` | Token name, symbol, decimals | 🆓 Free | Due diligence |
| `get_gas_price` | Current Base gas in gwei | 🆓 Free | Know when to trade |
| `get_pools` | Top Aerodrome liquidity pools | ⭐ Premium | Yield opportunities |
| `analyze_wallet` | Full wallet breakdown | ⭐ Premium | Whale tracking |
| `track_new_tokens` | Scan for new deployments | ⭐ Premium | Alpha detection |
| `get_token_price` | Token price in USD | ⭐ Premium | Market data |
| `get_recent_transactions` | Recent wallet txs | ⭐ Premium | Activity tracking |
| `get_payment_status` | Check your tier + usage | ⭐ Premium | Account management |
| `prepare_swap` | Prepare Aerodrome swap tx | 🔒 $GATE Holder | Trading |

## 📋 Requirements

- Python 3.10+
- Base RPC (public: `https://mainnet.base.org`)
- No API keys needed for basic usage

## 💰 Pricing

| Tier | Operations/mo | Price | Best for |
|------|--------------|-------|----------|
| **Free** | 1,000 | $0 | Prototyping, hobbyists |
| **Pro** | 10,000 | $19.99/mo | Developers, trading bots |
| **Enterprise** | Unlimited | $99/mo | DeFi protocols, agents at scale |

Payment via Solana (SOL), Base ETH, or USDC.

## 🔌 Integration

### Claude Desktop
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

### Script/Code
```python
# Your AI agent calls this like any MCP tool
result = await agent.call_tool("get_balance", {
    "address": "0xYourWalletAddress"
})
```

## 🏗️ Architecture

```
AI Agent → MCP Protocol → DeFAI Gateway → Base RPC
                              ↓
                         Aerodrome API
                              ↓
                         CoinGecko API
```

The server is stateless, fast, and deployable anywhere — local, VPS, or serverless.

## 🗺️ Roadmap

- [x] Balance checks (ETH + ERC-20)
- [x] Token info (name, symbol, supply)
- [x] Gas prices
- [x] Aerodrome pool data
- [x] Wallet analysis
- [x] Token deployment tracking
- [ ] **Swap execution** (Aerodrome/Uniswap via private key)
- [ ] **Limit orders** 
- [ ] **x402 payments** (AI agents pay per API call)
- [ ] **WebSocket real-time tracking**
- [ ] **Solana chain support**

## 🔐 Security

- **Read-only by default** — no private keys required
- **No data stored** — all queries go directly to Base RPC
- **Rate limited** per API key to prevent abuse
- **Open source** — fully auditable

## 📬 Contact

`hermes-business@agentmail.to`

---

*Built with Hermes Agent · Part of the DeFAI ecosystem*
