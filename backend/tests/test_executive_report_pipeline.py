"""
Executive Report Pipeline & Input Contract Verification Suite.
Verifies:
1. Executive report consumes verified outputs from:
   - Deterministic reconciliation engine
   - Exception engine
   - Systemic RCA agent
   - Liquidity / forecast engine
   - Cryptographic audit & compliance engine
2. Report uses exact values without recalculating or inventing numbers.
3. If RCA / Liquidity / Audit exists, report never denies their presence.
4. Missing components are explicitly marked NOT_AVAILABLE or INSUFFICIENT_DATA.
5. All financial figures are strictly traceable to deterministic sources.
"""

import unittest
import uuid
from typing import Any, Dict

from app.models.schemas import (
    ExecutiveReportInputContract,
    ReportReconciliationSection,
    ReportExceptionsSection,
    ReportRCASection,
    ReportLiquiditySection,
    ReportAuditSection,
    ReportProvenanceSection,
    SystemicRCAFinding,
    RootCauseStatus
)
from app.services.agents.report_agent import ReportGenerationAgent


class TestExecutiveReportPipeline(unittest.TestCase):

    def setUp(self):
        self.agent = ReportGenerationAgent()
        self.batch_id = f"BATCH-REP-{uuid.uuid4().hex[:6]}"

    def test_01_report_consumes_exact_reconciliation_values_without_inventing_numbers(self):
        """1. Report contains exact numbers from contract and zero fabricated constants."""
        contract = ExecutiveReportInputContract(
            batch_id=self.batch_id,
            reconciliation=ReportReconciliationSection(
                total_records=4,
                unique_transactions_count=4,
                source_counts={"GATEWAY": 2, "BANK": 2},
                matched_records=2,
                unmatched_records=2,
                exact_matches_count=1,
                contextual_matches_count=0,
                match_rate=50.0,
                total_gross_inr=499.00,
                execution_time_seconds=0.08
            ),
            exceptions=ReportExceptionsSection(
                total_exceptions=1,
                total_held_impact_inr=100.00,
                breakdown_by_type={"MISSING_BANK_SETTLEMENT": 1},
                pending_review_count=1,
                resolved_count=0
            ),
            rca=ReportRCASection(status="NOT_AVAILABLE"),
            liquidity=ReportLiquiditySection(status="NOT_AVAILABLE"),
            audit=ReportAuditSection(status="NOT_AVAILABLE"),
            provenance=ReportProvenanceSection(
                execution_mode="USER_UPLOAD",
                source_files=[{"filename": "gateway.csv", "sha256": "abc123hash"}],
                sha256_digests={"gateway.csv": "abc123hash"}
            )
        )

        res = self.agent.generate_controller_report(contract)
        md = res["full_markdown_report"]

        # Assert exact numbers appear in the markdown
        self.assertIn("4 canonical records", md)
        self.assertIn("50.0%", md)
        self.assertIn("₹100.00", md)
        self.assertNotIn("240 multi-stream", md, "Must not contain legacy hardcoded 240 constant")
        self.assertNotIn("98.5%", md, "Must not contain legacy hardcoded 98.5% constant")

    def test_02_report_consumes_verified_rca_and_never_claims_rca_missing_when_present(self):
        """2. When RCA data is supplied, report renders findings and does NOT say RCA was missing."""
        finding = SystemicRCAFinding(
            pattern_name="Gateway MDR Processing Deductions Booked Net",
            affected_count=2,
            impact_inr=236.00,
            affected_exception_ids=["EXC-1", "EXC-2"],
            affected_record_ids=["TXN-1", "TXN-2"],
            observed_evidence=["2 payments have gross captures booked net of MDR."],
            root_cause_status=RootCauseStatus.CONFIRMED,
            root_cause_explanation="Contractual MDR fee deduction matching registry.",
            confidence=0.98,
            recommended_remediation="Enable automated fee splitting rule.",
            remediation_owner="Accounting Operations"
        )

        contract = ExecutiveReportInputContract(
            batch_id=self.batch_id,
            reconciliation=ReportReconciliationSection(total_records=10, match_rate=80.0, matched_records=8),
            exceptions=ReportExceptionsSection(total_exceptions=2, total_held_impact_inr=236.00),
            rca=ReportRCASection(
                status="AVAILABLE",
                primary_bottleneck="MDR Fee Netting",
                systemic_risk_score=0.20,
                findings=[finding],
                operational_summary="MDR deductions accounted for across 2 records."
            ),
            liquidity=ReportLiquiditySection(status="NOT_AVAILABLE"),
            audit=ReportAuditSection(status="NOT_AVAILABLE"),
            provenance=ReportProvenanceSection()
        )

        res = self.agent.generate_controller_report(contract)
        md = res["full_markdown_report"]

        self.assertIn("Gateway MDR Processing Deductions Booked Net", md)
        self.assertIn("₹236.00", md)
        self.assertIn("CONFIRMED", md)
        self.assertNotIn("No RCA data was supplied", md)
        self.assertNotIn("Status:** `NOT_AVAILABLE` — Systemic root cause", md)

    def test_03_report_consumes_verified_liquidity_and_shows_insufficient_data_honestly(self):
        """3. When liquidity is supplied with INSUFFICIENT_DATA, report displays the exact explanation."""
        missing_exp = "Insufficient forward horizon data for weeks 3–13: no future scheduled invoices provided."
        contract = ExecutiveReportInputContract(
            batch_id=self.batch_id,
            reconciliation=ReportReconciliationSection(total_records=10, match_rate=100.0, matched_records=10),
            exceptions=ReportExceptionsSection(total_exceptions=0),
            rca=ReportRCASection(status="ZERO_EXCEPTIONS"),
            liquidity=ReportLiquiditySection(
                status="INSUFFICIENT_DATA",
                missing_fields_explanation=missing_exp,
                total_observed_cash_inr=5000.00,
                total_projected_inflow_inr=500.00,
                forward_weeks_status="INSUFFICIENT_DATA"
            ),
            audit=ReportAuditSection(status="NOT_AVAILABLE"),
            provenance=ReportProvenanceSection()
        )

        res = self.agent.generate_controller_report(contract)
        md = res["full_markdown_report"]

        self.assertIn("₹5,000.00", md)
        self.assertIn("₹500.00", md)
        self.assertIn("INSUFFICIENT_DATA", md)
        self.assertIn(missing_exp, md)
        self.assertNotIn("Liquidity insights are unavailable", md)

    def test_04_report_consumes_verified_audit_and_shows_5_control_states(self):
        """4. When audit is supplied, report renders all 5 compliance control states and auditor signoff."""
        contract = ExecutiveReportInputContract(
            batch_id=self.batch_id,
            reconciliation=ReportReconciliationSection(total_records=10, match_rate=100.0, matched_records=10),
            exceptions=ReportExceptionsSection(total_exceptions=0),
            rca=ReportRCASection(status="ZERO_EXCEPTIONS"),
            liquidity=ReportLiquiditySection(status="NOT_AVAILABLE"),
            audit=ReportAuditSection(
                status="AVAILABLE",
                hash_chain_integrity="VALID",
                maker_checker_status="FULLY_APPROVED",
                access_control_status="SEGREGATION_COMPLIANT",
                change_control_status="IMMUTABLE_LOG_VERIFIED",
                overall_compliance_status="AUDIT_READY",
                auditor_signed_off=True,
                auditor_id="usr_lead_auditor_ey",
                auditor_notes="Signed off"
            ),
            provenance=ReportProvenanceSection()
        )

        res = self.agent.generate_controller_report(contract)
        md = res["full_markdown_report"]

        self.assertIn("VALID", md)
        self.assertIn("FULLY_APPROVED", md)
        self.assertIn("SEGREGATION_COMPLIANT", md)
        self.assertIn("IMMUTABLE_LOG_VERIFIED", md)
        self.assertIn("AUDIT_READY", md)
        self.assertIn("usr_lead_auditor_ey", md)
        self.assertNotIn("Audit compliance data was not supplied", md)

    def test_05_missing_components_are_explicitly_marked_not_available(self):
        """5. Unsupplied sections are explicitly marked NOT_AVAILABLE without inventing values."""
        contract = ExecutiveReportInputContract(
            batch_id=self.batch_id,
            reconciliation=ReportReconciliationSection(total_records=10, match_rate=100.0, matched_records=10),
            exceptions=ReportExceptionsSection(total_exceptions=0),
            rca=ReportRCASection(status="NOT_AVAILABLE"),
            liquidity=ReportLiquiditySection(status="NOT_AVAILABLE"),
            audit=ReportAuditSection(status="NOT_AVAILABLE"),
            provenance=ReportProvenanceSection()
        )

        res = self.agent.generate_controller_report(contract)
        md = res["full_markdown_report"]

        self.assertIn("Status:** `NOT_AVAILABLE` — Systemic root cause diagnostics were not executed", md)
        self.assertIn("Status:** `NOT_AVAILABLE` — Forward liquidity projections were not provided", md)
        self.assertIn("Status:** `NOT_AVAILABLE` — Audit and compliance controls were not evaluated", md)


if __name__ == "__main__":
    unittest.main()
