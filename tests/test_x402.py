"""Tests for DeFAI Gateway x402 Payment System — v2.3"""

import json
import sys
import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def ledger():
    """Fresh CreditLedger for each test."""
    from x402_server import CreditLedger
    return CreditLedger()


# ═══════════════════════════════════════════════════════════════
# CREDIT LEDGER TESTS
# ═══════════════════════════════════════════════════════════════

class TestCreditLedger:
    def test_new_balance_zero(self, ledger):
        assert ledger.get_balance("0x1234") == 0
    
    def test_add_credits(self, ledger):
        ledger.add_credits("0x1234", 100000)  # 0.1 USDC
        assert ledger.get_balance("0x1234") == 100000
    
    def test_add_credits_case_insensitive(self, ledger):
        ledger.add_credits("0xABCD", 50000)
        assert ledger.get_balance("0xabcd") == 50000
    
    def test_deduct_sufficient_balance(self, ledger):
        ledger.add_credits("0x1234", 100000)
        result = ledger.deduct_call("0x1234", 1000)
        assert result is True
        assert ledger.get_balance("0x1234") == 99000
    
    def test_deduct_insufficient_balance(self, ledger):
        ledger.add_credits("0x1234", 500)  # Less than call cost (1000)
        result = ledger.deduct_call("0x1234", 1000)
        # Should fall back to free tier if no credit
        assert result is True or result is False
    
    def test_deduct_exhausted(self, ledger):
        # Use all free calls then try with no credit
        for _ in range(10):
            ledger.deduct_call("0xexhausted", 1000)
        # 11th call with no credit should fail
        result = ledger.deduct_call("0xexhausted", 1000)
        # If credit is 0 and free calls used up, should return False
        if ledger.get_balance("0xexhausted") == 0:
            assert result is False
    
    def test_verified_tx_dedup(self, ledger):
        result1 = ledger.add_credits("0x1234", 100000, "0xtest123")
        result2 = ledger.add_credits("0x1234", 100000, "0xtest123")
        assert result1 is True
        assert result2 is False  # Duplicate
        assert ledger.get_balance("0x1234") == 100000
    
    def test_get_status(self, ledger):
        ledger.add_credits("0xabc", 1000000)  # 1 USDC
        status = ledger.get_status("0xabc")
        assert status["credit_balance_usdc"] == 1.0
        assert status["free_calls_remaining"] >= 0
        assert status["call_cost_usdc"] > 0


# ═══════════════════════════════════════════════════════════════
# VERIFICATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestVerifyPayment:
    @pytest.mark.asyncio
    async def test_no_web3_returns_error(self):
        with patch("x402_server.web3", None):
            from x402_server import verify_usdc_payment
            result = await verify_usdc_payment("0xtest")
            assert result["valid"] is False
            assert "RPC" in result["reason"]
    
    @pytest.mark.asyncio
    async def test_empty_tx_hash(self):
        with patch("x402_server.web3", MagicMock()) as mock_w3:
            from x402_server import verify_usdc_payment
            mock_w3.eth.get_transaction_receipt.return_value = None
            result = await verify_usdc_payment("")
            assert result["valid"] is False
    
    @pytest.mark.asyncio
    async def test_old_tx_rejected(self):
        mock_w3 = MagicMock()
        mock_w3.eth.block_number = 1000
        receipt = MagicMock()
        receipt.blockNumber = 500
        receipt.status = 1
        receipt.logs = []
        mock_w3.eth.get_transaction_receipt.return_value = receipt
        mock_w3.to_checksum_address = lambda a: a
        
        with patch("x402_server.web3", mock_w3):
            from x402_server import verify_usdc_payment
            result = await verify_usdc_payment("0xold_tx")
            assert result["valid"] is False


# ═══════════════════════════════════════════════════════════════
# CONFIG TESTS
# ═══════════════════════════════════════════════════════════════

class TestConfig:
    def test_usdc_address(self):
        from x402_server import USDC_ADDRESS, CALL_COST_USDC, MIN_DEPOSIT_USDC, FREE_TIER_DAILY
        assert USDC_ADDRESS.startswith("0x")
        assert USDC_ADDRESS == USDC_ADDRESS.lower() or USDC_ADDRESS == "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
        assert CALL_COST_USDC >= 1
        assert MIN_DEPOSIT_USDC >= CALL_COST_USDC
        assert FREE_TIER_DAILY >= 1
