# 🏦 AI Financial Controller

> **Autonomous Three-Way Financial Reconciliation & AI-Powered Audit Platform**
> Automatically matches transactions across Payment Gateways, Bank Statements, and ERP General Ledgers with deterministic precision, AI exception analysis, and cryptographic audit trails.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLite / PostgreSQL](https://img.shields.io/badge/Database-SQLite%20%7C%20Postgres-blue)](https://www.sqlite.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)

---

## ⚡ Quick Start (60 Seconds)

Get the application running locally in 3 steps:

```bash
# 1. Setup virtual environment
python -m venv .venv
.\.venv\Scripts\activate      # On macOS/Linux: source .venv/bin/activate

# 2. Install dependencies
pip install -r backend/requirements.txt

# 3. Start application
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend
```

Open your browser at **[http://127.0.0.1:8000](http://127.0.0.1:8000)** and sign in:

| Role | Email | Password | Access Level |
|---|---|---|---|
| **Controller (Admin)** | `admin@acme.co` | `Admin@2026!` | Full administrative access, audit chain inspection, all approvals |
| **Approver (Checker)** | `approver@acme.co` | `Approver@2026!` | Maker-Checker dual control sign-off on journal adjustment vouchers |
| **Analyst (Maker)** | `analyst@acme.co` | `Analyst@2026!` | Ingest CSVs, trigger reconciliation batches, draft proposals |

> **Tip**: You can also click **"Sign in as Admin (Full Access)"** on the login screen for instant one-click demo access.

---

## 💡 What Problem Does This Solve?

Finance teams spend **up to 70% of their time manually reconciling transactions** between three disconnected systems:

```
  1. Payment Gateway           2. Bank Statement           3. General Ledger (ERP)
  (Razorpay, Stripe)           (HDFC, ICICI, Citi)         (NetSuite, SAP, Tally)
  Gross customer charge        Net wire payout             Accounting journal entry
        │                             │                               │
        └─────────────────────────────┼───────────────────────────────┘
                                      ▼
                       ⚠️ THE SETTLEMENT DISCREPANCY
            Gross Payment: ₹10,000  vs  Bank Deposit: ₹9,764
            Breakdown: 2% MDR Fee (₹200) + 18% GST on Fee (₹36)
```

### Why Traditional Systems Fail:
- **Fee Deductions**: Gateways deduct Merchant Discount Rates (MDR) and tax before wiring net funds to the bank.
- **Batch Payouts (N:1)**: Gateways bundle hundreds of individual customer transactions into single lump-sum bank deposits.
- **Timing Differences (T+2)**: Friday transactions settle in the bank on Tuesday, causing false discrepancy flags.
- **AI Math Hallucinations**: Standard LLMs cannot be trusted with financial calculations and ledger entries.

---

## ✨ Key Features

- **🔄 Automated 3-Way Reconciliation**: Matches Gateway captures, Bank payouts, and ERP Ledgers across exact references, fee splits, and batched deposits.
- **🛡️ Zero-Arithmetic-Trust Verifier Gate**: All calculations use integer minor units (paise) with deterministic Python math checks before any AI recommendation is accepted.
- **🤖 Autonomous AI Exception Investigator**: Pinpoints exact root causes (cutoff delays, missing bank credits, fee tier changes) and drafts balanced journal adjustment entries.
- **⚖️ Maker-Checker Dual Governance**: Strict segregation of duties—analysts propose adjustments, but only authorized approvers can release and finalize them.
- **⛓️ Cryptographic SHA-256 Audit Chain**: Every financial event, approval, and batch execution is sealed in a tamper-evident sequential hash chain.
- **💬 Conversational Financial Assistant (`Ctrl+K`)**: Ask natural language questions about match rates, specific invoice references, or cash runway.

---

## 🏛️ How It Works

```mermaid
flowchart LR
    A["📥 1. Ingestion\n(Gateway, Bank, Ledger)"] --> B["⚙️ 2. Matching Engine\n(Multi-Pass Reconciliation)"]
    B --> C["🔍 3. AI Investigation\n(Root Cause & Adjustments)"]
    D["⚖️ 4. Maker-Checker\n(Dual-Control Sign-Off)"]
    C --> D
    D --> E["⛓️ 5. SHA-256 Audit\n(Immutable Hash Chain)"]
```

1. **Ingest**: Upload Gateway, Bank, and Ledger CSV feeds (or load the bundled reference fixtures).
2. **Reconcile**: The engine executes multi-pass matching (exact reference keys, fee logic, and batch settlement solvers).
3. **Investigate**: Unmatched items are classified and analyzed by AI agents to draft proposed adjustments.
4. **Approve**: An Approver reviews and signs off on vouchers in the Maker-Checker queue.
5. **Audit**: Every action is cryptographically chained and verifiable in real time.

---

## 📂 Project Structure

```text
ai-finance-controller/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # REST endpoints (auth, batches, exceptions, audit, qa)
│   │   ├── core/            # Configuration, security, and Redis locks
│   │   ├── db/              # Database schemas and services (SQLite / PostgreSQL)
│   │   ├── models/          # Pydantic data schemas
│   │   └── services/        # Matching engine, AI reasoning agents, audit hash chain
│   └── tests/               # 25 test suites covering 198 automated test cases
├── frontend/
│   ├── index.html           # Modern single-page financial console
│   └── static/
│       ├── css/styles.css   # Monochromatic dark/light design system
│       └── js/app.js        # Reactive client and state management
├── data/
│   ├── gateway.csv          # Reference Payment Gateway dataset (Razorpay/Stripe)
│   ├── bank.csv             # Reference Bank Statement dataset (HDFC/ICICI)
│   ├── general_ledger.csv   # Reference ERP General Ledger dataset (NetSuite)
│   └── ground_truth_links.json # Benchmark ground-truth validation data
├── docs/                    # System architecture specification & interactive diagram
├── docker-compose.yml       # Production stack (App + PostgreSQL + Redis)
└── README.md                # Project documentation
```

---

## 🧪 Testing

The codebase includes a comprehensive automated test suite covering reconciliation accuracy, accounting semantics, security, and agent verification:

```bash
# Run the full test suite
pytest backend/tests/ -v
```

```text
=================== 198 passed in ~3m 50s (100% success rate) ===================
```

---

## 🐳 Docker Deployment

To run the complete production container stack (FastAPI + PostgreSQL + Redis):

```bash
docker-compose up --build
```

Access the application at `http://localhost:8000`.

---

## 📄 License

This project is licensed under the [Apache License 2.0](LICENSE).
