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

class ToolEvidence(BaseModel):
    tool: str
    rule_id: Optional[str] = None
    record_id: Optional[str] = None
    field: Optional[str] = None
    value: Optional[Any] = None

class InvestigationResult(BaseModel):
    exception_id: str
    classification: str
    likely_cause: str
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

class CashForecastSegment(BaseModel):
    week_number: int
    period_start: str
    period_end: str
    confirmed_inflow_minor: int
    probable_inflow_minor: int
    at_risk_inflow_minor: int
    unknown_inflow_minor: int
    risk_narrative: str

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


