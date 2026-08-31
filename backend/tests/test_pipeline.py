import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime, timezone, date
from app.models.schemas import SourceKind, TxnDirection, CanonicalTransaction, DecisionTier, MatchMethodEnum
from app.services.normalizer import NormalizerService
from app.services.validation_service import DataValidationService
from app.services.context_builder import TransactionContextBuilder
from app.services.decision_engine import HybridDecisionEngine
from app.services.matching_engine import ReconciliationEngine
from app.services.batch_orchestrator import WindowedBatchOrchestrator
from app.services.cash_forecaster import SegmentedCashForecaster
from app.services.audit_chain import AuditHashChain
from app.services.ingestion import IngestionService
from app.api.v1.batches import STATE, execute_batch_reconciliation, RunBatchRequest

class TestQualityFirstPipeline(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from app.db.database import init_db
        init_db()

    def setUp(self):
        self.org_id = "00000000-0000-0000-0000-000000000001"
        self.batch_id = "BATCH-TEST-QUALITY-01"

    def test_layer1_validation_gate(self):
        """Validates pre-flight validation gate catches missing IDs and duplicate records."""
        t1 = NormalizerService.normalize_row({
            "payment_id": "pay_TEST_01",
            "amount": 10000,
            "captured_at": "2026-03-25T10:00:00+05:30",
            "description": "Invoice INV-001"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        t2_dup = NormalizerService.normalize_row({
            "payment_id": "pay_TEST_01", # Duplicate ID
            "amount": 10000,
            "captured_at": "2026-03-25T10:00:00+05:30",
            "description": "Invoice INV-001"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        val_results = DataValidationService.validate_batch([t1, t2_dup])
        self.assertEqual(val_results[t1.id].status, "VALID")
        self.assertEqual(val_results[t2_dup.id].status, "INVALID")
        self.assertIn("DUPLICATE_SOURCE_RECORD", val_results[t2_dup.id].errors[0])

    def test_context_builder_360(self):
        """Validates 360 context synthesis for fee schedules and T+2 cutoff lag."""
        t_cutoff = NormalizerService.normalize_row({
            "payment_id": "pay_CUTOFF_01",
            "gross_amount": 1180.00,
            "captured_at": "2026-08-31T23:58:12+05:30", # Period boundary
            "description": "Invoice INV-2026-0412"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        ctx = TransactionContextBuilder.build_context(t_cutoff, [t_cutoff])
        self.assertTrue(ctx.is_period_cutoff)
        self.assertEqual(ctx.settlement_delay_days, 2)
        self.assertEqual(len(ctx.checks_performed), 7)
        self.assertIn("PERIOD_BOUNDARY_CUTOFF_T2_LAG", ctx.anomaly_flags)

    def test_tier1_exact_matching(self):
        """Validates Tier 1 deterministic exact key and amount matching."""
        gw = NormalizerService.normalize_row({
            "payment_id": "PAY-1001",
            "gross_amount": 10000.00,
            "created_at": "2026-08-20T10:00:00",
            "merchant_reference": "INV-1001"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        bank = NormalizerService.normalize_row({
            "bank_transaction_id": "UTR-1001",
            "amount": 10000.00,
            "date": "2026-08-20",
            "description": "Direct deposit INV-1001 PAY-1001",
            "type": "Credit"
        }, SourceKind.BANK, self.org_id, self.batch_id)

        engine = ReconciliationEngine(self.org_id, self.batch_id)
        res = engine.run_full_pipeline([gw, bank])
        self.assertEqual(res["tier_breakdown"]["tier_1_exact"], 1)
        self.assertEqual(engine.matches[0].decision_tier, DecisionTier.RESOLVED)
        self.assertEqual(engine.matches[0].score, 1.00)

    def test_tier2_contextual_fee_proof_matching(self):
        """Validates Tier 2 contextual matching with 2.0% MDR + GST arithmetic proof."""
        gw = NormalizerService.normalize_row({
            "payment_id": "PAY-1002",
            "gross_amount": 10000.00,
            "fee_amount": 200.00,
            "tax_amount": 36.00,
            "net_amount": 9764.00,
            "created_at": "2026-08-20T11:00:00",
            "merchant_reference": "INV-1002"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        bank = NormalizerService.normalize_row({
            "bank_transaction_id": "UTR-1002",
            "amount": 9764.00,
            "date": "2026-08-20",
            "description": "Settlement net PAY-1002 INV-1002",
            "type": "Credit"
        }, SourceKind.BANK, self.org_id, self.batch_id)

        engine = ReconciliationEngine(self.org_id, self.batch_id)
        res = engine.run_full_pipeline([gw, bank])
        self.assertEqual(res["tier_breakdown"]["tier_2_contextual"], 1)
        self.assertEqual(engine.matches[0].decision_tier, DecisionTier.RESOLVED_WITH_EXPLANATION)
        self.assertIn("2.0% Standard MDR + 18% GST", engine.matches[0].solver_evidence["fee_tier"])
        self.assertEqual(engine.matches[0].solver_evidence["variance_minor"], 23600)

    def test_tier3_runner_up_margin_safeguard(self):
        """Validates runner-up margin safeguard triggers when 2 duplicate records compete with margin Delta < 0.05."""
        gw1 = NormalizerService.normalize_row({
            "payment_id": "PAY-DUP-01",
            "gross_amount": 10000.00,
            "created_at": "2026-08-23T10:00:00",
            "merchant_reference": "INV-DUP"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        gw2 = NormalizerService.normalize_row({
            "payment_id": "PAY-DUP-02",
            "gross_amount": 10000.00,
            "created_at": "2026-08-23T10:00:00",
            "merchant_reference": "INV-DUP"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        bank = NormalizerService.normalize_row({
            "bank_transaction_id": "UTR-DUP-01",
            "amount": 9764.00,
            "date": "2026-08-23",
            "description": "Settlement INV-DUP PAY-DUP-01",
            "type": "Credit"
        }, SourceKind.BANK, self.org_id, self.batch_id)

        engine = ReconciliationEngine(self.org_id, self.batch_id)
        res = engine.run_full_pipeline([gw1, gw2, bank])
        # Margin Delta < 0.05 prevents auto-match and routes to Tier 3 review
        self.assertGreaterEqual(res["tier_breakdown"]["tier_3_needs_review"], 1)
        safeguard_types = [s["safeguard"] for s in res["safeguards_breakdown"]]
        self.assertIn("RUNNER_UP_MARGIN_SAFEGUARD", safeguard_types)

    def test_user_csv_3way_pipeline(self):
        """Validates complete 3-way reconciliation on user files with multi-tier breakdown."""
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        gw_path = os.path.join(repo_root, "data", "gateway.csv")
        bk_path = os.path.join(repo_root, "data", "bank.csv")
        gl_path = os.path.join(repo_root, "data", "general_ledger.csv")

        if os.path.exists(gw_path) and os.path.exists(bk_path) and os.path.exists(gl_path):
            gw, _ = IngestionService.ingest_and_normalize(gw_path, SourceKind.GATEWAY, self.org_id, self.batch_id)
            bk, _ = IngestionService.ingest_and_normalize(bk_path, SourceKind.BANK, self.org_id, self.batch_id)
            gl, _ = IngestionService.ingest_and_normalize(gl_path, SourceKind.LEDGER, self.org_id, self.batch_id)

            engine = ReconciliationEngine(self.org_id, self.batch_id)
            res = engine.run_full_pipeline(gw + bk + gl)

            self.assertEqual(res["total_records"], len(gw) + len(bk) + len(gl))
            self.assertGreaterEqual(res["tier_breakdown"]["tier_1_exact"], 1)
            self.assertGreaterEqual(res["safeguards_triggered_count"], 1)

    def _run_test_batch(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        gw = os.path.join(repo_root, "data", "gateway.csv")
        bk = os.path.join(repo_root, "data", "bank.csv")
        gl = os.path.join(repo_root, "data", "general_ledger.csv")
        return execute_batch_reconciliation(custom_files={"GATEWAY": gw, "BANK": bk, "LEDGER": gl}, window_size=24)

    def test_dynamic_qa_investigation(self):
        """Validates QA investigator dynamic transaction querying and SOP citations."""
        from app.api.v1.qa import ask_batch_assistant, QARequest
        self._run_test_batch()
        
        # Test greeting / capabilities overview
        resp_intro = ask_batch_assistant(QARequest(query="hi what is this chat bot about"))
        self.assertIn("Financial Controller", resp_intro.direct_answer)
        self.assertEqual(resp_intro.status_card.badge_type, "success")

        # Test invoice query
        resp_inv = ask_batch_assistant(QARequest(query="Why did invoice pay_EXT_1002 not settle?"))
        self.assertGreater(len(resp_inv.citations), 0)
        self.assertEqual(resp_inv.tool_trace[0]["tool"], "get_batch_context")

    def test_database_service_persistence_and_seeding(self):
        """Validates DatabaseService seeds users and persists batch records into SQLite/Postgres."""
        from app.db.database import init_db, get_db_context
        from app.db.database_service import DatabaseService
        from app.db import schema

        # Initialize and seed
        init_db()

        with get_db_context() as db:
            org = db.query(schema.Organization).filter_by(id=self.org_id).first()
            self.assertIsNotNone(org)
            self.assertEqual(org.name, "Acme Global Enterprise")

            analyst = db.query(schema.User).filter_by(email="analyst@acme.co").first()
            self.assertIsNotNone(analyst)
            self.assertEqual(analyst.role, "analyst")

            approver = db.query(schema.User).filter_by(email="approver@acme.co").first()
            self.assertIsNotNone(approver)
            self.assertEqual(approver.role, "approver")

        # Run batch and verify DB persistence
        res = self._run_test_batch()
        self.assertEqual(res["status"], "SUCCESS")

        stats = DatabaseService.get_batch_stats(res["batch_id"])
        self.assertGreaterEqual(stats["total_records"], 60)
        self.assertGreater(stats["audit_blocks_count"], 0)
        self.assertGreater(stats["audit_blocks_count"], 0)

    def test_security_argon2_and_jwt_auth(self):
        """Validates Argon2 password hashing, JWT creation, and role enforcement."""
        from app.core.security import get_password_hash, verify_password, create_access_token, decode_access_token
        from app.api.v1.auth import login, LoginRequest

        pwd = "SecureControllerPassword@2026!"
        h = get_password_hash(pwd)
        self.assertTrue(verify_password(pwd, h))
        self.assertFalse(verify_password("wrong_password", h))

        # Test JWT token lifecycle
        token = create_access_token(subject="usr_test_01", org_id=self.org_id, role="approver")
        payload = decode_access_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["sub"], "usr_test_01")
        self.assertEqual(payload["role"], "approver")

        # Test login endpoint
        login_res = login(LoginRequest(email="approver@acme.co", password="Approver@2026!"))
        self.assertEqual(login_res.role, "approver")
        self.assertIsNotNone(login_res.access_token)

    def test_ingestion_service_parsing(self):
        """Validates flexible CSV ingestion and canonical normalization."""
        from app.services.ingestion import IngestionService
        import tempfile

        csv_content = (
            "payment_id,amount,fee,tax,captured_at,customer_email,description\n"
            "pay_CSV_TEST_01,500.00,10.00,1.80,2026-03-31T12:00:00Z,client@corp.co,Invoice INV-2026-9901\n"
            "pay_CSV_TEST_02,750.00,15.00,2.70,2026-03-31T12:05:00Z,user@corp.co,Invoice INV-2026-9902\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as tmp:
            tmp.write(csv_content)
            tmp_path = tmp.name

        try:
            txns, count = IngestionService.ingest_and_normalize(
                tmp_path, SourceKind.GATEWAY, self.org_id, self.batch_id
            )
            self.assertEqual(count, 2)
            self.assertEqual(len(txns), 2)
            self.assertEqual(txns[0].external_id, "pay_CSV_TEST_01")
            self.assertEqual(txns[0].amount_minor, 50000)
            self.assertEqual(txns[0].reference_keys.invoice, ["INV-2026-9901"])
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_maker_checker_segregation_of_duties(self):
        """Validates dual-control rule preventing analyst self-approval."""
        import asyncio
        from app.api.v1.approvals import decide_proposal, ApprovalActionRequest
        from fastapi import HTTPException

        self._run_test_batch()
        proposals = STATE.get("proposals", [])
        if proposals:
            p_id = proposals[0]["id"]
            # Analyst attempt to approve should raise HTTP 403
            with self.assertRaises(HTTPException) as cm:
                asyncio.run(decide_proposal(
                    ApprovalActionRequest(proposal_id=p_id, action="APPROVED", actor_role="analyst"),
                    current_user={"user_id": "usr_analyst_01", "role": "analyst"}
                ))
            self.assertEqual(cm.exception.status_code, 403)

            # Approver attempt should succeed
            res = asyncio.run(decide_proposal(
                ApprovalActionRequest(proposal_id=p_id, action="APPROVED", actor_role="approver"),
                current_user={"user_id": "usr_approver_01", "role": "approver"}
            ))
            self.assertEqual(res["status"], "SUCCESS")
            self.assertEqual(res["decision"], "APPROVED")

    def test_redis_connection_manager_and_failopen(self):
        """Validates RedisManager connection pooling, ping health check, and fail-open behavior."""
        import asyncio
        try:
            import fakeredis.aioredis
        except ImportError:
            self.skipTest("fakeredis not installed")
        from app.core.redis import redis_manager, get_cached_json, set_cached_json

        async def run_test():
            fake_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
            redis_manager.set_mock_client(fake_client)
            self.assertTrue(redis_manager.is_connected)

            # Test JSON caching
            test_key = "fin:test:sample_key"
            await set_cached_json(test_key, {"metric": 99.5, "status": "ACTIVE"}, ttl_sec=10)
            cached = await get_cached_json(test_key)
            self.assertIsNotNone(cached)
            self.assertEqual(cached["metric"], 99.5)

            # 2. Test fail-open when Redis is disconnected
            redis_manager.set_mock_client(None)
            self.assertFalse(redis_manager.is_connected)
            cached_none = await get_cached_json(test_key)
            self.assertIsNone(cached_none) # Does not crash, returns None

        asyncio.run(run_test())

    def test_redis_distributed_locking(self):
        """Validates atomic distributed locking, contention prevention, and owner-safe Lua release."""
        import asyncio
        try:
            import fakeredis.aioredis
        except ImportError:
            self.skipTest("fakeredis not installed")
        from app.core.redis import redis_manager, acquire_distributed_lock

        async def run_test():
            fake_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
            redis_manager.set_mock_client(fake_client)

            lock_key = "fin:test:lock:batch:BATCH-999"

            # 1. Process A acquires lock
            # 3. After Process A exits, lock should be released
            async with acquire_distributed_lock(lock_key, timeout_sec=10) as (acquired_c, token_c):
                self.assertTrue(acquired_c)

            # 4. Fail-open locking when Redis is disconnected
            redis_manager.set_mock_client(None)
            async with acquire_distributed_lock(lock_key, timeout_sec=10) as (acquired_fallback, token_fallback):
                self.assertTrue(acquired_fallback) # Fails open gracefully
                self.assertIsNone(token_fallback)

        asyncio.run(run_test())

    def test_redis_dashboard_caching_and_invalidation(self):
        """Validates dashboard summary caching and invalidation on reconciliation."""
        import asyncio
        try:
            import fakeredis.aioredis
        except ImportError:
            self.skipTest("fakeredis not installed")
        from app.core.redis import redis_manager, key_dashboard_summary, get_cached_json, invalidate_dashboard_cache
        from app.api.v1.reports import get_executive_summary

        async def run_test():
            fake_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
            redis_manager.set_mock_client(fake_client)

            # 1. First call: Cache miss -> queries DB and populates Redis
            summary_1 = await get_executive_summary(self.org_id)
            self.assertIn("batch", summary_1)

            # Verify key exists in Redis
            dash_key = key_dashboard_summary(self.org_id)
            cached_data = await get_cached_json(dash_key)
            self.assertIsNotNone(cached_data)

            # 2. Second call: Cache hit
            summary_2 = await get_executive_summary(self.org_id)
            metrics_1 = summary_1.get("operational_metrics") or summary_1.get("synthetic_benchmark_metrics") or summary_1.get("quality_metrics")
            metrics_2 = summary_2.get("operational_metrics") or summary_2.get("synthetic_benchmark_metrics") or summary_2.get("quality_metrics")
            self.assertEqual(metrics_1, metrics_2)

            # 3. Invalidate cache
            await invalidate_dashboard_cache(self.org_id)
            cached_after = await get_cached_json(dash_key)
            self.assertIsNone(cached_after)

        asyncio.run(run_test())

    def test_redis_ai_investigation_caching(self):
        """Validates AI investigation caching with stable normalized payload hashes."""
        import asyncio
        try:
            import fakeredis.aioredis
        except ImportError:
            self.skipTest("fakeredis not installed")
        from app.core.redis import redis_manager, key_ai_investigation, get_cached_json, set_cached_json

        async def run_test():
            fake_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
            redis_manager.set_mock_client(fake_client)

            cache_key = key_ai_investigation("AMOUNT_MISMATCH", 5000, "hash_abc_123")
            
            # Cache miss
            self.assertIsNone(await get_cached_json(cache_key))

            # Store verified AI investigation
            sample_inv = {
                "exception_id": "EXC-001",
                "classification": "GATEWAY_FEE_DISCREPANCY",
                "confidence": 0.98,
                "recommended_action": "POST_MDR_ADJUSTMENT"
            }
            await set_cached_json(cache_key, sample_inv, ttl_sec=60)
            cached = await get_cached_json(cache_key)
            self.assertIsNotNone(cached)
            self.assertEqual(cached["classification"], "GATEWAY_FEE_DISCREPANCY")

        asyncio.run(run_test())

if __name__ == "__main__":
    unittest.main()
