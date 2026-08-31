"""
Comprehensive Unit & Integration Test Suite for Medium Findings (M1 - M6).

Verifies:
- M1: Versioned Fee Policy Engine (FeePolicyRegistry, policies, Decimal precision, evidence)
- M2: Dynamic Reporting Period & Boundary Cutoff Derivation (No hardcoded month/day)
- M3: Normalizer Decimal Parsing & Strict Value Validation (No silent zeros or fake dates)
- M4: Truthful Agent Execution Telemetry, Verifier Gates & Invariant Proofs
- M5: Secure Defaults & Production Environment Startup Validation
- M6: Durable Database Advisory Locking with Fail-Closed Exclusivity
"""

import os
import sys
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import Settings
from app.db.database import init_db
from app.models.schemas import (
    CanonicalTransaction, SourceKind, TxnDirection, InvestigationResult, ToolEvidence
)
from app.services.fee_policy import FeePolicyRegistry, FeePolicy, TaxJurisdiction, RoundingMode
from app.services.period import derive_period, ReportingPeriod
from app.services.normalizer import NormalizerService
from app.services.agent_runtime import AIAgentRuntime, DeterministicVerifier
from app.core.db_lock import DatabaseLockManager


class MediumFindingsTestSuite(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    # ==========================================================================
    # M1: Versioned Fee Policy Engine
    # ==========================================================================
    def test_m1_versioned_fee_policy_engine(self):
        """M1: Tests versioned fee policies, Decimal precision, and formula proofs."""
        # 1. Standard 2.0% MDR + 18% GST
        std_policy = FeePolicyRegistry.get_policy("POL-MDR-STD-2026")
        self.assertIsNotNone(std_policy)
        
        # Gross = ₹1,180.00 (118000 paise)
        # MDR = 2% of 118000 = 2360 paise (₹23.60)
        # GST = 18% of 2360 = 425 paise (₹4.25)
        # Total deduction = 2785 paise (₹27.85)
        # Net = 115215 paise (₹1,152.15)
        bd = std_policy.calculate(118000)
        self.assertEqual(bd.fee_minor, 2360)
        self.assertEqual(bd.tax_minor, 425)
        self.assertEqual(bd.total_deduction_minor, 2785)
        self.assertEqual(bd.expected_net_minor, 115215)
        self.assertEqual(bd.policy_id, "POL-MDR-STD-2026")
        self.assertIn("POL-MDR-STD-2026", bd.formula_proof)

        # 2. Enterprise 1.5% MDR + 18% GST
        ent_policy = FeePolicyRegistry.get_policy("POL-MDR-ENT-2026")
        self.assertIsNotNone(ent_policy)
        bd_ent = ent_policy.calculate(1000000) # ₹10,000.00
        # MDR = 1.5% of 1000000 = 15000 paise (₹150.00)
        # GST = 18% of 15000 = 2700 paise (₹27.00)
        # Net = 1000000 - 17700 = 982300 paise (₹9,823.00)
        self.assertEqual(bd_ent.fee_minor, 15000)
        self.assertEqual(bd_ent.tax_minor, 2700)
        self.assertEqual(bd_ent.expected_net_minor, 982300)

        # 3. Policy Resolution by Gross & Net
        policy, match_bd = FeePolicyRegistry.match_best_policy(118000, 115215, tolerance_minor=50)
        self.assertEqual(policy.policy_id, "POL-MDR-STD-2026")
        self.assertEqual(match_bd.expected_net_minor, 115215)

    # ==========================================================================
    # M2: Dynamic Reporting Period & Settlement Cutoff
    # ==========================================================================
    def test_m2_dynamic_reporting_period_and_cutoff(self):
        """M2: Tests deriving reporting period from data without hardcoded months."""
        # March Dataset
        march_txns = [
            {"value_date": date(2026, 3, 5)},
            {"value_date": date(2026, 3, 31)},
        ]
        p_march = derive_period(march_txns)
        self.assertEqual(p_march.start, date(2026, 3, 1))
        self.assertEqual(p_march.end, date(2026, 3, 31))
        self.assertTrue(p_march.is_cutoff_date(date(2026, 3, 31), window_days=2))
        self.assertTrue(p_march.is_cutoff_date(date(2026, 3, 30), window_days=2))
        self.assertFalse(p_march.is_cutoff_date(date(2026, 3, 15), window_days=2))

        # August Dataset
        aug_txns = [
            {"value_date": date(2026, 8, 10)},
            {"value_date": date(2026, 8, 31)},
        ]
        p_aug = derive_period(aug_txns)
        self.assertEqual(p_aug.start, date(2026, 8, 1))
        self.assertEqual(p_aug.end, date(2026, 8, 31))
        self.assertTrue(p_aug.is_cutoff_date(date(2026, 8, 31), window_days=1))
        self.assertFalse(p_aug.is_cutoff_date(date(2026, 8, 15), window_days=1))

    # ==========================================================================
    # M3: Normalizer Strict Decimal Parsing & Validation
    # ==========================================================================
    def test_m3_normalizer_decimal_parsing_and_rejection(self):
        """M3: Verifies Decimal precision and rejection of corrupted values."""
        # Exact Decimal paise conversion
        self.assertEqual(NormalizerService._to_paise("1180.00"), 118000)
        self.assertEqual(NormalizerService._to_paise("1,180.50"), 118050)
        self.assertEqual(NormalizerService._to_paise("0.05"), 5)

        # Corrupted money value must raise ValueError when default_zero=False
        with self.assertRaises(ValueError):
            NormalizerService._to_paise("corrupted_amount", default_zero=False)

        with self.assertRaises(ValueError):
            NormalizerService._to_paise("", default_zero=False)

        # Corrupted date value must raise ValueError
        with self.assertRaises(ValueError):
            NormalizerService._parse_datetime("invalid_date_format_xyz")

        with self.assertRaises(ValueError):
            NormalizerService._parse_datetime("")

    # ==========================================================================
    # M4: Truthful Agent Execution Telemetry & Verifier Gates
    # ==========================================================================
    def test_m4_agent_truthful_telemetry_and_verifiers(self):
        """M4: Tests agent execution telemetry and verifier gate rejection."""
        agent = AIAgentRuntime()
        inv = agent.investigate_exception(
            exception_id="EXC-TEST-M4",
            exception_type="AMOUNT_MISMATCH",
            impact_minor=2785,
            primary_txn={"id": "gw_101", "amount_minor": 118000},
            counterpart_txn={"id": "bk_101", "amount_minor": 115215},
            available_txns=[{"id": "gw_101"}, {"id": "bk_101"}],
            severity="HIGH"
        )

        self.assertIsNotNone(inv.telemetry)
        self.assertIn("provider", inv.telemetry)
        self.assertIn("model", inv.telemetry)
        self.assertIn("latency_ms", inv.telemetry)
        self.assertEqual(inv.telemetry["verifier_status"], "PASSED")

        # Verifier Gate: Hallucinated candidate ID must fail verification
        hallucinated_inv = InvestigationResult(
            exception_id="EXC-HALLUCINATED",
            classification="FEE_AND_TAX_BOOKED_NET",
            likely_cause="Hallucinated candidate match",
            candidate_match_ids=["NON_EXISTENT_TXN_99999"],
            recommended_action="ADJUST_LEDGER_FEE_SPLIT",
            confidence=0.99
        )
        is_valid, err = DeterministicVerifier.verify_proposal(
            hallucinated_inv,
            {"impact_minor": 2785},
            valid_txn_ids={"gw_101", "bk_101"}
        )
        self.assertFalse(is_valid)
        self.assertIn("does not exist in the active batch", err)

    # ==========================================================================
    # M5: Secure Defaults & Production Startup Validation
    # ==========================================================================
    def test_m5_production_config_safety(self):
        """M5: Verifies production mode disallows insecure defaults."""
        # 1. Insecure default secret key rejected in production
        bad_settings = Settings(
            APP_ENV="production",
            DEBUG=False,
            SECRET_KEY="dev_secret_key_change_in_production_finance_controller_jwt_9921",
            CORS_ORIGINS=["https://app.acme.co"],
            DATABASE_URL="postgresql://user:pass@localhost:5432/db"
        )
        with self.assertRaises(ValueError) as ctx:
            bad_settings.validate_production_environment()
        self.assertIn("PRODUCTION_CONFIG_ERROR", str(ctx.exception))
        self.assertIn("SECRET_KEY", str(ctx.exception))

        # 2. Wildcard CORS rejected in production
        bad_cors = Settings(
            APP_ENV="production",
            DEBUG=False,
            SECRET_KEY="a_very_long_secure_secret_key_for_production_2026_finance",
            CORS_ORIGINS=["*"],
            DATABASE_URL="postgresql://user:pass@localhost:5432/db"
        )
        with self.assertRaises(ValueError) as ctx:
            bad_cors.validate_production_environment()
        self.assertIn("CORS_ORIGINS", str(ctx.exception))

        # 3. Valid production config passes
        valid_prod = Settings(
            APP_ENV="production",
            DEBUG=False,
            SECRET_KEY="a_very_long_secure_secret_key_for_production_2026_finance",
            CORS_ORIGINS=["https://controller.acme.co"],
            DATABASE_URL="postgresql://user:pass@localhost:5432/db"
        )
        # Should not raise
        valid_prod.validate_production_environment()

    # ==========================================================================
    # M6: Durable Database Advisory Locking (Fail-Closed)
    # ==========================================================================
    def test_m6_durable_database_lock_fail_closed(self):
        """M6: Tests durable database lock acquisition, contention rejection, and release."""
        test_lock_key = "lock:test:batch_exclusivity_001"

        # 1. First worker acquires lock
        acquired_1, token_1 = DatabaseLockManager.acquire_lock(test_lock_key, timeout_sec=10)
        self.assertTrue(acquired_1)
        self.assertIsNotNone(token_1)

        # 2. Second worker attempts to acquire same lock -> MUST FAIL CLOSED (False, None)
        acquired_2, token_2 = DatabaseLockManager.acquire_lock(test_lock_key, timeout_sec=10)
        self.assertFalse(acquired_2)
        self.assertIsNone(token_2)

        # 3. First worker releases lock
        released = DatabaseLockManager.release_lock(test_lock_key, token_1)
        self.assertTrue(released)

        # 4. Second worker can now acquire lock
        acquired_3, token_3 = DatabaseLockManager.acquire_lock(test_lock_key, timeout_sec=10)
        self.assertTrue(acquired_3)
        self.assertIsNotNone(token_3)

        # Clean up
        DatabaseLockManager.release_lock(test_lock_key, token_3)


if __name__ == "__main__":
    unittest.main()
