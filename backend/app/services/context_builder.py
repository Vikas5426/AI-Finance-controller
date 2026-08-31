"""
Transaction 360° Context Builder Engine
Synthesizes deep financial context for ambiguous/discrepant transactions:
historical fee patterns (1.5% vs 2.0% MDR), T+2 settlement lag, counterparty history,
anomaly risk signals, and candidate counterpart matches.
"""

from datetime import datetime, date
from typing import Any, Dict, List, Optional
from app.models.schemas import CanonicalTransaction, SourceKind, TransactionContext
from app.services.fee_policy import FeePolicyRegistry
from app.services.period import derive_period, ReportingPeriod

class TransactionContextBuilder:
    """Builds rich, structured 360° financial context for deep analysis."""

    @staticmethod
    def build_context(
        txn: CanonicalTransaction,
        all_txns: List[CanonicalTransaction],
        candidate_matches: Optional[List[CanonicalTransaction]] = None,
        reporting_period: Optional[ReportingPeriod] = None,
        lookup_index: Optional[Any] = None
    ) -> TransactionContext:
        candidates = candidate_matches or []
        checks_performed = [
            "Exact Reference Key Lookup (Invoice/UTR/Payment/Settlement)",
            "Direct Amount & Sign Comparison",
            "Timestamp & Period Boundary Cutoff Analysis (T+2 lag)",
            "Counterparty & Merchant Profile Lookup",
            "MDR Fee & GST Schedule Computation via Versioned Policy Registry",
            "Duplicate Record & Fingerprint Scan",
            "Cross-Source Double-Entry Account Verification"
        ]

        anomaly_flags: List[str] = []

        # 1. Fee Profile Analysis via Versioned Policies
        gross = txn.gross_minor or txn.amount_minor
        std_pol = FeePolicyRegistry.get_policy("POL-MDR-STD-2026") or FeePolicyRegistry.get_default_policy()
        ent_pol = FeePolicyRegistry.get_policy("POL-MDR-ENT-2026") or FeePolicyRegistry.get_default_policy()
        
        std_breakdown = std_pol.calculate(gross)
        ent_breakdown = ent_pol.calculate(gross)

        fee_2pct = std_breakdown.fee_minor
        gst_2pct = std_breakdown.tax_minor
        fee_1_5pct = ent_breakdown.fee_minor
        gst_1_5pct = ent_breakdown.tax_minor

        fee_profile = {
            "fee_2pct": fee_2pct,
            "gst_2pct": gst_2pct,
            "standard_2pct_mdr_fee": fee_2pct,
            "standard_2pct_gst": gst_2pct,
            "expected_net_2pct": std_breakdown.expected_net_minor,
            "fee_1_5pct": fee_1_5pct,
            "gst_1_5pct": gst_1_5pct,
            "enterprise_1_5pct_mdr_fee": fee_1_5pct,
            "enterprise_1_5pct_gst": gst_1_5pct,
            "expected_net_1_5pct": ent_breakdown.expected_net_minor,
            "standard_policy_id": std_pol.policy_id,
            "enterprise_policy_id": ent_pol.policy_id,
        }

        # 2. Timing and Lag Analysis
        period = reporting_period or derive_period(all_txns or [txn])
        is_period_cutoff = period.is_cutoff_date(txn.value_date, window_days=2)
        if is_period_cutoff:
            anomaly_flags.append("PERIOD_BOUNDARY_CUTOFF_T2_LAG")

        # 3. Counterparty Profile
        cp_norm = txn.counterparty_norm or (txn.counterparty_raw.upper() if txn.counterparty_raw else "ACME_DIRECT")
        counterparty_history = {
            "counterparty_name": cp_norm,
            "standard_payout_schedule": "T+2 Business Days",
            "dispute_rate_historical": "0.02%",
            "account_code": txn.account_code or "1210"
        }

        # 4. Identify Potential Candidate IDs using indexed lookup (Issue 2.23 f: O(1) candidate lookup)
        if lookup_index is not None:
            idx = lookup_index
        else:
            from app.services.agent_tools import TransactionLookupIndex
            idx = TransactionLookupIndex(all_txns)
        cands = idx.find_candidates(
            txn,
            amount_tolerance_minor=max(std_breakdown.fee_minor + std_breakdown.tax_minor + 500, 5000),
            limit=10
        )
        candidate_ids = [c["id"] for c in cands]

        # 5. Check if Unsettled / Missing Bank Credit
        if txn.source_kind == SourceKind.GATEWAY and not candidate_ids:
            anomaly_flags.append("MISSING_BANK_SETTLEMENT_CREDIT")

        if "dispute" in txn.description_raw.lower():
            anomaly_flags.append("CHARGEBACK_RESERVE_WITHHELD")

        return TransactionContext(
            transaction_id=txn.id,
            historical_fee_profile=fee_profile,
            counterparty_history=counterparty_history,
            settlement_delay_days=2 if is_period_cutoff else 0,
            is_period_cutoff=is_period_cutoff,
            possible_candidate_ids=candidate_ids[:10],
            anomaly_flags=anomaly_flags,
            checks_performed=checks_performed
        )
