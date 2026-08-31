# 09 — Agentic Transformation: Analysis & Implementation Plan

> Read-only audit of the shipped code, followed by the plan to turn it into an agentic
> LangGraph-orchestrated finance controller **without putting an LLM on financial truth**.
> Every claim below is anchored to a file and line in this repository.

---

## 1. Problem Statement Understanding

No problem-statement image or separate plan document was supplied with the repo, so
`docs/00-product-and-scope.md` is treated as the plan of record. It states the bar plainly
(`docs/00`, line 7):

> "throughput plus measured accuracy plus an honest exception list. One cherry-picked match proves nothing."

The track is **"run the books *and the cash position*"**. Decomposed, the system must:

1. Ingest three heterogeneous sources — payment gateway, bank statement, general ledger — and
   reconcile them **three ways**, not pairwise.
2. Handle real settlement mechanics: **N:1 netted settlements**, MDR fees (2.0% standard /
   1.5% enterprise) plus 18% GST on the fee, refunds, chargebacks, T+1/T+2 lag, period cut-off
   timing differences, materiality thresholds, and double-entry polarity.
3. Process **2,000+ records** and report **records/sec and wall-clock**, with blocking so the
   candidate space is `O(n·k)` and not `O(n²)`.
4. Prove accuracy: a `ground_truth_links` manifest with **precision / recall / F1 computed
   against it, not asserted**.
5. Enumerate **100% of residuals** — "never a sample."
6. Three differentiators: (a) **Hungarian global optimal assignment**, (b) a **real N:1
   settlement solver** as bounded subset-sum with a fee model, (c) **calibrated confidence +
   ECE + a reliability curve**.
7. Keep the AI strictly subordinate (`docs/00`, line 21): *"the LLM has zero write access to
   financial state. It emits schema-validated proposals; a deterministic verifier re-checks
   every proposal against hard gates before anything is applied."*
8. Enforce maker-checker segregation of duties and a cryptographically hash-chained audit trail.
9. Produce a deterministic **13-week forward cash forecast**.

`docs/00` §3.4 "Decision rights" is the authoritative boundary and the plan below does not
deviate from it:

| Concern | Owner |
|---|---|
| Arithmetic, ID equality, date tolerance, blocking, scoring, assignment, subset-sum, thresholds, access control, ledger writes | **Deterministic — never AI** |
| Free-text normalization, alias resolution, the exception-classification tail, prose explanation, tie-break suggestions, proposal selection | **AI** |
| Accepting a resolution above materiality | **Human required** |

---

## 2. Requirement Coverage Audit

Status legend: **Complete** / **Partial** / **Missing** / **Incorrect** (present but wrong or fabricated).

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | 2,000+ record batch | **Incorrect** | Shipped data is 64 rows (`data/gateway.csv` 12, `data/bank.csv` 10, `data/general_ledger.csv` 42) while `batches.py` defaults `record_count=240` |
| 2 | records/sec + wall-clock measured | **Partial** | `benchmarks.py:` computes it, but falls back to a hardcoded `345.0` rps |
| 3 | `O(n·k)` blocking, not `O(n²)` | **Partial** | `ReconciliationGraphBuilder` blocks correctly, but `batch_orchestrator.py:84` calls `TransactionContextBuilder.build_context(txn, all_txns)` inside the per-transaction loop, and `context_builder.py` scans `for other in all_txns` → **O(n²)** |
| 4 | Three-way GW ↔ Bank ↔ GL | **Complete** | `matching_engine.py` `build_reconciliation_graph` → `three_way` / `n1` / `pairwise` components |
| 5 | N:1 netted settlement solver | **Complete** | `pass_n1_settlement_solver`: declared settlement-key tier + bounded subset-sum DP over paise |
| 6 | Hungarian global assignment | **Complete** | `pass_p4_fuzzy_hungarian` via `scipy.optimize.linear_sum_assignment` |
| 7 | MDR + GST fee model | **Complete** | `score_amount` recognises 2.0%/1.5% MDR + 18% GST within tolerance |
| 8 | T+1/T+2 lag & period cut-off | **Partial** | Works, but **six mutually contradictory hardcoded period anchors** exist (see §8) |
| 9 | Refunds / chargebacks | **Missing** | `leg_role` enum is only `PRIMARY / COUNTERPART / FEE / TAX`; `docs/03` specifies `REFUND`, `CHARGEBACK`, `ADJUSTMENT`, `ROUNDING` |
| 10 | Precision/recall/F1 vs ground truth | **Missing (in product)** | `BenchmarkEvaluator` is imported **only** by root `test_full_regression.py`, never by `backend/app/`. `data/ground_truth_links.json` (60 links, ids `pay_G8x0001`, `JE-5001_1`) matches **no shipped CSV** (which use `pay_EXT_1001`, `pay_1002`) |
| 11 | Calibrated confidence + ECE + reliability curve | **Incorrect** | `benchmarks.py`: `outcomes = [1 if np.random.rand() < precision else 0 ...]` — **ECE is computed against random numbers**. `matching_engine.py:9` imports `IsotonicRegression` and never uses it |
| 12 | 100% residual enumeration | **Complete** | `pass_p5_residuals` |
| 13 | LLM has zero write access | **Complete (code) / Incorrect (claims)** | No write tool exists — good. But `agent_runtime._deterministic_investigate` fabricates `ToolEvidence(tool="get_transaction_details", ...)` claiming tools ran when none exist |
| 14 | Schema-validated proposals + deterministic verifier | **Partial** | `DeterministicVerifier.verify_proposal` is real (id existence, fee arithmetic re-check, confidence bounds) but **omits the rule-citation gate** that `docs/03` §10.4 specifies via `valid_rules: set[str]` |
| 15 | Maker-checker human approval | **Incorrect** | Server-side gate is real (`approvals.py:63`, role from JWT). The **UI never calls it** — `app.js` `approveProposal()` only shows a toast saying "posted to ledger" and filters the row out of a local array |
| 16 | Approval limits / materiality gate | **Missing** | `User.approval_limit_minor` is seeded (500000 / 50000000 / 100000000) and never read; no maker≠checker identity check |
| 17 | Hash-chained audit trail | **Partial/Incorrect** | Preimage in `audit_chain.py` omits `entity_type` and `action`, so `REJECTED`→`APPROVED` can be flipped without breaking the chain. No unique index on `(org_id, event_seq)`; each batch restarts at seq 1, so `/audit/verify-chain` returns **409 "Potential tampering detected" on an untampered DB** after a second batch |
| 18 | Immutable batch report + report_hash | **Incorrect** | `database_service.py:348`: `report_hash=summary.get("report_hash", hashlib.sha256(b"report").hexdigest())` — a constant |
| 19 | 13-week cash forecast from real data | **Incorrect** | `cash_forecaster.py`: `base_date = date(2026,3,31)`, `weekly_baseline_inflow = 55000000`, weeks 3–13 wholly synthetic via `growth_factor = 1.0 + (w*0.015)`. Only 2 of 13 weeks touch real data |
| 20 | Org isolation / RLS | **Missing** | `org_id` columns exist; zero row-level enforcement. `GET /transactions/` has **no auth and no batch/org filter** |
| 21 | `raw_records` lineage | **Missing** | `docs/03` specifies an immutable append-only `raw_records` table with `content_hash` dedupe; `Transaction.raw_record_id` is nullable and never set |
| 22 | SOP / policy corpus | **Missing** | `agent_runtime` cites `SOP-01 §3`, `SOP-02 §4`, `SOP-04 §2`, `SOP-05 §1/§3`. **None of these documents exist anywhere in the repo.** `docs/03` shows they were meant to live in a `sop_documents` table that was never built |
| 23 | Bounded agent tool-use loop | **Missing** | `docs/03` §10 specifies "Maximum 6 tool calls", "Strict 60-second execution timeout", "12,000 token maximum context budget" and five read-only tools with JSON Schemas. The code has **no tool definitions and no loop** — one stateless `generate_content` call |
| 24 | Agent telemetry | **Missing** | `docs/03` specifies `agent_runs` + `agent_tool_calls`; neither table exists. `AIInvestigation` exists in `schema.py` and is **never written** |
| 25 | Persisted step DAG | **Missing** | `BatchStep` table exists (`schema.py`) with `step_name/status/records_in/records_out/error_message` and is **never written** |
| 26 | Batch runs outside the request | **Incorrect** | `POST /batches/run` is `async def` but calls the synchronous pipeline inline → **blocks the event loop**. `docs/01` §5.15 warned: "That cannot live in a request" |
| 27 | LangGraph orchestration | **Missing** | Repo-wide grep for `langgraph\|langchain\|mcp` across `.py/.md/.txt/.js/.html/.yml` (excluding `.venv`) returns **zero matches** |
| 28 | MCP | **Missing** | By design — see §13 |
| 29 | Structured logging | **Partial** | `logging` used ad-hoc; no `request_id`/`batch_id`/`agent_run_id` correlation as `docs/01` §5.16 specifies |
| 30 | Scoped batch Q&A | **Incorrect** | `qa.py:373` uses `model="gemini-3.6-flash"` — **a model ID that does not exist**, so the call always raises and every answer falls through to ~570 lines of hardcoded templates (`amount="₹14,50,000.00 Net Inflow"`, `ref = ref_target or "INV-2026-0412"`) |

**Summary: 6 Complete, 7 Partial, 9 Missing, 8 Incorrect.**

The deterministic reconciliation mathematics is genuinely strong. Everything that *reports on*
or *governs* that mathematics — metrics, audit sealing, human approval, the AI layer, and the
entire dashboard — is either fabricated or disconnected.

---

## 3. Current Architecture

```
frontend/index.html + static/js/app.js   (vanilla JS, no framework/bundler, Chart.js)
        │  8 fetch() call sites only
        ▼
FastAPI app  (backend/app/main.py — mounts /static, serves index.html)
        │
        ├── api/v1/auth.py         JWT + Argon2, fails closed
        ├── api/v1/sources.py      upload → SHA-256 → UPLOAD_DIR → Upload row
        ├── api/v1/batches.py      ⚠ module-level global  STATE = {...}
        ├── api/v1/transactions.py ⚠ no auth, no batch/org filter
        ├── api/v1/exceptions.py   only path that would call an LLM (UI never calls it)
        ├── api/v1/approvals.py    real maker-checker (UI never calls it)
        ├── api/v1/audit.py        chain verify (409s after 2nd batch)
        ├── api/v1/reports.py      reads STATE, not the DB
        └── api/v1/qa.py           1000 lines; broken model id → templates
        │
        ▼
services/
  provenance.py      ✅ real streaming SHA-256, hard-fails on missing/mismatched file
  ingestion.py       ✅ polars CSV + schema validation  (ignores column_map/amount_scale)
  normalizer.py      🟡 real regex ref-keys; hardcodes counterparty & account_code
  validation_service.py ⚠ real — but never called in production
  matching_engine.py ✅✅ the crown jewel: gates, blocking, 6 passes, subset-sum, Hungarian
  batch_orchestrator.py ⚠ the de-facto pipeline; calls _deterministic_investigate, never an LLM
  agent_runtime.py   ⚠ 1 stateless LLM call, no tools, no loop; fabricates tool evidence
  decision_engine.py 🟡 real fee arithmetic; fabricates an "AI confidence" of 0.92/0.90/0.70
  rules_engine.py    ⚠ clean RuleEvaluator + DEFAULT_RULES — entirely dead code
  benchmarks.py      ⚠ ECE from np.random; hardcoded precision 0.994 / recall 0.958
  cash_forecaster.py ⚠ 11 of 13 weeks synthetic
  audit_chain.py     🟡 hash chain with an incomplete preimage
        │
        ▼
db/schema.py  16 SQLAlchemy tables → SQLite finance_controller.db
```

**The single most consequential structural fact:** `backend/app/api/v1/batches.py` holds a
module-level dict

```python
STATE = {active_batch, transactions, matches, exceptions, decisions, proposals,
         approvals, audit_events, windows, quality_metrics, cash_forecast, provenance}
```

which is imported by `reports.py`, `exceptions.py`, `approvals.py`, `transactions.py`,
`audit.py`, and `qa.py`. It is single-process, single-batch, and lost on restart. It — not the
database — is what the API actually reads. This is the root cause of a whole class of
"works in the demo, 500s after a restart" behaviour.

---

## 4. Current System Flow (end to end, as actually executed)

1. `POST /api/v1/auth/login` → JWT. `app.js` **auto-logs-in as `approver@acme.co`** with the
   password shipped in the client bundle, and `authFetch` silently re-auths as approver on any 401.
2. `POST /api/v1/sources/upload` → bytes read, SHA-256 computed, written to `UPLOAD_DIR`,
   `Upload` row persisted. A parse failure is swallowed (`except Exception: total_rows = 0`) yet
   the row is stored `status="COMPLETED"`. Schema validation does **not** run at upload time.
3. `POST /api/v1/batches/run` (blocking, in-request):
   - `USER_UPLOAD`: `resolved_files[s_kind_str] = u.storage_path` — **a dict keyed by source
     kind, so only one file per kind survives**.
   - `provenance.py` verifies each hash and hard-fails on mismatch. ✅
   - `ingestion.parse_file` → `normalizer.normalize` → `CanonicalTransaction[]`.
     `DataValidationService` is imported at `batch_orchestrator.py:19` and **never called**.
   - `matching_engine` runs P0→P5 with the semantic gate, blocking graph, N:1 solver and
     Hungarian assignment. ✅ This part is real.
   - For each non-exact transaction, `batch_orchestrator.py:96-103` calls
     `self.agent._deterministic_investigate(...)` — the private hardcoded-template method.
     **No LLM is invoked anywhere in the production pipeline.**
   - `decision_engine` blends in a fabricated `ai_score` of `0.92 / 0.90 / 0.70` when no AI ran.
   - `benchmarks` fabricates ECE from `np.random`.
   - `cash_forecaster` synthesises weeks 3–13.
   - Everything is written to `STATE`, then `save_batch_run` persists a subset to SQLite —
     omitting `AIInvestigation`, `MatchCandidate`, `BatchStep`, and `Match.solver_evidence`.
4. The UI polls `/transactions/?limit=500` (unauthenticated, unscoped — returns rows from
   **every** historical batch), `/reports/summary` (reads `STATE`), `/exceptions/`,
   `/audit/events`.
5. The analyst clicks **Approve**. `app.js`:
   ```javascript
   window.approveProposal = function (excId) {
     showToast(`Voucher for ${excId} signed off & posted to ledger.`, 'success');
     appState.allExceptions = (appState.allExceptions || []).filter(e => (e.id||'') !== excId);
     renderExceptionsQueue();
   };
   ```
   **No network call. Nothing is posted. Nothing is audited.** The defining control of the
   system is a toast notification.

---

## 5. Frontend Analysis

Vanilla HTML/CSS/JS, no build step, Chart.js via CDN, served by FastAPI's static mount.
Four views (`view-overview`, `view-workflow`, `view-exceptions`, `view-audit`) plus a `qa-modal`.
The visual design is competent and worth preserving.

What is real: the transaction table, the exception list, the audit event list, file upload, batch
trigger, and the Q&A modal round-trip.

What is cosmetic:

| Element | Reality |
|---|---|
| `renderClusterHistogram()` | 52 fixed bar heights with fabricated tooltips `"Analysis Window #i Load: h%"`; critical/warm indices hardcoded |
| `chartThreatVectors` | `data: [120, 48, 79, 71, 76, 26, 12, 18, 24]` — literal |
| `chartNetworkFlow`, `renderWorkflowLiquidityChart` | `[12.4, 15.2, 18.0, …]` — literal |
| All three charts | Grep confirms **no `.data.datasets` mutation and no `.update()` call anywhere** in `app.js`. They can never show real data |
| 13-week cash forecast | Never fetched from the backend at all |
| Exception "AI proposal" column | Derived client-side from `exception_type` substrings |
| `updateActiveExceptionLanes()` | Classifies by `description_raw` substrings and `occurred_at.includes('2026-03-31')` |
| `startWorkflowProcessing()` | Does real work, then prints fabricated `logLine('Stage 01…05')` messages interleaved with `await sleep(200)` |
| `index.html` static values | `12 Held`, `98.5%`, `228`, `₹28.45L`, `240`, `52 Windows`, `wf-kpi-acc 98.5%`, `wf-kpi-excs 173`, `wf-badge-sop "SOP-01: Three-Way Matching"` (a nonexistent document) |
| Role switcher | Hardcoded credentials for both accounts in shipped JS |

A grep for `cash_forecast|windows|quality_metrics|proposals|approvals|precision|recall|f1|ece`
in `app.js` returns only unrelated string matches: **the frontend consumes none of the
backend's telemetry, quality metrics, proposals, approvals, or accuracy numbers.**

Endpoints the backend exposes that the UI never calls: `/batches/active` (which returns rich
real `quality_metrics`, `windows`, `provenance`, `operational_metrics`), `/approvals/pending`,
`/approvals/decide`, `/transactions/matches`, `/exceptions/{id}`, `/batches/{id}/progress`.

---

## 6. Backend Analysis

**Preserve as-is (real, correct, valuable):**
- `matching_engine.py` — `AccountingSemanticGate` (`ALLOWED_SOURCE_PAIRS`, polarity, currency,
  self-match and chronology gates), `ReconciliationGraphBuilder`, the scoring statics
  (`score_id`, `score_amount` with the MDR+GST recognition, `score_date` with a 1-day grace and
  exponential decay, rapidfuzz `token_set_ratio` for description/counterparty), the six passes,
  the two-tier N:1 solver with `AMBIGUOUS_SETTLEMENT_GROUP_SAFEGUARD`, and the Hungarian
  assignment with entry threshold `0.50`, acceptance `s >= 0.80 and margin >= 0.05`, and
  `RUNNER_UP_MARGIN_SAFEGUARD`.
- `provenance.py` — real streaming SHA-256, real row counts, and hard gates:
  `USER_INPUT_FILE_NOT_FOUND: … Synthetic fallback is strictly blocked.` /
  `HASH_VERIFICATION_FAILED: … Reconciliation halted immediately.`
- `ingestion.py` — polars with a `csv.Sniffer` fallback and per-source `validate_schema`.
- `core/security.py` — Argon2, JWT with `exp/sub/org_id/role/iat`, `get_current_user` fails
  closed with 401, `require_roles` guard exists.
- `DeterministicVerifier` and `should_invoke_ai` in `agent_runtime.py`.
- `rules_engine.py` `RuleEvaluator` (eq/neq/lt/lte/gt/gte/between/in/pct_of/days_between/regex_match).
- `validation_service.py`.

**Defects to fix (highest severity first):**

| Severity | File | Defect |
|---|---|---|
| Critical | `app.js` | `approveProposal` claims "posted to ledger" without any network call |
| Critical | `benchmarks.py` | ECE derived from `np.random.rand()`; `precision = 0.994` / `recall = 0.958` hardcoded fallbacks |
| Critical | `batch_orchestrator.py:96` | Pipeline calls `_deterministic_investigate`, never the LLM |
| Critical | `agent_runtime.py` | Fabricated `ToolEvidence` and citations to SOP documents that do not exist |
| Critical | `database_service.py:348` | `report_hash = sha256(b"report")` — a fake integrity seal |
| Critical | `qa.py:373` | `model="gemini-3.6-flash"` doesn't exist → 570 lines of hardcoded answers |
| Critical | `transactions.py` | `GET /transactions/` unauthenticated and unscoped by batch/org |
| High | `audit_chain.py` | Preimage omits `entity_type` and `action` |
| High | `schema.py` | No unique constraint on `(org_id, event_seq)`; `Index` imported and never used → **no indexes at all** |
| High | `audit.py` | `/verify-chain` orders globally by `event_seq` → 409 on an untampered DB after batch 2 |
| High | `approvals.py` | No `approval_limit_minor` check, no maker≠checker identity, audit link taken globally with no `batch_id` |
| High | `cash_forecaster.py` | 11 of 13 weeks synthetic |
| High | `batches.py` | Global `STATE`; `POST /run` blocks the event loop; `resolved_files` dict drops files |
| High | `normalizer.py` | `cp_raw = "RAZORPAY SOFTWARE PVT"` for **every** BANK row; `acct_code = "1210 …"` for every GATEWAY row → `score_cp` and the polarity gate operate on constants |
| High | `schemas.py` | `CanonicalTransaction` lacks `txn_type`, `amount`, `normalizer_version` → the normalizer's values are silently dropped by Pydantic |
| Medium | six files | Six contradictory period anchors: engine `month==8 and day==31`; `agent_runtime` `"2026-03-31"`; `database_service` `date(2026,3,1)–date(2026,3,31)`; `STATE` `"2026-08-01"–"2026-08-31"`; `context_builder` `day in (28,29,30,31) and hour >= 20`; `normalizer` default `date(2026,8,20)`; `cash_forecaster` `date(2026,3,31)` |
| Medium | `database_service.py:165` | `matched_records = exact*2 + contextual*2` — wrong for N:1 clusters |
| Medium | `context_builder.py` | Unconditional 7-item `checks_performed` list; fabricated `counterparty_history`; O(n²) scan |
| Medium | `decision_engine.py` | Tier 3 returns hardcoded `confidence=0.88`, ignoring its own computed scores |
| Medium | `matching_engine.py:9` | `IsotonicRegression` imported, never used → no calibration exists |
| Medium | `ingestion.py` | `parse_file(column_map=None, amount_scale=100)` ignores both parameters → seeded `SourceProfile.column_mapping` is decorative |
| Medium | `sources.py` | `"pay" in fn_lower → GATEWAY` tested before any bank keyword, so `bank_payments.csv` → GATEWAY; unknown files default to GATEWAY; whole file read into memory, no size cap |
| Medium | `rules_engine.py`, `validation_service.py`, `benchmarks.py` | Dead in production — grep confirms no caller inside `backend/app/` |

---

## 7. Frontend ↔ Backend Integration Map

| UI element | Calls | Server reads from | Verdict |
|---|---|---|---|
| Login / role switch | `POST /auth/login` | `users` table | ✅ Real (but credentials in client JS) |
| Upload panel | `POST /sources/upload` | writes `uploads` | ✅ Real (no schema check at upload) |
| "Run reconciliation" | `POST /batches/run` | files → engine → `STATE` + DB | ✅ Real work, ⚠ blocks the event loop |
| Transaction table | `GET /transactions/?limit=500` | `transactions` (**all batches**) | ⚠ Real rows, wrong scope, no auth |
| KPI tiles | `GET /reports/summary` | **`STATE`**, not DB | ⚠ Dies after restart |
| Exception queue | `GET /exceptions/` | `exceptions` (thin projection) | 🟡 Real ids; findings/confidence invented client-side |
| **Approve / Reject** | *(nothing)* | — | ❌ **Fake** |
| Investigation detail | *(nothing)* | — | ❌ Never calls `/exceptions/{id}` |
| Audit log | `GET /audit/events` | `audit_events` | ✅ Real |
| Verify chain | `GET /audit/verify-chain` | `audit_events` | ⚠ 409s on a clean DB after batch 2 |
| Q&A modal | `POST /qa/ask` | tools run, then a dead model id | ⚠ Answers are templates |
| 3 dashboard charts | *(nothing)* | — | ❌ **Hardcoded arrays** |
| Cluster histogram | *(nothing)* | — | ❌ **52 literal bars** |
| 13-week cash forecast | *(nothing)* | — | ❌ Backend forecast never fetched |
| Progress terminal | *(nothing)* | — | ❌ Fabricated stage lines + `sleep(200)` |
| Quality metrics / precision / recall / F1 / ECE | *(nothing)* | — | ❌ Never surfaced |
| Pending approvals | *(nothing)* | — | ❌ `/approvals/pending` never called |

Eight fetch sites total. The backend exposes materially more truth than the frontend displays,
and the frontend displays materially more "truth" than the backend actually produces.

---

## 8. Real vs Mock Data Inventory

| Artefact | Real? | Where |
|---|---|---|
| Uploaded file bytes, SHA-256, row counts | ✅ Real | `provenance.py`, `sources.py` |
| CSV parsing & schema validation | ✅ Real | `ingestion.py` |
| Canonical normalization | 🟡 Mostly real; counterparty and account_code are constants | `normalizer.py` |
| Matching (all six passes, N:1, Hungarian) | ✅ Real | `matching_engine.py` |
| Exception detection & residual enumeration | ✅ Real | `matching_engine.py` |
| Match confidence | ❌ Hardcoded per tier (1.00 / 0.95 / 0.88 / 0.60) | `batch_orchestrator.py` |
| "AI investigation" | ❌ Template strings; no LLM runs | `agent_runtime._deterministic_investigate` |
| Tool evidence | ❌ Fabricated — the named tools don't exist | `agent_runtime.py` |
| SOP citations | ❌ SOP-01…05 do not exist in the repo | `agent_runtime.py`, `qa.py`, `index.html` |
| `checks_performed` | ❌ Unconditional hardcoded list | `context_builder.py`, `matching_engine.py:992` |
| Precision / recall / F1 | ❌ Hardcoded fallbacks; never computed in-product | `benchmarks.py` |
| ECE / calibration | ❌ `np.random.rand()` | `benchmarks.py` |
| records/sec | 🟡 Computed, with a `345.0` fallback | `benchmarks.py` |
| `report_hash` | ❌ `sha256(b"report")` | `database_service.py:348` |
| Audit chain | 🟡 Real hashes, incomplete preimage, breaks on batch 2 | `audit_chain.py`, `audit.py` |
| 13-week cash forecast | ❌ 11 of 13 weeks synthetic | `cash_forecaster.py` |
| Dashboard charts (×3) + histogram | ❌ Literal arrays in JS | `app.js` |
| Progress terminal | ❌ Fabricated | `app.js` |
| Q&A answers | ❌ Templates (dead model id) | `qa.py` |
| Approval action | ❌ Client-side toast only | `app.js` |
| Reporting period | ❌ Six contradictory hardcoded anchors | six files |
| Ground-truth manifest | ⚠ Exists (60 links) but its ids match no shipped CSV | `data/ground_truth_links.json` |

Per the **REAL DATA REQUIREMENT**, every ❌ in a production path must be replaced with real
data flow or removed. Mock data survives only in `backend/tests/` and
`data/test_utilities/synthetic_generator.py`, both explicitly labelled.

---

## 9. Current AI Analysis — is it agentic?

**No.** It is a single stateless completion call with a template fallback.

| Agentic property | Present? |
|---|---|
| Tool definitions exposed to the model | ❌ None exist |
| Multi-step tool-use loop | ❌ One `generate_content` call |
| Iterative state across steps | ❌ None |
| Planning / routing | 🟡 Only `should_invoke_ai`, a single boolean gate |
| Bounded budget (calls / time / tokens) | ❌ None of the three from `docs/03` §10 |
| Model routing (haiku triage → sonnet investigate) | ❌ Hardcoded `gemini-2.5-flash`, then `claude-3-5-sonnet-20241022` |
| Telemetry / traceability | ❌ `AIInvestigation` never written |
| Recovery from failure | ⚠ `except Exception: pass` → silent fallback to templates |
| **Actually invoked in the pipeline** | ❌ **No** — `batch_orchestrator` calls the private template method |

What *is* worth keeping: `should_invoke_ai` (a genuine cost gate with a `deterministic_types`
skip-set, LOW/≤₹500 → manual queue, CRITICAL/HIGH or ≥ materiality → AI),
`build_targeted_context` (correctly scopes candidates to ≤3 bank / ≤5 ledger and precomputes
the gross/MDR/GST arithmetic so the model never does math), the SHA-256 response cache, and
`DeterministicVerifier`.

`docs/03` §10 designed the right thing and it was never built: 5 read-only tools
(`get_transaction_details`, `get_counterparty_history`, `get_reconciliation_rules`,
`search_similar_past_exceptions`, `get_batch_context`), a ≤6-call bounded loop, a 60s timeout,
a 12k token budget, zero write access, prompt caching on static SOPs, and a system prompt whose
first line is *"You are a PROPOSER, not an executor… NEVER guess or fabricate numbers."*

---

## 10. Agentification Plan — what becomes an agent, and what must never

The test applied to every step: *if an LLM gets this wrong, can it corrupt a number?*
If yes, it stays deterministic code.

| Pipeline step | Classification | Rationale |
|---|---|---|
| File hashing / provenance | **Deterministic node** | Integrity primitive |
| Parse + schema validate | **Deterministic node** | Structural |
| Data quality validation | **Deterministic node** | Rule enforcement |
| Normalization (typed ref-key extraction, paise conversion) | **Deterministic node** | Arithmetic + regex |
| Counterparty alias resolution (free text → entity) | **AI-assisted, deterministic apply** | Genuinely ambiguous text; result is a *proposed* alias written to `counterparty_aliases`, applied only after verification |
| Blocking / candidate generation | **Deterministic node** | Complexity guarantee |
| Feature scoring | **Deterministic node** | Arithmetic |
| Exact / rule matching (P0–P3) | **Deterministic node** | Financial truth |
| N:1 subset-sum settlement solve | **Deterministic node** | Financial truth |
| Hungarian assignment | **Deterministic node** | Optimisation, must be reproducible |
| Residual enumeration | **Deterministic node** | Completeness guarantee |
| Exception triage (type + severity) | **AI agent (bounded)** | Classification tail; wrong answer only mis-routes work |
| Exception investigation (cause + proposal + evidence) | **AI agent (bounded, tools)** | The actual value-add; output is a *proposal* |
| Proposal verification | **Deterministic node** | The gate that makes the AI safe |
| Policy / approval routing | **Deterministic node** | Rule enforcement, materiality, limits |
| Human approval | **Human interrupt** | Segregation of duties |
| Applying a resolution | **Deterministic node** | Ledger write |
| Metrics / precision / recall / F1 / ECE | **Deterministic node** | Measurement must not be persuadable |
| Cash forecast | **Deterministic node** | Arithmetic over real matched data |
| Report snapshot + audit seal | **Deterministic node** | Integrity |
| Batch Q&A | **AI agent (bounded, read-only tools)** | Natural-language surface over real data |

**Three agents. No more.**

1. **Triage Agent** — cheap/fast model. Input: deterministic exception facts. Output:
   `{classification, severity, needs_investigation, suggested_tools}`. Read-only.
2. **Investigation Agent** — stronger model, bounded tool loop (≤6 calls, 60s, 12k tokens).
   Output: a schema-validated `InvestigationResult` (classification, likely_cause,
   candidate_match_ids, recommended_action, confidence, evidence[], citations[],
   requires_human_review). Read-only tools only.
3. **Batch Q&A Agent** — bounded read-only tool loop scoped to a single `batch_id`. Replaces the
   fabricated template engine in `qa.py`.

**Explicitly NOT created**, because each would put an LLM on financial truth: a matching agent,
a ledger-posting agent, a forecasting agent, an approval agent, a metrics agent.

---

## 11. Target Architecture

```
                    DETERMINISTIC FINANCIAL TRUTH
                              ▲
                              │ (only code writes financial state)
┌─────────────────────────────┴──────────────────────────────────────┐
│  LangGraph  StateGraph("reconciliation")   thread_id = batch_id    │
│  checkpointer = SqliteSaver(finance_controller.db)                 │
│                                                                    │
│  ingest_provenance → parse_validate →[router]→ normalize →          │
│  persist_raw → block → match_deterministic → solve_n1 →            │
│  assign_hungarian → enumerate_residuals →                          │
│        │                                                           │
│        └─[route_exception]─┬─ deterministic type ─→ skip           │
│                            ├─ below materiality  ─→ manual_queue   │
│                            └─ material/critical  ─→ triage_agent   │
│                                                        ↓           │
│                                              investigate_agent     │
│                                              (≤6 tools, 60s, 12k)  │
│                                                        ↓           │
│                                              verify_proposal (D)   │
│                                          ┌─────────────┴────────┐  │
│                                     rejected              accepted│
│                                          ↓                     ↓  │
│                                    human_queue        apply_policy│
│                                                              ↓    │
│                                        ┌──── auto-post (below     │
│                                        │      materiality AND     │
│                                        │      calibrated conf ≥ θ)│
│                                        └──── interrupt() ─→ HUMAN │
│                                                              ↓    │
│                                                    apply_resolution│
│  → compute_metrics → forecast_cash → snapshot_report → seal_audit  │
└────────────────────────────────────────────────────────────────────┘
     every node writes a batch_steps row; every agent writes
     agent_runs + agent_tool_calls; every transition emits a
     hash-chained audit_event
```

Invariants enforced by construction:

- The LLM has **no write tool**. Tools are typed Python functions returning read-only DTOs;
  no LLM-authored SQL (`docs/01` §5.17).
- Every AI output passes `verify_proposal` before it can become a `resolution_proposal`.
- No resolution above materiality is applied without a human `approvals` row.
- The AI is a distinct actor (`actor_type='agent'`) with **no** approval capability
  (`docs/01` §5.12).
- Deterministic nodes are idempotent, keyed `(batch_id, step_name)`; re-running is a no-op.
- Financial state lives in the DB, not in a module global. `STATE` is deleted.

---

## 12. LangGraph Workflow Design

**Shared state** (`backend/app/graph/state.py`):

```python
class FinanceState(TypedDict, total=False):
    # identity / control
    org_id: str; batch_id: str; run_id: str; actor_id: str
    execution_mode: str            # USER_UPLOAD | INTERNAL_TEST | SYNTHETIC_BENCHMARK
    period_start: date; period_end: date
    halt_reason: Optional[str]
    errors: Annotated[list[NodeError], operator.add]
    step_telemetry: Annotated[list[StepRecord], operator.add]
    # data lineage
    source_files: list[FileProvenance]
    raw_record_ids: list[str]
    canonical_txns: list[CanonicalTransaction]
    validation_report: Optional[ValidationReport]
    # matching
    blocking_stats: dict
    match_candidates: list[MatchCandidateRecord]
    matches: list[MatchSchema]
    residuals: list[str]
    # exceptions & AI
    exceptions: list[ExceptionSchema]
    triage: Annotated[list[TriageResult], operator.add]
    investigations: Annotated[list[InvestigationResult], operator.add]
    tool_calls: Annotated[list[ToolCallRecord], operator.add]
    verifier_rejections: Annotated[list[VerifierRejection], operator.add]
    # decisions
    proposals: list[ProposalRecord]
    pending_approvals: list[str]
    human_decisions: Annotated[list[HumanDecision], operator.add]
    # outputs
    metrics: Optional[BatchMetrics]
    cash_forecast: list[dict]
    report: Optional[dict]
```

**Nodes** (D = deterministic, A = AI, H = human):

| # | Node | Kind | Wraps |
|---|---|---|---|
| 1 | `ingest_provenance` | D | `provenance.py` (unchanged) |
| 2 | `parse_and_validate` | D | `ingestion.parse_file` + `validate_schema` + `DataValidationService.validate_batch` ← **finally wired in** |
| 3 | `normalize` | D | `normalizer.py` |
| 4 | `persist_raw_and_canonical` | D | new `raw_records` + `transactions` |
| 5 | `build_blocking_graph` | D | `ReconciliationGraphBuilder` |
| 6 | `match_deterministic` | D | passes P0–P3 |
| 7 | `solve_n1_settlement` | D | `pass_n1_settlement_solver` |
| 8 | `assign_hungarian` | D | `pass_p4_fuzzy_hungarian` |
| 9 | `enumerate_residuals` | D | `pass_p5_residuals` |
| 10 | `triage_agent` | A | new — cheap model, no tools |
| 11 | `investigate_agent` | A | new — bounded tool loop, 5 read-only tools |
| 12 | `verify_proposal` | D | `DeterministicVerifier` **+ the missing rule-citation gate** |
| 13 | `apply_policy` | D | `rules_engine.RuleEvaluator` ← **finally wired in** + materiality + `approval_limit_minor` |
| 14 | `human_approval` | H | `interrupt()` — durable pause |
| 15 | `apply_resolution` | D | writes the resolution effect + audit event |
| 16 | `compute_metrics` | D | `BenchmarkEvaluator` vs `ground_truth_links` ← **finally wired in**, plus isotonic calibration |
| 17 | `forecast_cash` | D | rewritten `cash_forecaster` over real matched data |
| 18 | `snapshot_report` | D | immutable `batch_reports` + a **real** `report_hash` |
| 19 | `seal_audit_chain` | D | chained events for every transition |
| — | `manual_queue` | D | terminal sink for sub-materiality and AI-declined items |

**Conditional routers:**

- `after_validate` → `halt` if fatal schema/quality failure, else `normalize`.
  A fatal validation failure must stop the batch, not degrade it.
- `route_exception(exc)` → `skip` (deterministic type) | `manual_queue` (severity LOW and
  impact < ₹500) | `triage_agent`.
- `after_triage` → `investigate_agent` | `manual_queue`.
- `after_verify` → `apply_policy` (passed) | `human_queue` **with the failed check attached**
  (rejected). A rejected proposal is never silently retried with a template.
- `after_policy` → `apply_resolution` (auto-post permitted) | `human_approval` (interrupt).
  Auto-post requires impact < materiality **and** calibrated confidence ≥ θ **and** the
  exception type to be on an explicit allow-list.

**Error handling:** every node is wrapped by a decorator that (a) writes a `batch_steps` row
with `records_in`/`records_out`/`duration_ms`/`error_message`, (b) emits an audit event, and
(c) on exception appends to `state["errors"]`. Deterministic nodes are idempotent and safe to
retry. AI nodes retry twice with backoff and then route to `manual_queue` — **never** to a
fabricated template. A node that cannot complete sets `halt_reason` rather than emitting
plausible output.

**Checkpointing & HITL:** `SqliteSaver` against the same database, `thread_id = batch_id`.
This is what makes `interrupt()` at `human_approval` durable — the graph can pause for a human
across a process restart, which the current in-memory `STATE` fundamentally cannot do.
Resumption is `graph.invoke(Command(resume=decision), config)` after `POST /approvals/decide`.

**Execution:** the graph runs in a worker, not in the request. `POST /batches/run` enqueues and
returns `202` with a `batch_id`; `GET /batches/{id}/progress` reads real `batch_steps` rows.
`docs/01` §5.15 chose Dramatiq+Redis; since Redis is optional and fail-open here, the initial
implementation uses a FastAPI background worker writing the same `batch_steps` DAG, so swapping
in Dramatiq later is a transport change only.

---

## 13. MCP Decision

**Decision: do not adopt MCP for this system now.** MCP would add a process boundary, a
serialization layer, and a second authorization surface without adding a single capability
this system needs.

| Candidate use | MCP? | Reason |
|---|---|---|
| The 5 read-only investigation tools | **No** | They are in-process Python over the same SQLAlchemy session and org context. MCP would move them out of the request's org scope — a privilege-escalation surface for zero gain. `docs/01` §5.17 mandates a typed tool layer with **no LLM-authored SQL**; a generic MCP SQL server would violate that directly |
| Batch Q&A tools | **No** | Same, plus answers must be scoped to one `batch_id` — an in-process closure enforces that; a remote server would have to re-derive it |
| Reading local CSV uploads | **No** | Already handled by `provenance.py` + `ingestion.py` with hash verification |
| Exposing *this* system's read-only tools to external clients (e.g. Claude Desktop for a controller who wants to ask questions outside the app) | **Later — legitimate** | This is MCP's actual strength: a stable server contract for third-party hosts. Worth doing **after** the tools exist and are audited in-process |
| Consuming third-party MCP servers for live bank / gateway APIs | **Later — legitimate** | Only once a real banking integration exists. Today ingestion is file-based |

Revisit when either of the last two becomes a real requirement. Adopting MCP before then is
architecture theatre.

---

## 14. Frontend Agent Integration

Design constraint honoured: **no private chain-of-thought is ever exposed.** The UI shows only
structured, auditable agent output.

1. **Exception queue** gains real columns from the backend: severity, impact, `agent_status`
   (`SKIPPED_DETERMINISTIC` / `MANUAL_QUEUE` / `INVESTIGATED` / `VERIFIER_REJECTED` /
   `AWAITING_APPROVAL` / `RESOLVED`), and calibrated confidence. Where AI did not run, the UI
   says so honestly instead of inventing a proposal client-side.
2. **Investigation drawer** (`GET /exceptions/{id}`, finally wired) renders:
   classification · likely_cause (the agent's *output* prose, not its reasoning trace) ·
   recommended_action · calibrated confidence with its band · an **evidence table**
   (`tool` · `record_id` · `field` · `value`) · rule and SOP citations · and a verifier badge:
   *"Arithmetic re-verified in code ✓"* or *"Rejected by verifier: <failed check>"*.
3. **Approve / Reject actually POST** to `/approvals/decide` with the JWT, then re-fetch. On a
   403 the maker-checker or limit breach is surfaced verbatim. The toast-only path is deleted.
4. **Approvals view** driven by `/approvals/pending`, showing the maker, the impact, the limit
   that applies, and whether the current user is permitted to approve it.
5. **Progress terminal** streams real `batch_steps` rows — node name, status, records in/out,
   duration. The `sleep(200)` theatre and fabricated stage lines are deleted.
6. **Charts bound to real data**: cluster histogram from real blocking windows; the flow chart
   from real matched volume; the 13-week forecast from `/reports/summary`. Each chart gets a
   real empty state ("No completed batch yet") instead of literal arrays. Every `new Chart(...)`
   dataset becomes a function of fetched state, with `.update()` on refresh.
7. **Accuracy panel** — the scored deliverable, currently invisible: precision, recall, F1,
   ECE, records/sec, and a reliability curve, all from `batch_reports`, with an explicit
   "not measured — no ground truth manifest for this batch" state.
8. **Q&A modal** shows the real tool trace (tool name + record ids touched) beside the answer,
   and refuses to answer outside the batch scope.

---

## 15. File-by-File Implementation Plan

**New files**

| Path | Purpose |
|---|---|
| `backend/app/graph/state.py` | `FinanceState` + typed records |
| `backend/app/graph/nodes/ingest.py` | nodes 1–4 |
| `backend/app/graph/nodes/matching.py` | nodes 5–9 (thin wrappers; engine untouched) |
| `backend/app/graph/nodes/agents.py` | nodes 10–11 |
| `backend/app/graph/nodes/governance.py` | nodes 12–15 |
| `backend/app/graph/nodes/reporting.py` | nodes 16–19 |
| `backend/app/graph/routers.py` | all conditional edges |
| `backend/app/graph/telemetry.py` | `@node` decorator: `batch_steps` + audit + error capture |
| `backend/app/graph/build.py` | `StateGraph` assembly + `SqliteSaver` |
| `backend/app/agents/tools.py` | 5 read-only tools, typed, org+batch scoped |
| `backend/app/agents/loop.py` | bounded tool loop (≤6 calls / 60 s / 12 k tokens) |
| `backend/app/agents/prompts.py` | system prompts (proposer-not-executor) |
| `backend/app/agents/schemas.py` | `TriageResult`, `InvestigationResult` |
| `backend/app/services/calibration.py` | isotonic calibration + ECE + reliability curve |
| `backend/app/services/period.py` | **single** source of truth for the reporting period |
| `backend/app/api/v1/graph_runs.py` | run/resume/progress endpoints |
| `backend/tests/test_graph_*.py` | node, router, verifier, HITL, and no-write-access tests |

**Modified files**

| Path | Change |
|---|---|
| `api/v1/batches.py` | **delete global `STATE`**; `POST /run` enqueues → `202`; fix `resolved_files` to a list per kind; period from `services/period.py` |
| `api/v1/reports.py`, `exceptions.py`, `transactions.py`, `audit.py`, `qa.py`, `approvals.py` | read from the DB instead of `STATE` |
| `api/v1/transactions.py` | add auth; filter by `batch_id` + `org_id`; fix the `org_id`-less `CanonicalTransaction(**target)` 500 |
| `api/v1/approvals.py` | enforce `approval_limit_minor` and maker≠checker; per-batch audit linkage with `batch_id`; resume the graph |
| `api/v1/qa.py` | delete ~570 lines of templates; real bounded tool loop; correct model id |
| `services/agent_runtime.py` | delete `_deterministic_investigate` fabrication; add the `valid_rules` citation gate; keep `should_invoke_ai`, `build_targeted_context`, `DeterministicVerifier` |
| `services/batch_orchestrator.py` | becomes a thin adapter over the graph; O(n²) context call removed |
| `services/benchmarks.py` | **delete `np.random` outcomes and all hardcoded precision/recall/ECE/rps fallbacks**; return `None` + `"not_measured"` when ground truth is absent |
| `services/cash_forecaster.py` | rewrite over real matched/open data; no baseline constant; correct lakh formatting |
| `services/context_builder.py` | `checks_performed` becomes the real list of executed checks; delete fabricated counterparty history; O(n·k) via the blocking index |
| `services/decision_engine.py` | remove fabricated `ai_score` defaults; use calibrated confidence; Tier 3 returns its computed score |
| `services/audit_chain.py` | add `entity_type` and `action` to the preimage; versioned preimage tag |
| `services/normalizer.py` | derive real counterparty/account_code; fail loudly on unparseable dates instead of substituting one |
| `services/matching_engine.py` | **minimal, surgical**: remove the unused import, replace `month==8/day==31` with the period service, emit real `checks_performed`, real runner-up delta text, include SETTLEMENT in the Hungarian right pool. No algorithmic rewrite |
| `models/schemas.py` | add `txn_type`, `amount`, `normalizer_version` to `CanonicalTransaction`; make it frozen; add exception evidence fields |
| `db/schema.py` | add `raw_records`, `agent_runs`, `agent_tool_calls`, `rules`, `sop_documents`, `counterparty_aliases`; unique index on `(org_id, event_seq)`; the blocking index; exception evidence columns; tz-aware `utc_now()` everywhere |
| `db/database_service.py` | period from the service; correct `matched_records` for N:1; persist `AIInvestigation`, `MatchCandidate`, `BatchStep`, `solver_evidence`; real `report_hash`; real metrics |
| `core/config.py` | `SECRET_KEY` required from env (no code default); `CORS_ORIGINS` non-wildcard; agent budget settings; auto-approve threshold |
| `frontend/static/js/app.js` | real `approveProposal`; remove hardcoded credentials and auto-login; bind all charts to fetched data; real progress stream; investigation drawer; accuracy panel |
| `frontend/index.html` | replace baked-in placeholder numbers with empty states; remove the `SOP-01` badge until a real corpus exists |
| `backend/requirements.txt` | `langgraph`, `langgraph-checkpoint-sqlite`, `structlog` |

---

## 16. Implementation Priority

**P1 — Truth & Safety (must land before any agent work).** An agent built on fabricated
metrics and a fake approval button would only industrialise the problem.

1. Real approval path end to end (frontend → `/approvals/decide` → audit) + limit and
   maker≠checker enforcement.
2. Delete fabricated metrics; wire `BenchmarkEvaluator` into the pipeline; return
   `not_measured` instead of inventing numbers.
3. Single period source of truth (removes all six anchors).
4. Kill global `STATE`; all reads from the DB; scope + authenticate `/transactions`.
5. Audit chain: complete preimage, `(org_id, event_seq)` uniqueness, working verifier.
6. Delete fabricated tool evidence and nonexistent SOP citations; add the rule-citation gate.
7. Wire `DataValidationService` into the pipeline.
8. Real `report_hash`.
9. Frontend: remove hardcoded charts/forecast/credentials; real empty states.

**P2 — Agentification.**

10. `raw_records`, `agent_runs`, `agent_tool_calls`, `rules`, `counterparty_aliases`,
    `sop_documents` + indexes.
11. The 5 read-only tools + bounded loop (≤6 / 60 s / 12 k) + `agent_tool_calls` telemetry.
12. LangGraph graph with the deterministic engine wrapped unchanged, `batch_steps` telemetry,
    and `SqliteSaver` checkpointing.
13. `interrupt()`-based human approval with durable resume.
14. Triage + Investigation agents with model routing and prompt caching.
15. Real Q&A agent (delete the templates).
16. Background execution + real progress endpoint.
17. Investigation drawer, approvals view, accuracy panel, real progress terminal.

**P3 — Rigour & Scale.**

18. Isotonic calibration + reliability curve UI; ECE measured on ≥2,000 records.
19. A real 2,000+ record dataset with a matching `ground_truth_links` manifest.
20. Refund / chargeback leg roles and exception states.
21. Postgres + RLS + immutability triggers (per `docs/03` §8.6).
22. `structlog` correlation ids + the domain metrics from `docs/01` §5.16.
23. Real SOP corpus in `sop_documents` with tag-based retrieval; citations re-enabled.
24. MCP server exposing the read-only tools to external hosts, if wanted.

---

## 17. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Regression in `matching_engine.py` while wrapping it | **High** | Wrap, never rewrite. `test_n1_settlement.py`, `test_accounting_semantics.py`, `test_pipeline.py` must stay green after every step; golden-output comparison on the shipped dataset before/after |
| Prompt injection via CSV `description` fields (attacker-influenceable text reaching the model) | **High** | Descriptions are passed as clearly delimited data, never as instructions; tool *arguments* are validated against ids already present in state, so injected text cannot widen the query; no LLM-authored SQL; no write tools exist |
| LLM fabricating arithmetic | **High** | The model is *given* every computed number and never asked to compute; `verify_proposal` re-checks arithmetic, id existence, confidence bounds, and now rule citations; failures route to a human with the failed check attached |
| Silent financial mutation | **High** | No write tool in the tool registry; `apply_resolution` is deterministic code gated on an `approvals` row; DB-level `REVOKE UPDATE, DELETE` on append-only tables when on Postgres |
| Deleting fabricated data makes the demo look emptier | **Medium** | Expected and correct. Real empty states plus one honest completed batch. This is exactly what `docs/00` line 7 demands |
| Calibration on 64 records is meaningless | **Medium** | ECE/reliability reported only above a minimum sample size, otherwise `not_measured`; needs the 2,000-record dataset |
| Migrating off global `STATE` breaks endpoints subtly | **Medium** | One endpoint at a time, each with a test that passes with a cold process (restart between write and read) |
| Existing audit rows have the old preimage | **Medium** | Versioned preimage tag; verifier accepts v1 for pre-migration rows and v2 after; a one-time re-seal migration recorded as an audit event |
| SQLite write contention between the checkpointer and the app | **Medium** | WAL mode + short transactions; Postgres is the P3 answer |
| Agent cost/latency runaway | **Medium** | Hard bounds (≤6 calls, 60 s, 12 k tokens), `should_invoke_ai` gate, SHA-256 response cache, cheap-model triage before the expensive model |
| Frontend rework damaging a good design | **Medium** | Keep vanilla JS, keep the existing CSS and layout; change data sources and add panels, not the visual language |
| Ground-truth manifest matches no dataset | **Medium** | Regenerate the manifest against the real dataset; until then report `not_measured` rather than a number |

---

## 18. Required API Keys & Integrations — one consolidated checklist

**Required**

1. **`ANTHROPIC_API_KEY`** — currently **absent** from `.env` (only `GEMINI_API_KEY` is
   present). `docs/01` §5.9 specifies Anthropic for the tool-use loop with cheap-model triage
   → stronger-model investigation and prompt caching on static policy text. Needed for the
   Investigation and Q&A agents.
2. **`SECRET_KEY`** — must be set in the environment. `core/config.py` currently ships
   `"dev_secret_key_change_in_production_finance_controller_jwt_9921"` as a code default, which
   means every deployment signs JWTs with a key that is in the repository.

**Already present / optional**

3. `GEMINI_API_KEY` — present. Keep as a secondary provider or make it primary (see Q4).

**Explicitly NOT requested** — none of these are needed and I am not asking for them:
no vector-DB or embeddings key (policy retrieval is deterministic tag lookup per
`docs/01` §5.10), no bank or payment-gateway API credentials (ingestion is file upload),
no LangSmith/OTel/Sentry keys (telemetry goes to `batch_steps` + `agent_tool_calls` +
`structlog`), no object-store credentials (local `UPLOAD_DIR`), no Postgres credentials
unless you choose to move off SQLite now, no Redis credentials (fail-open, optional).

**Configuration decisions, not secrets:** `DATABASE_URL`, `REDIS_ENABLED`,
`MATERIALITY_THRESHOLD_MINOR` (currently ₹500.00), the auto-approve confidence threshold θ,
`CORS_ORIGINS` (currently `["*"]`), and the reporting period source.

---

## 19. Open Questions

1. **Problem statement** — no image or document was attached. Confirm `docs/00`–`08` is the
   plan of record.
2. **Scale & accuracy** — is the 2,000+ record / measured-precision-recall-F1 requirement in
   scope? Shipped data is 64 rows and `data/ground_truth_links.json` matches no CSV. I need
   either a real dataset with a matching manifest, or approval to generate a labelled one
   (clearly marked `SYNTHETIC_BENCHMARK`, never shown as production truth).
3. **Reporting period** — six contradictory anchors exist. Should the period be derived from
   the uploaded data (recommended), or fixed in config?
4. **Primary LLM provider** — Anthropic (what the docs specify) or Gemini (the only key
   present)?
5. **SOP corpus** — is there real policy text? If not, all SOP citations get removed until it
   exists, rather than citing documents that don't.
6. **Database** — stay on SQLite, or move to Postgres now (needed for RLS, immutability
   triggers, and concurrent checkpointing)?
7. **"Apply resolution" semantics** — with no ERP connection, does applying a resolution mean
   writing a journal-entry proposal row only, or exporting a posting file?
8. **Deleting fabrications** — confirmed approach is to delete the hardcoded charts, forecast,
   and Q&A templates outright rather than keep them as fallbacks. The UI will show empty states
   until a real batch runs.
