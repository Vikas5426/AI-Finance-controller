# Autonomous AI Financial Controller — Core Logic & Architecture Report

## 1. System Overview & Architecture Topology

The application performs **Autonomous Three-Way Financial Reconciliation** across three heterogeneous financial sources:
1. **Payment Gateway** (e.g., Razorpay, Stripe — captured payments, refunds, MDR fees, tax deductions).
2. **Bank Statements** (e.g., HDFC, ICICI MT940 / CSV — settlement credits, clearing wire debits, UTR references).
3. **General Ledger (ERP)** (e.g., NetSuite, SAP, Tally — double-entry debits and credits, receivable clearing accounts).

```
   ┌──────────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐
   │ Payment Gateway      │   │ Bank Statements      │   │ General Ledger (ERP) │
   │ (Razorpay/Stripe API)│   │ (MT940 / Bank CSV)   │   │ (Journal Entries)    │
   └──────────┬───────────┘   └──────────┬───────────┘   └──────────┬───────────┘
              │                          │                          │
              ▼                          ▼                          ▼
   ┌────────────────────────────────────────────────────────────────────────────┐
   │ Ingestion & Normalizer Service (Reference Key Extraction & Decimal Casting)│
   └─────────────────────────────────────┬──────────────────────────────────────┘
                                         │
                                         ▼
   ┌────────────────────────────────────────────────────────────────────────────┐
   │ Quality-First Windowed Batch Orchestrator (20–30 Record Controlled Windows)│
   └─────────────────────────────────────┬──────────────────────────────────────┘
                                         │
   ┌─────────────────────────────────────┴──────────────────────────────────────┐
   │                                                                            │
   ▼                                                                            ▼
┌──────────────────────────────────────────────┐  ┌─────────────────────────────┐
│ 6-Pass Matching Engine                       │  │ 360° Context Builder        │
│ • P0: Intra-Source Deduplication             │  │ • MDR Schedule Analysis     │
│ • P1: Exact Typed Reference Keys             │  │ • Period Boundary Lag Scan  │
│ • P3: Fuzzy Scored Hungarian Assignment      │  │ • Counterparty Profiling    │
│ • P4: N:1 Bounded Subset-Sum Settlement DP   │  └──────────────┬──────────────┘
│ • P5: Residual Exception Classification      │                 │
└──────────────────────┬───────────────────────┘                 │
                       │                                         │
                       ▼                                         ▼
   ┌────────────────────────────────────────────────────────────────────────────┐
   │ Bounded AI Agent Runtime & Verifier Gate (Gemini 3.6 Flash / Sonnet 3.5)   │
   │ • Strict JSON Schema Output & Hallucination Elimination                    │
   │ • Deterministic Arithmetic Verifier Gate (Claims must equal actual math)   │
   └─────────────────────────────────────┬──────────────────────────────────────┘
                                         │
                                         ▼
   ┌────────────────────────────────────────────────────────────────────────────┐
   │ Hybrid 4-Tier Decision Engine                                              │
   │ • Tier 1: RESOLVED (100% Deterministic exact tie-out)                      │
   │ • Tier 2: RESOLVED_WITH_EXPLANATION (MDR/GST formula verified)             │
   │ • Tier 3: NEEDS_REVIEW (Period cutoff / Timing delay -> Maker-Checker)     │
   │ • Tier 4: UNRESOLVED_EXCEPTION (Missing settlement / Fraud / Chargeback)  │
   └──────────────────────┬─────────────────────────────────────────────────────┘
                          │
         ┌────────────────┴────────────────┬────────────────────────────┐
         ▼                                 ▼                            ▼
┌───────────────────────────┐ ┌───────────────────────────┐ ┌───────────────────┐
│ SHA-256 Audit Hash Chain  │ │ Maker-Checker Dual Review │ │ 13-Week Cash      │
│ • Cryptographic Tamper    │ │ • Analyst (Maker) Propose │ │ Forecaster        │
│   Evident Blockchain Log  │ │ • Controller (Checker) OK │ │ • Risk-Segmented  │
└───────────────────────────┘ └───────────────────────────┘ └───────────────────┘
```

---

## 2. Directory Map & File Locations

All source files are organized cleanly under the backend and frontend directories:

| Component | File Path | Primary Responsibility |
| :--- | :--- | :--- |
| **API Entry Point** | `backend/app/main.py` | FastAPI lifecycle, router registration, CORS, and static UI file mounting. |
| **Batch Runner & Demo** | `run_demo.py` | End-to-end demo execution: dataset generation, 6-pass matching, benchmarks, web server boot. |
| **Matching Engine** | `backend/app/services/matching_engine.py` | Core 6-pass reconciliation engine (P0 dedupe, P1 exact, P3 Hungarian fuzzy, P4 subset-sum DP, P5 residuals). |
| **Batch Orchestrator** | `backend/app/services/batch_orchestrator.py` | Controlled 20–30 record analysis windows, 7-stage processing, and progress state machine. |
| **Context Builder** | `backend/app/services/context_builder.py` | 360° financial contextualizer (historical fee profile, T+2 lag detection, cross-source candidate links). |
| **AI Agent Runtime** | `backend/app/services/agent_runtime.py` | Bounded LLM investigation engine (Gemini/Claude) with deterministic arithmetic verifier gates. |
| **Decision Engine** | `backend/app/services/decision_engine.py` | 4-tier decision routing (RESOLVED, RESOLVED_WITH_EXPLANATION, NEEDS_REVIEW, UNRESOLVED_EXCEPTION). |
| **Rules Engine** | `backend/app/services/rules_engine.py` | Zero-dependency declarative rule evaluator for SOP thresholds, fee allowances, and write-offs. |
| **Audit Hash Chain** | `backend/app/services/audit_chain.py` | SHA-256 tamper-evident cryptographic hash chain recording all financial state mutations. |
| **Cash Forecaster** | `backend/app/services/cash_forecaster.py` | 13-week forward liquidity runway segmented into Confirmed, Probable, At-Risk, and Unknown buckets. |
| **Normalizer Service** | `backend/app/services/normalizer.py` | Regular-expression reference key extractor, text tokenization, and canonical model mapper. |
| **Data Validation** | `backend/app/services/validation_service.py` | Structural sanity checks (nulls, negative amounts, future dates, ISO currencies). |
| **Synthetic Generator** | `backend/app/services/synthetic_generator.py` | Generates 240+ multi-source records modeling 12 realistic financial topologies with ground truth. |
| **Benchmarks** | `backend/app/services/benchmarks.py` | Computes Precision, Recall, F1-Score, and Expected Calibration Error (ECE) against ground truth. |
| **Schemas & Models** | `backend/app/models/schemas.py` | Pydantic v2 schemas: CanonicalTransaction, MatchSchema, ExceptionSchema, ReconciliationDecision. |
| **Database Schema** | `backend/app/db/schema.py` | SQLAlchemy relational tables with foreign keys, compound indexes, and JSON payloads. |
| **Database Service** | `backend/app/db/database_service.py` | Database repository layer, transaction commits, seed users with Argon2 hashes. |
| **Conversational Q&A** | `backend/app/api/v1/qa.py` | Dynamic Insight Cards, visual timeline steps, and evidence checklists for the UI financial analyst. |
| **Approvals API** | `backend/app/api/v1/approvals.py` | Maker-checker dual-authorization workflows (propose, approve, reject with audit hashes). |
| **Batches API** | `backend/app/api/v1/batches.py` | Batch creation, windowed reconciliation trigger, and progress streaming. |
| **Frontend UI** | `frontend/index.html` | Single-page console with window-by-window visualizer, match breakdown, and Q&A chat. |

---

## 3. Detailed Core Logic & Mathematical Workflows

### 3.1 Normalization & Reference Key Extraction
**File**: `backend/app/services/normalizer.py`

Raw financial records enter with inconsistent formats (timestamps in IST vs UTC, amounts in floats vs integers, free-form bank memos). The `NormalizerService` transforms all records into a unified `CanonicalTransaction` model:
- **Paise Quantization**: All amounts are cast to integer minor units (paise for INR, e.g., ₹100.50 -> `10050` paise) to prevent floating-point inaccuracies.
- **Typed Reference Extraction**: Regular expressions extract typed keys:
  ```python
  # Invoice Key: INV-YYYY-NNNN
  inv_matches = re.findall(r"INV-\d{4}-\d{4}", text, re.IGNORECASE)
  # Payment Key: pay_LtPk29Xq7
  pay_matches = re.findall(r"pay_[A-Za-z0-9]{6,}", text)
  # Settlement Key: SETL9KA22 / setl_9KA22
  setl_matches = re.findall(r"setl_?[A-Za-z0-9]+", text, re.IGNORECASE)
  # Bank UTR Number: N2604029912 / R2604029912
  utr_matches = re.findall(r"[NR]\d{10,}", text, re.IGNORECASE)
  ```

---

### 3.2 The 6-Pass Matching Engine
**File**: `backend/app/services/matching_engine.py`

The `ReconciliationEngine` executes a multi-pass pipeline where each pass handles a specific financial topology and removes reconciled transactions from subsequent passes:

```
Raw Multi-Source Records
        │
        ▼
   [ Pass P0: Intra-Source Deduplication ]
        │ (Identifies duplicate ingestion fingerprints)
        ▼
   [ Pass P1: Exact 1:1 Typed Key Matching ]
        │ (Exact Payment ID / UTR / Invoice tie-outs)
        ▼
   [ Pass P4: N:1 Bounded Subset-Sum Settlement Solver ]
        │ (Batched gateway payouts to bank settlement credit)
        ▼
   [ Pass P3: Scored Fuzzy Hungarian Global Assignment ]
        │ (Linear sum assignment over 6-feature similarity matrix)
        ▼
   [ Pass P5: Residual Anomaly & Exception Classification ]
        │ (Classifies remaining items into 16-type taxonomy)
        ▼
 Reconciled Matches + Actionable Exceptions
```

#### Pass P0: Intra-Source Deduplication
- Scans for duplicate external IDs or identical fingerprint tuples `(source_kind, external_id)` within the same source batch.
- Flags duplicate rows as `DUPLICATE_RECORD` exceptions and retains only the primary record.

#### Pass P1: Exact 1:1 Typed Key Matching
- Builds an in-memory inverted index over `reference_keys` (`PAYMENT`, `UTR`, `INVOICE`).
- If an exact reference key matches across sources (e.g. Gateway Payment `pay_G8x0001` and Ledger line with `doc_ref: INV-2026-1001`), the engine verifies amount equality and marks them `100% MATCHED` with confidence `0.999`.

#### Pass P4: N:1 Bounded Settlement Solver (Dynamic Programming)
Gateways settle transactions in aggregated net batches (e.g., 5 gateway payments totaling ₹50,000 minus 2% MDR fee -> 1 Bank Credit of ₹48,820).
- **Arithmetic Fee Model**:
  `Net = Sum(Gross) - Sum(round(Gross * 0.02)) - Sum(round(round(Gross * 0.02) * 0.18))`
- **Quantised Subset-Sum Algorithm**:
  If a settlement key is not declared, the solver quantizes target paise by `q=100` and executes a bounded DP knapsack across candidates within a +-3-day window:
  ```python
  T = target_amount // 100
  reach: Dict[int, Tuple[int, ...]] = {0: ()}
  for idx, c in enumerate(cands[:60]):
      fee = round(c.amount_minor * 0.02)
      tax = round(fee * 0.18)
      net_paise = c.amount_minor - fee - tax
      vq = net_paise // 100
      for s, chosen in list(reach.items()):
          ns = s + vq
          if ns <= T + 2 and ns not in reach:
              reach[ns] = chosen + (idx,)
  ```

#### Pass P3: Scored Fuzzy Assignment with Hungarian Algorithm
For discrepant or non-indexed records, the engine builds a weighted cost matrix between unmatched source pools (e.g., Gateway pool A of size N and Ledger pool B of size M):
- **Feature Weights** (customized per source pair):
  `Score = w_id*S_id + w_amt*S_amt + w_date*S_date + w_desc*S_desc + w_cp*S_cp + w_ctx*S_ctx`
  For Gateway <-> Ledger: `w_id=0.45, w_amt=0.25, w_date=0.10, w_desc=0.10, w_cp=0.05, w_ctx=0.05`.
- **Distance / Decay Functions**:
  - `S_date = exp(-max(0, delta_days - grace) / tau)` (where `grace=1, tau=2.0`).
  - `S_amt` checks exact equality, <= 100 paise rounding tolerance, or known 2.0% MDR + 18% GST formulas.
  - `S_desc` and `S_cp` use RapidFuzz token set ratio `ratio / 100`.
- **Global Optimum**: Solved using the Hungarian Algorithm (`scipy.optimize.linear_sum_assignment(cost_matrix, maximize=True)`).
- **Runner-Up Margin Threshold**: A match is committed only if `Score >= 0.85` and its margin over the second-best candidate in that row/column `>= 0.05`.

#### Pass P5: Residual Classification
All remaining unmatched records are classified into the controller taxonomy:
- `UNKNOWN_BANK_CREDIT`: Bank inflow with no matching gateway or ledger line.
- `TIMING_DIFFERENCE`: Gateway transaction captured at period cutoff (T+2 delay).
- `MISSING_BANK_RECORD`: Gateway payment with no bank credit after the settlement window.

---

### 3.3 360° Financial Context Builder
**File**: `backend/app/services/context_builder.py`

Before an ambiguous or discrepant record is evaluated by the decision engine or LLM, `TransactionContextBuilder` enriches the transaction with:
1. **Historical Fee Schedule Calculations**: Computes predicted net payout for standard 2.0% MDR and enterprise 1.5% MDR + 18% GST.
2. **Period Boundary Lag Analysis**: Detects transactions captured after 23:00 on month-end dates (e.g. March 31, 2026) indicating T+2 clearing delays.
3. **Counterparty History & Account Codes**: Extracts normalized counterparty profile, default payout schedule, and ledger accounts.

---

### 3.4 Bounded AI Agent Runtime & Verifier Gate
**File**: `backend/app/services/agent_runtime.py`

To prevent uncalibrated hallucination in financial workflows, the `AIAgentRuntime` applies two safety measures:
1. **Deterministic Verifier Gate (`DeterministicVerifier`)**:
   When an LLM (Gemini 3.6 Flash or Claude 3.5 Sonnet) generates an investigation proposal, the output is intercepted and verified:
   - *Candidate ID Exists*: Every ID referenced by the model must exist in the active batch.
   - *Arithmetic Proof Verification*: If the model claims an amount difference is due to fee/tax splits, the verifier checks that:
     `Sum(claimed fee components) == actual variance`
     If arithmetic fails, the proposal is rejected.
2. **High-Precision Deterministic Reasoner Fallback**:
   If API keys are not supplied or the LLM output is invalid, the system automatically falls back to an exact, rule-verified financial reasoner (`_deterministic_investigate`).

---

### 3.5 Hybrid 4-Tier Decision Engine
**File**: `backend/app/services/decision_engine.py`

The `HybridDecisionEngine` routes every transaction into one of four operational tiers:
- **Tier 1: RESOLVED**: 100% Deterministic exact tie-out across reference keys and amounts. Confidence = 1.00. Auto-closed.
- **Tier 2: RESOLVED_WITH_EXPLANATION**: Contextual tie-out net of MDR fee and GST with verified arithmetic proof. Confidence ~0.92. Auto-closed.
- **Tier 3: NEEDS_REVIEW**: Period boundary cutoff or timing lag requiring Maker-Checker dual review (proposed clearing to Account 1290). Confidence ~0.88.
- **Tier 4: UNRESOLVED_EXCEPTION**: Missing settlement credits, duplicate rows, or chargeback disputes. High/Critical risk. Escalated to Controller.

---

### 3.6 Cryptographic SHA-256 Audit Hash Chain
**File**: `backend/app/services/audit_chain.py`

Every financial action (batch creation, window execution, analyst proposal, dual approval, rule trigger) writes an immutable block to the `AuditHashChain`:
- **Genesis Block**: `0000000000000000000000000000000000000000000000000000000000000000` (64 zeros).
- **Preimage Hashing**:
  `Hash_n = SHA-256(PrevHash_(n-1) | OrgId | EventSeq | EventType | EntityId | ActorId | Timestamp | CanonicalJSON(Payload))`
- **Chain Verification**: `verify_chain_integrity` iterates through all events sequentially, recomputes the SHA-256 hash, and flags any tampered payload or broken link.

---

### 3.7 13-Week Forward Cash Forecaster
**File**: `backend/app/services/cash_forecaster.py`

The `SegmentedCashForecaster` projects liquidity runway by mapping decision tiers to risk buckets:
- **Confirmed Inflows**: Tier 1 and Tier 2 reconciled transactions (net of verified fees).
- **Probable Inflows**: Tier 3 period cutoff timing differences expected to settle in Week 1.
- **At-Risk Inflows**: Tier 4 un-settled gateway captures or disputed chargeback reserves.
- **Unknown Inflows**: Unclassified residual variances.

---

## 4. End-to-End Concrete Code Examples

### Example 1: Resolving an MDR Fee & GST Discrepancy (Test Case 2)

#### Input Data:
1. **Gateway Payment**:
   `payment_id: "pay_1002"`, `amount: 1000000` (₹10,000.00), `fee: 20000` (₹200.00), `tax: 3600` (₹36.00).
2. **Bank Statement Line**:
   `credit: 9764.00` (₹9,764.00), `ref_no: "pay_1002"`.

#### Execution Step:
1. `NormalizerService` normalizes the gateway payment to `1000000` paise and the bank credit to `976400` paise.
2. Direct variance is $1,000,000 - 976,400 = 23,600$ paise (₹236.00).
3. `TransactionContextBuilder` computes standard 2.0% MDR:
   `MDR Fee = 1,000,000 * 0.02 = 20,000 paise`
   `GST on Fee = 20,000 * 0.18 = 3,600 paise`
   `Total Expected Variance = 20,000 + 3,600 = 23,600 paise`
4. `DeterministicVerifier` confirms claimed sum ($23,600$) equals actual variance ($23,600$).
5. `HybridDecisionEngine` routes transaction to **Tier 2: RESOLVED_WITH_EXPLANATION** with confidence `0.92`.
6. A `MatchSchema` is recorded linking Gateway `pay_1002` to Bank `BANK-TEST-1002`, debiting `5010 Processing Fee` for ₹236.00.

---

### Example 2: Period Boundary Cutoff & Maker-Checker Proposal

#### Input Data:
- Gateway payment captured at `2026-03-31 23:55:00 IST` for ₹5,000.00.
- No corresponding bank credit exists on the March 31 bank statement.

#### Execution Step:
1. `TransactionContextBuilder` detects hour >= 23 on March 31 and attaches `is_period_cutoff = True` and flag `PERIOD_BOUNDARY_CUTOFF_T2_LAG`.
2. `HybridDecisionEngine` routes the transaction to **Tier 3: NEEDS_REVIEW** with `requires_maker_checker = True`.
3. The orchestrator generates a Maker-Checker proposal:
   ```json
   {
     "id": "PROP-pay_G8x0",
     "action": "ACCRUE_TO_CLEARING_1290",
     "justification": "T+2 period boundary cutoff timing difference. Propose accrual to Account 1290 (In-Transit Clearing).",
     "confidence": 0.88,
     "status": "PENDING_APPROVAL",
     "tier": "NEEDS_REVIEW"
   }
   ```
4. **Analyst (Maker)** reviews the card and submits a proposal.
5. **Controller (Checker)** hits `/api/v1/approvals/{id}/approve`, which validates dual authorization, updates the status to `APPROVED`, and writes an immutable block to the audit hash chain.

---

### Example 3: Cryptographic Audit Hash Verification

```python
from app.services.audit_chain import AuditHashChain

# Event 1: Batch Inception
prev_hash = AuditHashChain.GENESIS_HASH
h1 = AuditHashChain.compute_event_hash(
    prev_hash=prev_hash,
    org_id="00000000-0000-0000-0000-000000000001",
    event_seq=1,
    event_type="BATCH_INITIALIZED",
    entity_id="BATCH-20260331-01",
    actor_id="usr_system",
    payload={"total_records": 240, "total_windows": 10},
    created_at="2026-03-31T23:59:00+00:00"
)

# Event 2: Maker-Checker Dual Approval
h2 = AuditHashChain.compute_event_hash(
    prev_hash=h1,
    org_id="00000000-0000-0000-0000-000000000001",
    event_seq=2,
    event_type="PROPOSAL_APPROVED",
    entity_id="PROP-pay_G8x0",
    actor_id="usr_approver_01",
    payload={"action": "ACCRUE_TO_CLEARING_1290", "approved_amount_minor": 500000},
    created_at="2026-04-01T01:15:00+00:00"
)

# Verifying Chain Integrity
is_valid, broken_seq = AuditHashChain.verify_chain_integrity([event1, event2])
assert is_valid is True
```

---

## 5. Database Schema & Relational Model

The persistence layer in `backend/app/db/schema.py` defines 11 tables:
- `organizations`: Multi-tenant boundaries, default currency, materiality thresholds.
- `users`: Controller accounts with Argon2 password hashes, role-based access (`analyst`, `approver`, `admin`), and approval limits.
- `source_profiles`: CSV/JSON ingestion mapping rules and datetime format specifications.
- `batches`: Processing lifecycle metadata, window counts, match rates, and verification metrics.
- `transactions`: Unified canonical transactions with typed reference keys, minor amounts, and status.
- `matches`: Reconciled groups (1:1, 1:N, N:1) with solver evidence and confidence.
- `match_legs`: Individual legs of a match (primary vs. counterpart with signed minor amounts).
- `exception_records`: 16-type taxonomy exceptions with severity, impact amount, and AI investigation JSON.
- `approval_requests`: Maker-checker review queue with analyst proposals and approver sign-offs.
- `audit_events`: Cryptographically linked event ledger (`prev_hash`, `event_hash`, `payload`).
- `rules`: SOP business rule definitions with JSON conditions and actions.

---

## 6. API Endpoints Reference

All endpoints are prefixed with `/api/v1` and defined across modular router files:

| Router | File | Key Endpoints | Description |
| :--- | :--- | :--- | :--- |
| **Auth** | `auth.py` | `POST /login`, `GET /me` | JWT authentication and role extraction. |
| **Batches** | `batches.py` | `POST /create`, `POST /run-windowed-pipeline`, `GET /active/windows` | Windowed reconciliation orchestration and state streaming. |
| **Transactions** | `transactions.py` | `GET /`, `GET /{id}` | Search transactions by source, reference key, or status. |
| **Exceptions** | `exceptions.py` | `GET /`, `POST /{id}/investigate` | Exception taxonomy list and live AI investigation trigger. |
| **Approvals** | `approvals.py` | `GET /proposals`, `POST /{id}/approve`, `POST /{id}/reject` | Maker-checker dual-authorization review queue. |
| **Audit** | `audit.py` | `GET /events`, `GET /verify-chain` | Cryptographic SHA-256 chain verification. |
| **Reports** | `reports.py` | `GET /cash-forecast-13w`, `GET /benchmarks` | 13-week cash runway and ECE benchmark metrics. |
| **QA / Assistant** | `qa.py` | `POST /qa/ask` | Progressive-disclosure financial assistant with dynamic insight cards. |
