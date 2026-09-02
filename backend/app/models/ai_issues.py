"""
Pydantic Schemas for AI Issues Center
Canonical structured payload for unified financial issue priority reporting.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AIIssueCard(BaseModel):
    issue_id: str
    title: str
    type: str  # e.g., MISSING_LEDGER, MISSING_BANK, AMOUNT_MISMATCH, PERIOD_CUTOFF, FEE_VARIANCE, DUPLICATE
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    severity_rank: int = 1  # 1 for CRITICAL, 2 for HIGH, 3 for MEDIUM, 4 for LOW
    financial_impact: float = 0.0  # in INR
    financial_impact_formatted: str = "₹0.00"
    affected_records: int = 0
    status: str = "Needs Human Review"
    requires_human_review: bool = True
    confidence: float = 0.90  # 0.0 to 1.0
    what_happened: str = ""
    why_it_matters: str = ""
    likely_cause: str = ""
    likely_cause_is_inference: bool = True
    evidence: List[str] = Field(default_factory=list)
    recommended_action: str = ""
    owner: str = "Treasury Operations"
    next_step: str = ""
    arithmetic_proof: Optional[Dict[str, Any]] = None
    source_references: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)


class SystemicPattern(BaseModel):
    pattern_id: str
    pattern_name: str
    affected_count: int
    impact_inr: float
    impact_formatted: str = "₹0.00"
    root_cause_status: str = "SUPPORTED_HYPOTHESIS"  # CONFIRMED, SUPPORTED_HYPOTHESIS, UNKNOWN
    likely_systemic_cause: str
    recommended_remediation: str
    remediation_owner: str
    observed_evidence: List[str] = Field(default_factory=list)


class FinancialImpactBreakdown(BaseModel):
    total_exception_exposure: float = 0.0
    total_exception_exposure_formatted: str = "₹0.00"
    critical_exposure: float = 0.0
    critical_exposure_formatted: str = "₹0.00"
    high_exposure: float = 0.0
    high_exposure_formatted: str = "₹0.00"
    medium_exposure: float = 0.0
    medium_exposure_formatted: str = "₹0.00"
    low_exposure: float = 0.0
    low_exposure_formatted: str = "₹0.00"
    unresolved_exposure: float = 0.0
    unresolved_exposure_formatted: str = "₹0.00"


class AIIssuesReport(BaseModel):
    batch_id: Optional[str] = None
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    summary: str = ""
    overall_health: str = "HEALTHY"  # HEALTHY, ACTION_REQUIRED, CRITICAL_RISK, UNHEALTHY
    audit_integrity: str = "EMPTY"  # PASS, TAMPERED, EMPTY
    audit_integrity_detail: str = "Awaiting verification"
    total_issues: int = 0
    total_financial_impact: float = 0.0
    total_financial_impact_formatted: str = "₹0.00"
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    human_review_count: int = 0
    issues: List[AIIssueCard] = Field(default_factory=list)
    systemic_patterns: List[SystemicPattern] = Field(default_factory=list)
    financial_impact: FinancialImpactBreakdown = Field(default_factory=FinancialImpactBreakdown)
    controller_takeaway: str = ""
