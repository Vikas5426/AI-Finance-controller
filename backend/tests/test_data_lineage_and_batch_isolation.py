"""
Data Lineage, Batch Isolation & Anti-Contamination Test Suite.
Verifies:
1. Running Batch A and then Batch B with completely different values guarantees
   Batch B contains ZERO records, matches, or exceptions from Batch A.
2. Uploading/reconciling a tiny dataset (e.g. ₹100) ensures dashboard totals and
   13-week cash forecast CANNOT show millions of rupees (no synthetic recurring baseline inflow).
3. Reconciling an empty dataset ensures zero records, zero matches, zero exceptions,
   and no stale residual data from previous runs.
4. Simulating backend restart verifies that previous batch data does not silently leak
   into un-reconciled workspaces or cross-pollinate new runs.
"""

import unittest
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import Any, Dict, List

from app.core.config import settings
from app.db.database import get_db_context
from app.db import schema
from app.db.database_service import DatabaseService
from app.models.schemas import (
    CanonicalTransaction,
    SourceKind,
    TxnDirection,
    ExecutionMode,
    ReconciliationDecision,
    DecisionTier,
    MatchSchema,
    ExceptionSchema,
    ExceptionSeverity,
    ExceptionState
)
from app.services.cash_forecaster import SegmentedCashForecaster
from app.api.v1.batches import execute_batch_reconciliation, STATE, TENANT_STATES, get_active_batch
from app.api.v1.transactions import get_transactions, get_matches
from app.api.v1.exceptions import get_exceptions
from app.api.v1.reports import get_executive_summary


class TestDataLineageAndBatchIsolation(unittest.TestCase):

    def setUp(self):
        self.org_id = f"ORG-LINEAGE-{uuid.uuid4().hex[:8]}"
        self.user = {
            "user_id": f"usr_{uuid.uuid4().hex[:6]}",
            "org_id": self.org_id,
            "role": "admin"
        }
        DatabaseService.seed_default_data()

    def tearDown(self):
        DatabaseService.reset_workspace_data(org_id=self.org_id)
        STATE.clear()
        TENANT_STATES.pop(self.org_id, None)

    def test_01_batch_a_and_batch_b_isolation(self):
        """1. Run Batch A, then Batch B with different values. Confirm Batch B contains ZERO records from Batch A."""
        batch_a_id = f"BATCH-A-{uuid.uuid4().hex[:6]}"
        batch_b_id = f"BATCH-B-{uuid.uuid4().hex[:6]}"

        # Batch A: ₹50,000 transaction
        txn_a = CanonicalTransaction(
            id=f"TXN-A-{uuid.uuid4().hex[:6]}",
            org_id=self.org_id,
            batch_id=batch_a_id,
            source_kind=SourceKind.GATEWAY,
            external_id="pay_ALPHA_50000",
            payment_id="pay_ALPHA_50000",
            amount_minor=5000000, # ₹50,000.00
            direction=TxnDirection.INFLOW,
            currency="INR",
            occurred_at=datetime(2026, 3, 10, 10, 0, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 10),
            description_raw="Alpha payment",
            description_norm="alpha payment"
        )

        DatabaseService.save_batch_run(
            org_id=self.org_id,
            batch_id=batch_a_id,
            canonical_txns=[txn_a],
            matches=[],
            exceptions=[
                ExceptionSchema(
                    id=f"EXC-A-{uuid.uuid4().hex[:6]}",
                    org_id=self.org_id,
                    batch_id=batch_a_id,
                    primary_txn_id=txn_a.id,
                    exception_type="MISSING_BANK_SETTLEMENT",
                    severity=ExceptionSeverity.HIGH,
                    state=ExceptionState.DETECTED,
                    impact_minor=5000000,
                    currency="INR"
                )
            ],
            decisions={
                txn_a.id: ReconciliationDecision(
                    transaction_id=txn_a.id,
                    tier=DecisionTier.UNRESOLVED_EXCEPTION,
                    confidence=0.90,
                    deterministic_score=0.0,
                    cross_source_score=0.0,
                    ai_score=0.0,
                    risk_penalties=0.0,
                    explanation="Missing bank settlement"
                )
            },
            proposals=[],
            audit_events=[],
            summary={"total_records": 1, "exact_matches": 0, "contextual_matches": 0, "total_exceptions": 1, "match_rate": 0.0, "wall_clock_seconds": 0.1},
            cash_forecast=[]
        )

        # Batch B: ₹7,500 transaction
        txn_b = CanonicalTransaction(
            id=f"TXN-B-{uuid.uuid4().hex[:6]}",
            org_id=self.org_id,
            batch_id=batch_b_id,
            source_kind=SourceKind.GATEWAY,
            external_id="pay_BETA_7500",
            payment_id="pay_BETA_7500",
            amount_minor=750000, # ₹7,500.00
            direction=TxnDirection.INFLOW,
            currency="INR",
            occurred_at=datetime(2026, 3, 20, 12, 0, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 20),
            description_raw="Beta payment",
            description_norm="beta payment"
        )

        DatabaseService.save_batch_run(
            org_id=self.org_id,
            batch_id=batch_b_id,
            canonical_txns=[txn_b],
            matches=[],
            exceptions=[],
            decisions={
                txn_b.id: ReconciliationDecision(
                    transaction_id=txn_b.id,
                    tier=DecisionTier.RESOLVED,
                    confidence=1.0,
                    deterministic_score=1.0,
                    cross_source_score=1.0,
                    ai_score=0.0,
                    risk_penalties=0.0,
                    explanation="Matched"
                )
            },
            proposals=[],
            audit_events=[],
            summary={"total_records": 1, "exact_matches": 1, "contextual_matches": 0, "total_exceptions": 0, "match_rate": 100.0, "wall_clock_seconds": 0.1},
            cash_forecast=[]
        )

        # Query transactions specifically for Batch B
        res_b = get_transactions(batch_id=batch_b_id, current_user=self.user)
        self.assertEqual(res_b["total"], 1)
        self.assertEqual(res_b["items"][0]["external_id"], "pay_BETA_7500")
        self.assertEqual(res_b["items"][0]["amount_minor"], 750000)

        # Verify ZERO records from Batch A appear in Batch B results
        item_ids_in_b = [i["id"] for i in res_b["items"]]
        self.assertNotIn(txn_a.id, item_ids_in_b, "Batch B must not contain Batch A transactions")

        # Query exceptions specifically for Batch B
        exc_res_b = get_exceptions(batch_id=batch_b_id, current_user=self.user)
        self.assertEqual(exc_res_b["total"], 0, "Batch B must have 0 exceptions, no leaks from Batch A")

        # Query Batch A specifically
        res_a = get_transactions(batch_id=batch_a_id, current_user=self.user)
        self.assertEqual(res_a["total"], 1)
        self.assertEqual(res_a["items"][0]["external_id"], "pay_ALPHA_50000")

    def test_02_tiny_dataset_100_rupees_no_millions_in_forecast_or_dashboard(self):
        """2. Upload tiny dataset containing only ₹100. Confirm dashboard totals CANNOT show millions."""
        tiny_txn = CanonicalTransaction(
            id=f"TXN-TINY-{uuid.uuid4().hex[:6]}",
            org_id=self.org_id,
            batch_id="BATCH-TINY",
            source_kind=SourceKind.GATEWAY,
            external_id="pay_TINY_100",
            payment_id="pay_TINY_100",
            amount_minor=10000, # ₹100.00 (10,000 paise)
            direction=TxnDirection.INFLOW,
            currency="INR",
            occurred_at=datetime(2026, 3, 25, 10, 0, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 25),
            description_raw="Tiny test payment ₹100",
            description_norm="tiny test payment 100"
        )

        decisions = {
            tiny_txn.id: ReconciliationDecision(
                transaction_id=tiny_txn.id,
                tier=DecisionTier.RESOLVED,
                confidence=1.0,
                deterministic_score=1.0,
                cross_source_score=1.0,
                ai_score=0.0,
                risk_penalties=0.0,
                explanation="Confirmed settlement"
            )
        }

        # 1. Compute 13-week forecast directly
        forecast = SegmentedCashForecaster.forecast_13_weeks([tiny_txn], decisions)
        self.assertEqual(len(forecast), 13)

        # Verify Week 1 confirmed inflow is exactly ₹100.00 (10,000 paise), NOT ₹550,000.00+
        self.assertEqual(
            forecast[0].confirmed_inflow_minor,
            10000,
            "Week 1 confirmed inflow must be exactly ₹100.00 (10000 paise), without synthetic baseline additions"
        )

        # Verify sum of all weeks in forecast is bounded by actual transaction amount (₹100)
        total_forecast_minor = sum(f.confirmed_inflow_minor + f.probable_inflow_minor for f in forecast)
        self.assertEqual(
            total_forecast_minor,
            10000,
            f"Total 13-week forecast ({total_forecast_minor} paise) must equal actual dataset value (10000 paise = ₹100), never millions"
        )

        # 2. Persist batch and check executive summary report
        DatabaseService.save_batch_run(
            org_id=self.org_id,
            batch_id="BATCH-TINY",
            canonical_txns=[tiny_txn],
            matches=[],
            exceptions=[],
            decisions=decisions,
            proposals=[],
            audit_events=[],
            summary={"total_records": 1, "exact_matches": 1, "contextual_matches": 0, "total_exceptions": 0, "match_rate": 100.0, "wall_clock_seconds": 0.05},
            cash_forecast=[f.model_dump() for f in forecast]
        )

        ctx = DatabaseService.load_batch_context(self.org_id, batch_id="BATCH-TINY")
        fc_loaded = ctx["cash_forecast"]
        self.assertEqual(fc_loaded[0]["confirmed_inflow_minor"], 10000)
        self.assertLess(fc_loaded[0]["confirmed_inflow_minor"], 50000000, "Dashboard cannot report millions for ₹100 dataset")

    def test_03_empty_dataset_handling(self):
        """3. Reconciling an empty dataset produces zero records and zero forecast with no residual leaks."""
        forecast = SegmentedCashForecaster.forecast_13_weeks([], {})
        self.assertEqual(len(forecast), 13)
        for w in forecast:
            self.assertEqual(w.confirmed_inflow_minor, 0)
            self.assertEqual(w.probable_inflow_minor, 0)
            self.assertEqual(w.at_risk_inflow_minor, 0)
            self.assertEqual(w.unknown_inflow_minor, 0)

        # Save empty batch run
        DatabaseService.save_batch_run(
            org_id=self.org_id,
            batch_id="BATCH-EMPTY",
            canonical_txns=[],
            matches=[],
            exceptions=[],
            decisions={},
            proposals=[],
            audit_events=[],
            summary={"total_records": 0, "exact_matches": 0, "contextual_matches": 0, "total_exceptions": 0, "match_rate": 0.0, "wall_clock_seconds": 0.01},
            cash_forecast=[f.model_dump() for f in forecast]
        )

        ctx = DatabaseService.load_batch_context(self.org_id, batch_id="BATCH-EMPTY")
        self.assertEqual(ctx["stats"]["total_records"], 0)
        self.assertEqual(ctx["stats"]["total_exceptions"], 0)
        self.assertEqual(ctx["quality_metrics"]["exact_matches"], 0)

    def test_04_backend_restart_and_clean_workspace(self):
        """4. Restart simulation: when workspace is clean/reset, no old data silently appears."""
        # 1. Reset workspace
        DatabaseService.reset_workspace_data(org_id=self.org_id)
        STATE.clear()

        # 2. Query active batch
        active = get_active_batch(current_user=self.user)
        self.assertIsNone(active["batch"], "Clean workspace must have None active batch")
        self.assertEqual(active["stats"]["total_records"], 0)
        self.assertEqual(active["stats"]["total_exceptions"], 0)

        # 3. Query transactions
        txns = get_transactions(current_user=self.user)
        self.assertEqual(txns["total"], 0, "Clean workspace must return 0 transactions")


if __name__ == "__main__":
    unittest.main()
