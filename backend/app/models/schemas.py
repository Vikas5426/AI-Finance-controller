"""
Pydantic v2 Canonical Schemas for Quality-First Financial Reconciliation Controller
"""

from datetime import datetime, timezone, date
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class SourceKind(str, Enum):
    GATEWAY = "GATEWAY"
    BANK = "BANK"
    LEDGER = "LEDGER"
    SETTLEMENT = "SETTLEMENT"

class TxnDirection(str, Enum):
    INFLOW = "INFLOW"
    OUTFLOW = "OUTFLOW"
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"

class MatchStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    MATCHED = "MATCHED"
    EXCEPTION = "EXCEPTION"
    NEEDS_REVIEW = "NEEDS_REVIEW"

class MatchTypeEnum(str, Enum):
    ONE_TO_ONE = "1:1"
    ONE_TO_MANY = "1:N"
    MANY_TO_ONE = "N:1"
    MANY_TO_MANY = "N:M"

class MatchMethodEnum(str, Enum):
    EXACT_ID = "EXACT_ID"
    RULE_GATE = "RULE_GATE"
    FUZZY_HUNGARIAN = "FUZZY_HUNGARIAN"
    SETTLEMENT_NET_DP = "SETTLEMENT_NET_DP"
    CONTEXTUAL_AI = "CONTEXTUAL_AI"

class LegRoleEnum(str, Enum):
    PRIMARY = "PRIMARY"
    COUNTERPART = "COUNTERPART"
    FEE = "FEE"
    TAX = "TAX"

class FeatureScores(BaseModel):
    s_id: float = 0.0
    s_amt: float = 0.0
    s_date: float = 0.0
    s_desc: float = 0.0
    s_cp: float = 0.0
    s_ctx: float = 0.0

class MatchCandidate(BaseModel):
    id: str
    source_txn_id: str
    target_txn_id: str
    feature_scores: FeatureScores
    total_score: float
    pass_name: str

class DecisionTier(str, Enum):
    RESOLVED = "RESOLVED"                                     # Tier 1: 100% Deterministic match
    RESOLVED_WITH_EXPLANATION = "RESOLVED_WITH_EXPLANATION"   # Tier 2: Contextual match + verified AI proof
    NEEDS_REVIEW = "NEEDS_REVIEW"                             # Tier 3: Ambiguous match / Material discrepancy
    UNRESOLVED_EXCEPTION = "UNRESOLVED_EXCEPTION"             # Tier 4: Honest un-reconciled exception

class ExceptionSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class ExceptionState(str, Enum):
    DETECTED = "DETECTED"
    INVESTIGATING = "INVESTIGATING"
    PROPOSED = "PROPOSED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"

class ReferenceKeys(BaseModel):
    invoice: List[str] = Field(default_factory=list)
    settlement: List[str] = Field(default_factory=list)
    utr: List[str] = Field(default_factory=list)
    payment: List[str] = Field(default_factory=list)
    order: List[str] = Field(default_factory=list)
    je: List[str] = Field(default_factory=list)
    custom: Dict[str, str] = Field(default_factory=dict)

class JournalLine(BaseModel):
    line_no: int
    account_code: str
    account_name: Optional[str] = None
    direction: TxnDirection
    amount_minor: int
    original_amount: Optional[str] = None
    memo: Optional[str] = None
    doc_ref: Optional[str] = None

class CanonicalTransaction(BaseModel):
    id: str
    org_id: str
    batch_id: str
    window_id: Optional[str] = None
    source_kind: SourceKind
    external_id: str
    direction: TxnDirection
    amount_minor: int
    gross_minor: Optional[int] = None
    fee_minor: Optional[int] = None
    tax_minor: Optional[int] = None
    currency: str = "INR"
    occurred_at: datetime
    value_date: date
    source_timezone: str = "Asia/Kolkata"
    counterparty_raw: Optional[str] = None
    counterparty_norm: Optional[str] = None
    description_raw: str
    description_norm: str
    reference_keys: ReferenceKeys = Field(default_factory=ReferenceKeys)
    account_code: Optional[str] = None
    match_status: str = "UNMATCHED"
    
    # Complete Source Lineage & Entity Distinction
    source_row_id: Optional[str] = None
    source_row_number: Optional[int] = None
    payment_id: Optional[str] = None
    order_id: Optional[str] = None
    settlement_id: Optional[str] = None
    journal_id: Optional[str] = None
    journal_line_no: Optional[int] = None
    original_amount: Optional[str] = None
    normalized_amount: Optional[int] = None
    original_date: Optional[str] = None
    normalized_date: Optional[date] = None
    source_reference: Optional[str] = None
    
    # Compound GL Journal Entry Representation
    lines: List[JournalLine] = Field(default_factory=list)
    is_duplicate_source_row: bool = False
    is_balanced_je: Optional[bool] = None
    total_debit_minor: Optional[int] = None
    total_credit_minor: Optional[int] = None

class ToolEvidence(BaseModel):
    tool: str
    rule_id: Optional[str] = None
    record_id: Optional[str] = "SYSTEM"
    field: Optional[str] = None
    value: Optional[Any] = None

class AIExceptionContext(BaseModel):
    batch_id: str
    exception_id: str
    classification: str
    payment_id: Optional[str] = None
    source_records: List[Dict[str, Any]] = Field(default_factory=list)
    matched_records: List[Dict[str, Any]] = Field(default_factory=list)
    gross_amount: float
    fee: float
    tax: float
    expected_net_settlement: float
    actual_bank_settlement: Optional[float] = None
    variance: float
    capture_date: Optional[str] = None
    settlement_date: Optional[str] = None
    timing_window: str = "T+2 Banking Days (0 <= days <= 7)"
    deterministic_rules: List[str] = Field(default_factory=list)
    deterministic_result: str

class InvestigationResult(BaseModel):
    exception_id: str
    classification: str
    likely_cause: str
    facts: List[str] = Field(default_factory=list)
    observations: List[str] = Field(default_factory=list)
    possible_cause: Optional[str] = None
    recommendation: Optional[str] = None
    candidate_match_ids: List[str] = Field(default_factory=list)
    recommended_action: str
    confidence: float
    evidence: List[ToolEvidence] = Field(default_factory=list)
    risk_flags: List[str] = Field(default_factory=list)
    requires_human_review: bool = True
    citations: List[str] = Field(default_factory=list)
    arithmetic_proof: Optional[Dict[str, Any]] = None
    telemetry: Optional[Dict[str, Any]] = None

class TransactionContext(BaseModel):
    transaction_id: str
    historical_fee_profile: Optional[Dict[str, Any]] = None
    counterparty_history: Optional[Dict[str, Any]] = None
    settlement_delay_days: int = 0
    is_period_cutoff: bool = False
    possible_candidate_ids: List[str] = Field(default_factory=list)
    anomaly_flags: List[str] = Field(default_factory=list)
    checks_performed: List[str] = Field(default_factory=list)

class ReconciliationDecision(BaseModel):
    transaction_id: str
    tier: DecisionTier
    confidence: float
    deterministic_score: float
    cross_source_score: float
    ai_score: float
    risk_penalties: float
    explanation: str
    evidence_summary: List[str] = Field(default_factory=list)
    matched_counterpart_id: Optional[str] = None
    requires_maker_checker: bool = False

class BatchWindowSummary(BaseModel):
    window_index: int
    window_id: str
    records_count: int
    start_index: int
    end_index: int
    status: str
    exact_matches: int = 0
    contextual_matches: int = 0
    ai_investigated: int = 0
    exceptions_count: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class MatchLegSchema(BaseModel):
    transaction_id: str
    role: str # PRIMARY, COUNTERPART, FEE, TAX
    signed_amount_minor: int

class MatchSchema(BaseModel):
    id: str
    batch_id: str
    window_id: Optional[str] = None
    match_type: MatchTypeEnum
    method: MatchMethodEnum
    score: float
    confidence: float
    solver_evidence: Optional[Dict[str, Any]] = None
    legs: List[MatchLegSchema] = Field(default_factory=list)
    decision_tier: DecisionTier = DecisionTier.RESOLVED

class ExceptionSchema(BaseModel):
    id: str
    org_id: str
    batch_id: str
    window_id: Optional[str] = None
    primary_txn_id: Optional[str] = None
    counterpart_txn_id: Optional[str] = None
    exception_type: str
    severity: ExceptionSeverity
    state: ExceptionState
    impact_minor: int
    currency: str = "INR"
    checks_performed: List[str] = Field(default_factory=list)
    findings: List[str] = Field(default_factory=list)
    resolution_confidence: float = 0.0
    recommended_action: Optional[str] = None
    investigation: Optional[InvestigationResult] = None
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ForecastClassification(str, Enum):
    OBSERVED_CASH = "OBSERVED_CASH"
    CONFIRMED_FUTURE_INFLOWS = "CONFIRMED_FUTURE_INFLOWS"
    PROBABLE_INFLOWS = "PROBABLE_INFLOWS"
    AT_RISK_INFLOWS = "AT_RISK_INFLOWS"
    UNKNOWN_INFLOWS = "UNKNOWN_INFLOWS"
    ASSUMPTIONS = "ASSUMPTIONS"

class DataNature(str, Enum):
    OBSERVED = "Observed"
    CALCULATED = "Calculated"
    FORECAST = "Forecast"
    ASSUMPTION = "Assumption"

class ForecastStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class ForecastEntry(BaseModel):
    week_number: int
    amount_minor: int
    amount_inr: float
    classification: ForecastClassification
    data_nature: DataNature
    source_record_ids: List[str] = Field(default_factory=list)
    calculation_method: str
    assumption_ids: List[str] = Field(default_factory=list)
    narrative: str

class CashForecastSegment(BaseModel):
    week_number: int
    period_start: str
    period_end: str
    observed_cash_minor: int = 0
    confirmed_future_inflows_minor: int = 0
    probable_inflows_minor: int = 0
    at_risk_inflows_minor: int = 0
    unknown_inflows_minor: int = 0
    assumptions_minor: int = 0
    
    # Backwards-compatible aliases
    confirmed_inflow_minor: int = 0
    probable_inflow_minor: int = 0
    at_risk_inflow_minor: int = 0
    unknown_inflow_minor: int = 0
    
    entries: List[ForecastEntry] = Field(default_factory=list)
    risk_narrative: str

class LiquidityForecastEnvelope(BaseModel):
    forecast_status: ForecastStatus
    missing_fields_explanation: Optional[str] = None
    as_of_date: str
    total_observed_cash_minor: int
    total_projected_inflow_minor: int
    segments: List[CashForecastSegment] = Field(default_factory=list)
    provenance_summary: Dict[str, Any] = Field(default_factory=dict)

class ExecutionMode(str, Enum):
    USER_UPLOAD = "USER_UPLOAD"
    INTERNAL_TEST = "INTERNAL_TEST"
    MOCK = "MOCK"
    SYNTHETIC_BENCHMARK = "SYNTHETIC_BENCHMARK"

class ProvenanceSourceType(str, Enum):
    USER_UPLOAD = "USER_UPLOAD"
    TEST_FIXTURE = "TEST_FIXTURE"
    DATABASE = "DATABASE"
    SYNTHETIC = "SYNTHETIC"
    UNKNOWN = "UNKNOWN"

class SourceProvenance(BaseModel):
    batch_id: str
    source_kind: SourceKind
    source_type: ProvenanceSourceType
    original_filename: str
    absolute_file_path: str
    sha256_hash: str
    file_size_bytes: int
    raw_rows_count: int
    parsed_rows_count: int
    normalized_rows_count: int
    first_3_record_ids: List[str] = Field(default_factory=list)
    last_3_record_ids: List[str] = Field(default_factory=list)

class BatchProvenanceManifest(BaseModel):
    batch_id: str
    execution_mode: ExecutionMode = ExecutionMode.USER_UPLOAD
    overall_source_type: ProvenanceSourceType
    sources: Dict[str, SourceProvenance] = Field(default_factory=dict)
    total_raw_rows: int = 0
    total_normalized_records: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class RootCauseStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    SUPPORTED_HYPOTHESIS = "SUPPORTED_HYPOTHESIS"
    UNKNOWN = "UNKNOWN"

class SystemicRCAFinding(BaseModel):
    pattern_name: str
    affected_count: int
    impact_inr: float
    affected_exception_ids: List[str] = Field(default_factory=list)
    affected_record_ids: List[str] = Field(default_factory=list)
    observed_evidence: List[str] = Field(default_factory=list)
    root_cause_status: RootCauseStatus
    root_cause_explanation: str
    confidence: float
    recommended_remediation: str
    remediation_owner: str

class SystemicRCAResult(BaseModel):
    batch_id: str
    total_exceptions_analyzed: int
    total_impact_inr: float
    systemic_risk_score: float
    systemic_findings: List[SystemicRCAFinding] = Field(default_factory=list)
    operational_summary: str
    preventative_action_items: List[str] = Field(default_factory=list)
    telemetry: Dict[str, Any] = Field(default_factory=dict)

class HashChainIntegrityStatus(str, Enum):
    VALID = "VALID"
    TAMPERED = "TAMPERED"
    EMPTY = "EMPTY"

class MakerCheckerStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    FULLY_APPROVED = "FULLY_APPROVED"
    SEGREGATION_VIOLATION = "SEGREGATION_VIOLATION"
    MISSING_CHECKER = "MISSING_CHECKER"
    NO_APPROVALS_REQUIRED = "NO_APPROVALS_REQUIRED"

class AccessControlStatus(str, Enum):
    ENFORCED = "ENFORCED"
    SEGREGATION_COMPLIANT = "SEGREGATION_COMPLIANT"
    VIOLATION_DETECTED = "VIOLATION_DETECTED"
    UNVERIFIABLE_ACTORS = "UNVERIFIABLE_ACTORS"

class ChangeControlStatus(str, Enum):
    IMMUTABLE_LOG_VERIFIED = "IMMUTABLE_LOG_VERIFIED"
    UNAUTHORIZED_MODIFICATION = "UNAUTHORIZED_MODIFICATION"
    LOGS_UNVERIFIED = "LOGS_UNVERIFIED"

class OverallComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    PENDING_ACTION = "PENDING_ACTION"
    AUDIT_READY = "AUDIT_READY"

class ApprovalRecordSchema(BaseModel):
    id: str
    exception_id: str
    proposal_id: str
    maker_id: str
    checker_id: Optional[str] = None
    maker_timestamp: str
    checker_timestamp: Optional[str] = None
    approval_status: str # "PENDING_CHECKER", "APPROVED", "REJECTED", "SEGREGATION_VIOLATION"
    segregation_check: bool # maker_id != checker_id and checker_id is not None
    decision_notes: Optional[str] = None

class AuditorSignOffState(BaseModel):
    is_signed_off: bool = False
    signed_by_auditor_id: Optional[str] = None
    signed_at: Optional[str] = None
    auditor_notes: Optional[str] = None
    system_event_id: Optional[str] = None

class ComplianceAssessment(BaseModel):
    batch_id: str
    hash_chain_integrity: HashChainIntegrityStatus
    maker_checker_status: MakerCheckerStatus
    access_control_status: AccessControlStatus
    change_control_status: ChangeControlStatus
    overall_compliance_status: OverallComplianceStatus
    
    total_exceptions: int
    pending_review_count: int
    completed_approvals_count: int
    segregation_violations_count: int
    
    approvals: List[ApprovalRecordSchema] = Field(default_factory=list)
    auditor_sign_off: AuditorSignOffState = Field(default_factory=AuditorSignOffState)
    controls_breakdown: Dict[str, Any] = Field(default_factory=dict)

class ReportReconciliationSection(BaseModel):
    total_records: int = 0
    unique_transactions_count: int = 0
    source_counts: Dict[str, int] = Field(default_factory=dict)
    matched_records: int = 0
    unmatched_records: int = 0
    exact_matches_count: int = 0
    contextual_matches_count: int = 0
    match_rate: float = 0.0
    total_gross_inr: float = 0.0
    execution_time_seconds: float = 0.0

class ReportExceptionsSection(BaseModel):
    total_exceptions: int = 0
    total_held_impact_inr: float = 0.0
    breakdown_by_type: Dict[str, int] = Field(default_factory=dict)
    breakdown_by_severity: Dict[str, int] = Field(default_factory=dict)
    pending_review_count: int = 0
    resolved_count: int = 0

class ReportRCASection(BaseModel):
    status: str = "NOT_AVAILABLE" # AVAILABLE, NOT_AVAILABLE, ZERO_EXCEPTIONS
    primary_bottleneck: Optional[str] = None
    systemic_risk_score: Optional[float] = None
    findings: List[SystemicRCAFinding] = Field(default_factory=list)
    operational_summary: Optional[str] = None

class ReportLiquiditySection(BaseModel):
    status: str = "INSUFFICIENT_DATA" # COMPLETE, PARTIAL, INSUFFICIENT_DATA, NOT_AVAILABLE
    missing_fields_explanation: Optional[str] = None
    total_observed_cash_inr: float = 0.0
    total_projected_inflow_inr: float = 0.0
    week_1_inflow_inr: float = 0.0
    week_2_inflow_inr: float = 0.0
    forward_weeks_status: str = "INSUFFICIENT_DATA"

class ReportAuditSection(BaseModel):
    status: str = "NOT_AVAILABLE" # AVAILABLE, NOT_AVAILABLE
    hash_chain_integrity: str = "EMPTY" # VALID, TAMPERED, EMPTY
    maker_checker_status: str = "PENDING_REVIEW" # FULLY_APPROVED, PENDING_REVIEW, SEGREGATION_VIOLATION, NO_APPROVALS_REQUIRED
    access_control_status: str = "ENFORCED"
    change_control_status: str = "IMMUTABLE_LOG_VERIFIED"
    overall_compliance_status: str = "PENDING_ACTION"
    auditor_signed_off: bool = False
    auditor_id: Optional[str] = None
    auditor_notes: Optional[str] = None

class ReportProvenanceSection(BaseModel):
    execution_mode: str = "USER_UPLOAD"
    source_files: List[Dict[str, Any]] = Field(default_factory=list)
    sha256_digests: Dict[str, str] = Field(default_factory=dict)

class ExecutiveReportInputContract(BaseModel):
    batch_id: str
    reconciliation: ReportReconciliationSection
    exceptions: ReportExceptionsSection
    rca: ReportRCASection
    liquidity: ReportLiquiditySection
    audit: ReportAuditSection
    provenance: ReportProvenanceSection




