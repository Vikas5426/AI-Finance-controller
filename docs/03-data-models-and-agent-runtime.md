# 03 — Data Models, Database DDL & AI Agent Runtime

## 8. Database Architecture & PostgreSQL 16 DDL

The database is PostgreSQL 16 with extensions `pg_trgm` (trigram text similarity), `btree_gin`, and `pgcrypto`. Every table is org-scoped with Row-Level Security (RLS). Money is stored strictly as signed minor integer units (`BIGINT` paise/cents) alongside `NUMERIC(18,4)` for human-readable audit views. Never use floating-point types for monetary values.

### 8.1 Extensions and Schema Setup

```sql
-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gin";

-- Custom Types and Enums
CREATE TYPE user_role AS ENUM ('viewer', 'analyst', 'approver', 'admin');
CREATE TYPE source_kind AS ENUM ('GATEWAY', 'BANK', 'LEDGER', 'SETTLEMENT');
CREATE TYPE txn_direction AS ENUM ('INFLOW', 'OUTFLOW', 'DEBIT', 'CREDIT');
CREATE TYPE match_status AS ENUM ('UNMATCHED', 'CANDIDATE', 'MATCHED', 'EXCEPTION');
CREATE TYPE match_type_enum AS ENUM ('ONE_TO_ONE', 'ONE_TO_MANY', 'MANY_TO_ONE', 'MANY_TO_MANY');
CREATE TYPE match_method_enum AS ENUM ('EXACT_ID', 'RULE', 'SCORED_FUZZY', 'NET_SETTLEMENT', 'MANUAL_LINK');
CREATE TYPE leg_role_enum AS ENUM ('PRIMARY', 'COUNTERPART', 'FEE', 'TAX', 'REFUND', 'CHARGEBACK', 'ADJUSTMENT', 'ROUNDING');
CREATE TYPE exception_severity AS ENUM ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL');
CREATE TYPE exception_state AS ENUM ('DETECTED', 'TRIAGED', 'INVESTIGATING', 'PROPOSED', 'PENDING_APPROVAL', 'RESOLVED', 'CLOSED', 'REJECTED', 'ESCALATED', 'SUPERSEDED');
CREATE TYPE proposal_action AS ENUM ('AUTO_RESOLVE_TOLERANCE', 'ADJUST_LEDGER_FEE_SPLIT', 'LINK_CANDIDATES', 'WRITE_OFF_MATERIALITY', 'RECLASSIFY_TIMING', 'FLAG_FOR_VENDOR_DISPUTE', 'MANUAL_JOURNAL_ENTRY');
CREATE TYPE proposal_status AS ENUM ('PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'APPLIED', 'SUPERSEDED');
CREATE TYPE actor_type_enum AS ENUM ('user', 'agent', 'system');
```

### 8.2 Core Tenancy, Identity, and Ingestion Tables

```sql
-- Organizations
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    base_currency VARCHAR(3) NOT NULL DEFAULT 'INR',
    materiality_threshold_minor BIGINT NOT NULL DEFAULT 50000, -- ₹500.00
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role user_role NOT NULL DEFAULT 'analyst',
    full_name VARCHAR(255) NOT NULL,
    approval_limit_minor BIGINT NOT NULL DEFAULT 1000000, -- ₹10,000.00
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_users_org_id ON users(org_id);

-- Source Configuration Profiles
CREATE TABLE source_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    name VARCHAR(100) NOT NULL,
    source_kind source_kind NOT NULL,
    column_mapping JSONB NOT NULL,     -- e.g. {"date": "Txn Date", "amount": "Credit", "ref": "Ref No"}
    amount_scale INT NOT NULL DEFAULT 100, -- 100 for INR paise / USD cents, 1 for JPY
    date_formats JSONB NOT NULL,       -- ["%d/%m/%Y", "%Y-%m-%d"]
    timezone VARCHAR(50) NOT NULL DEFAULT 'Asia/Kolkata',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_source_profiles_org ON source_profiles(org_id);

-- Ingestion Upload Batches
CREATE TABLE uploads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    source_profile_id UUID NOT NULL REFERENCES source_profiles(id),
    file_name VARCHAR(255) NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    file_hash CHAR(64) NOT NULL, -- SHA-256 of raw bytes
    storage_path VARCHAR(512) NOT NULL, -- MinIO/S3 URI
    total_rows INT NOT NULL DEFAULT 0,
    accepted_rows INT NOT NULL DEFAULT 0,
    duplicate_rows INT NOT NULL DEFAULT 0,
    rejected_rows INT NOT NULL DEFAULT 0,
    status VARCHAR(50) NOT NULL DEFAULT 'COMPLETED',
    uploaded_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_uploads_org_file_hash ON uploads(org_id, file_hash);

-- Raw Ingested Records (Immutable, Append-Only)
CREATE TABLE raw_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    upload_id UUID NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    source_kind source_kind NOT NULL,
    row_number INT NOT NULL,
    content_hash CHAR(64) NOT NULL, -- SHA-256(source_id || canonical_json(payload))
    payload JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_raw_records_dedupe ON raw_records(org_id, upload_id, content_hash);
CREATE INDEX idx_raw_records_upload ON raw_records(upload_id);
```

### 8.3 Canonical Financial Transactions & Batches

```sql
-- Reconciliation Batches
CREATE TABLE batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING', -- PENDING, PROCESSING, COMPLETED, FAILED
    total_records INT NOT NULL DEFAULT 0,
    matched_records INT NOT NULL DEFAULT 0,
    exception_records INT NOT NULL DEFAULT 0,
    match_rate NUMERIC(5,4) NOT NULL DEFAULT 0.0000,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_batches_org_period ON batches(org_id, period_start, period_end);

-- DAG Execution Steps
CREATE TABLE batch_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    step_name VARCHAR(50) NOT NULL, -- P0_DEDUPE, P1_EXACT, P2_RULE, P3_FUZZY, P4_SETTLEMENT, P5_RESIDUALS, REPORT
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    records_in INT NOT NULL DEFAULT 0,
    records_out INT NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_batch_steps_batch_step ON batch_steps(batch_id, step_name);

-- Canonical Transactions Table
CREATE TABLE transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    batch_id UUID NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    raw_record_id UUID NOT NULL REFERENCES raw_records(id) ON DELETE RESTRICT,
    source_kind source_kind NOT NULL,
    external_id VARCHAR(255) NOT NULL,
    txn_type VARCHAR(50) NOT NULL,
    direction txn_direction NOT NULL,
    amount_minor BIGINT NOT NULL, -- signed minor units (Paise/Cents)
    amount NUMERIC(18,4) NOT NULL, -- human-readable display amount
    gross_minor BIGINT,
    fee_minor BIGINT,
    tax_minor BIGINT,
    currency VARCHAR(3) NOT NULL DEFAULT 'INR',
    occurred_at TIMESTAMPTZ NOT NULL,
    value_date DATE NOT NULL,
    source_timezone VARCHAR(50) NOT NULL DEFAULT 'Asia/Kolkata',
    counterparty_raw TEXT,
    counterparty_norm VARCHAR(255),
    description_raw TEXT NOT NULL,
    description_norm TEXT NOT NULL,
    reference_keys JSONB NOT NULL DEFAULT '{}'::jsonb, -- e.g. {"invoice":["INV-01"],"utr":["N123"]}
    account_code VARCHAR(50),
    match_status match_status NOT NULL DEFAULT 'UNMATCHED',
    normalizer_version VARCHAR(20) NOT NULL DEFAULT 'v1.0.0',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Performance and Indexing Strategy for Matching Engine
CREATE INDEX idx_txns_org_batch_status ON transactions(org_id, batch_id, match_status);
CREATE INDEX idx_txns_blocking ON transactions(batch_id, match_status, source_kind, currency, direction, value_date, amount_minor);
CREATE INDEX idx_txns_ref_keys_gin ON transactions USING gin (reference_keys);
CREATE INDEX idx_txns_desc_norm_trgm ON transactions USING gin (description_norm gin_trgm_ops);
CREATE INDEX idx_txns_cp_norm ON transactions(counterparty_norm);
```

### 8.4 Matching, Exceptions, and Workflow Tables

```sql
-- Scored Match Candidates (Retained for auditability & explainability)
CREATE TABLE match_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    batch_id UUID NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    source_txn_id UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    target_txn_id UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    feature_scores JSONB NOT NULL, -- {s_id: 1.0, s_amt: 0.98, s_date: 0.90, s_desc: 0.85, ...}
    total_score NUMERIC(5,4) NOT NULL,
    runner_up_margin NUMERIC(5,4),
    pass_name VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_match_candidates_source ON match_candidates(source_txn_id);
CREATE INDEX idx_match_candidates_target ON match_candidates(target_txn_id);

-- Confirmed / Approved Matches
CREATE TABLE matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    batch_id UUID NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    match_type match_type_enum NOT NULL,
    method match_method_enum NOT NULL,
    score NUMERIC(5,4) NOT NULL,
    confidence NUMERIC(5,4) NOT NULL,
    solver_evidence JSONB, -- arithmetic decomposition, formula breakdown, or solver proof
    status VARCHAR(50) NOT NULL DEFAULT 'CONFIRMED', -- CONFIRMED, SUPERSEDED, REVERSED
    superseded_by UUID REFERENCES matches(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_matches_org_batch ON matches(org_id, batch_id);

-- Match Legs (Multi-legged balance check)
CREATE TABLE match_legs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    match_id UUID NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    transaction_id UUID NOT NULL REFERENCES transactions(id) ON DELETE RESTRICT,
    role leg_role_enum NOT NULL,
    signed_amount_minor BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_match_legs_match ON match_legs(match_id);
CREATE INDEX idx_match_legs_txn ON match_legs(transaction_id);

-- Exceptions Table (Primary Work Object)
CREATE TABLE exceptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    batch_id UUID NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    primary_txn_id UUID REFERENCES transactions(id) ON DELETE RESTRICT,
    counterpart_txn_id UUID REFERENCES transactions(id) ON DELETE RESTRICT,
    exception_type VARCHAR(50) NOT NULL, -- AMOUNT_MISMATCH, MISSING_BANK_RECORD, TIMING_DIFFERENCE, etc.
    severity exception_severity NOT NULL DEFAULT 'MEDIUM',
    state exception_state NOT NULL DEFAULT 'DETECTED',
    impact_minor BIGINT NOT NULL DEFAULT 0,
    currency VARCHAR(3) NOT NULL DEFAULT 'INR',
    assigned_to UUID REFERENCES users(id),
    version INT NOT NULL DEFAULT 1, -- Optimistic locking
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_exceptions_org_state ON exceptions(org_id, state);
CREATE INDEX idx_exceptions_batch ON exceptions(batch_id);

-- AI Agent Investigations
CREATE TABLE ai_investigations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    exception_id UUID NOT NULL REFERENCES exceptions(id) ON DELETE CASCADE,
    model VARCHAR(100) NOT NULL,
    classification VARCHAR(100) NOT NULL,
    likely_cause TEXT NOT NULL,
    confidence NUMERIC(5,4) NOT NULL,
    evidence JSONB NOT NULL,
    policy_citations JSONB NOT NULL,
    tokens_prompt INT NOT NULL DEFAULT 0,
    tokens_completion INT NOT NULL DEFAULT 0,
    duration_ms INT NOT NULL DEFAULT 0,
    cost_inr NUMERIC(10,4) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_investigations_exc ON ai_investigations(exception_id);

-- AI Agent Tool Invocations
CREATE TABLE agent_tool_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    investigation_id UUID NOT NULL REFERENCES ai_investigations(id) ON DELETE CASCADE,
    tool_name VARCHAR(100) NOT NULL,
    tool_input JSONB NOT NULL,
    tool_output JSONB NOT NULL,
    execution_time_ms INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_agent_tool_calls_inv ON agent_tool_calls(investigation_id);

-- Resolution Proposals
CREATE TABLE resolution_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    exception_id UUID NOT NULL REFERENCES exceptions(id) ON DELETE CASCADE,
    investigation_id UUID REFERENCES ai_investigations(id),
    action proposal_action NOT NULL,
    recommended_parameters JSONB NOT NULL,
    justification TEXT NOT NULL,
    confidence NUMERIC(5,4) NOT NULL,
    requires_human_review BOOLEAN NOT NULL DEFAULT TRUE,
    status proposal_status NOT NULL DEFAULT 'PENDING_APPROVAL',
    verified_by_code BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_resolution_proposals_exc ON resolution_proposals(exception_id);

-- Maker-Checker Approvals
CREATE TABLE approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    proposal_id UUID NOT NULL REFERENCES resolution_proposals(id) ON DELETE RESTRICT,
    exception_id UUID NOT NULL REFERENCES exceptions(id) ON DELETE RESTRICT,
    actor_id UUID NOT NULL, -- User ID or System Principal
    actor_type actor_type_enum NOT NULL,
    action VARCHAR(20) NOT NULL, -- APPROVED, REJECTED, OVERRIDDEN
    decision_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_approvals_proposal ON approvals(proposal_id);
```

### 8.5 Governance, Policy Rules & Cryptographic Audit Trail

```sql
-- Declarative Reconciliation Rules
CREATE TABLE rules (
    id VARCHAR(50) PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    version INT NOT NULL DEFAULT 1,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    rule_condition JSONB NOT NULL, -- {"when": [...], "then": {...}}
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    effective_from DATE NOT NULL,
    effective_to DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_rules_org_active ON rules(org_id, is_active);

-- SOP / Policy Knowledge Documents (Tag-based retrieval)
CREATE TABLE sop_documents (
    id VARCHAR(50) PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    title VARCHAR(255) NOT NULL,
    tags JSONB NOT NULL, -- ["FEE_DISCREPANCY", "GATEWAY", "MDR", "GST"]
    content TEXT NOT NULL,
    version VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_sop_tags_gin ON sop_documents USING gin (tags);

-- Counterparty Aliases
CREATE TABLE counterparty_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    alias_raw VARCHAR(255) NOT NULL,
    alias_norm VARCHAR(255) NOT NULL,
    canonical_name VARCHAR(255) NOT NULL,
    canonical_id VARCHAR(100),
    confidence NUMERIC(5,4) NOT NULL DEFAULT 1.0,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_cp_aliases_org_norm ON counterparty_aliases(org_id, alias_norm);

-- Immutable Tamper-Evident SHA-256 Audit Chain
CREATE TABLE audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    event_seq BIGSERIAL NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id UUID NOT NULL,
    actor_id UUID NOT NULL,
    actor_type actor_type_enum NOT NULL,
    action VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    prev_hash CHAR(64) NOT NULL,
    event_hash CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_audit_events_seq ON audit_events(org_id, event_seq);
CREATE INDEX idx_audit_events_entity ON audit_events(entity_type, entity_id);

-- Period Batch Snapshots
CREATE TABLE batch_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    batch_id UUID NOT NULL UNIQUE REFERENCES batches(id) ON DELETE RESTRICT,
    report_json JSONB NOT NULL,
    report_hash CHAR(64) NOT NULL, -- SHA-256 snapshot seal
    match_rate NUMERIC(5,4) NOT NULL,
    precision_rate NUMERIC(5,4),
    recall_rate NUMERIC(5,4),
    f1_score NUMERIC(5,4),
    ece NUMERIC(5,4), -- Expected Calibration Error
    records_per_second NUMERIC(10,2) NOT NULL,
    total_exceptions INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 8.6 Immutability Triggers

```sql
-- Trigger: Prevent updates or deletes on raw records, audit logs, and reports
CREATE OR REPLACE FUNCTION enforce_table_immutability()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Table % is immutable. UPDATE and DELETE operations are strictly forbidden.', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_raw_records_immutable
BEFORE UPDATE OR DELETE ON raw_records
FOR EACH ROW EXECUTE FUNCTION enforce_table_immutability();

CREATE TRIGGER trg_audit_events_immutable
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION enforce_table_immutability();

CREATE TRIGGER trg_batch_reports_immutable
BEFORE UPDATE OR DELETE ON batch_reports
FOR EACH ROW EXECUTE FUNCTION enforce_table_immutability();

CREATE TRIGGER trg_approvals_immutable
BEFORE UPDATE OR DELETE ON approvals
FOR EACH ROW EXECUTE FUNCTION enforce_table_immutability();
```

---

## 9. Canonical Schemas & Pydantic v2 Models

Pydantic v2 is used as the single source of truth across the API boundary, the deterministic matching engine, and LLM structured outputs.

```python
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    CANDIDATE = "CANDIDATE"
    MATCHED = "MATCHED"
    EXCEPTION = "EXCEPTION"

class ReferenceKeys(BaseModel):
    invoice: List[str] = Field(default_factory=list)
    order: List[str] = Field(default_factory=list)
    payment: List[str] = Field(default_factory=list)
    settlement: List[str] = Field(default_factory=list)
    utr: List[str] = Field(default_factory=list)
    je: List[str] = Field(default_factory=list)

class CanonicalTransaction(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    org_id: UUID
    batch_id: UUID
    raw_record_id: UUID
    source_kind: SourceKind
    external_id: str
    txn_type: str
    direction: TxnDirection
    amount_minor: int = Field(description="Amount in minor units (paise/cents)")
    amount: Decimal = Field(description="Standard decimal unit for human display")
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
    reference_keys: ReferenceKeys
    account_code: Optional[str] = None
    match_status: MatchStatus = MatchStatus.UNMATCHED
    normalizer_version: str = "v1.0.0"

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        if len(v) != 3:
            raise ValueError("Currency must be a 3-letter ISO code")
        return v.upper()

class FeatureScores(BaseModel):
    s_id: float = Field(ge=0.0, le=1.0)
    s_amt: float = Field(ge=0.0, le=1.0)
    s_date: float = Field(ge=0.0, le=1.0)
    s_desc: float = Field(ge=0.0, le=1.0)
    s_cp: float = Field(ge=0.0, le=1.0)
    s_ctx: float = Field(ge=0.0, le=1.0)

class ToolEvidence(BaseModel):
    tool: str
    record_id: Optional[str] = None
    rule_id: Optional[str] = None
    field: Optional[str] = None
    value: Optional[Any] = None

class InvestigationResult(BaseModel):
    """Schema returned by LLM investigator and validated before ingestion"""
    exception_id: str
    classification: str
    likely_cause: str = Field(description="Clear, fact-based financial explanation")
    candidate_match_ids: List[str] = Field(default_factory=list)
    recommended_action: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[ToolEvidence]
    requires_human_review: bool = True
    citations: List[str] = Field(default_factory=list)
```

---

## 10. AI Agent Investigation Runtime

The AI Agent acts strictly as a read-only financial analyst. It is bounded by rigid system constraints:
- **Maximum 6 tool calls** per investigation.
- **Strict 60-second execution timeout**.
- **12,000 token maximum context budget**.
- **Zero direct write access** to Postgres or financial balances.
- **Anthropic Prompt Caching** enabled for static system instructions and SOP policy texts.

### 10.1 Agent Architecture & Model Routing

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        AI INVESTIGATION RUNTIME                        │
│                                                                        │
│  Exception Context (Pre-fetched deterministic findings + SOP tags)     │
│                                  │                                     │
│                                  ▼                                     │
│  Model Router:                                                         │
│  • Low Severity / Immaterial → Claude 3.5 Haiku (Fast triage)          │
│  • High Severity / Complex   → Claude 3.7 / 3.5 Sonnet (Deep analysis) │
│                                  │                                     │
│                                  ▼                                     │
│  Bounded Tool-Use Loop (Max 6 steps, read-only tools, org-scoped)      │
│  ├── get_transaction_details(txn_id)                                   │
│  ├── get_counterparty_history(counterparty_norm, lookback_days)        │
│  ├── get_reconciliation_rules(rule_ids)                                │
│  ├── search_similar_past_exceptions(exception_type, limit)             │
│  └── get_batch_context(batch_id)                                       │
│                                  │                                     │
│                                  ▼                                     │
│  Structured Output Extraction (Pydantic InvestigationResult)          │
│                                  │                                     │
│                                  ▼                                     │
│  Deterministic Verifier Gate (Re-checks arithmetic & foreign keys)     │
│  ├── Math Check: Does claimed fee split equal abs_diff_minor?         │
│  ├── Foreign Key Check: Do candidate_match_ids exist in batch?        │
│  └── Policy Check: Are cited SOPs valid?                              │
│                                  │                                     │
│          ┌───────────────────────┴───────────────────────┐             │
│          ▼                                               ▼             │
│     [ PASSED ]                                      [ FAILED ]         │
│  Persist proposal                             Reject proposal          │
│  Route to Approvals Queue                     Route directly to human  │
│  (or auto-apply if within policy)             with validation errors   │
└────────────────────────────────────────────────────────────────────────┘
```

### 10.2 System Prompt & Prompt Caching Strategy

```python
INVESTIGATION_SYSTEM_PROMPT = """
You are the AI Financial Controller Investigation Agent.
Your responsibility is to analyze reconciliation exceptions between payment gateways, bank statements, and general ledgers.

CORE OPERATING PRINCIPLES:
1. You are a PROPOSER, not an executor. You have zero authority to alter balances or post transactions.
2. NEVER guess or fabricate numbers. Every financial variance must tie out to exact minor units (paise/cents).
3. Always inspect raw fee breakdowns, tax calculations, and timestamps before asserting a root cause.
4. If the discrepancy cannot be explained with 100% arithmetic certainty, state the ambiguity and recommend human review.

You have access to read-only tools to fetch transaction details, counterparty patterns, rules, and historical exceptions.
"""

def build_cached_prompt(sop_texts: List[str]) -> List[Dict[str, Any]]:
    """Builds prompt structure utilizing Anthropic prompt caching on static SOPs"""
    return [
        {
            "type": "text",
            "text": INVESTIGATION_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"}
        },
        {
            "type": "text",
            "text": f"CURRENT APPLICABLE STANDARD OPERATING PROCEDURES (SOPs):\n\n" + "\n\n".join(sop_texts),
            "cache_control": {"type": "ephemeral"}
        }
    ]
```

### 10.3 Tool Definitions (JSON Schema for Claude)

```json
[
  {
    "name": "get_transaction_details",
    "description": "Fetch full raw and normalized transaction metadata, fee breakup, and reference keys by ID.",
    "input_schema": {
      "type": "object",
      "properties": {
        "transaction_id": {"type": "string", "description": "UUID of the transaction"}
      },
      "required": ["transaction_id"]
    }
  },
  {
    "name": "get_counterparty_history",
    "description": "Fetch historical settlement latency and variance patterns for a specific normalized counterparty.",
    "input_schema": {
      "type": "object",
      "properties": {
        "counterparty_norm": {"type": "string", "description": "Normalized counterparty slug"},
        "lookback_days": {"type": "integer", "default": 90}
      },
      "required": ["counterparty_norm"]
    }
  },
  {
    "name": "get_reconciliation_rules",
    "description": "Fetch the active rule definition and parameters for specified rule IDs.",
    "input_schema": {
      "type": "object",
      "properties": {
        "rule_ids": {"type": "array", "items": {"type": "string"}}
      },
      "required": ["rule_ids"]
    }
  },
  {
    "name": "search_similar_past_exceptions",
    "description": "Find previously resolved exceptions of the same type to inspect human approval decisions.",
    "input_schema": {
      "type": "object",
      "properties": {
        "exception_type": {"type": "string"},
        "limit": {"type": "integer", "default": 5}
      },
      "required": ["exception_type"]
    }
  }
]
```

### 10.4 Deterministic Post-Verification Engine

The verifier ensures that no hallucinations or invalid proposals enter the system:

```python
class DeterministicVerifier:
    """Hard-gate verifier that re-executes arithmetic before accepting LLM proposals."""

    @staticmethod
    def verify_proposal(
        proposal: InvestigationResult,
        exception_ctx: Dict[str, Any],
        valid_txn_ids: set[str],
        valid_rules: set[str]
    ) -> tuple[bool, Optional[str]]:
        
        # 1. Verify candidate IDs exist in the active batch
        for cand_id in proposal.candidate_match_ids:
            if cand_id not in valid_txn_ids:
                return False, f"Candidate ID {cand_id} does not exist in the current batch."

        # 2. Arithmetic verification for fee/tax splits
        if proposal.recommended_action == "ADJUST_LEDGER_FEE_SPLIT":
            claimed_sum = 0
            evidence_found = False
            for ev in proposal.evidence:
                if ev.field == "fee_breakup" and isinstance(ev.value, dict):
                    evidence_found = True
                    claimed_sum = sum(int(v) for v in ev.value.values())
            
            if not evidence_found:
                return False, "ADJUST_LEDGER_FEE_SPLIT requires explicit fee_breakup evidence."
            
            actual_diff = exception_ctx.get("deterministic_findings", {}).get("abs_diff_minor", 0)
            if claimed_sum != actual_diff:
                return False, f"Arithmetic mismatch: claimed sum ({claimed_sum}) != actual variance ({actual_diff})."

        # 3. Verify rule citations
        for ev in proposal.evidence:
            if ev.rule_id and ev.rule_id not in valid_rules:
                return False, f"Invalid rule cited: {ev.rule_id}."

        # 4. Confidence bounds check
        if proposal.confidence < 0.0 or proposal.confidence > 1.0:
            return False, "Confidence score must be strictly bounded between 0.0 and 1.0."

        return True, None
```
