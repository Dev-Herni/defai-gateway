"""Tests for DeFAI Gateway Solana Cross-Chain Support — v2.5"""

import json
import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def sv():
    """Fresh solana_server import."""
    for mod in list(sys.modules.keys()):
        if "solana_server" in mod:
            del sys.modules[mod]
    import solana_server
    return solana_server


# ═══════════════════════════════════════════════════════════════
# ADDRESS DETECTION
# ═══════════════════════════════════════════════════════════════

class TestAddressDetection:
    def test_solana_address_valid(self, sv):
        # Real Solana address
        addr = "4EnixhxrxT4RE3AyK5tzxDdYZic8jv756CLS3cKZW2AU"
        assert sv.is_solana_address(addr) is True

    def test_solana_address_short(self, sv):
        assert sv.is_solana_address("0xshort") is False

    def test_evm_address(self, sv):
        assert sv.is_evm_address("0x1234567890abcdef1234567890abcdef12345678") is True

    def test_evm_address_no_prefix(self, sv):
        assert sv.is_evm_address("1234567890abcdef1234567890abcdef12345678") is False

    def test_detect_chain_solana(self, sv):
        addr = "4EnixhxrxT4RE3AyK5tzxDdYZic8jv756CLS3cKZW2AU"
        assert sv.detect_chain(addr) == "solana"

    def test_detect_chain_evm(self, sv):
        addr = "0x1234567890abcdef1234567890abcdef12345678"
        assert sv.detect_chain(addr) == "base"

    def test_detect_chain_unknown(self, sv):
        assert sv.detect_chain("garbage") == "unknown"

    def test_solana_wallet_nonce(self, sv):
        """Solana wallet with valid length but not a valid address."""
        addr = "A" * 44
        assert sv.is_solana_address(addr) is True

    def test_solana_address_too_short(self, sv):
        assert sv.is_solana_address("abc123") is False


# ═══════════════════════════════════════════════════════════════
# FORMAT HELPERS
# ═══════════════════════════════════════════════════════════════

class TestFormatHelpers:
    def test_lamports_to_sol(self, sv):
        assert sv.lamports_to_sol(1_000_000_000) == 1.0
        assert sv.lamports_to_sol(500_000_000) == 0.5
        assert sv.lamports_to_sol(0) == 0.0

    def test_format_token_amount_9_decimals(self, sv):
        assert sv.format_token_amount(1_000_000_000, 9) == 1.0

    def test_format_token_amount_6_decimals(self, sv):
        assert sv.format_token_amount(1_000_000, 6) == 1.0

    def test_format_token_amount_no_decimals(self, sv):
        assert sv.format_token_amount(100, 0) == 100.0


# ═══════════════════════════════════════════════════════════════
# RPC CALLS (mocked)
# ═══════════════════════════════════════════════════════════════

class TestSolRpcCall:
    @pytest.mark.asyncio
    async def test_success(self, sv):
        async def mock_post(url, **kw):
            resp = MagicMock()
            resp.status_code = 200
            resp.json = MagicMock(return_value={"jsonrpc": "2.0", "result": {"value": 1000000000}})
            return resp

        with patch("httpx.AsyncClient") as mc:
            mc.return_value.__aenter__.return_value.post = mock_post
            result = await sv.sol_rpc_call("getBalance", ["4EnixhxrxT4RE3AyK5tzxDdYZic8jv756CLS3cKZW2AU"])
            assert "result" in result
            assert result["result"]["value"] == 1000000000

    @pytest.mark.asyncio
    async def test_error_response(self, sv):
        async def mock_post(url, **kw):
            resp = MagicMock()
            resp.status_code = 200
            resp.json = MagicMock(return_value={"jsonrpc": "2.0", "error": {"message": "Invalid param"}})
            return resp

        with patch("httpx.AsyncClient") as mc:
            mc.return_value.__aenter__.return_value.post = mock_post
            result = await sv.sol_rpc_call("getBalance", ["bad"])
            assert "error" in result


# ═══════════════════════════════════════════════════════════════
# JSON RESPONSE HELPERS
# ═══════════════════════════════════════════════════════════════

class TestJsonHelpers:
    def test_sol_json_ok(self, sv):
        d = json.loads(sv.sol_json_ok({"msg": "hi"}))
        assert d["_status"] == "ok"
        assert d["chain"] == "solana"
        assert d["msg"] == "hi"

    def test_sol_json_error(self, sv):
        d = json.loads(sv.sol_json_error("bad", "invalid"))
        assert d["_status"] == "invalid"
        assert d["chain"] == "solana"
        assert "bad" in d["error"]


# ═══════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════

class TestTokenRegistry:
    def test_major_tokens_present(self, sv):
        assert "SOL" in sv.SOL_TOKENS
        assert "USDC" in sv.SOL_TOKENS
        assert "JUP" in sv.SOL_TOKENS
        assert "BONK" in sv.SOL_TOKENS

    def test_usdc_mint_known(self, sv):
        assert sv.SOL_TOKENS["USDC"] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
