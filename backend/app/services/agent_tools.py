"""
Deterministic Agent Tools for Recon
Deterministic calculations, indexed lookups, fee arithmetic, and SOP compliance.
These tools are invoked by the Reasoning Agent during exception investigation.
The LLM is NEVER permitted to calculate arithmetic or invent IDs on its own.
"""

from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from app.models.schemas import CanonicalTransaction, SourceKind, TxnDirection
from app.services.rules_engine import RuleEvaluator, DEFAULT_RULES
from app.services.fee_policy import FeePolicyRegistry
from app.services.period import ReportingPeriod, derive_period, _as_date


class TransactionLookupIndex:
    """Pre-built in-memory inverted index for O(1) candidate matching across feeds."""

    def __init__(self, transactions: List[CanonicalTransaction]):
        self.by_id: Dict[str, CanonicalTransaction] = {t.id: t for t in transactions}
        self.by_source: Dict[SourceKind, List[CanonicalTransaction]] = {}
        self.by_ref_key: Dict[str, List[CanonicalTransaction]] = {}
        self.by_amount_bucket: Dict[int, List[CanonicalTransaction]] = {} # 100-paise (₹1) buckets

        for txn in transactions:
            self.by_source.setdefault(txn.source_kind, []).append(txn)

            # Index all reference keys
            all_keys = set(
                txn.reference_keys.invoice +
                txn.reference_keys.payment +
                txn.reference_keys.utr +
                txn.reference_keys.settlement +
                txn.reference_keys.order +
                txn.reference_keys.je
            )
            if txn.external_id:
                all_keys.add(txn.external_id.strip().upper())

            for k in all_keys:
                if k:
                    self.by_ref_key.setdefault(k.strip().upper(), []).append(txn)

            # Amount bucket (rounded to nearest ₹10)
            bucket = txn.amount_minor // 1000
            self.by_amount_bucket.setdefault(bucket, []).append(txn)

    def find_candidates(
        self,
        primary_txn: CanonicalTransaction,
        amount_tolerance_minor: int = 5000,
        date_window_days: int = 7,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Fast indexed search for possible counterpart transactions in other feeds."""
        candidates: Dict[str, Tuple[CanonicalTransaction, List[str], int]] = {} # id -> (txn, reasons, score)

        # 1. Exact or partial Reference Key matching (Highest score)
        primary_keys = set(
            primary_txn.reference_keys.invoice +
            primary_txn.reference_keys.payment +
            primary_txn.reference_keys.utr +
            primary_txn.reference_keys.settlement +
            primary_txn.reference_keys.order +
            primary_txn.reference_keys.je
        )
        if primary_txn.external_id:
            primary_keys.add(primary_txn.external_id.strip().upper())

        for k in primary_keys:
            if not k:
                continue
            matched = self.by_ref_key.get(k.strip().upper(), [])
            for cand in matched:
                if cand.id != primary_txn.id and cand.source_kind != primary_txn.source_kind:
                    if cand.id not in candidates:
                        candidates[cand.id] = (cand, [f"Shared reference key: {k}"], 100)
                    else:
                        candidates[cand.id][1].append(f"Shared reference key: {k}")

        # 2. Amount & Date Proximity matching (Score 50-80)
        p_amt = primary_txn.amount_minor
        p_bucket = p_amt // 1000
        adjacent_buckets = [p_bucket - 1, p_bucket, p_bucket + 1]

        for b in adjacent_buckets:
            for cand in self.by_amount_bucket.get(b, []):
                if cand.id != primary_txn.id and cand.source_kind != primary_txn.source_kind:
                    diff_amt = abs(cand.amount_minor - p_amt)
                    if diff_amt <= amount_tolerance_minor:
                        diff_days = abs((cand.value_date - primary_txn.value_date).days)
                        if diff_days <= date_window_days:
                            reason = f"Amount delta ₹{diff_amt/100:.2f} within {diff_days}d window"
                            if cand.id not in candidates:
                                candidates[cand.id] = (cand, [reason], 60 - diff_days * 2)
                            else:
                                candidates[cand.id][1].append(reason)

        # Format candidate output
        sorted_cands = sorted(candidates.values(), key=lambda x: x[2], reverse=True)[:limit]
        results = []
        for cand_txn, reasons, score in sorted_cands:
            results.append({
                "id": cand_txn.id,
                "external_id": cand_txn.external_id,
                "source_kind": cand_txn.source_kind.value if hasattr(cand_txn.source_kind, "value") else str(cand_txn.source_kind),
                "amount_minor": cand_txn.amount_minor,
                "amount_rs": f"Rs. {cand_txn.amount_minor/100:.2f}",
                "direction": cand_txn.direction.value if hasattr(cand_txn.direction, "value") else str(cand_txn.direction),
                "occurred_at": str(cand_txn.occurred_at),
                "value_date": str(cand_txn.value_date),
                "description": cand_txn.description_raw,
                "match_reasons": reasons,
                "relevance_score": score
            })

        return results


def tool_lookup_candidates(
    primary_txn: CanonicalTransaction,
    all_txns: List[CanonicalTransaction],
    amount_tolerance_minor: int = 5000,
    date_window_days: int = 7
) -> List[Dict[str, Any]]:
    """Tool: Fast indexed search for candidate counterpart records."""
    index = TransactionLookupIndex(all_txns)
    return index.find_candidates(primary_txn, amount_tolerance_minor, date_window_days)


def tool_calculate_fee_split(
    gross_amount_minor: int,
    policy_id: Optional[str] = None,
    fee_tier: Optional[str] = None
) -> Dict[str, Any]:
    """
    Tool: Computes exact mathematical fee split using versioned FeePolicyRegistry.
    Preserves policy ID, tax jurisdiction, and formula proof.
    """
    if policy_id:
        policy = FeePolicyRegistry.get_policy(policy_id) or FeePolicyRegistry.get_default_policy()
    elif fee_tier and "1.5" in str(fee_tier):
        policy = FeePolicyRegistry.get_policy("POL-MDR-ENT-2026") or FeePolicyRegistry.get_default_policy()
    else:
        policy = FeePolicyRegistry.get_default_policy()

    breakdown = policy.calculate(gross_amount_minor)
    return breakdown.to_dict()


def tool_check_period_cutoff(
    occurred_at: Any,
    value_date: Any,
    bank_sla_days: int = 2,
    reporting_period: Optional[ReportingPeriod] = None
) -> Dict[str, Any]:
    """
    Tool: Evaluates period boundary cutoff timing differences (T+1/T+2 clearing lag)
    derived dynamically from reporting period boundaries.
    """
    val_d = _as_date(value_date) or _as_date(occurred_at) or date.today()
    
    if reporting_period is None:
        reporting_period = derive_period([{"value_date": val_d}])

    is_cutoff_lag = reporting_period.is_cutoff_date(val_d, window_days=bank_sla_days)
    expected_clearing_date = val_d + timedelta(days=bank_sla_days)

    return {
        "is_period_cutoff_timing_difference": is_cutoff_lag,
        "value_date": val_d.isoformat(),
        "period_start": reporting_period.start.isoformat(),
        "period_end": reporting_period.end.isoformat(),
        "period_source": reporting_period.source,
        "settlement_delay_days": bank_sla_days,
        "expected_bank_clearing_date": str(expected_clearing_date),
        "recommended_accounting_action": "ACCRUE_TO_CLEARING_1290" if is_cutoff_lag else "STANDARD_CLEARING",
        "target_account": "1290 In-Transit Clearing",
        "explanation": f"Transaction dated {val_d} evaluated against period boundary {reporting_period.end.isoformat()}. Under T+{bank_sla_days} banking SLA, settlement wire clears on {expected_clearing_date}."
    }


def tool_evaluate_sop_rules(context_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Tool: Evaluates organizational Standard Operating Procedures (SOP-01 to SOP-05)
    using zero-dependency deterministic rule evaluation.
    """
    return RuleEvaluator.evaluate_rules(DEFAULT_RULES, context_dict)
