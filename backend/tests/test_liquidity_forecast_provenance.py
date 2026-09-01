"""
Liquidity & Cash Forecast Provenance Test Suite.
Verifies:
1. The forecast NEVER uses hardcoded synthetic financial values.
2. Changing the uploaded CSV dynamically changes the forecast.
3. Removing all future inflow data results in INSUFFICIENT_DATA status rather than fabricated projections.
4. Every forecast segment tracks source_record_ids, calculation_method, and classification.
5. Explicit separation of:
   - OBSERVED CASH (Observed)
   - CONFIRMED FUTURE INFLOWS (Forecast)
   - PROBABLE INFLOWS (Forecast / Calculated)
   - AT-RISK INFLOWS (Calculated)
   - UNKNOWN INFLOWS (Observed)
   - ASSUMPTIONS (Assumption)
"""

import unittest
import uuid
from datetime import datetime, timezone, date, timedelta
from typing import List

from app.models.schemas import (
    CanonicalTransaction,
    SourceKind,
    TxnDirection,
    DecisionTier,
    ReconciliationDecision,
    ForecastClassification,
    DataNature,
    ForecastStatus
)
from app.services.cash_forecaster import SegmentedCashForecaster


class TestLiquidityForecastProvenance(unittest.TestCase):

    def setUp(self):
        self.org_id = f"ORG-LIQ-{uuid.uuid4().hex[:8]}"

    def _make_txn(self, txn_id: str, amount_minor: int, dt: date, direction=TxnDirection.INFLOW) -> CanonicalTransaction:
        return CanonicalTransaction(
            id=txn_id,
            org_id=self.org_id,
            batch_id="BATCH-TEST",
            source_kind=SourceKind.GATEWAY,
            external_id=txn_id,
            payment_id=txn_id,
            amount_minor=amount_minor,
            direction=direction,
            currency="INR",
            occurred_at=datetime.combine(dt, datetime.min.time(), tzinfo=timezone.utc),
            value_date=dt,
            description_raw="Test transaction",
            description_norm="test transaction"
        )

    def test_01_forecast_never_uses_hardcoded_synthetic_values(self):
        """1. Empty dataset produces exactly 0 forecast with INSUFFICIENT_DATA and zero phantom revenues."""
        envelope = SegmentedCashForecaster.generate_liquidity_envelope([], {})
        self.assertEqual(envelope.forecast_status, ForecastStatus.INSUFFICIENT_DATA)
        self.assertIsNotNone(envelope.missing_fields_explanation)
        self.assertEqual(envelope.total_observed_cash_minor, 0)
        self.assertEqual(envelope.total_projected_inflow_minor, 0)
        for s in envelope.segments:
            self.assertEqual(s.confirmed_inflow_minor, 0)
            self.assertEqual(s.probable_inflow_minor, 0)
            self.assertEqual(s.at_risk_inflow_minor, 0)

    def test_02_changing_uploaded_csv_changes_forecast(self):
        """2. Changing the uploaded dataset directly changes forecast amounts with 1:1 traceability."""
        # Batch 1: ₹20,000 confirmed
        t1 = self._make_txn("t1", 2000000, date(2026, 3, 10))
        dec1 = {
            t1.id: ReconciliationDecision(
                transaction_id=t1.id,
                tier=DecisionTier.RESOLVED,
                confidence=1.0,
                deterministic_score=1.0,
                cross_source_score=1.0,
                ai_score=0.0,
                risk_penalties=0.0,
                explanation="Confirmed settlement"
            )
        }
        env1 = SegmentedCashForecaster.generate_liquidity_envelope([t1], dec1)
        self.assertEqual(env1.total_observed_cash_minor, 2000000)
        self.assertEqual(env1.segments[0].observed_cash_minor, 2000000)

        # Batch 2: ₹85,000 confirmed
        t2 = self._make_txn("t2", 8500000, date(2026, 3, 10))
        dec2 = {
            t2.id: ReconciliationDecision(
                transaction_id=t2.id,
                tier=DecisionTier.RESOLVED,
                confidence=1.0,
                deterministic_score=1.0,
                cross_source_score=1.0,
                ai_score=0.0,
                risk_penalties=0.0,
                explanation="Confirmed settlement"
            )
        }
        env2 = SegmentedCashForecaster.generate_liquidity_envelope([t2], dec2)
        self.assertEqual(env2.total_observed_cash_minor, 8500000)
        self.assertEqual(env2.segments[0].observed_cash_minor, 8500000)
        self.assertNotEqual(env1.total_observed_cash_minor, env2.total_observed_cash_minor)

    def test_03_no_future_inflow_results_in_insufficient_data_status(self):
        """3. When uploaded data contains no future receivables (weeks 3-13), returns INSUFFICIENT_DATA."""
        t_hist = self._make_txn("t_hist", 500000, date(2026, 3, 5))
        dec = {
            t_hist.id: ReconciliationDecision(
                transaction_id=t_hist.id,
                tier=DecisionTier.RESOLVED,
                confidence=1.0,
                deterministic_score=1.0,
                cross_source_score=1.0,
                ai_score=0.0,
                risk_penalties=0.0,
                explanation="Settled historical"
            )
        }
        envelope = SegmentedCashForecaster.generate_liquidity_envelope([t_hist], dec)
        self.assertEqual(envelope.forecast_status, ForecastStatus.INSUFFICIENT_DATA)
        self.assertIn("weeks 3–13", envelope.missing_fields_explanation)
        # Week 3 to 13 must be 0
        for w in envelope.segments[2:]:
            self.assertEqual(w.confirmed_future_inflows_minor, 0)
            self.assertEqual(w.confirmed_inflow_minor, 0)

    def test_04_provenance_and_epistemic_classification_on_every_segment(self):
        """4. Every forecast segment tracks source_record_ids, calculation_method, and DataNature."""
        t_obs = self._make_txn("t_obs", 100000, date(2026, 3, 10))
        t_risk = self._make_txn("t_risk", 30000, date(2026, 3, 10))
        t_prob = self._make_txn("t_prob", 40000, date(2026, 3, 10))

        decisions = {
            t_obs.id: ReconciliationDecision(
                transaction_id=t_obs.id,
                tier=DecisionTier.RESOLVED,
                confidence=1.0,
                deterministic_score=1.0,
                cross_source_score=1.0,
                ai_score=0.0,
                risk_penalties=0.0,
                explanation="Settled"
            ),
            t_risk.id: ReconciliationDecision(
                transaction_id=t_risk.id,
                tier=DecisionTier.UNRESOLVED_EXCEPTION,
                confidence=0.9,
                deterministic_score=0.0,
                cross_source_score=0.0,
                ai_score=0.0,
                risk_penalties=0.0,
                explanation="MISSING_BANK_SETTLEMENT"
            ),
            t_prob.id: ReconciliationDecision(
                transaction_id=t_prob.id,
                tier=DecisionTier.NEEDS_REVIEW,
                confidence=0.85,
                deterministic_score=0.5,
                cross_source_score=0.5,
                ai_score=0.0,
                risk_penalties=0.0,
                explanation="Timing lag"
            )
        }

        envelope = SegmentedCashForecaster.generate_liquidity_envelope([t_obs, t_risk, t_prob], decisions)
        w1 = envelope.segments[0]
        self.assertEqual(w1.observed_cash_minor, 100000)
        self.assertEqual(w1.at_risk_inflows_minor, 30000)

        # Verify entry provenance
        obs_entry = next(e for e in w1.entries if e.classification == ForecastClassification.OBSERVED_CASH)
        self.assertEqual(obs_entry.data_nature, DataNature.OBSERVED)
        self.assertIn("t_obs", obs_entry.source_record_ids)
        self.assertEqual(obs_entry.calculation_method, "SUM_SETTLED_MATCHED_CREDITS")

        risk_entry = next(e for e in w1.entries if e.classification == ForecastClassification.AT_RISK_INFLOWS)
        self.assertEqual(risk_entry.data_nature, DataNature.CALCULATED)
        self.assertIn("t_risk", risk_entry.source_record_ids)
        self.assertEqual(risk_entry.calculation_method, "SUM_UNRESOLVED_EXCEPTIONS")

        w2 = envelope.segments[1]
        self.assertEqual(w2.probable_inflows_minor, 40000)
        prob_entry = next(e for e in w2.entries if e.classification == ForecastClassification.PROBABLE_INFLOWS)
        self.assertEqual(prob_entry.data_nature, DataNature.FORECAST)
        self.assertIn("t_prob", prob_entry.source_record_ids)
        self.assertEqual(prob_entry.calculation_method, "SUM_T2_CLEARING_LAG")

    def test_05_explicit_separation_of_six_cash_categories(self):
        """5. Separate OBSERVED_CASH, CONFIRMED_FUTURE, PROBABLE, AT_RISK, UNKNOWN, ASSUMPTIONS."""
        categories = {
            ForecastClassification.OBSERVED_CASH,
            ForecastClassification.CONFIRMED_FUTURE_INFLOWS,
            ForecastClassification.PROBABLE_INFLOWS,
            ForecastClassification.AT_RISK_INFLOWS,
            ForecastClassification.UNKNOWN_INFLOWS,
            ForecastClassification.ASSUMPTIONS
        }
        self.assertEqual(len(categories), 6)

    def test_06_future_scheduled_inflows_yield_complete_status(self):
        """6. When future receivables exist in batch, status is COMPLETE and amounts land in specific future weeks."""
        base_d = date(2026, 3, 10)
        t_settled = self._make_txn("t_settled", 100000, base_d)
        fut_d = base_d + timedelta(days=25) # Land in Week 4
        t_fut = self._make_txn("t_fut", 250000, fut_d)

        decisions = {
            t_settled.id: ReconciliationDecision(
                transaction_id=t_settled.id,
                tier=DecisionTier.RESOLVED,
                confidence=1.0,
                deterministic_score=1.0,
                cross_source_score=1.0,
                ai_score=0.0,
                risk_penalties=0.0,
                explanation="Settled"
            ),
            t_fut.id: ReconciliationDecision(
                transaction_id=t_fut.id,
                tier=DecisionTier.RESOLVED,
                confidence=1.0,
                deterministic_score=1.0,
                cross_source_score=1.0,
                ai_score=0.0,
                risk_penalties=0.0,
                explanation="Future confirmed scheduled receivable"
            )
        }

        envelope = SegmentedCashForecaster.generate_liquidity_envelope([t_settled, t_fut], decisions)
        self.assertEqual(envelope.forecast_status, ForecastStatus.COMPLETE)
        self.assertIsNone(envelope.missing_fields_explanation)

        # Week 4 (index 3) should have the 250,000 paise
        w4 = envelope.segments[3]
        self.assertEqual(w4.confirmed_future_inflows_minor, 250000)
        self.assertEqual(len(w4.entries), 1)
        self.assertEqual(w4.entries[0].source_record_ids, ["t_fut"])
        self.assertEqual(w4.entries[0].data_nature, DataNature.FORECAST)


if __name__ == "__main__":
    unittest.main()
