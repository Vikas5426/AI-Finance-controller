# AI Finance Controller — System Architecture Specification

## 1. Architectural Overview

The **AI Finance Controller** is an enterprise financial reconciliation, anomaly investigation, and autonomous reporting system. It is designed to reconcile multi-stream transactional data across Payment Service Providers (Razorpay, Stripe), Core Banking Feeds (HDFC, ICICI, Citi), and ERP General Ledgers (SAP, NetSuite).

Unlike traditional statistical forecasting platforms, the system enforces **deterministic accounting invariants**, **minor-unit integer arithmetic (Paise)**, and **cryptographic audit trails (SHA-256 block-chaining)**. All financial calculations are mathematically proven; LLMs are strictly quarantined to qualitative reasoning, root cause analysis (RCA), and explainability.

```
+---------------------------------------------------------------------------------------+
|                                1. CLIENT & INTERACTION LAYER                          |
|  Finance Controller Web UI • Reconciliation Workbench • ⌘K Assistant • Audit Dossier   |
+-------------------------------------------+-------------------------------------------+
                                            | HTTPS / WSS / JWT
+-------------------------------------------v-------------------------------------------+
|                                  2. API GATEWAY LAYER                                 |
|      FastAPI Router • Rate Limiter • Security & RBAC • Background Task Dispatcher     |
+-------------------------------------------+-------------------------------------------+
                                            |
         +----------------------------------+----------------------------------+
         |                                                                     |
+--------v------------------------------------+       +------------------------v--------+
|       3. DETERMINISTIC ENGINE PIPELINE      |       |      4. AI REASONING AGENT SUITE|
|  • Data Ingestion & Sanitization            |       |  • Agent 1: Financial Analysis  |
|  • Normalizer (ISO-4217, Paise Minor Units) | <===> |  • Agent 2: Ingestion & Cleanser|
|  • 3-Tier Matcher (Exact, Window, Heuristic)|       |  • Agent 3: Anomaly & Risk      |
|  • 16-Type Residual Exception Classifier    |       |  • Agent 4: Tax & Compliance    |
|  • Period Boundary & Cut-off Evaluator      |       |  • Agent 5: Audit & Explain     |
+---------------------------------------------+       +---------------------------------+
         |                                                                     |
         +----------------------------------+----------------------------------+
                                            |
+-------------------------------------------v-------------------------------------------+
|                             5. PERSISTENCE & AUDIT BUS                                |
|  • SQLite / PostgreSQL Storage (Batches, Transactions, Exceptions, Approval Logs)     |
|  • Append-Only SHA-256 Cryptographic Audit Trail (Dual-Control Maker-Checker Proofs)   |
|  • Multi-Tier Settlement Ledger & Executive Report Generation Engine                 |
+---------------------------------------------------------------------------------------+
```

---

## 2. Core Subsystems

### Subsystem 1: Client & User Interaction Layer
- **Web Frontend**: Vanilla CSS and modern JavaScript single-page application with dark-mode glassmorphism.
- **Three-Way Reconciliation Workbench**: Side-by-side inspection of Gateway, Bank, and Ledger records.
- **Exception & Adjustment Queue**: Workflow for viewing flagged discrepancy types (T+2 cutoff lag, fee misconfigurations, phantom debits).
- **Interactive Architecture Viewer**: Dedicated interactive pan/zoom SVG visualizer (`docs/architecture_diagram.html`).

### Subsystem 2: API Gateway Layer
- Built with **FastAPI**.
- JWT-based authentication supporting role-based access control (`CONTROLLER`, `AUDITOR`, `OPERATOR`).
- Pydantic v2 request contracts with strict validation.

### Subsystem 3: Deterministic Data Processing Pipeline
1. **Multi-Source Ingestion**: Ingests CSV and JSON transactions across Gateway, Bank, and Ledger feeds.
2. **Canonical Normalization**: Standardizes descriptions and converts all monetary amounts into 64-bit integer minor units (`amount_minor` in paise) to eliminate floating-point rounding errors.
3. **Deterministic Matching Engine**:
   - **Tier 1 (Exact Match)**: Matches identical amount, reference (UTR/Payment ID), and timestamp.
   - **Tier 2 (Tolerance Window Match)**: Matches transactions with minor timing lags (e.g., T+2 settlement cutoff) within statutory fee bands.
   - **Tier 3 (Contextual Match)**: Heuristic scoring with risk penalties and deterministic tie-breaking.
4. **Exception Classification**: Categorizes residual breaks into a 16-type taxonomy (e.g., `MDR_FEE_MISMATCH`, `SPLIT_PAYMENT_UNMATCHED`, `GST_REVERSE_CHARGE_DEFICIT`, `PERIOD_BOUNDARY_CUTOFF`).

### Subsystem 4: AI Reasoning Agent Suite (5 Specialized Agents)
The system leverages 5 specialized LLM reasoning agents (Groq LLaMA-3.3-70B / Mixtral-8x7B) that consume verified deterministic state and generate human-readable explanations:
1. **Financial Analysis Agent**: Analyzes overall settlement match efficiency, fees, and cross-channel discrepancies.
2. **Data / Ingestion Cleansing Agent**: Flags malformed metadata, formatting anomalies, and ingestion errors.
3. **Anomaly & Risk Agent**: Assesses fraud patterns, phantom entries, velocity spikes, and assigns 0–100 risk severity scores.
4. **Tax & Compliance Agent**: Validates statutory 18% GST splits on payment gateway MDR fees and input tax credit (ITC) eligibility.
5. **Audit & Explainability Agent**: Formulates step-by-step SOX-404 explanations, verifies SHA-256 hash chains, and produces auditor-facing evidence packs.

### Subsystem 5: Cryptographic Audit & Governance
- **Sequential SHA-256 Hash Chaining**: Every batch creation, matching pass, exception trigger, and approval generates an immutable audit record chained to `prev_hash`.
- **Maker-Checker Dual Control**: Approval of journal adjustments requires distinct maker (`usr_analyst`) and checker (`usr_approver`) identities.
- **Tamper Detection**: An on-demand `/audit/verify-chain` endpoint validates block-by-block cryptographic preimage integrity.

---

## 3. Verified Separation of Epistemic Boundaries

| Subsystem / Operation | Implementation Type | Guarantees |
| :--- | :--- | :--- |
| **Transaction Ingestion** | Deterministic Python / Pydantic | Exact field validation, no synthesized rows |
| **Amount Representation** | Integer Minor Units (Paise) | Zero IEEE-754 floating-point drift |
| **Reconciliation Matching** | Deterministic 3-Tier Matcher | Pure algorithmic assignment, mathematical replayability |
| **Exception Taxonomies** | Deterministic Rule Matrix | 16 discrete rule-based exception classifications |
| **Audit Chaining** | SHA-256 Cryptographic Digests | Tamper-evident ledger sequence |
| **Qualitative Explanations** | LLM Reasoning Agents | Read-only access to deterministic state; no numeric mutation |

---

## 4. Test Suite & Verification

The codebase maintains 100% test pass rates across all 198 integration, security, and accounting tests:
- `test_accounting_semantics.py` — Invariant preservation & immutable batch validation.
- `test_adversarial_40_cases.py` — 40 edge cases including boundary dates, leap years, and currency codes.
- `test_audit_and_compliance_subsystem.py` — SHA-256 hash chain verification and dual-control approvals.
- `test_frontend_dashboard_consistency.py` — Consistency of metrics between frontend views and backend state.
- `test_data_lineage_and_batch_isolation.py` — Verification that batch data never cross-pollinates or leaks.
