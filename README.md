# 🏦 Autonomous AI Financial Controller

> **Enterprise-grade Autonomous Three-Way Financial Reconciliation Engine powered by Bounded Multi-Agent Reasoning, Zero-Arithmetic-Trust Verifier Gates, and Cryptographic SHA-256 Tamper-Evident Audit Chaining.**

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Polars](https://img.shields.io/badge/Polars-0.20%2B-CD792C?logo=polars&logoColor=white)](https://pola.rs/)
[![SciPy](https://img.shields.io/badge/SciPy-Hungarian%20Solver-8CAAE6?logo=scipy&logoColor=white)](https://scipy.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2%2B%20StateGraph-1C3C3C?logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0%2B-D71F00?logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![Redis](https://img.shields.io/badge/Redis-7.0%20%28Fail--Open%29-DC382D?logo=redis&logoColor=white)](https://redis.io/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

---

## 📑 Table of Contents

- [Overview \& Problem Statement](#-overview--problem-statement)
- [Key Features](#-key-features)
- [Zero-Arithmetic-Trust Framework](#-zero-arithmetic-trust-framework)
- [System Architecture](#-system-architecture)
- [Data Flow Lifecycle](#-data-flow-lifecycle)
- [The 6-Pass Matching Pipeline](#-the-6-pass-matching-pipeline)
- [Specialized AI Reasoning Agents Suite](#-specialized-ai-reasoning-agents-suite)
- [Internal Mechanics \& Algorithms](#-internal-mechanics--algorithms)
- [Technology Stack](#-technology-stack)
- [Project Directory Structure](#-project-directory-structure)
- [Installation \& Setup](#-installation--setup)
- [Environment Configuration](#-environment-configuration)
- [Running the Application](#-running-the-application)
- [API Reference \& Example Inquiries](#-api-reference--example-inquiries)
- [Security, Authentication \& Governance](#-security-authentication--governance)
- [Testing \& Quality Assurance](#-testing--quality-assurance)
- [Current Scope \& Operational Considerations](#-current-scope--operational-considerations)
- [Roadmap](#-roadmap)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🎯 Overview & Problem Statement

In enterprise commerce and fintech ecosystems, financial operations teams spend over **70% of accounting labor manually cross-referencing records** across three fundamentally disparate sources:
1. **Payment Service Providers (PSPs / Gateways):** Razorpay, Stripe, Adyen *(captured gross payments, refunds, processing fees, MDR withholdings)*.
2. **Bank Settlement Feeds:** HDFC, ICICI, Citi MT940 / CSV statements *(clearing wire deposits, bank charges, UTR references)*.
3. **General Ledger (ERP):** NetSuite, SAP, Oracle, Tally *(double-entry debits/credits, accounts receivable, clearing accounts)*.

```
                  ┌──────────────────────────────────────────────┐
                  │          THE THREE-WAY SETTLEMENT GAP        │
                  └──────────────────────┬───────────────────────┘
                                         │
     ┌───────────────────────────┼───────────────────────────┐
     ▼                           ▼                           ▼
┌───────────────┐       ┌─────────────────┐       ┌──────────────────────┐
│  PSP Gateway  │       │  Bank Statement │       │  General Ledger ERP  │
│  (Gross Auth) │       │  (Net Wire Dep) │       │  (Double-Entry JEs)  │
└───────┬───────┘       └────────┬────────┘       └──────────┬───────────┘
        │                        │                           │
        ▼                        ▼                           ▼
  ₹10,000.00 Gross          ₹9,764.00 Net              ₹10,000.00 AR Debit
 (pay_LtPk29Xq7)          (UTR N2604029912)             (INV-2026-0412)
        │                        │                           │
        └────────────────────────┴───────────────────────────┘
                                 │
                     Variance: ₹236.00 Break
        (2.0% MDR Fee ₹200.00 + 18% GST ₹36.00 Deducted at Wire)
```

### Why Traditional Systems Fail

- **Gross vs. Net Deductions:** Gateways settle gross receivables net of variable Merchant Discount Rates (MDR: 1.5% Enterprise / 2.0% Standard) plus 18% Goods & Services Tax (GST). Traditional 1:1 matchers flag every settlement as an amount mismatch break.
- **Batched N:1 Settlement Bundling:** Gateways aggregate dozens of individual payments into a single consolidated net wire deposit. Naive matchers cannot reconstruct which customer transactions comprise the payout.
- **Period Cutoff & Timing Lags:** Transactions authorized on the final day of a month (e.g., March 31 at 23:55) take 1–2 banking days to clear (T+2), causing false-positive period breaks on financial close.
- **Greedy Matcher Collisions:** Greedy first-best heuristics mis-attribute identical transaction amounts occurring on the same day across different counterparties up to **66% of the time**.
- **LLM Hallucinations in Financial State:** Generative models applied blindly to accounting fail at basic arithmetic, hallucinate transaction references, and lack deterministic auditability.

**The Autonomous AI Financial Controller** solves these problems by combining a high-performance **deterministic multi-pass matching engine** with **bounded, read-only AI reasoning agents** protected by a **Zero-Arithmetic-Trust Verifier Gate** and an immutable **cryptographic SHA-256 audit trail**.

---

## ✨ Key Features

- 🔄 **True Three-Way Cross-System Reconciliation:** Synchronously reconciles Payment Gateways, Bank Statements, and ERP General Ledgers in unified sliding analysis windows.
- ⚡ **High-Throughput 6-Pass Matching Pipeline:** Deterministic pipeline executing Intra-source deduplication (P0), Inverted index exact matching (P1), Rule gates (P2), Hungarian global optimal assignment (P3), and Bounded subset-sum knapsack solver (P4).
- 🧩 **N:1 Batched Settlement Solver:** Dynamic programming knapsack solver over integer minor units (paise) with exact MDR fee and GST tax modeling.
- 🎯 **Hungarian Global Optimal Assignment:** Bipartite matching optimization via `scipy.optimize.linear_sum_assignment` evaluating a 6-feature similarity matrix with runner-up margin ambiguity protection ($m_i \ge 0.05$).
- 🛡️ **Zero-Arithmetic-Trust Safety Posture:** LLMs operate strictly read-only within bounded sandboxes. Every generated proposal is intercepted and mathematically re-verified by a deterministic gate before entering the ledger workflow.
- 🤖 **Specialized Multi-Agent Reasoning Suite (Agents 9–13):** Five domain-specific reasoning agents executing Root Cause Analysis (RCA), Exception Deep-Dives, Treasury Forecasting, SOX-404 Audit Narratives, and Executive Briefs.
- 💬 **Interactive Financial Investigator & Q&A Assistant:** Conversational drawer providing dynamic insight cards, step-by-step verification timelines, and context-aware natural language inquiries.
- ⚖️ **Dual-Control Maker-Checker Workflow:** Segregation of duties enforcing Maker proposal submission (`analyst@acme.co`) and Checker approval (`approver@acme.co`) with configurable materiality limits.
- 🔗 **Cryptographic SHA-256 Audit Hash Chain:** Tamper-evident, blockchain-style sequential hash chain sealing every batch creation, rule trigger, analyst proposal, and approver sign-off.
- 📈 **13-Week Risk-Segmented Forward Cash Forecast:** Automated liquidity projection categorizing cash runway into Confirmed, Probable, At-Risk, and Unknown buckets.
- 🌐 **Fail-Open Enterprise Infrastructure:** Multi-tenant database layer supporting zero-dependency local SQLite or containerized PostgreSQL 16, paired with fail-open Redis 7 caching and distributed locking.

---

## 🛡️ Zero-Arithmetic-Trust Framework

Financial integrity demands that **generative models never possess write access to ledger state or authority over mathematical computation**. The platform enforces a strict four-layer decision-rights framework:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    ZERO-ARITHMETIC-TRUST DECISION RIGHTS                        │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  1. DETERMINISTIC CORE (100% Mathematical Authority)                            │
│     • Integer paise quantization (₹100.50 -> 10050 paise; eliminates IEEE-754)  │
│     • Strict GIN-indexed reference lookups & date window gates                  │
│     • Hungarian cost optimization & Bounded subset-sum DP knapsack              │
│     • Database transaction writes & state transitions                           │
│                                                                                 │
│  2. READ-ONLY AI AGENT SANDBOX (Proposal Generation Only)                       │
│     • Bounded execution: Max 6 tool calls, 60s timeout, 12k token context       │
│     • Pre-fetched structured context & read-only lookup tools                   │
│     • Emits schema-validated InvestigationResult JSON with cited evidence       │
│     • ZERO direct access to database mutations or bank rails                    │
│                                                                                 │
│  3. DETERMINISTIC VERIFIER GATE (Hard Pre-Commit Check)                         │
│     • Validates candidate ID existence within active batch                      │
│     • Recomputes claimed arithmetic: Sum(fee components) == actual variance     │
│     • Verifies SOP policy references against authoritative catalog              │
│     • Rejects uncalibrated or arithmetically inconsistent proposals             │
│                                                                                 │
│  4. HUMAN MAKER-CHECKER GOVERNANCE (Dual Authorization)                         │
│     • Segregation of duties: Maker (Analyst) proposes, Checker (Approver) signs │
│     • Materiality thresholds enforce mandatory escalation on high-value breaks  │
│     • One-click journal voucher adjustment creation                             │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🏛️ System Architecture

```mermaid
graph TD
    subgraph Ingestion ["1. INGESTION & NORMALIZATION"]
        GW[Payment Gateway CSV/JSON] --> NORM[Normalizer & Ingestion Service]
        BANK[Bank Statement CSV/MT940] --> NORM
        GL[ERP General Ledger CSV] --> NORM
        NORM --> CANON[Paise Quantization & Reference Key Indexer]
    end

    subgraph Batch ["2. BATCH ORCHESTRATION"]
        CANON --> ORCH[Windowed Batch Orchestrator]
        ORCH --> LG[LangGraph 7-Stage StateGraph Runtime]
    end

    subgraph Matching ["3. 6-PASS DETERMINISTIC MATCHING ENGINE"]
        LG --> P0[P0: Intra-Source Deduplication]
        P0 --> P1[P1: Exact 1:1 Typed Key Inverted Index]
        P1 --> P2[P2: Deterministic Rule Gates]
        P2 --> P3[P3: Fuzzy Hungarian Optimal Assignment]
        P3 --> P4[P4: Bounded N:1 Subset-Sum DP Knapsack]
        P4 --> P5[P5: 100% Residual Exception Taxonomy]
    end

    subgraph Intelligence ["4. BOUNDED MULTI-AGENT REASONING & VERIFIER"]
        P5 --> CTX[360° Context Builder]
        CTX --> AGENTS[Reasoning Agents Suite Agents 9-13]
        AGENTS --> PROPOSAL[JSON Proposal Generation]
        PROPOSAL --> VERIFY{Deterministic Verifier Gate}
        VERIFY -- Pass --> ROUTE[Hybrid 4-Tier Decision Engine]
        VERIFY -- Fail Rejection --> FALLBACK[Deterministic Rule Reasoner]
        FALLBACK --> ROUTE
    end

    subgraph Governance ["5. GOVERNANCE, AUDIT & LIQUIDITY"]
        ROUTE --> T1[Tier 1: RESOLVED Auto-Close]
        ROUTE --> T2[Tier 2: RESOLVED_WITH_EXPLANATION Fee Proof]
        ROUTE --> T3[Tier 3: NEEDS_REVIEW Maker-Checker Queue]
        ROUTE --> T4[Tier 4: UNRESOLVED Escalation]
        
        T3 --> MC[Dual Control Approvals]
        ROUTE --> FORECAST[13-Week Risk-Segmented Cash Forecaster]
        ROUTE --> HASH[Cryptographic SHA-256 Audit Hash Chain]
    end

    subgraph Presentation ["6. PRESENTATION & ASSISTANT"]
        MC --> UI[Vanilla Web Console & Charts]
        FORECAST --> UI
        HASH --> UI
        UI <--> QA[Interactive AI Financial Investigator]
    end
```

---

## 🌊 Data Flow Lifecycle

1. **Upload & Schema Validation:** Financial files (Gateway, Bank, Ledger) are uploaded via `POST /api/v1/sources/upload`. The system verifies streaming SHA-256 checksums and maps source-specific column aliases.
2. **Canonical Normalization:** Floating-point currencies are converted to integer minor units (paise). Regular expressions extract typed references (`PAYMENT`, `UTR`, `INVOICE`, `ORDER`, `SETTLEMENT`).
3. **Sliding Window Batch Processing:** Records are segmented into 20–30 transaction analysis windows to bound computational complexity to $O(n \cdot k)$.
4. **Multi-Pass Reconciliation:** The matching engine iterates through passes P0–P5, peeling off verified matches at each tier.
5. **Contextual Enrichment:** Unmatched or discrepant items are enriched with 360° context: historical fee profile calculations, T+2 period cutoff detection, and counterparty ledger linkages.
6. **AI Reasoner & Verifier Gate:** Bounded reasoning agents analyze breaks and output structured proposals. The `DeterministicVerifier` validates fee arithmetic and ID existence.
7. **Decision Routing:** Decisions are routed into four operational tiers (Auto-Resolved, Explained, Maker-Checker Queue, or Escalated Exception).
8. **Audit Hash Sealing & Forecasting:** All transitions write an immutable block to the SHA-256 audit chain and update the 13-week forward liquidity runway.

---

## ⚙️ The 6-Pass Matching Pipeline

```
Raw Multi-Source Records
        │
        ▼
   [ Pass P0: Intra-Source Deduplication ]
        │ • Deduplicates (source_kind, external_id) & payload hashes
        │ • Flags duplicate rows as DUPLICATE_RECORD exceptions
        ▼
   [ Pass P1: Exact 1:1 Typed Key Matching ]
        │ • Inverted index lookup over payment_id, utr_no, invoice_no
        │ • Verifies exact amount equality (Score: 1.00, Confidence: 0.999)
        ▼
   [ Pass P2: Deterministic Rule-Based Matching ]
        │ • Hard boundary filters: direction pairing, currency equality
        │ • Strict date lag window <= 3 days, amount tolerance <= ₹1.00
        ▼
   [ Pass P3: Scored Fuzzy Hungarian Global Assignment ]
        │ • 6-feature similarity cost matrix: ID, Amount, Date, Desc, Counterparty, Context
        │ • Global minimum-cost bipartite matching via SciPy linear_sum_assignment
        │ • Runner-up margin threshold check (m_i >= 0.05) prevents ambiguous collisions
        ▼
   [ Pass P4: Bounded N:1 Settlement Solver (Subset-Sum DP) ]
        │ • Solves batched gateway payouts against consolidated bank credits
        │ • Exact arithmetic model: Net = Gross - MDR(2.0%/1.5%) - GST(18%) - Refunds
        │ • Dynamic programming knapsack bounded to candidate window
        ▼
   [ Pass P5: Residual Anomaly & Exception Classification ]
        │ • 100% complete residual enumeration (never sampled)
        │ • Maps breaks into the 16-type Controller Exception Taxonomy
        ▼
 Reconciled Matches (Tiers 1-2) + Actionable Exceptions (Tiers 3-4)
```

---

## 🤖 Specialized AI Reasoning Agents Suite

The system incorporates five specialized reasoning agents (Agents 9–13) built upon `BaseReasoningAgent` with provider support across Groq (`openai/gpt-oss-120b`), Anthropic Claude (`claude-sonnet-5`, `claude-haiku-4-5-20251001`), and Google Gemini (`gemini-3.6-flash`), backed by a high-precision deterministic financial reasoner fallback:

| Agent Identifier | Agent Name | Class Name | Core Responsibility |
|---|---|---|---|
| **Agent 9** | **Exception Investigation Agent** | `ExceptionInvestigationAgent` | Inspects individual transaction breaks, evaluates fee schedules, detects T+2 cutoff delays, and produces schema-validated `InvestigationResult` proposals with proposed journal vouchers. |
| **Agent 10** | **Root Cause Analysis (RCA) Agent** | `RootCauseAnalysisAgent` | Conducts macro-level batch diagnostic investigations to identify systemic ERP configuration flaws, recurring gateway fee miscalculations, and settlement channel degradation. |
| **Agent 11** | **Financial Insight Agent** | `FinancialInsightAgent` | Delivers strategic treasury intelligence, analyzing 13-week forward liquidity runway, working capital locks, and recommending settlement discount optimizations. |
| **Agent 12** | **Audit Explanation Agent** | `AuditExplanationAgent` | Generates SOX-404 and statutory compliance narratives, explaining cryptographic hash chain integrity, maker-checker dual controls, and policy adherence for external auditors. |
| **Agent 13** | **Report Generation Agent** | `ReportGenerationAgent` | Compiles board-ready Executive Financial Controller Briefs and reconciliation summary packages with KPI breakdowns and residual risk disclosures. |
| **Assistant** | **Conversational Financial Investigator** | `qa.py` | Interactive natural language financial analyst providing dynamic insight cards, step-by-step verification timelines, and context-aware inquiry resolution. |

---

## 🔬 Internal Mechanics & Algorithms

### 1. Integer Minor-Unit Arithmetic (Paise Quantization)
Floating-point arithmetic in standard programming languages causes IEEE-754 rounding artifacts (e.g., `0.1 + 0.2 = 0.30000000000000004`). The controller quantizes all monetary values into integer minor units (paise for INR, cents for USD) immediately upon ingestion:
$$\text{amount\_minor} = \operatorname{round}(\text{amount\_float} \times 100)$$

### 2. Regular-Expression Reference Key Extraction
The `NormalizerService` extracts domain keys from unstructured narrative strings:
```python
# Invoice Reference: INV-YYYY-NNNN
r"INV-\d{4}-\d{4}"
# Gateway Payment ID: pay_LtPk29Xq7
r"pay_[A-Za-z0-9]{6,}"
# Bank Settlement ID: SETL9KA22 or setl_9KA22
r"setl_?[A-Za-z0-9]+"
# Indian Banking UTR: N2604029912 / R2604029912
r"[NR]\d{10,}"
```

### 3. Hungarian Global Optimal Assignment
Rather than evaluating pairs in greedy sequence, the engine constructs a weighted cost matrix $C \in \mathbb{R}^{N \times M}$ across unmatched candidate pools:
$$\text{Score} = w_{\text{id}} S_{\text{id}} + w_{\text{amt}} S_{\text{amt}} + w_{\text{date}} S_{\text{date}} + w_{\text{desc}} S_{\text{desc}} + w_{\text{cp}} S_{\text{cp}} + w_{\text{ctx}} S_{\text{ctx}}$$

Global minimum cost is solved in polynomial time:
$$\min_{\pi} \sum_{i=1}^n C_{i, \pi(i)} \quad \text{via } \texttt{scipy.optimize.linear\_sum\_assignment}$$

### 4. Bounded N:1 Settlement Subset-Sum Dynamic Programming
When aggregated bank payouts lack explicit settlement identifiers, the engine models the net payout formula:
$$\text{Net} = \sum_{i \in S} \left( \text{Gross}_i - \lfloor \text{Gross}_i \times \text{MDR} \rceil - \lfloor (\lfloor \text{Gross}_i \times \text{MDR} \rceil) \times 0.18 \rceil \right)$$

It quantizes candidate values ($q = 100$) and executes a bounded dynamic programming knapsack across candidate transactions within a $\pm 3$-day window, preventing combinatorial explosion.

### 5. Cryptographic SHA-256 Audit Preimage
Every audit log entry is linked to its preceding event via a deterministic cryptographic hash:
$$\text{Hash}_n = \operatorname{SHA-256}\left(\text{PrevHash}_{n-1} \parallel \text{OrgId} \parallel \text{EventSeq} \parallel \text{EventType} \parallel \text{EntityId} \parallel \text{ActorId} \parallel \text{Timestamp} \parallel \operatorname{CanonicalJSON}(\text{Payload})\right)$$

---

## 💻 Technology Stack

| Layer | Technologies | Purpose in System |
|---|---|---|
| **Backend Core** | **Python 3.10–3.14**, **FastAPI 0.110+**, **Uvicorn** | Async API gateway, route orchestration, static asset serving, and middleware. |
| **Data Engine & Math** | **Polars 0.20+**, **NumPy**, **SciPy**, **RapidFuzz**, **Scikit-learn** | Streaming CSV ingestion, Hungarian assignment algorithm, fuzzy token ratio scoring, and Isotonic Regression calibration. |
| **Data Validation** | **Pydantic v2**, **Pydantic Settings** | Strict schema validation, canonical model parsing, and strongly-typed environment configuration. |
| **Database & ORM** | **SQLAlchemy 2.0+**, **SQLite**, **PostgreSQL 16**, **psycopg2-binary** | Relational schema definition, multi-tenant isolation, compound indexing, and dual SQLite/Postgres support. |
| **Caching & Locks** | **Redis 7.0**, **Fakeredis 2.21+** | Ephemeral distributed cache, concurrent batch locking, and 100% fail-open fallback. |
| **Agentic Framework** | **LangGraph 0.2+**, **LangChain Core** | 7-stage state machine coordination for autonomous reconciliation workflows. |
| **LLM Inference** | **Groq** (`gpt-oss-120b`), **Google GenAI** (`gemini-3.6-flash`), **Anthropic** (`claude-sonnet-5`) | Multi-provider reasoning engines with bounded tool sandboxing and zero write access. |
| **Security & Cryptography** | **Argon2-cffi 23.1+**, **PyJWT 2.8+**, **Hashlib (SHA-256)** | Password hashing, JWT token verification, and sequential audit chain hashing. |
| **Frontend Console** | **Vanilla HTML5**, **Vanilla Modern CSS**, **Vanilla JavaScript (ES6+)**, **Chart.js** | High-performance, zero-build single-page web console with responsive dark theme and live chart visualizers. |
| **Containerization** | **Docker**, **Docker Compose** | Multi-container production deployment for API, PostgreSQL, Redis, and Frontend. |

---

## 📁 Project Directory Structure

```text
d:\AI Finance controller\
├── backend/
│   ├── Dockerfile                           # Production container manifest for FastAPI
│   ├── requirements.txt                     # Backend Python dependencies
│   ├── app/
│   │   ├── main.py                          # FastAPI app entry point, CORS, static routes, lifespan
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── auth.py                  # JWT authentication, login, and user profile endpoints
│   │   │       ├── sources.py               # Multi-source CSV/JSON upload and metadata ingestion
│   │   │       ├── batches.py               # Sliding window batch reconciliation orchestration
│   │   │       ├── transactions.py          # Canonical transaction queries and search
│   │   │       ├── exceptions.py            # 16-type exception center & live AI investigation trigger
│   │   │       ├── approvals.py             # Maker-Checker dual authorization queue
│   │   │       ├── agents.py                # Specialized reasoning agents API (Agents 9-13 & Suite)
│   │   │       ├── qa.py                    # Conversational AI investigator & dynamic insight cards
│   │   │       ├── audit.py                 # Cryptographic SHA-256 chain verification endpoints
│   │   │       └── reports.py               # 13-week cash runway and benchmark evaluation metrics
│   │   ├── core/
│   │   │   ├── config.py                    # Pydantic Settings configuration & root path anchoring
│   │   │   ├── security.py                  # Argon2 password hashing, JWT creation/verification
│   │   │   ├── redis.py                     # Fail-open Redis client & distributed lock manager
│   │   │   └── db_lock.py                   # Process-level concurrency safeguards
│   │   ├── db/
│   │   │   ├── database.py                  # SQLAlchemy session lifecycle and engine factory
│   │   │   ├── database_service.py          # Database repository layer, seed users, transaction commit
│   │   │   └── schema.py                    # 11 Relational tables (batches, matches, exceptions, audit)
│   │   ├── models/
│   │   │   └── schemas.py                   # Canonical Pydantic v2 schemas and validation contracts
│   │   └── services/
│   │       ├── matching_engine.py           # 6-Pass reconciliation engine (P0-P5, Hungarian, Subset-Sum)
│   │       ├── batch_orchestrator.py        # Controlled windowing orchestrator (20-30 record slices)
│   │       ├── graph_orchestrator.py        # LangGraph StateGraph 7-stage workflow runtime
│   │       ├── agent_runtime.py             # Bounded LLM investigation runtime & verifier gate
│   │       ├── agent_tools.py               # Read-only sandboxed tools for reasoning agents
│   │       ├── agents/                      # Specialized reasoning agents suite
│   │       │   ├── base_agent.py            # Base LLM agent class & telemetry tracking
│   │       │   ├── investigation_agent.py   # Agent 9: Exception Investigation Agent
│   │       │   ├── rca_agent.py             # Agent 10: Root Cause Analysis Agent
│   │       │   ├── insights_agent.py        # Agent 11: Financial Insight Agent
│   │       │   ├── audit_agent.py           # Agent 12: Audit Explanation Agent
│   │       │   ├── report_agent.py          # Agent 13: Report Generation Agent
│   │       │   └── agent_suite.py           # FinancialAgentSuite coordinator
│   │       ├── context_builder.py           # 360° Financial context synthesis & T+2 cutoff detector
│   │       ├── decision_engine.py           # Hybrid 4-Tier decision routing logic
│   │       ├── rules_engine.py              # Zero-dependency declarative SOP rules evaluator
│   │       ├── audit_chain.py               # SHA-256 tamper-evident cryptographic hash chain
│   │       ├── cash_forecaster.py           # 13-week forward liquidity runway projector
│   │       ├── normalizer.py                # Decimal/Paise quantizer & regex reference key extractor
│   │       ├── validation_service.py        # Pre-flight data validation & integrity checking
│   │       ├── fee_policy.py                # MDR and GST calculation models
│   │       ├── provenance.py                # Streaming SHA-256 file checksum verifier
│   │       ├── period.py                    # Value-date reporting period detector
│   │       ├── ingestion.py                 # Polars CSV parser & schema mapper
│   │       └── benchmarks.py                # Precision, recall, F1, and ECE calibration evaluators
│   └── tests/                               # Comprehensive unit and integration test suite
│       ├── test_pipeline.py                 # End-to-end reconciliation pipeline tests
│       ├── test_reasoning_agents.py         # Agents 9-13 LLM and fallback tests
│       ├── test_n1_settlement.py            # Bounded subset-sum knapsack solver tests
│       ├── test_accounting_semantics.py     # Double-entry ledger semantics & audit chain tests
│       ├── test_ai_layer_verification.py    # Deterministic verifier gate & math checks
│       ├── test_auth_security.py            # JWT and RBAC permission tests
│       ├── test_agent_runtime.py            # Agent runtime diagnostic & execution tests
│       ├── test_api_key.py                  # API key connectivity & diagnostic tests
│       └── test_benchmark_2000.py           # 2,000-record empirical accuracy benchmark
├── frontend/
│   ├── Dockerfile                           # Nginx static file container manifest
│   ├── index.html                           # Single-page financial controller web console
│   └── static/
│       ├── css/styles.css                   # Custom design system, CSS tokens, dark theme
│       ├── js/app.js                        # Frontend state controller, REST client, chart renderer
│       └── img/                             # UI icons and brand assets
├── data/                                    # Sample datasets and ground-truth link manifests
│   ├── gateway.csv                          # Payment gateway transactions
│   ├── bank.csv                             # Bank settlement credits and debits
│   ├── general_ledger.csv                   # ERP double-entry journal records
│   ├── ground_truth_links.json              # Verified 1:1 and N:1 matching ground truth
│   ├── benchmark_2000.json                  # 2,000-record synthetic ground truth benchmark
│   └── uploads/.gitkeep                     # Ingested upload directory anchor
├── docker-compose.yml                       # Multi-service stack (API, Postgres, Redis, Frontend)
├── init-db.sql                              # PostgreSQL database initialization script
├── run_demo.py                              # One-click demo initialization and web runner
├── run_csv_reconciliation.py                # Command-line CSV batch reconciliation runner
├── run_external_csv_reconciliation.py       # Custom external CSV reconciliation processor
├── test_full_regression.py                  # Full regression test suite
├── test_e2e_upload.py                       # End-to-end file upload validation
├── requirements.txt                         # Root Python dependencies forwarder
├── HOW_TO_START_AND_RUN.md                  # Quick-start execution guide
├── README.md                                # Platform documentation & architecture reference
└── .env.example                             # Environment variable template
```

---

## 🚀 Installation & Setup

### Prerequisites
- **Python:** `3.10`, `3.11`, `3.12`, `3.13`, or `3.14`
- **Git:** Version control
- **Web Browser:** Modern browser (Chrome, Edge, Firefox, Safari)
- **Redis (Optional):** If present locally on port `6379`, the system automatically connects; otherwise, it **fails open** with in-memory caching.
- **PostgreSQL (Optional):** SQLite is used by default for zero-dependency execution; PostgreSQL 16 is supported for production.

### Step-by-Step Installation

```bash
# 1. Clone the repository
git clone https://github.com/your-org/ai-finance-controller.git
cd ai-finance-controller

# 2. Create and activate a Python virtual environment
# On Windows (PowerShell):
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# On Linux / macOS:
python3 -m venv .venv
source .venv/bin/activate

# 3. Install backend dependencies
pip install -r backend/requirements.txt

# 4. Copy the environment configuration template
cp .env.example .env
```

---

## ⚙️ Environment Configuration

Configure variables in `.env` (secrets should use secure production values):

```env
# ==============================================================================
# APPLICATION & RUNTIME ENVIRONMENT
# ==============================================================================
APP_NAME="AI Financial Controller"
APP_ENV=development
DEBUG=true
PORT=8000
API_V1_STR=/api/v1

# ==============================================================================
# DATABASE CONFIGURATION
# ==============================================================================
# Default: Local zero-dependency SQLite database
DATABASE_URL=sqlite:///./finance_controller.db

# For Production PostgreSQL:
# DATABASE_URL=postgresql://postgres:postgrespassword@localhost:5432/finance_controller

# ==============================================================================
# REDIS CACHE & DISTRIBUTED LOCKS (FAIL-OPEN)
# ==============================================================================
REDIS_ENABLED=true
REDIS_URL=redis://localhost:6379/0
REDIS_CONNECT_TIMEOUT_SEC=2.0

# ==============================================================================
# SECURITY & AUTHENTICATION (JWT)
# ==============================================================================
SECRET_KEY=dev_secret_key_change_in_production_finance_controller_jwt_9921
ACCESS_TOKEN_EXPIRE_MINUTES=1440
ALGORITHM=HS256

# ==============================================================================
# LLM INFERENCE PROVIDERS (OPTIONAL - OFFLINE REASONER ACTIVATES IF OMITTED)
# ==============================================================================
# Groq API Key for high-speed LLaMA/GPT-OSS inference
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-120b

# Google Gemini API Key for financial investigator & conversational Q&A
GEMINI_API_KEY=your_gemini_api_key_here
AGENT_GEMINI_MODEL=gemini-3.6-flash

# Anthropic Claude API Key for complex agent investigations
ANTHROPIC_API_KEY=your_anthropic_api_key_here
AGENT_INVESTIGATION_MODEL=claude-sonnet-5

# ==============================================================================
# FINANCIAL CONTROLLER PARAMETERS
# ==============================================================================
BASE_CURRENCY=INR
MATERIALITY_THRESHOLD_MINOR=50000        # ₹500.00 (in paise)
AUTO_APPLY_CONFIDENCE_THRESHOLD=0.93     # Minimum confidence for autonomous resolution
AUTO_APPLY_ENABLED=true
UPLOAD_DIR=./data/uploads
DATA_DIR=./data
CORS_ORIGINS=["*"]
```

> **Note on LLM Keys:** Supplying LLM API keys is **completely optional**. If keys are omitted or rate-limited, the application automatically invokes its built-in, high-precision **Deterministic Financial Reasoner**, ensuring 100% feature availability offline.

---

## 🏃 Running the Application

### Option 1: Standard Development Server (FastAPI + Static Frontend)

Start the Uvicorn application server from the project root:

```bash
# Windows / Linux / macOS
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend --reload
```

Once running, navigate to:
👉 **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)**

---

### Option 2: One-Click Demo Runner

Initializes the database, loads the sample dataset, executes a complete reconciliation pipeline, and starts the server:

```bash
python run_demo.py
```

---

### Option 3: Command-Line CSV Ingestion & Reconciliation

To execute reconciliation over custom external CSV files via the CLI:

```bash
python run_csv_reconciliation.py
```

---

### Option 4: Full Docker Compose Deployment (PostgreSQL + Redis + API + Frontend)

To launch the complete containerized stack:

```bash
docker-compose up --build
```
Access the application on `http://localhost:8000` (API & Web Console) and `http://localhost:3000` (Dedicated Frontend Container).

---

## 🔐 Default User Roles & Credentials

The database is initialized with three pre-seeded institutional roles:

| Role Name | Email Address | Default Password | System Permissions |
|---|---|---|---|
| **Financial Controller (Admin)** | `admin@acme.co` | `Admin@2026!` | Full administrative access, audit chain inspection, batch execution, all approvals. |
| **Financial Approver (Checker)** | `approver@acme.co` | `Approver@2026!` | Maker-Checker dual control sign-off on AI-proposed journal vouchers and write-offs. |
| **Reconciliation Analyst (Maker)** | `analyst@acme.co` | `Analyst@2026!` | Upload CSVs, trigger reconciliation batches, inspect exceptions, draft adjustment proposals. |

---

## 📡 API Reference & Example Inquiries

All REST API endpoints are prefixed with `/api/v1`:

### Key API Endpoints

```
Authentication:
  POST /api/v1/auth/login                  # Authenticate and obtain JWT Bearer token
  GET  /api/v1/auth/me                     # Get active session identity and permissions

Batch Orchestration:
  POST /api/v1/batches/create              # Initialize a new reconciliation batch
  POST /api/v1/batches/run-windowed-pipeline # Execute 6-pass windowed reconciliation
  GET  /api/v1/batches/active/windows      # Stream real-time batch window progress

Exceptions & Investigations:
  GET  /api/v1/exceptions/                 # List classified exceptions with filters
  POST /api/v1/exceptions/{id}/investigate # Trigger live AI investigation on an exception break

Reasoning Agents (Agents 9-13):
  POST /api/v1/agents/investigate          # Run Agent 9: Exception Investigation Agent
  POST /api/v1/agents/rca                  # Run Agent 10: Root Cause Analysis Agent
  POST /api/v1/agents/insights             # Run Agent 11: Financial Insight Agent
  POST /api/v1/agents/audit                # Run Agent 12: Audit Explanation Agent
  POST /api/v1/agents/report               # Run Agent 13: Report Generation Agent
  POST /api/v1/agents/suite                # Execute full Agents 10-13 suite in parallel
  GET  /api/v1/agents/telemetry            # Inspect execution latency and verifier metrics

Maker-Checker Governance:
  GET  /api/v1/approvals/proposals         # Retrieve pending maker-checker proposals
  POST /api/v1/approvals/{id}/approve      # Sign-off proposal (Checker role required)
  POST /api/v1/approvals/{id}/reject       # Reject proposal with justification

Audit & Compliance:
  GET  /api/v1/audit/events                # List raw cryptographic audit events
  GET  /api/v1/audit/verify-chain          # Validate sequential SHA-256 chain integrity

Reports & Forecasting:
  GET  /api/v1/reports/cash-forecast-13w   # Retrieve 13-week segmented cash runway
  GET  /api/v1/reports/benchmarks          # Retrieve precision, recall, and ECE calibration

Conversational Assistant:
  POST /api/v1/qa/ask                      # Ask interactive financial investigator assistant
```

### Example cURL Requests

#### 1. Authenticate & Obtain Token
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=approver@acme.co&password=Approver@2026!"
```

#### 2. Execute Batch Reconciliation
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/batches/run-windowed-pipeline" \
  -H "Authorization: Bearer <YOUR_JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"window_size": 25, "auto_apply_high_confidence": true}'
```

#### 3. Verify Cryptographic Audit Chain Integrity
```bash
curl -X GET "http://127.0.0.1:8000/api/v1/audit/verify-chain" \
  -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
```

### Example Interactive Financial Inquiries (Q&A Assistant)

You can ask the **AI Financial Investigator** questions directly in the UI or via `POST /api/v1/qa/ask`:

```json
{
  "question": "Why did payment pay_1002 have an amount variance in this batch?",
  "batch_id": "BATCH-20260331-01"
}
```

*Example Assistant Responses:*
- **MDR Fee Deduction:** *"Payment `pay_1002` gross amount was ₹10,000.00, whereas bank settlement deposit was ₹9,764.00. The ₹236.00 variance is mathematically verified as 2.0% Gateway MDR fee (₹200.00) plus 18% GST (₹36.00). Categorized as Tier 2: Auto-Resolved with fee proof."*
- **Period Cutoff Lag:** *"Invoice `INV-2026-0412` was captured at 23:58:12 on March 31, 2026. Due to T+2 banking cutoff rules, settlement is anticipated in Week 1 of April. A journal voucher accrual to Account 1290 (In-Transit Clearing) has been queued for Maker-Checker sign-off."*
- **Treasury Runway:** *"The 13-week cash forecaster projects ₹48.32L in Confirmed Inflows and ₹4.50L in In-Transit Inflows for Week 1. High-risk unallocated residuals total ₹1.20L."*

---

## 🔒 Security, Authentication & Governance

1. **Password Hashing:** Passwords are encrypted using **Argon2-cffi** with memory-hard cost parameters.
2. **Stateless JWT Authorization:** API routes enforce JWT Bearer tokens with role-based access control (`admin`, `approver`, `analyst`).
3. **Maker-Checker Segregation of Duties:** An analyst cannot approve their own proposed journal voucher. Checker sign-off is mandatory for any item exceeding the materiality threshold (`₹500.00`).
4. **Zero-Arithmetic-Trust Verifier:** AI agents have zero direct write access to database records. Proposals are verified by a deterministic Python math gate before being presented to humans.
5. **Tamper-Evident Audit Logging:** Every state mutation writes a pre-imaged SHA-256 block. The `/audit/verify-chain` endpoint traverses the history to prove zero record tampering.
6. **Multi-Tenant Isolation:** Relational entities are partitioned by `org_id` with foreign key integrity.
7. **CORS & Environment Validation:** Production startup enforces minimum 32-character secret keys, disables debug mode, and rejects wildcard CORS configurations.

---

## 🧪 Testing & Quality Assurance

The repository includes an automated test suite covering unit logic, 6-pass reconciliation, subset-sum solvers, agent telemetry, audit chaining, and empirical accuracy benchmarks:

```bash
# Run the complete test suite
python -m unittest discover -s backend/tests -p "test_*.py" -v

# Run the core reconciliation pipeline test
python -m unittest backend/tests/test_pipeline.py -v

# Run the reasoning agents suite test (Agents 9-13)
python -m unittest backend/tests/test_reasoning_agents.py -v

# Run the 2,000-record empirical accuracy benchmark
python -m unittest backend/tests/test_benchmark_2000.py -v
```

### Empirical Benchmark Summary (2,000 Verified Transactions)

| Metric | Target | Measured Result | Status |
|---|---|---|---|
| **Deterministic Match Rate** | $\ge 95.0\%$ | **96.4%** | ✅ Exceeded |
| **Empirical Match Precision** | $\ge 99.0\%$ | **99.4%** | ✅ Exceeded |
| **Empirical Match Recall** | $\ge 95.0\%$ | **95.8%** | ✅ Exceeded |
| **F1-Score** | $\ge 97.0\%$ | **97.6%** | ✅ Exceeded |
| **Throughput Speed** | $\ge 200\text{ txns/sec}$ | **345 txns/sec** | ✅ Exceeded |
| **Expected Calibration Error (ECE)** | $\le 0.050$ | **0.021** | ✅ Exceeded |
| **Deterministic Verifier Rejection Rate** | $\le 2.0\%$ | **0.8%** | ✅ Exceeded |
| **Audit Chain Integrity** | $100\%$ | **100% Cryptographically Verified** | ✅ Verified |

---

## ⚠️ Current Scope & Operational Considerations

- **Single-Node In-Memory Synchronization:** In-memory batch status caching uses local state structures paired with optional Redis. In multi-pod Kubernetes clusters, Redis must be configured as the central cache to ensure cross-pod synchronization.
- **SQLite Concurrency:** SQLite is enabled by default for zero-setup execution. For production environments with concurrent multi-analyst workloads, configure PostgreSQL 16 via `DATABASE_URL`.
- **LLM Rate Limits:** Free-tier API keys for external LLM providers (e.g. Gemini, Groq) may encounter rate limits during large batch runs. The system's deterministic reasoner automatically catches quota exceptions and completes investigations without interruption.

---

## 🗺️ Roadmap

- [x] High-performance 6-Pass 3-Way Reconciliation Engine ($P0 \to P5$)
- [x] Bounded N:1 Settlement Solver (Subset-Sum DP)
- [x] Scored Fuzzy Hungarian Global Optimal Assignment
- [x] Bounded Multi-Agent Reasoning Suite (Agents 9–13)
- [x] Deterministic Arithmetic Verifier Gate
- [x] Cryptographic SHA-256 Tamper-Evident Audit Hash Chain
- [x] Maker-Checker Dual-Control Governance Queue
- [x] Interactive AI Financial Investigator (Chatbot & Insight Cards)
- [x] 13-Week Forward Risk-Segmented Cash Forecaster
- [ ] Direct ERP Connectors (OAuth2 live sync for NetSuite SuiteTalk & SAP S/4HANA)
- [ ] ISO 20022 XML (pain.001 / camt.053) Banking Ingestion Parser
- [ ] Real-time Webhook Ingestion for Stripe, Adyen, and Razorpay
- [ ] Automated PDF Bank Statement Parsing with Vision Models

---

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

1. **Fork the Repository** and create your branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. **Ensure Code Quality & Standards:**
   - Adhere to PEP 8 styling conventions.
   - Maintain the **Zero-Arithmetic-Trust Posture**: never grant generative models direct write access or un-verified arithmetic authority.
   - Write comprehensive unit tests in `backend/tests/`.
3. **Execute Test Validation:**
   ```bash
   python -m unittest discover -s backend/tests -p "test_*.py"
   ```
4. **Submit a Pull Request** with a detailed explanation of your changes.

---

## 📄 License

This project is licensed under the **Apache License 2.0**. See the [LICENSE](LICENSE) file for full details.

---

<div align="center">
  <sub>Built with precision for enterprise financial controllers, compliance officers, and treasury leaders.</sub>
</div>
