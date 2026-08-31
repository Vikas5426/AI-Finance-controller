import uuid
from datetime import datetime, timezone, date
from sqlalchemy import (
    Column, String, Integer, BigInteger, Numeric, Boolean, Date, DateTime, Text, JSON, ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from app.db.database import Base

def generate_uuid():
    return str(uuid.uuid4())

def utc_now():
    return datetime.now(timezone.utc)

class Organization(Base):
    __tablename__ = "organizations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    base_currency = Column(String(3), nullable=False, default="INR")
    materiality_threshold_minor = Column(BigInteger, nullable=False, default=50000)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="analyst")
    full_name = Column(String(255), nullable=False)
    approval_limit_minor = Column(BigInteger, nullable=False, default=1000000)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class SourceProfile(Base):
    __tablename__ = "source_profiles"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    name = Column(String(100), nullable=False)
    source_kind = Column(String(50), nullable=False) # GATEWAY, BANK, LEDGER, SETTLEMENT
    column_mapping = Column(JSON, nullable=False)
    amount_scale = Column(Integer, nullable=False, default=100)
    date_formats = Column(JSON, nullable=False)
    timezone = Column(String(50), nullable=False, default="Asia/Kolkata")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class Upload(Base):
    __tablename__ = "uploads"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    source_profile_id = Column(String(36), ForeignKey("source_profiles.id"), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_size_bytes = Column(BigInteger, nullable=False)
    file_hash = Column(String(64), nullable=False)
    storage_path = Column(String(512), nullable=False)
    total_rows = Column(Integer, nullable=False, default=0)
    accepted_rows = Column(Integer, nullable=False, default=0)
    duplicate_rows = Column(Integer, nullable=False, default=0)
    rejected_rows = Column(Integer, nullable=False, default=0)
    status = Column(String(50), nullable=False, default="COMPLETED")
    uploaded_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class Batch(Base):
    __tablename__ = "batches"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    status = Column(String(50), nullable=False, default="PENDING")
    total_records = Column(Integer, nullable=False, default=0)
    matched_records = Column(Integer, nullable=False, default=0)
    exception_records = Column(Integer, nullable=False, default=0)
    match_rate = Column(Numeric(5, 4), nullable=False, default=0.0)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class BatchStep(Base):
    __tablename__ = "batch_steps"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    batch_id = Column(String(36), ForeignKey("batches.id"), nullable=False)
    step_name = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, default="PENDING")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    records_in = Column(Integer, nullable=False, default=0)
    records_out = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    batch_id = Column(String(36), ForeignKey("batches.id"), nullable=False)
    raw_record_id = Column(String(36), nullable=True)
    source_kind = Column(String(50), nullable=False)
    external_id = Column(String(255), nullable=False)
    txn_type = Column(String(50), nullable=False)
    direction = Column(String(50), nullable=False)
    amount_minor = Column(BigInteger, nullable=False)
    amount = Column(Numeric(18, 4), nullable=False)
    gross_minor = Column(BigInteger, nullable=True)
    fee_minor = Column(BigInteger, nullable=True)
    tax_minor = Column(BigInteger, nullable=True)
    currency = Column(String(3), nullable=False, default="INR")
    occurred_at = Column(DateTime, nullable=False)
    value_date = Column(Date, nullable=False)
    source_timezone = Column(String(50), nullable=False, default="Asia/Kolkata")
    counterparty_raw = Column(Text, nullable=True)
    counterparty_norm = Column(String(255), nullable=True)
    description_raw = Column(Text, nullable=False)
    description_norm = Column(Text, nullable=False)
    reference_keys = Column(JSON, nullable=False, default=dict)
    account_code = Column(String(50), nullable=True)
    match_status = Column(String(50), nullable=False, default="UNMATCHED")
    normalizer_version = Column(String(20), nullable=False, default="v1.0.0")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class Match(Base):
    __tablename__ = "matches"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    batch_id = Column(String(36), ForeignKey("batches.id"), nullable=False)
    match_type = Column(String(50), nullable=False)
    method = Column(String(50), nullable=False)
    score = Column(Numeric(5, 4), nullable=False)
    confidence = Column(Numeric(5, 4), nullable=False)
    solver_evidence = Column(JSON, nullable=True)
    status = Column(String(50), nullable=False, default="CONFIRMED")
    superseded_by = Column(String(36), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class MatchLeg(Base):
    __tablename__ = "match_legs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    match_id = Column(String(36), ForeignKey("matches.id"), nullable=False)
    transaction_id = Column(String(36), ForeignKey("transactions.id"), nullable=False)
    role = Column(String(50), nullable=False)
    signed_amount_minor = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class MatchCandidate(Base):
    __tablename__ = "match_candidates"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    batch_id = Column(String(36), ForeignKey("batches.id"), nullable=False)
    source_txn_id = Column(String(36), ForeignKey("transactions.id"), nullable=False)
    target_txn_id = Column(String(36), ForeignKey("transactions.id"), nullable=False)
    feature_scores = Column(JSON, nullable=False)
    total_score = Column(Numeric(5, 4), nullable=False)
    runner_up_margin = Column(Numeric(5, 4), nullable=True)
    pass_name = Column(String(50), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class ExceptionRecord(Base):
    __tablename__ = "exceptions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    batch_id = Column(String(36), ForeignKey("batches.id"), nullable=False)
    primary_txn_id = Column(String(36), ForeignKey("transactions.id"), nullable=True)
    counterpart_txn_id = Column(String(36), ForeignKey("transactions.id"), nullable=True)
    exception_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False, default="MEDIUM")
    state = Column(String(50), nullable=False, default="DETECTED")
    impact_minor = Column(BigInteger, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default="INR")
    assigned_to = Column(String(36), ForeignKey("users.id"), nullable=True)
    version = Column(Integer, nullable=False, default=1)
    detected_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class AIInvestigation(Base):
    __tablename__ = "ai_investigations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    exception_id = Column(String(36), ForeignKey("exceptions.id"), nullable=False)
    model = Column(String(100), nullable=False)
    classification = Column(String(100), nullable=False)
    likely_cause = Column(Text, nullable=False)
    confidence = Column(Numeric(5, 4), nullable=False)
    evidence = Column(JSON, nullable=False)
    policy_citations = Column(JSON, nullable=False)
    tokens_prompt = Column(Integer, nullable=False, default=0)
    tokens_completion = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=False, default=0)
    cost_inr = Column(Numeric(10, 4), nullable=False, default=0.0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class ResolutionProposal(Base):
    __tablename__ = "resolution_proposals"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    exception_id = Column(String(36), ForeignKey("exceptions.id"), nullable=False)
    investigation_id = Column(String(36), ForeignKey("ai_investigations.id"), nullable=True)
    action = Column(String(50), nullable=False)
    recommended_parameters = Column(JSON, nullable=False)
    justification = Column(Text, nullable=False)
    confidence = Column(Numeric(5, 4), nullable=False)
    requires_human_review = Column(Boolean, nullable=False, default=True)
    status = Column(String(50), nullable=False, default="PENDING_APPROVAL")
    verified_by_code = Column(Boolean, nullable=False, default=False)
    # Identity of the maker: the user whose batch run raised this voucher.
    # Segregation of duties needs a maker to compare the checker against, and
    # there was previously no such column, so maker == checker was undetectable.
    # Nullable because rows written before this column existed have no known maker.
    created_by = Column(String(36), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class Approval(Base):
    __tablename__ = "approvals"

    # One decision per proposal, enforced by the database rather than only by the
    # handler: the terminal-state check in the API can be raced by two concurrent
    # requests, and before this constraint existed the same proposal was approved
    # twice, producing two approval rows and two audit events for one adjustment.
    __table_args__ = (
        UniqueConstraint("proposal_id", name="uq_approvals_proposal_id"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    proposal_id = Column(String(36), ForeignKey("resolution_proposals.id"), nullable=False)
    exception_id = Column(String(36), ForeignKey("exceptions.id"), nullable=False)
    actor_id = Column(String(36), nullable=False)
    actor_type = Column(String(20), nullable=False)
    action = Column(String(50), nullable=False)
    decision_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    batch_id = Column(String(36), nullable=True)
    event_seq = Column(BigInteger, nullable=False)
    event_type = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(36), nullable=False)
    actor_id = Column(String(36), nullable=False)
    actor_type = Column(String(20), nullable=False)
    action = Column(String(100), nullable=False)
    payload = Column(JSON, nullable=False)
    prev_hash = Column(String(64), nullable=False)
    event_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class BatchReport(Base):
    __tablename__ = "batch_reports"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    batch_id = Column(String(36), ForeignKey("batches.id"), unique=True, nullable=False)
    report_json = Column(JSON, nullable=False)
    report_hash = Column(String(64), nullable=False)
    match_rate = Column(Numeric(5, 4), nullable=False)
    precision_rate = Column(Numeric(5, 4), nullable=True)
    recall_rate = Column(Numeric(5, 4), nullable=True)
    f1_score = Column(Numeric(5, 4), nullable=True)
    ece = Column(Numeric(5, 4), nullable=True)
    records_per_second = Column(Numeric(10, 2), nullable=False)
    total_exceptions = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class DistributedLock(Base):
    __tablename__ = "distributed_locks"

    lock_key = Column(String(255), primary_key=True)
    owner_token = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
