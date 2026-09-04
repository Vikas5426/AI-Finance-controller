# 🚀 AI Financial Controller: How to Start & Run the Application

Welcome to the **Autonomous Three-Way Financial Reconciliation & AI Financial Controller** platform. This guide provides step-by-step instructions to set up, start, and use the complete application (Backend API, Database, Redis caching, and Frontend UI).

---

## 📋 Table of Contents
1. [Prerequisites](#1-prerequisites)
2. [Environment Configuration (`.env`)](#2-environment-configuration-env)
3. [Step-by-Step: Starting the App](#3-step-by-step-starting-the-app)
4. [Accessing the Web Interface & User Credentials](#4-accessing-the-web-interface--user-credentials)
5. [Application Features & Navigation](#5-application-features--navigation)
6. [Alternative Startup Methods](#6-alternative-startup-methods)
7. [Running Automated Tests](#7-running-automated-tests)
8. [Troubleshooting & FAQ](#8-troubleshooting--faq)

---

## 1. Prerequisites

Before running the application, ensure you have the following installed on your machine:

- **Python**: Version `3.10`, `3.11`, `3.12`, `3.13`, or `3.14`
- **Git**: For version control (optional)
- **Web Browser**: Chrome, Edge, Firefox, or Safari
- **Redis (Optional)**: If installed/running locally on port `6379` (Docker or native), the app will automatically use it for caching and distributed locking. If Redis is **not** available, the application automatically **fails open** and operates smoothly using in-memory fallbacks.

---

## 2. Environment Configuration (`.env`)

The project contains a `.env` configuration file in the root directory.

### Key Environment Variables

```env
# Google Gemini API Key for AI Financial Investigator & RAG
GEMINI_API_KEY=your_gemini_api_key_here

# Database Configuration (SQLite by default; supports PostgreSQL)
DATABASE_URL=sqlite:///./finance_controller.db

# Redis Infrastructure (Optional - Fail-Open)
REDIS_ENABLED=true
REDIS_URL=redis://localhost:6379/0
REDIS_CONNECT_TIMEOUT_SEC=1.0

# JWT & Security
SECRET_KEY=dev-secret-key-change-in-production-12345
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Base Financial Settings
BASE_CURRENCY=INR
CORS_ORIGINS=["*"]
```

> **Note**: If you do not have a `GEMINI_API_KEY`, the application will automatically use its rich deterministic financial controller engine with full accounting domain rules.

---

## 3. Step-by-Step: Starting the App

Follow these commands in your PowerShell / Terminal:

### Step 1: Open the Project Directory
```powershell
cd "d:\AI Finance controller"
```

### Step 2: Activate the Virtual Environment
- **Windows (PowerShell)**:
  ```powershell
  .\.venv\Scripts\Activate.ps1
  ```
- **Windows (Command Prompt `cmd`)**:
  ```cmd
  .\.venv\Scripts\activate.bat
  ```
- **macOS / Linux**:
  ```bash
  source .venv/bin/activate
  ```

### Step 3: Install Dependencies (if not already installed)
```powershell
pip install -r backend/requirements.txt
```

### Step 4: Start the FastAPI Application Server
Run Uvicorn to serve the API and static frontend:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend --reload
```

You will see output similar to:
```text
INFO:     Started server process [XXXX]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

### Step 5: Open in Your Browser
Open your browser and navigate to:
👉 **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)**

---

## 4. Accessing the Web Interface & User Credentials

The database is pre-seeded with 3 institutional controller roles:

| Role | Email | Password | Permissions |
| :--- | :--- | :--- | :--- |
| **Financial Controller / Admin** | `admin@acme.co` | `Admin@2026!` | Full administrative access, audit chain inspection, all approvals |
| **Financial Approver (Checker)** | `approver@acme.co` | `Approver@2026!` | Maker-Checker dual control sign-off on journal adjustment vouchers |
| **Reconciliation Analyst (Maker)** | `analyst@acme.co` | `Analyst@2026!` | Ingest CSVs, trigger batch runs, draft adjustment proposals |

---

## 5. Application Features & Navigation

Once loaded on `http://127.0.0.1:8000/`, you can explore all modules via the top navigation bar:

1. **📊 Executive Dashboard**:
   - High-level KPIs: Reconciled Volume, Match Rate %, Precision/Recall, Unresolved Exceptions, and 13-Week Segmented Cash Forecast.
2. **🪟 Batch Windows**:
   - Inspect sliding reconciliation windows (e.g. WIN-01 through WIN-10) with exact timing boundary metadata.
3. **🔍 Reconciliation Explorer**:
   - 3-Way matching table comparing Gateway Captures vs. Bank Statement Deposits vs. ERP General Ledgers.
   - Filter by **Tier 1 (Exact Match)** vs **Tier 2 (Contextual MDR Fee Split)**.
4. **⚠️ Exception Center**:
   - 16-type exception taxonomy (Cutoff timing differences, missing bank credits, fee deductions, duplicate references).
   - Click any exception to open the AI Investigation Drawer with root-cause analysis and proposed ledger adjustments.
5. **🛡️ Maker-Checker Queue**:
   - Strict dual-control segregation of duties.
   - Approvers review AI-proposed journal vouchers and click **Approve** or **Reject**.
6. **⛓️ Cryptographic Audit Trail**:
   - Sequential SHA-256 block hash chain with real-time verification (`GET /api/v1/audit/verify-chain`).
7. **🤖 AI Financial Investigator (Chatbot)**:
   - Click **"Ask AI Investigator"** in the navigation bar (or press `Ctrl + K` / `Cmd + K`).
   - Ask any question, click prompt chips, or inquire about specific transactions:
     - *"Why didn't invoice INV-2026-0412 settle in this batch?"*
     - *"How many exceptions are there?"*
     - *"What is the cash forecast for next month?"*
     - *"Explain MDR fee tiers (1.5% Enterprise vs 2.0% Standard)"*
     - *"Explain maker-checker governance rules"*
8. **📥 Multi-Source CSV Ingestion**:
   - Click **"Upload CSVs"** in the top-right header to upload custom Gateway, Bank, and Ledger files.

---

## 6. Alternative Startup Methods

### Option A: Direct Application Startup
To run the server without reloading in production mode:
```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend
```

### Option B: Docker Compose (Full Stack with PostgreSQL & Redis)
To run the full stack containerized:
```bash
docker-compose up --build
```
Access the application on `http://localhost:8000`.

---

## 7. Running Automated Tests

The application includes a comprehensive test suite covering data ingestion, 3-way matching, decision policy, segmented cash forecasting, SHA-256 audit chaining, Redis caching/locking, and AI QA investigations.

Run the test suite with:
```powershell
$env:PYTHONIOENCODING="utf-8"
python -m unittest backend/tests/test_pipeline.py -v
```

Expected output:
```text
Ran 16 tests in ~20s
OK
```

---

## 8. Troubleshooting & FAQ

### Q: Port 8000 is already in use
**Fix**: Start Uvicorn on another port, for example `8080`:
```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --app-dir backend
```
Then visit `http://127.0.0.1:8080/`.

### Q: Redis connection warnings in the logs
**Explanation**: Redis is optional. If Redis is not running, the application logs:
```text
redis_unavailable: Could not connect to Redis. Operating with local in-memory fallback.
```
This is **normal behavior**. The app is designed to **fail open** gracefully and continue functioning at 100% capacity.

### Q: Where are the database files stored?
**Answer**: SQLite database is stored locally at `finance_controller.db` in the workspace root.

---

🎉 **You are now ready to run and experience the Autonomous AI Financial Controller!**
