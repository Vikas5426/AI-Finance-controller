"""
Versioned Fee Policy Engine for Recon.

Replaces hardcoded MDR percentages with explicit, auditable, and versioned
processor fee schedules, tax jurisdictions, rounding modes, caps, and refunds.
Preserves policy IDs and formula proofs in reconciliation evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class TaxJurisdiction(str, Enum):
    GST_INDIA_18 = "GST_IN_18"
    VAT_UAE_5 = "VAT_AE_5"
    ZERO_TAX = "TAX_EXEMPT_0"


class RoundingMode(str, Enum):
    ROUND_HALF_UP = "ROUND_HALF_UP"
    ROUND_DOWN = "ROUND_DOWN"
    ROUND_UP = "ROUND_UP"


@dataclass(frozen=True)
class FeeBreakdown:
    """Deterministic arithmetic output of a fee policy evaluation."""
    policy_id: str
    policy_name: str
    gross_minor: int
    mdr_rate_pct: float
    tax_rate_pct: float
    tax_jurisdiction: str
    fee_minor: int
    tax_minor: int
    total_deduction_minor: int
    expected_net_minor: int
    cap_applied: bool = False
    formula_proof: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "policy_name": self.policy_name,
            "gross_minor": self.gross_minor,
            "mdr_rate_pct": self.mdr_rate_pct,
            "tax_rate_pct": self.tax_rate_pct,
            "tax_jurisdiction": self.tax_jurisdiction,
            "fee_minor": self.fee_minor,
            "tax_minor": self.tax_minor,
            "total_deduction_minor": self.total_deduction_minor,
            "expected_net_minor": self.expected_net_minor,
            "cap_applied": self.cap_applied,
            "formula_proof": self.formula_proof,
        }


@dataclass(frozen=True)
class FeePolicy:
    """A versioned fee policy specification."""
    policy_id: str
    name: str
    processor_code: str  # e.g., "RAZORPAY", "STRIPE", "DIRECT_WIRE", "DEFAULT"
    mdr_rate: Decimal     # e.g., Decimal("0.02") for 2.0%
    tax_rate: Decimal     # e.g., Decimal("0.18") for 18% GST
    tax_jurisdiction: TaxJurisdiction = TaxJurisdiction.GST_INDIA_18
    rounding_mode: RoundingMode = RoundingMode.ROUND_HALF_UP
    cap_minor: Optional[int] = None       # Optional fee cap in paise
    min_fee_minor: Optional[int] = None   # Optional minimum fee in paise
    chargeback_fee_minor: int = 0
    refund_fee_reversal: bool = True
    version: str = "2026.1"
    is_active: bool = True

    def calculate(self, gross_minor: int) -> FeeBreakdown:
        """
        Calculates exact integer paise breakdown using Decimal arithmetic.
        """
        if gross_minor <= 0 or self.mdr_rate == Decimal("0"):
            return FeeBreakdown(
                policy_id=self.policy_id,
                policy_name=self.name,
                gross_minor=gross_minor,
                mdr_rate_pct=float(self.mdr_rate * 100),
                tax_rate_pct=float(self.tax_rate * 100),
                tax_jurisdiction=self.tax_jurisdiction.value,
                fee_minor=0,
                tax_minor=0,
                total_deduction_minor=0,
                expected_net_minor=gross_minor,
                cap_applied=False,
                formula_proof=f"Gross {gross_minor} - 0 Fee (Zero MDR Policy {self.policy_id}) = Net {gross_minor}"
            )

        gross_dec = Decimal(gross_minor)
        raw_fee = gross_dec * self.mdr_rate

        cap_applied = False
        if self.cap_minor is not None and raw_fee > Decimal(self.cap_minor):
            raw_fee = Decimal(self.cap_minor)
            cap_applied = True
        elif self.min_fee_minor is not None and raw_fee < Decimal(self.min_fee_minor):
            raw_fee = Decimal(self.min_fee_minor)

        fee_minor = int(raw_fee.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        raw_tax = Decimal(fee_minor) * self.tax_rate
        tax_minor = int(raw_tax.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

        total_deduction = fee_minor + tax_minor
        expected_net = gross_minor - total_deduction

        proof = (
            f"Gross: ₹{gross_minor/100:.2f} | Policy: {self.policy_id} ({self.name}) | "
            f"MDR {self.mdr_rate * 100:.1f}% = ₹{fee_minor/100:.2f} | "
            f"Tax ({self.tax_jurisdiction.value}) {self.tax_rate * 100:.1f}% = ₹{tax_minor/100:.2f} | "
            f"Net: ₹{expected_net/100:.2f}"
        )

        return FeeBreakdown(
            policy_id=self.policy_id,
            policy_name=self.name,
            gross_minor=gross_minor,
            mdr_rate_pct=float(self.mdr_rate * 100),
            tax_rate_pct=float(self.tax_rate * 100),
            tax_jurisdiction=self.tax_jurisdiction.value,
            fee_minor=fee_minor,
            tax_minor=tax_minor,
            total_deduction_minor=total_deduction,
            expected_net_minor=expected_net,
            cap_applied=cap_applied,
            formula_proof=proof
        )


class FeePolicyRegistry:
    """Registry of active, versioned fee policies across payment gateways."""

    _POLICIES: Dict[str, FeePolicy] = {
        "POL-MDR-STD-2026": FeePolicy(
            policy_id="POL-MDR-STD-2026",
            name="2.0% Standard MDR + 18% GST",
            processor_code="RAZORPAY",
            mdr_rate=Decimal("0.020"),
            tax_rate=Decimal("0.180"),
            tax_jurisdiction=TaxJurisdiction.GST_INDIA_18,
            version="2026.1"
        ),
        "POL-MDR-ENT-2026": FeePolicy(
            policy_id="POL-MDR-ENT-2026",
            name="1.5% Enterprise MDR + 18% GST",
            processor_code="RAZORPAY_ENTERPRISE",
            mdr_rate=Decimal("0.015"),
            tax_rate=Decimal("0.180"),
            tax_jurisdiction=TaxJurisdiction.GST_INDIA_18,
            version="2026.1"
        ),
        "POL-STRIPE-STD-2026": FeePolicy(
            policy_id="POL-STRIPE-STD-2026",
            name="Stripe 2.0% Standard MDR + 18% GST",
            processor_code="STRIPE",
            mdr_rate=Decimal("0.020"),
            tax_rate=Decimal("0.180"),
            tax_jurisdiction=TaxJurisdiction.GST_INDIA_18,
            version="2026.1"
        ),
        "POL-DIRECT-WIRE-2026": FeePolicy(
            policy_id="POL-DIRECT-WIRE-2026",
            name="0% Direct / Gross Net Wire",
            processor_code="DIRECT_WIRE",
            mdr_rate=Decimal("0.000"),
            tax_rate=Decimal("0.000"),
            tax_jurisdiction=TaxJurisdiction.ZERO_TAX,
            version="2026.1"
        ),
    }

    @classmethod
    def get_policy(cls, policy_id: str) -> Optional[FeePolicy]:
        return cls._POLICIES.get(policy_id)

    @classmethod
    def get_default_policy(cls) -> FeePolicy:
        return cls._POLICIES["POL-MDR-STD-2026"]

    @classmethod
    def list_active_policies(cls) -> List[FeePolicy]:
        return [p for p in cls._POLICIES.values() if p.is_active]

    @classmethod
    def register_policy(cls, policy: FeePolicy) -> None:
        cls._POLICIES[policy.policy_id] = policy

    @classmethod
    def match_best_policy(
        cls,
        gross_minor: int,
        net_minor: int,
        tolerance_minor: int = 100
    ) -> Optional[Tuple[FeePolicy, FeeBreakdown]]:
        """
        Tests active fee policies against observed gross and net amounts.
        Returns the matching policy and breakdown within tolerance, or None.
        """
        for policy in cls.list_active_policies():
            breakdown = policy.calculate(gross_minor)
            if abs(breakdown.expected_net_minor - net_minor) <= tolerance_minor:
                return policy, breakdown
        return None
