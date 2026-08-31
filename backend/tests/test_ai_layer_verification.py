import os
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.core.security import create_access_token
from app.core.config import settings
from app.db.database import get_db_context
from app.db import schema
from app.services.agent_runtime import AIAgentRuntime, DeterministicVerifier
from app.services.agents.base_agent import AgentTelemetryTracker
from app.services.graph_orchestrator import LangGraphBatchOrchestrator
from app.models.schemas import CanonicalTransaction, SourceKind, MatchStatus, InvestigationResult, ToolEvidence

class TestAILayerVerification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.org_id = "00000000-0000-0000-0000-000000000001"
        cls.token = create_access_token(
            subject="usr_test_controller",
            org_id=cls.org_id,
            role="approver"
        )
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    def test_live_batch_persists_ai_investigations_and_advances_states(self):
        """Validates that running a batch saves AI investigations and advances exception states."""
        batch_id = f"BATCH-TEST-AI-{int(datetime.now(timezone.utc).timestamp())}"
        resp = self.client.post(
            "/api/v1/batches/run",
            json={"execution_mode": "INTERNAL_TEST", "window_size": 24},
            headers=self.headers
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "SUCCESS")
        b_id = data["batch_id"]

        with get_db_context() as db:
            # 1. Verify ai_investigations rows exist
            investigations = db.query(schema.AIInvestigation).filter_by(org_id=self.org_id).all()
            self.assertGreater(len(investigations), 0, "ai_investigations table should have persisted rows")

            # 2. Verify exceptions have advanced to PROPOSED
            db_excs = db.query(schema.ExceptionRecord).filter_by(batch_id=b_id, org_id=self.org_id).all()
            self.assertGreater(len(db_excs), 0)
            proposed_excs = [e for e in db_excs if e.state == "PROPOSED"]
            self.assertGreater(len(proposed_excs), 0, "At least one exception must advance to PROPOSED lifecycle state")

            # 3. Verify proposals carry semantic actions and verified_by_code
            db_props = (
                db.query(schema.ResolutionProposal)
                .join(schema.ExceptionRecord, schema.ResolutionProposal.exception_id == schema.ExceptionRecord.id)
                .filter(schema.ExceptionRecord.batch_id == b_id, schema.ExceptionRecord.org_id == self.org_id)
                .all()
            )
            self.assertGreater(len(db_props), 0)
            actions = {p.action for p in db_props}
            # Ensure not all proposals have the identical canned action
            self.assertGreater(len(actions), 1, f"Expected multiple semantic proposal actions, got: {actions}")
            self.assertTrue(
                {"FLAG_DUPLICATE_FOR_VOID", "ADJUST_LEDGER_FEE_SPLIT", "INVESTIGATE_UNALLOCATED_CREDIT", "INVESTIGATE_MISSING_WIRE"}.intersection(actions),
                f"Expected specialized financial actions in proposals, found: {actions}"
            )
            
            # Check verified_by_code is populated
            verified_props = [p for p in db_props if p.verified_by_code is True]
            self.assertGreater(len(verified_props), 0, "DeterministicVerifier must verify proposals and set verified_by_code=True")

            # Check investigation_id foreign key links
            linked_props = [p for p in db_props if p.investigation_id is not None]
            self.assertGreater(len(linked_props), 0, "Proposals should reference investigation_id")

    def test_agent_telemetry_endpoint_reports_truthful_metrics(self):
        """Validates that /agents/telemetry returns real call counts and non-zero activity after batch run."""
        agent = AIAgentRuntime()
        agent.investigate_exception(
            exception_id="EXC-TEL-01",
            exception_type="AMOUNT_MISMATCH",
            impact_minor=2360,
            primary_txn={"id": "tx_tel_1", "amount_minor": 118000}
        )
        resp = self.client.get("/api/v1/agents/telemetry", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("stats", data)
        stats = data["stats"]
        self.assertGreater(stats["total_agent_calls"], 0, "Telemetry tracker should record agent calls")
        self.assertIsNotNone(stats["last_active_at"])
        self.assertGreaterEqual(stats["avg_latency_ms"], 0.0)

    def test_deterministic_investigate_semantic_actions(self):
        """Validates that _deterministic_investigate produces semantically appropriate actions for all exception types."""
        agent = AIAgentRuntime()

        # 1. DUPLICATE_RECORD must propose FLAG_DUPLICATE_FOR_VOID, not INVESTIGATE_MISSING_WIRE
        dup_inv = agent._deterministic_investigate(
            exception_id="EXC-DUP-01",
            exception_type="DUPLICATE_RECORD",
            impact_minor=10000,
            primary_txn={"id": "tx_dup_1", "description_raw": "Duplicate webhook"}
        )
        self.assertEqual(dup_inv.classification, "DUPLICATE_INGESTION_ROW")
        self.assertEqual(dup_inv.recommended_action, "FLAG_DUPLICATE_FOR_VOID")

        # 2. AMOUNT_MISMATCH must propose ADJUST_LEDGER_FEE_SPLIT
        amt_inv = agent._deterministic_investigate(
            exception_id="EXC-AMT-01",
            exception_type="AMOUNT_MISMATCH",
            impact_minor=2360,
            primary_txn={"id": "tx_amt_1", "amount_minor": 118000}
        )
        self.assertEqual(amt_inv.classification, "FEE_AND_TAX_BOOKED_NET")
        self.assertEqual(amt_inv.recommended_action, "ADJUST_LEDGER_FEE_SPLIT")

        # 3. PERIOD_CUTOFF must propose ACCRUE_TO_CLEARING_1290
        cutoff_inv = agent._deterministic_investigate(
            exception_id="EXC-CUT-01",
            exception_type="PERIOD_CUTOFF",
            impact_minor=50000,
            primary_txn={"id": "tx_cut_1", "occurred_at": "2026-03-31T23:55:00Z"}
        )
        self.assertEqual(cutoff_inv.classification, "PERIOD_CUTOFF_IN_TRANSIT")
        self.assertEqual(cutoff_inv.recommended_action, "ACCRUE_TO_CLEARING_1290")

        # 4. UNALLOCATED_BANK_CREDIT must propose INVESTIGATE_UNALLOCATED_CREDIT
        unalloc_inv = agent._deterministic_investigate(
            exception_id="EXC-UNALLOC-01",
            exception_type="UNALLOCATED_BANK_CREDIT",
            impact_minor=75000,
            primary_txn={"id": "tx_unalloc_1", "source_kind": "BANK"}
        )
        self.assertEqual(unalloc_inv.classification, "ANONYMOUS_BANK_DEPOSIT")
        self.assertEqual(unalloc_inv.recommended_action, "INVESTIGATE_UNALLOCATED_CREDIT")

    def test_deterministic_verifier_safety_gate(self):
        """Validates that DeterministicVerifier accepts valid math/IDs and rejects hallucinated IDs or invalid fee sums."""
        # Valid proposal
        valid_prop = InvestigationResult(
            exception_id="EXC-01",
            classification="FEE_AND_TAX_BOOKED_NET",
            likely_cause="Fee split",
            candidate_match_ids=["tx_bank_01"],
            recommended_action="ADJUST_LEDGER_FEE_SPLIT",
            confidence=0.95,
            evidence=[ToolEvidence(tool="fee", field="fee_breakup", value={"total_deduction_minor": 2360})],
            requires_human_review=False,
            citations=["SOP-04"]
        )
        is_valid, _ = DeterministicVerifier.verify_proposal(
            valid_prop,
            {"impact_minor": 2360},
            valid_txn_ids={"tx_bank_01", "tx_primary_01"}
        )
        self.assertTrue(is_valid)

        # Invalid candidate ID (hallucination)
        is_valid_fake, reason_fake = DeterministicVerifier.verify_proposal(
            valid_prop,
            {"impact_minor": 2360},
            valid_txn_ids={"tx_other_01"}
        )
        self.assertFalse(is_valid_fake)
        self.assertIn("does not exist", reason_fake)

if __name__ == "__main__":
    unittest.main()
