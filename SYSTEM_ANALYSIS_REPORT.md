# AI Finance Controller — End-to-End System Analysis

**Analyst:** Claude Opus 5 · **Date:** 2026-08-29
**Method:** Static review + live execution. A dedicated server instance was run on port 8020 (`uvicorn --app-dir backend app.main:app`), the UI was driven and inspected in a real browser, and every claim below marked **[VERIFIED]** was reproduced by execution — not inferred from reading code.

**Scope note:** No product code was modified. One file was added: `.claude/launch.json` (dev-server config for the browser harness). Temp artifacts (`tx.json`, `ex.json`, `qa1.json`, `conc*.json`, `pend.json`, `pid.txt`, `oapi.json`, `batchrun.json`) are analysis scratch and can be deleted.

---

## 1. What Is Working Well

These are genuine strengths. Several are better than the surrounding code suggests, and **none of the fixes in this report require changing them.**

### 1.1 The matching engine is sound — it is being fed corrupted input
`ReconciliationEngine` (`backend/app/services/matching_engine.py`, 1063 lines) implements a real 6-pass cascade: P0 dedupe → P1 exact ID → P2 rules/MDR → P3 gateway↔ledger → P4 Hungarian assignment → P5 residual subset-sum. **[VERIFIED]** When I corrected only the upstream amount-scale defect (§2.1) and re-ran the *unmodified* engine on the real fixtures:

| Metric | Current | Engine fed correct data |
|---|---|---|
| Exact matches | 1 | **13** |
| Three-way matches | 0 | **1** |
| Match rate | 1.56% | **20.31%** |
| Exceptions | 63 | **51** |
| Gateway records matched | 0 / 12 (0%) | **8 / 12 (66.7%)** |

The engine is not the problem. This is the single most important finding in the report.

### 1.2 Money is handled correctly
All amounts are integer minor units (`amount_minor`, paise) with `Decimal` + `ROUND_HALF_UP` at the boundary. No floats anywhere in the monetary path. The MDR fee arithmetic in the fixtures is exact: **[VERIFIED]** gateway gross 49900p − fee 998p − tax 180p = 48722p, which equals the bank credit ₹487.22 to the paise. The domain model is right.

### 1.3 The cryptographic audit chain actually works
**[VERIFIED]** `GET /api/v1/audit/verify-chain?batch_id=<id>` returns `{"status":"VERIFIED","total_events_checked":4}` with a correct SHA-256 head hash. The hashing, sequencing, and GENESIS anchoring are all correct. Only the *unscoped* entry point is broken (§2.11) — a query-scoping bug, not a cryptographic one.

### 1.4 Security primitives are correctly built (they are just barely used)
- `backend/app/core/security.py` is solid: `get_current_user` fails **closed** on missing/malformed/expired tokens; `require_roles()` is a correct RBAC dependency.
- Argon2 password hashing (`argon2-cffi`), JWT HS256 via PyJWT.
- `settings.validate_production_environment()` correctly hard-fails production on default `SECRET_KEY`, `DEBUG=True`, wildcard CORS, or SQLite.
- **[VERIFIED]** The one maker-checker control that works: an analyst attempting to approve gets `HTTP 403 — "Maker-Checker Segregation Breach"`.

### 1.5 The deterministic tool layer is well-designed
`backend/app/services/agent_tools.py` — `TransactionLookupIndex` builds O(1) indices (by id, source, ref_key, amount bucket at ₹10 granularity) plus four clean tools. Genuinely good code. Its problem is that the "agent" almost never calls it (§2.14).

### 1.6 The QA assistant does real LLM reasoning
**[VERIFIED]** `POST /api/v1/qa/ask` performs live Groq inference and returns coherent, well-formatted, domain-aware answers with SOP citations and sensible next steps. This is the most genuinely "AI" part of the product. (Its numbers drift — §2.12 — but the reasoning path is real.)

### 1.7 The UI is legitimately well-crafted
Cohesive dark theme, disciplined 4-card KPI grid, dual Chart.js panels, 52-bar histogram, sensible IA (Dashboards / Governance & Risk / AI Intelligence Suite), light-mode toggle, breadcrumbs. **[VERIFIED]** The browser console is clean of JavaScript errors during normal operation. **Nothing in this report asks you to change the visual design.**

### 1.8 Other solid pieces
Redis fail-open (app runs fine with Redis absent); versioned `FeePolicyRegistry`; input provenance tracking with SHA-256 file hashes; segmented 13-week cash forecaster; `DeterministicVerifier` is a genuinely good architectural idea (§2.14 covers why it never fires).

---

## 2. Problems and Weaknesses

Severity key: **P0** = ship-blocking (wrong numbers, security, data loss) · **P1** = high (core feature broken or misleading) · **P2** = medium · **P3** = low/hygiene.

---

### 2.1 — P0 — Amount-scale corruption destroys the core product

**Symptom.** **[VERIFIED]** A live batch run returns `total_records=64, exact_matches=1, match_rate=0.0156, three_way_matches_count=0`. Across the **entire database history — 174 batches, 164 matches — every single match has exactly 2 legs. Zero three-way matches have ever been produced.** The product's headline capability has never once worked.

**Exact root cause.** `backend/app/services/normalizer.py`, `_to_paise()`:

```python
d = Decimal(val_cleaned)
return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))   # unconditional ×100
```

`normalize_row()` declares a parameter `amount_scale: int = 100` — and **never reads it**. **[VERIFIED]** by grep: `amount_scale` appears only in a schema column, an ingestion default, an API echo, and this unused signature. The hook was designed and never wired.

`data/gateway.csv` already stores **paise** (`amount=49900` = ₹499.00), while `bank.csv` and `general_ledger.csv` store **rupees** (`487.22`, `499.00`). Gateway therefore gets inflated 100×. **[VERIFIED]** live values for one logical transaction:

```
GATEWAY  pay_EXT_1001    4990000 minor  = ₹49,900.00   ← 100× too large
BANK     UTR-EXT-0001      48722 minor  = ₹487.22
LEDGER   JE-EXT-1001:1     49900 minor  = ₹499.00
```

Cross-source amount matching is arithmetically impossible. Every gateway record falls through all six passes to `MISSING_LEDGER_ENTRY` / `MISSING_BANK_RECORD`.

**Blast radius.** This corrupts every downstream money figure: the ₹30.15L "Gross Flow Volume" KPI, exception `impact_minor`, materiality tiering (inflated amounts cross the ₹500 threshold spuriously), the cash forecast, and the rupee figures the QA agent quotes back to users.

---

### 2.2 — P0 — Production credentials shipped in client-side JavaScript

**[VERIFIED]** `curl http://localhost:8020/static/js/app.js` — no authentication — returns:

```js
// frontend/static/js/app.js:70
async function loginUser(email = 'approver@acme.co', password = 'Approver@2026!') { … }
// :102  await loginUser('approver@acme.co', 'Approver@2026!');
// :130  await loginUser('analyst@acme.co',  'Analyst@2026!');
// :150  const reAuthed = await loginUser('approver@acme.co', 'Approver@2026!');
```

Three compounding failures:

1. **No login screen exists.** `DOMContentLoaded → ensureAuthenticated() → loginUser()` auto-authenticates every visitor as **Approver (Checker)**. **[VERIFIED]** in the server log: `POST /api/v1/auth/login → 200` fires with zero user interaction.
2. **Maker-checker is defeated by one click.** `app.js:226-227` binds `switchUserRole` to the avatar and session badge. **[VERIFIED]** Clicking the avatar silently re-authenticates as Analyst — and back. Two identities, both passwords in the page, one click apart. The dual-control governance that is the product's core compliance claim is cosmetic.
3. **Privilege escalation on token expiry.** `authFetch` (`app.js:148-158`) re-authenticates as **approver** on any 401, regardless of who was logged in. An analyst whose token lapses is silently upgraded to Checker.

---

### 2.3 — P0 — Agent failures are reported to the user as verified successes

**[VERIFIED]** end-to-end. I clicked **Run Agent 10** in the UI. Network: `POST /api/v1/agents/rca → 500 Internal Server Error`. Telemetry after: `total_agent_calls: 0`. The UI displayed:

- Status badge: **"Completed (Fallback Verified)"** — styled **green**
- A "LIVE MULTI-AGENT REASONING THOUGHT STREAM" with green ✓ on **"Groq LPU (120B) Deep Inference"** and **"DeterministicVerifier"**
- Body text simultaneously frozen at **"Running… Executing reasoning on Groq LPU"**

Three mutually contradictory states, and the truth — a hard 500 with zero LLM calls — is not among them.

**Exact root cause.** `frontend/static/js/app.js:1998-2004`:

```js
} catch (err) {
  if (badgeEl) {
    badgeEl.textContent = 'Completed (Fallback Verified)';
    badgeEl.className = 'badge-min badge-green';   // ← green on HTTP 500
  }
  fetchAgentTelemetry();
}
```

There is **no error branch anywhere in this handler**. Additionally `renderThoughtStreamSteps(3)` / `(4)` are called at `:1981-1983` — *before* `if (res.ok)` at `:1985`. The reasoning checkmarks are unconditional animation, decoupled from whether anything ran.

---

### 2.4 — P0 — Agents 10–13 are dead: guaranteed exception on every call

**[VERIFIED]** `POST /api/v1/agents/rca` → 500. Two stacked defects in `backend/app/api/v1/agents.py`:

```python
# :60 — crash. resolution_proposals has NO batch_id column.
db_props = db.query(schema.ResolutionProposal).filter_by(batch_id=target_b_id).all()
#   → sqlalchemy.exc.InvalidRequestError: Entity namespace for
#     "resolution_proposals" has no property "batch_id"

# :68 — latent AttributeError, revealed only after fixing :60.
"findings": e.findings or []     # ExceptionRecord has no `findings` attribute
```

**[VERIFIED]** against the live DB: `resolution_proposals` columns are `id, org_id, exception_id, investigation_id, action, recommended_parameters, justification, confidence, requires_human_review, status, verified_by_code, created_at`. `ExceptionRecord` has `state`, not `findings`.

Because `_get_batch_context_data()` is the shared helper, this kills **all five** batch endpoints: `/rca`, `/insights`, `/audit-explain`, `/generate-report`, `/run-all`, plus `/analysis/{batch_id}`. Agents 10–13 have never been reachable through the API. Fixing line 60 alone will surface the line 68 crash — fix both together.

---

### 2.5 — P0 — When the backend dies, the dashboard shows stale numbers as if live

**[VERIFIED]** by direct experiment: I replaced `window.fetch` with an immediate rejection (simulating total backend outage) and called `fetchProcessedData()`. Result — the dashboard was **byte-for-byte identical**: every KPI retained its value, `any_error_shown_to_user: false`, and the exception was swallowed.

**Exact root cause.** `app.js:711-713` and `:607-609` — the two primary data-load paths terminate in `console.error` / `console.debug` only. A `showToast()` helper exists at `:1615` and is simply not used here. **[VERIFIED]** 8 of 16 catch blocks surface nothing to the user.

Compounding it: `frontend/index.html` ships **hardcoded placeholder values** (`240` records at `:307`, `4,521` / `92%` lanes, `52 Windows` at `:361`, `+12.8%` at `:343`). On a cold load against a dead backend, a controller sees fabricated numbers with no indication they are not live. For a system whose output is signed off on, this is the most dangerous defect in the product.

---

### 2.6 — P0 — Financial data and batch execution are unauthenticated

**[VERIFIED]** from `/openapi.json`: **only 6 of 32 routes require authentication.** Wide open:

| Open route | Exposure |
|---|---|
| `POST /api/v1/batches/run` | Anyone triggers a full reconciliation — and freezes the server ~10 s (§2.7). Trivial unauthenticated DoS. |
| `GET /api/v1/transactions/` | All 8,445 transactions, all organisations |
| `GET /api/v1/exceptions/`, `/audit/events`, `/reports/summary` | Complete financial position |
| All 8 `/api/v1/agents/*` | Unauthenticated LLM invocation on your server-side API key — direct cost/abuse vector |
| `POST /api/v1/qa/ask` | Same |

`require_roles()` exists and is correct — it is simply almost never applied. Authenticated: only `approvals` (GET ×3, POST decide), `auth/me`, `sources/upload`, `sources/upload-batch`.

Two further auth defects in `backend/app/api/v1/auth.py`:
- `:37` — a `DEBUG`-gated backdoor accepting `password123` / `demo` / `admin` / `analyst` / `approver`. `DEBUG` **defaults to `True`**. **[VERIFIED]**: `demo` mints a valid JWT.
- `:61-82` — for a user absent from the DB, **any** password returns a valid token for `analyst@acme.co` / `approver@acme.co` / `admin@acme.co`.

---

### 2.7 — P0 — A single batch run freezes the entire server

**[VERIFIED]** `/health` responds in **4 ms** idle. During one batch run it took **8,331 ms** — a 1,770× degradation. The three subsequent probes returned to 3 ms once the batch finished.

**Exact root cause.** `backend/app/api/v1/batches.py:322` declares `async def run_windowed_batch(...)` and then calls the fully synchronous, CPU- and DB-bound `execute_batch_reconciliation()` at `:348` directly on the event loop. No `run_in_threadpool`, no worker queue. The whole process — every other user's request — blocks for the duration.

**[VERIFIED]** consequence: three concurrent runs completed at 9.6 s / 18.7 s / 29.1 s — perfectly serialized, confirming single-threaded starvation. A Kubernetes liveness probe on `/health` with a typical timeout would declare the pod dead and restart it **mid-batch**.

---

### 2.8 — P0 — The concurrency lock provably does nothing

**[VERIFIED]** I fired three simultaneous `POST /batches/run`. **All three returned HTTP 200** and created three distinct batches. The `409 "Concurrent run locked"` branch never fired.

**Exact root cause.** `backend/app/api/v1/batches.py:323-324`:

```python
batch_id = f"BATCH-{…}-{uuid.uuid4().hex[:6]}"   # fresh UUID every request
lock_key = key_batch_lock(batch_id)              # → lock key is always unique
```

The lock is keyed on a value generated *inside* the request, so contention is impossible by construction. The code is labelled "Fail-Closed Durable Concurrency Lock" and is unreachable dead weight. Combined with §2.15 (the submit button is never disabled), a double-click fires parallel full pipelines.

---

### 2.9 — P0 — Approvals are not idempotent; admin bypasses the checker role

**[VERIFIED]** by execution against `POST /api/v1/approvals/decide`:

1. Approver approves `PROP-ab31418b` → `200 SUCCESS`, audit hash `ee54a8f6…`
2. **Same approver approves the same already-APPROVED proposal again** → `200 SUCCESS`, audit hash `06b6b30d…`
3. DB after: **2 rows in `approvals`** for one proposal, two distinct audit events.
4. **Admin approves** a proposal → `200 SUCCESS`. Only `analyst` is blocked.

**Exact root cause.** `backend/app/api/v1/approvals.py:58-118` — nothing checks `db_prop.status != "PENDING_APPROVAL"` before writing. An approved voucher is never terminal; it can be re-approved without limit, each time minting a fresh audit event that records the same adjustment being signed again.

Three further defects in the same handler:
- `:64` — `actor_role = current_user.get("role", "approver")` **defaults to approver** if the claim is absent. Fail-**open** on the most security-critical attribute in the system.
- `:93-98` — lookup matches on `id` **or** `exception_id`; `:111` then writes `proposal_id=req.proposal_id`. Passing an exception id populates the `Approval.proposal_id` foreign key with an *exception* id. Silent referential corruption.
- `:70` — the error text says analysts cannot approve "**their own**" adjustments, but the check has nothing to do with ownership; it blocks all analysts from approving anything. There is no maker≠checker identity comparison anywhere.

---

### 2.10 — P0 — Live API keys committed to the repository

- `backend/app/core/config.py:37` — `GROQ_API_KEY: Optional[str] = "gsk_REDACTED_API_KEY_1"` as a **default value**, so it is used whenever the env var is unset.
- `backend/app/api/v1/qa.py:257` — a **second, different** hardcoded key: `settings.GROQ_API_KEY or "gsk_REDACTED_API_KEY_2"`.

Both must be treated as compromised and **rotated now** — not merely deleted, since they are in file history. Combined with §2.6 (unauthenticated `/agents/*` and `/qa/ask`), anyone reaching the service can bill LLM usage to these keys.

---

### 2.11 — P1 — The audit "Verify Chain" button always reports tampering

**[VERIFIED]** `GET /api/v1/audit/verify-chain` (no `batch_id`) returns:

> `"Audit chain verification failed at sequence 1. Potential tampering detected."`

**[VERIFIED]** `frontend/static/js/app.js:1398` calls it **unscoped** — so the UI's compliance control reports tampering **100% of the time**. Scoped, the same endpoint returns `VERIFIED`.

**Exact root cause.** The chain is minted **per batch**: each batch's first event uses `prev_hash = GENESIS`. `verify_audit_chain()` with no `batch_id` loads *all* events `ORDER BY event_seq ASC` and validates them as one continuous chain, breaking at the second batch's `event_seq = 1`. **[VERIFIED]** by SQL: 174 batches, 142+ events claiming GENESIS as `prev_hash`.

A control that cries wolf every time is worse than no control — staff learn to ignore it, and a real tamper event becomes invisible.

---

### 2.12 — P1 — Dashboard KPIs are pagination artifacts, and one batch has three different match rates

**[VERIFIED]** The API reports `total_records=64, exceptions_count=63`. The UI displays **500 records** and **100 Held**.

| UI shows | Truth | Why |
|---|---|---|
| Ingested Records **500** | 64 in batch (8,445 in DB) | `app.js:638` uses `items.length` — the `limit=500` **cap**. **[VERIFIED]** those 500 rows span **39 unrelated batches**. The response's own `total: 8445` field is ignored. |
| Exceptions **100 Held** | 63 | `app.js:685` `allExceptions.length \|\| op.exceptions_count` prefers the array — capped at the default limit of 100, spanning 2 batches. |
| **+156.3%** variance | ~98% | `app.js:699` divides the capped global count (100) by the batch-scoped total (64). `(100/64*100).toFixed(1)` = **exactly "156.3"**. A percentage over 100% because numerator and denominator come from different scopes. |
| **₹30.15L** Gross Flow | — | `app.js:646` sums `amount_minor` over an arbitrary 500-row page spanning 39 batches — and every gateway row is 100× inflated (§2.1). |
| **52 Windows**, **+12.8%** | 3 windows | Hardcoded in `index.html:361` / `:343`; never updated. |
| Lanes 14/38/6/0 (=58) | 63 | Frontend re-derives categories by substring-matching `description_raw` for `'CUTOFF'`/`'MDR'`/`'DUP'` and hardcoded dates `'2026-03-31'`/`'2026-08-31'` (`app.js:741-744`), ignoring the backend's authoritative `exception_type`. Percentages are normalised against the sum of these heuristics, not the real total — which is why they always sum to 100%. |

**Structural root cause.** **[VERIFIED]** from OpenAPI: `/exceptions/`, `/transactions/`, and `/approvals/pending` accept **no `batch_id` parameter at all**. The UI *cannot* request one batch's data, so it mixes batch-scoped metrics from `/reports/summary` with unbounded global lists.

**Three match rates for one batch.** **[VERIFIED]** for `BATCH-20260829122608-721408`:

| Surface | Value | Source |
|---|---|---|
| Dashboard KPI | **0.0%** | `/reports/summary` → `matched_records: 0` |
| Batch report | **1.56%** | `summary.match_rate` (1 match / 64) |
| QA agent | **3.12%** | `pairwise_match_rate` (2 legs / 64) |

None is a hallucination — all three are real fields. But `matched_records` is computed differently in each path, and a `× 2` legs assumption (`batches.py:183`, `:365`; `agents.py:98`) hardcodes two legs per match in a **three-way** system, systematically undercounting. Three surfaces, three numbers, same batch.

Also: `/approvals/pending` returns **8,528 unbounded items** **[VERIFIED]** with no pagination or scoping, all loaded into the browser.

---

### 2.13 — P1 — The LangGraph orchestration visualization is fabricated

The workflow screen presents *"LangGraph Multi-Agent Orchestration State Machine — Real-time execution across 7 deterministic nodes."* **[VERIFIED]: there is no streaming transport anywhere in the codebase** — zero occurrences of `EventSource`, `WebSocket`, `StreamingResponse`, or `text/event-stream` in either frontend or backend. Real-time node telemetry is impossible.

What actually runs (`frontend/static/js/app.js:1705-1762`):

```js
updateDagNode('1', 'completed', '240 Normalized');            // hardcoded count
const payload = { record_count: 240, window_size: 24, … };    // hardcoded 240
const res = await authFetch(`${API_BASE}/batches/run`, …);     // the ONE real call
if (res.ok) { … }                                             // no else branch
updateDagNode('2', 'completed', '10 Windows Match');           // hardcoded
await sleep(200); updateDagNode('3', 'completed', 'SOP Rules Applied');
updateDagNode('4', 'running',   'Groq Agent 9 Active...');     // no request is made
await sleep(250); updateDagNode('4', 'completed', 'Investigated');
await sleep(200); updateDagNode('4b','completed', '100% Math Verified');   // hardcoded
await sleep(250); updateDagNode('6', 'completed', 'SHA-256 Sealed');
```

Nodes 3, 4, 4b, 5 and 6 all render **after** the single API call has returned, on fixed `sleep()` timers, with hardcoded success labels. Node 4 announces *"Groq Agent 9 Active"* → *"Investigated"* while issuing **no request at all**. Node 4b asserts *"100% Math Verified"* unconditionally. **[VERIFIED]** the screen shows "240 Normalized" while processing 64 records.

The `catch` at `:1731` logs `[WARN]` and then lets the DAG paint every remaining node green — so a total pipeline failure still ends in "SHA-256 Sealed". `if (res.ok)` has no `else`, so an HTTP 500 also proceeds to full green.

Two related items: the request hardcodes `record_count: 240`, which the backend echoes as truth into Redis progress (`batches.py:340`, `:364`) — reporting 240 records for a 64-record run. And the CTA advertises "240+ Records" when the fixtures contain **[VERIFIED]** 64 rows (12 gateway + 10 bank + 42 ledger).

---

### 2.14 — P1 — The AI layer has never actually run

**[VERIFIED]** across all 174 batches ever executed:

- **`ai_investigations` table: 0 rows.** Not one investigation has ever been persisted.
- **All 63 exceptions remain in state `DETECTED`.** The lifecycle never advances to INVESTIGATING / PROPOSED / RESOLVED.
- **All 63 proposals carry the identical action `INVESTIGATE_MISSING_WIRE`** — including the one `DUPLICATE_RECORD` exception, for which "investigate missing wire" is semantically wrong. Four distinct exception types, one canned response.
- **`verified_by_code = 0` on all 63.** The `DeterministicVerifier` — the product's flagship safety gate — has never verified a single proposal.
- `/agents/telemetry`: `total_agent_calls: 0, avg_latency_ms: 0.0, last_active_at: null`.

Contributing causes:

1. **Failures are silent.** `backend/app/services/agent_runtime.py:471`, `:507`, `:544` — each of the three providers (Groq → Gemini → Anthropic) is wrapped in `except Exception: pass`. Every provider can fail for every exception and the system reports nothing, silently degrading to canned text.
2. **Model config is ignored.** `agent_runtime.py:517` hardcodes `claude-3-5-sonnet-20241022`; `:480` hardcodes `gemini-2.5-flash`. `base_agent.py:196` reads `getattr(settings, "GEMINI_MODEL", "gemini-2.0-flash")` — **`GEMINI_MODEL` does not exist** in `Settings` (the real name is `AGENT_GEMINI_MODEL`), so the configured model is silently ignored and `gemini-2.0-flash` is always used. `qa.py:265` lists `"qwen/qwen3.8-27b"`, which does not appear to be a valid Groq model id.
3. **The retry edge is a no-op.** `graph_orchestrator.py` `route_after_verification()` re-routes rejected proposals while `retry_counts < 2`, but the L1 cache returns the *identical* cached result on retry, so a rejected proposal can never pass. `retry_counts[exc_id] += 1` also increments for **all** items, not just rejected ones.
4. **Declared autonomy limits are dead code.** **[VERIFIED]** by grep: 14 settings — `AGENT_MAX_TOOL_CALLS`, `AGENT_TIMEOUT_SECONDS`, `AGENT_MAX_CONTEXT_TOKENS`, `AGENT_TRIAGE_MODEL`, `AGENT_INVESTIGATION_MODEL`, `AGENT_GEMINI_MODEL`, `AGENT_PRIMARY_PROVIDER`, `AGENT_MAX_RETRIES`, `AUTO_APPLY_CONFIDENCE_THRESHOLD`, `AUTO_APPLY_ENABLED`, `AUTO_APPLY_ALLOWED_TYPES`, `MIN_SAMPLES_FOR_CALIBRATION`, `GROUND_TRUTH_PATH`, `ASYNC_DATABASE_URL` — have **zero usages outside `config.py`**. The documented autonomy contract is not enforced by any code path.
5. **Declared tools are never called.** `graph_orchestrator.py:30-33` imports `tool_lookup_candidates`, `tool_calculate_fee_split`, `tool_check_period_cutoff`; only `tool_evaluate_sop_rules` is ever invoked.

**Unearned metrics.** `finalize_batch_node` hardcodes `"avg_investigation_depth": 7.0`; `false_match_risk` is merely `mean(1 − confidence)`, not a measured false-match rate; matches are counted as `len([...]) // 2`. The QA fallback template asserts "zero false-positive collisions" and "Risk Level: Low (<0.8% False Match Risk)" — neither is measured anywhere. The telemetry panel shows **"380 ms"** average latency because `app.js:1834` reads `stats.avg_latency_ms || 380` — a falsy-coalesce that converts a genuine `0.0` into a fabricated number, while the sidebar badge reads "5 Live" with zero agents having run.

---

### 2.15 — P1 — No loading states anywhere; double-submit is possible

**[VERIFIED]** Zero occurrences of `skeleton`, `spinner`, `is-loading`, or `aria-busy` in **both** `app.js` and `styles.css`.

**[VERIFIED]** I clicked "Start Processing & Matching" and sampled the UI at 87 ms / 401 ms / 1,603 ms / 4,607 ms. Across all four samples: `btn_disabled: false`, button text unchanged, no toast, no progress indicator. During a ~10 s server-blocking operation (§2.7) the user gets **no feedback at all** and can re-click freely — firing parallel pipelines that the lock does not stop (§2.8).

---

### 2.16 — P1 — Unusable below ~960px

**[VERIFIED]** At a 375px viewport the 240px sidebar does not collapse, leaving ~135px for content, with **799px of horizontal overflow** measured. No hamburger control exists (`has_hamburger: false`).

**Exact root cause.** The viewport meta is correct (`width=device-width, initial-scale=1.0`). But **[VERIFIED]** all four media queries (`max-width: 1100px / 1000px / 960px / 600px`) only ever change `grid-template-columns`. **No rule anywhere collapses, hides, or overlays the sidebar.**

---

### 2.17 — P1 — Production startup crashes; two divergent databases

- **`backend/app/db/database_service.py:47`** calls `logger.info(...)` while **`logger` is never imported or defined** in the module → guaranteed `NameError` on the seeding path.
- **[VERIFIED] Two live, divergent databases.** `DATABASE_URL = "sqlite:///./finance_controller.db"` is **relative to the working directory**, so which database you get depends on where you launch from:

  | Path | Size | Batches |
  |---|---|---|
  | `./finance_controller.db` | 10.7 MB | 174 |
  | `./backend/finance_controller.db` | 737 KB | 10 |

  `HOW_TO_START_AND_RUN.md` instructs `cd backend`, while helper scripts run from the repo root — so documentation and tooling write to *different databases*. Silent, ongoing data divergence.

---

### 2.18 — P2 — Documented credentials are all wrong

`HOW_TO_START_AND_RUN.md` documents `admin@acme.co/admin123`, `approver@acme.co/approver123`, `analyst@acme.co/analyst123`. **[VERIFIED]** `admin123` returns `{"detail":"Invalid email or password"}`. The real seeded passwords (`database_service.py seed_default_data()`) are `Analyst@2026!`, `Approver@2026!`, `Admin@2026!`. **All three documented credentials fail.** A new user's first action fails — and only succeeds because the app auto-logs-in behind their back (§2.2).

### 2.19 — P2 — Global mutable state prevents multi-user and multi-tenant use
`backend/app/api/v1/batches.py:34` defines a module-level `STATE` dict holding `active_batch`, `transactions`, `matches`, `exceptions`, `decisions`, `proposals`, `audit_events`, `windows`, `quality_metrics`, `cash_forecast`, `provenance`. It is process-global, single-tenant, non-durable, and lost on restart. Concurrent users overwrite each other's "active batch". Similarly class-level mutable state in `AIAgentRuntime._L1_CACHE` / `.stats`, `AgentTelemetryTracker._logs`, and `FinancialAgentSuite._cached_batch_analyses` (unbounded — a slow memory leak).

### 2.20 — P2 — Hardcoded reporting periods override derived values
`batches.py:179-180` hardcodes `"period_start": "2026-08-01", "period_end": "2026-08-31"`; `database_service.py:164-165` hardcodes `date(2026,3,1)`/`date(2026,3,31)` — two different periods in one system. `config.py` documents that the period is *derived* from data via `services/period.py` with `PERIOD_START_OVERRIDE` as an explicit opt-in; the hardcoded literals bypass both.

### 2.21 — P2 — CORS wildcard with credentials
`main.py:35-41` sets `allow_origins=settings.CORS_ORIGINS` (default `["*"]`) together with `allow_credentials=True`. Browsers reject that combination, so it fails confusingly rather than safely. `validate_production_environment()` blocks it in prod — but `APP_ENV` defaults to `development`.

### 2.22 — P2 — Canned narrative presented as analysis of the user's data
`app.js:164-210` `CATEGORY_WHY_DEFINITIONS` (commented "Single Source of Truth") is static prose containing invented specifics — `variance: '₹27.81 on ₹1,180.00'`, `'₹0.00 (Zero Discrepancy Verified)'`, `'e.g. 23:45 IST'`. It is rendered in the "Why It Happened" panel as an explanation of the user's actual records. Similarly `qa.py execute_dynamic_data_reasoner()` is keyword-matched templates asserting "✓ 100% Balanced" and "zero false-positive collisions".

### 2.23 — P2 — Other confirmed issues

| # | Issue | Location |
|---|---|---|
| a | `/reports/summary` fetched **twice** on every page load **[VERIFIED]** in network trace | `app.js` init path |
| b | `get_batch_stats()` counts **all** audit events globally, not per batch | `database_service.py:387` |
| c | Chart.js + Google Fonts loaded from public CDNs, no SRI — breaks air-gapped deploys; third-party dependency in a financial app | `index.html` |
| d | `run_all_batch_agents()` is strictly sequential, but the UI toast says *"Initiating **parallel** execution across all 5 reasoning agents"* | `agent_suite.py:49-80`, `app.js:2011` |
| e | `tier_breakdown` key mismatch: engine emits `tier_4_honest_exceptions`, orchestrator fallback writes `tier_4_unresolved` | `matching_engine.py` vs `graph_orchestrator.py` |
| f | `O(n²)` — `TransactionContextBuilder.build_context(txn, all_txns)` called per transaction; one maker-checker proposal emitted per transaction *leg*, creating duplicates | `graph_orchestrator.py decision_routing_node` |
| g | Arbitrary severity rule: `sev = "HIGH" if (idx < 3 or …)` — the first three items are High by position | `graph_orchestrator.py` |
| h | `_anthropic_client` built in `__init__` is dead — a fresh client is constructed per call | `agent_runtime.py` |
| i | Normalizer `or`-chains (`raw_row.get("amount") or raw_row.get("Amount")`) discard legitimate `0` values | `normalizer.py` |
| j | Fallback injects fake transactions (`amount_minor: 118000` / `115215`) when the list is empty, so Agent 9 "investigates" invented data | `app.js:1957-1958` |
| k | `"hi"` substring-matches "t**hi**s"/"w**hi**ch"/"**hi**gh" in the greeting branch. **[VERIFIED] latent only** — the live LLM path handled "…**high** severity…" correctly; this misfires only when the LLM is unavailable and the fallback runs | `qa.py:545` |
| l | LLM output is constrained by prompt text alone — no tool-forcing or structured-output mode | `agent_runtime.py`, `base_agent.py` |
| m | **[VERIFIED]** QA numeric drift: claimed "14 high-severity" then "12" in one answer; DB has **21** HIGH. Another answer called all 63 "high-severity" (actual: 21 HIGH / 41 MEDIUM / 1 LOW) | `qa.py` |
| n | Avatar initial derives from `full_name` → shows "C" for `approver@acme.co` | `app.js:120` |
| o | 12 stray `.db` files in the repo root (`.audit-*.db`, `.recheck-*.db`, `.ui-*.db`) | repo root |

---

## 3. Is This System Truly Agentic?

**No. It is a deterministic pipeline with a decorative AI layer.** Concretely:

**What "agentic" would require** — an LLM that chooses actions, calls tools, observes results, and iterates toward a goal, with autonomy bounded by policy.

**What actually exists:**

| Property | Reality |
|---|---|
| Tool-calling loop | **None.** `investigate_exception_agent_node` is a `for` loop of single-shot completions. `AGENT_MAX_TOOL_CALLS = 6` is dead code. |
| Tool access | 3 of 4 tools imported and never called. Only `tool_evaluate_sop_rules` runs. |
| Observe → re-plan | **None.** No result is ever fed back into a second LLM turn. |
| Retry / self-correction | Edge exists but is provably inert — the L1 cache returns the identical rejected result. |
| Autonomous action | Zero. All 63 proposals are `requires_human_review=1`; `AUTO_APPLY_*` is unreferenced. |
| Differentiated reasoning | **[VERIFIED]** 63/63 exceptions → the identical canned action, across 4 distinct types. |
| Evidence of any AI run | **[VERIFIED]** `ai_investigations` = **0 rows** in 174 batches; telemetry `total_agent_calls: 0`. |
| Orchestration visibility | **[VERIFIED]** The "real-time LangGraph state machine" is client-side `sleep()` animation; no streaming transport exists. |

**The honest characterisation:** a well-structured **deterministic workflow** (LangGraph `StateGraph`, 7 nodes, conditional edges) wrapping a solid rule-based matching engine, with **one optional single-shot LLM call per ambiguous exception** that in practice has never persisted a result. The QA assistant (§1.6) is the only component doing real, useful LLM work.

**This is not inherently bad.** For financial reconciliation, deterministic matching is *correct* — it is auditable, reproducible, and cheap, which is exactly what a controller needs. The problem is not the architecture; it is that **the UI and documentation claim agentic behaviour that does not occur.** The fix is to make the claims match reality — and then, if you want genuine agency, add it deliberately at the one place it adds value (§6.3).

---

## 4. Severity Summary

| ID | Issue | Sev | Effort |
|---|---|---|---|
| 2.1 | Amount-scale ×100 corruption → 0 three-way matches ever | **P0** | S |
| 2.2 | Production passwords in client JS; auto-login; 1-click role switch | **P0** | M |
| 2.3 | HTTP 500 rendered as "Completed (Fallback Verified)" in green | **P0** | S |
| 2.4 | `agents.py:60` + `:68` — Agents 10–13 always 500 | **P0** | S |
| 2.5 | Backend outage shows stale/placeholder numbers as live | **P0** | M |
| 2.6 | 26 of 32 routes unauthenticated, incl. `POST /batches/run` | **P0** | M |
| 2.7 | Sync pipeline on event loop — 4 ms → 8,331 ms | **P0** | S |
| 2.8 | Concurrency lock keyed on per-request UUID — inert | **P0** | S |
| 2.9 | Approvals non-idempotent; admin bypass; role fail-open | **P0** | S |
| 2.10 | Two live Groq keys committed | **P0** | S |
| 2.11 | Unscoped audit verify always reports tampering | **P1** | S |
| 2.12 | KPIs are pagination caps; 3 different match rates | **P1** | M |
| 2.13 | Fabricated LangGraph DAG animation | **P1** | M |
| 2.14 | AI layer never ran; silent failures; dead config | **P1** | L |
| 2.15 | No loading states; double-submit possible | **P1** | S |
| 2.16 | Unusable below ~960px | **P1** | M |
| 2.17 | `logger` NameError; two divergent databases | **P1** | S |
| 2.18 | All documented credentials wrong | **P2** | S |
| 2.19 | Module-global `STATE`; unbounded caches | **P2** | L |
| 2.20 | Hardcoded reporting periods | **P2** | S |
| 2.21 | CORS `*` with credentials | **P2** | S |
| 2.22 | Canned narrative shown as user-data analysis | **P2** | M |
| 2.23 | 15 further confirmed issues (a–o) | P2/P3 | varies |

---

## 5. Specific Fixes

### Fix 2.1 — Amount scale *(highest value in the report)*

1. In `normalizer.py`, honour the parameter that already exists:
   ```python
   def _to_paise(val, amount_scale: int = 100):
       d = Decimal(val_cleaned)
       return int((d * amount_scale).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
   ```
   Thread `amount_scale` from `normalize_row()` into every `_to_paise` call (amount, fee, tax, net).
2. Persist scale **per source** — `source_profiles.amount_scale` already exists in the schema and is already surfaced by `sources.py:26`. Set `GATEWAY → 1` (already minor units) and `BANK`/`LEDGER → 100`. Pass it through `IngestionService.ingest_and_normalize`, whose `amount_scale: int = 100` default (`ingestion.py:28`) is likewise unused.
3. Replace the `or`-chains with an explicit key-presence lookup so `0` survives (§2.23i).
4. **Add a regression guard** — assert `gateway.amount − fee − tax == bank.credit` on the fixtures. This one invariant would have caught the bug immediately.
5. Add a startup sanity check: if median amounts across sources differ by ~100×, refuse the batch with a clear scale-mismatch error rather than silently producing a 1.5% match rate.

**Expected result** (**[VERIFIED]** by A/B run): match rate 1.56% → **20.31%**, exact matches 1 → **13**, first three-way match ever, exceptions 63 → 51. Investigate the residual 51 separately — the ledger holds multi-line journal entries (42 rows for ~12 transactions) that require summing legs before three-way comparison.

### Fix 2.2 — Authentication
1. Delete every hardcoded password from `app.js` (lines 70, 102, 130, 132, 150).
2. Add a real login form. On 401, clear the token and **show the login screen** — never silently re-authenticate.
3. Delete `switchUserRole()` and its two listeners (`:226-227`). Role comes from the JWT only. To keep the demo convenience, gate it behind an explicit, clearly-labelled dev-only build flag.
4. Move tokens from `localStorage` to `httpOnly` `Secure` `SameSite=Strict` cookies (localStorage is XSS-readable).
5. Delete the `auth.py:37` DEBUG backdoor and the `:61-82` phantom-user branch outright. Do not gate them on `DEBUG` — it defaults to `True`.
6. Default `DEBUG` to `False`.

### Fix 2.3 — Honest agent status
```js
} catch (err) {
  badgeEl.textContent = 'Failed';
  badgeEl.className = 'badge-min badge-red';
  container.innerHTML = renderAgentError(err);       // show the real reason
  showToast(`Agent ${agentId} failed: ${err.message}`, 'error');
}
```
Move `renderThoughtStreamSteps(3)`/`(4)` **inside** the `if (res.ok)` block. Better: drive step state from the response, or delete the stream — a spinner that tells the truth beats five checkmarks that do not. Apply the same pattern to `runAllAgents()`.

### Fix 2.4 — Agents 10–13
```python
# agents.py:60 — join through the exception to reach batch_id
db_props = (
    db.query(schema.ResolutionProposal)
      .join(schema.ExceptionRecord,
            schema.ResolutionProposal.exception_id == schema.ExceptionRecord.id)
      .filter(schema.ExceptionRecord.batch_id == target_b_id)
      .all()
)
```
And at `:68` replace `e.findings or []` with a real column (`e.state`) or drop the key. **Fix both together** — repairing only line 60 exposes line 68. Add a smoke test that calls all six agent endpoints and asserts 200.

### Fix 2.5 — Fail loudly
1. In `fetchProcessedData()`'s catch: `showToast('Could not load live data — showing last known values', 'error')` and set a persistent "⚠ Data may be stale — last updated HH:MM" banner in the header.
2. Replace every hardcoded number in `index.html` (`240`, `4,521`, `92%`, `52 Windows`, `+12.8%`, `+156.3%`) with `—` so an unloaded state is visibly empty rather than plausibly wrong.
3. Track `lastSuccessfulFetch` in `appState` and show its timestamp beside the KPI row.

### Fix 2.6 — Lock down the API
1. Add `Depends(get_current_user)` to every route except `/health`, `/auth/login`, and static assets.
2. Add `Depends(require_roles("analyst","approver","admin"))` to `POST /batches/run` and all `/agents/*`.
3. Scope every query by `current_user["org_id"]` — the multi-tenant column exists on every table and is not being enforced.
4. Rate-limit `/qa/ask` and `/agents/*` per user (they cost money per call).

### Fix 2.7 — Get the pipeline off the event loop
Minimal, immediate:
```python
from fastapi.concurrency import run_in_threadpool
result = await run_in_threadpool(execute_batch_reconciliation, …)
```
Proper: return `202 Accepted` with a `batch_id`, run the job in a worker (Celery/RQ/`BackgroundTasks`), and let the client poll the existing `GET /batches/{batch_id}/progress`. That endpoint already exists and is already being written to — the async contract is half-built.

### Fix 2.8 — Make the lock real
Key the lock on the **tenant + logical resource**, not the new batch id:
```python
lock_key = key_batch_lock(f"{org_id}:active_reconciliation")
```
Then a second concurrent run correctly receives the 409 the code already raises. Add a test that fires two simultaneous runs and asserts exactly one 409.

### Fix 2.9 — Approval integrity
1. Guard the terminal state before writing:
   ```python
   if db_prop.status != "PENDING_APPROVAL":
       raise HTTPException(409, f"Proposal already {db_prop.status}; decisions are final.")
   ```
2. Add a DB `UNIQUE` constraint on `approvals(proposal_id)`.
3. `:64` — fail **closed**: `actor_role = current_user["role"]` (KeyError/403 if absent), never `.get(…, "approver")`.
4. Restrict approval to the `approver` role explicitly via `require_roles("approver")`; do not let `admin` sign financial adjustments.
5. Resolve `proposal_id` strictly by `ResolutionProposal.id`; if callers need exception-id lookup, expose a separate parameter so the FK can never receive an exception id.
6. Enforce real segregation: store the proposal's maker identity and reject when `approver_id == maker_id`.

### Fix 2.10 — Rotate keys
1. **Revoke both Groq keys now** (`config.py:37`, `qa.py:257`) — assume compromise.
2. Change both to `Optional[str] = None` and load only from the environment; fail fast with a clear message when a needed key is absent.
3. Purge from git history (`git filter-repo`), add `.env` to `.gitignore` (verify), and add a pre-commit secret scanner (`gitleaks`/`detect-secrets`).

### Fix 2.11 — Audit verification
Make `verify_audit_chain()` chain-aware: when `batch_id` is absent, **group events by batch** and verify each chain independently, returning a per-batch roll-up. Update `app.js:1398` to pass the active `batch_id`. Reserve the words "tampering detected" for an actual hash mismatch — never for a scoping artifact.

### Fix 2.12 — One number, one meaning
1. Add `batch_id` as a filter to `/exceptions/`, `/transactions/`, and `/approvals/pending`; default to the active batch. Paginate `/approvals/pending`.
2. Make `/reports/summary` the **single** source for all dashboard KPIs. Delete the client-side fallbacks at `app.js:638`, `:646`, `:685` — never derive a KPI from `items.length`; use the `total` field the API already returns.
3. Publish three explicitly-named metrics and label them in the UI: `three_way_match_rate`, `pairwise_match_rate`, `overall_reconciliation_rate`. The current ambiguity is why one batch reads 0.0% / 1.56% / 3.12%.
4. Remove the `× 2` legs assumption (`batches.py:183`, `:365`; `agents.py:98`); count actual `match_legs` rows.
5. Delete the frontend category heuristics (`app.js:741-744`) and render the backend's `exception_type` aggregation instead — the backend already classifies correctly.
6. Bind `52 Windows` / `+12.8%` (`index.html:361`, `:343`) to real data or remove them.

### Fix 2.13 — Truthful orchestration view
Cheapest honest fix: replace the fake DAG with a single indeterminate progress indicator plus the real per-node results from the `/batches/run` response after it returns. Remove `record_count: 240` from the request; send the actual file/row count. Correct the "240+ Records" label to reflect the fixtures (64). If you want the live DAG, implement it properly — SSE from `/batches/{id}/progress` driven by `batch_steps` rows the backend already persists.

### Fix 2.14 — Make the AI real (or drop the claim)
1. **Stop swallowing errors.** Replace the three `except Exception: pass` blocks (`agent_runtime.py:471`, `:507`, `:544`) with `logger.exception(...)`, record the failure in telemetry, and surface a per-exception `investigation_status`. You cannot fix what you cannot see — this is the prerequisite for everything else here.
2. **Persist every attempt** to `ai_investigations`, success or failure. A permanently empty table should be an alarm.
3. **Fix model configuration.** `base_agent.py:196` → `settings.AGENT_GEMINI_MODEL`. Replace hardcoded ids at `agent_runtime.py:480`, `:517` with settings. Validate `qa.py:265`'s `"qwen/qwen3.8-27b"` against Groq's live model list.
4. **Enforce structured output** — use Groq/Anthropic tool-calling or JSON mode instead of asking for JSON in the prompt.
5. **Make the retry meaningful** — exclude rejected results from the L1 cache, and only increment `retry_counts` for genuinely rejected items.
6. **Wire up or delete the 14 dead settings.** Either enforce `AGENT_MAX_TOOL_CALLS`, `AGENT_TIMEOUT_SECONDS`, and the `AUTO_APPLY_*` policy in code, or remove them — a documented safety contract that no code reads is worse than no contract.
7. **Delete unearned metrics**: hardcoded `avg_investigation_depth: 7.0`, `false_match_risk` as `mean(1−confidence)`, "zero false-positive collisions", "<0.8% False Match Risk", and `avg_latency_ms || 380`. Report "not measured" — `MIN_SAMPLES_FOR_CALIBRATION` exists for exactly this purpose.

### Fix 2.15 — Loading feedback
Add a `.is-loading` state to the existing button styles (no visual redesign needed): disable the button, swap the label to "Processing…", and render skeleton shimmer on KPI cards while `fetchProcessedData()` is in flight. Guard the handler with an `isRunning` flag so a double-click cannot double-submit.

### Fix 2.16 — Responsive
Add to the existing `@media (max-width: 960px)` block: transform the sidebar into an off-canvas drawer (`transform: translateX(-100%)` + `.is-open`), add a hamburger button in the existing header, and set `overflow-x: auto` on table wrappers. This is additive — desktop rendering is untouched.

### Fix 2.17 — Startup and database
1. Add `import logging; logger = logging.getLogger(__name__)` to `database_service.py`.
2. Make `DATABASE_URL` absolute, anchored to the repo root:
   ```python
   _ROOT = Path(__file__).resolve().parents[3]
   DATABASE_URL: str = f"sqlite:///{_ROOT / 'finance_controller.db'}"
   ```
3. Decide which of the two databases is canonical, archive the other, and correct `HOW_TO_START_AND_RUN.md` so docs and scripts agree on the launch directory.
4. Add a smoke test that boots the app with `APP_ENV=production` and asserts a clean startup.

### Fix 2.18–2.23 — Remaining
- **2.18** Correct the three credentials in `HOW_TO_START_AND_RUN.md` (+ `.docx`) to `Analyst@2026!` / `Approver@2026!` / `Admin@2026!`, or reseed to match the docs. Verify by actually logging in.
- **2.19** Replace `STATE` with per-request DB reads keyed by `batch_id` (the DB is already the source of truth — `STATE` is a redundant cache). Bound `_cached_batch_analyses` and `_L1_CACHE` with an LRU + TTL.
- **2.20** Delete the hardcoded dates in `batches.py:179-180` and `database_service.py:164-165`; call the existing `services/period.py` derivation and honour `PERIOD_*_OVERRIDE`.
- **2.21** Default `CORS_ORIGINS` to `["http://localhost:8000"]`; never pair `*` with credentials.
- **2.22** Drive the "Why It Happened" panel from the backend's per-exception rule evaluation. Keep `CATEGORY_WHY_DEFINITIONS` only as static SOP reference text, visually separated and labelled as policy — not as findings about the user's records. Strip invented figures like "₹27.81 on ₹1,180.00".
- **2.23** (a) de-duplicate the double `/reports/summary` fetch; (b) scope `get_batch_stats` by batch; (c) vendor Chart.js and fonts locally (also fixes air-gapped deploys) or add SRI; (d) either parallelise `run_all_batch_agents` with `asyncio.gather` or fix the toast copy; (e) unify the `tier_4_*` key; (f) build the `TransactionLookupIndex` once per batch and dedupe proposals by exception rather than by leg; (g) replace positional severity with a materiality rule; (h) delete the dead `_anthropic_client`; (j) remove the fake-transaction fallback and disable Agent 9 when no data is loaded; (k) reorder the greeting check to require an exact/word-boundary match; (m) feed the QA agent a pre-computed aggregate block (counts by severity and type) so it quotes rather than infers; (n) derive the avatar initial from email when `full_name` is a role label; (o) delete the 12 stray `.db` files and add `*.db` to `.gitignore`.

---

## 6. Recommended Architecture & Integration Improvements

### 6.1 Establish one source of truth per number
The recurring theme behind §2.12, §2.14 and §2.5 is **the same quantity computed in three places with three different formulas**. Introduce a single `BatchMetrics` service that computes every published metric once, persists it with the batch, and is the *only* thing the API serves. Frontend, QA agent, and report generator all read that one object. Delete every client-side metric derivation. Any number a controller might act on should be traceable to exactly one line of code.

### 6.2 Make the async contract real
`GET /batches/{batch_id}/progress` and the `batch_steps` table already exist — the design was right, the wiring was never finished. Complete it: `POST /batches/run` returns `202 + batch_id`; a worker executes the pipeline and writes a `batch_steps` row per node; the client polls (or subscribes via SSE). This simultaneously fixes event-loop starvation (§2.7), gives the DAG view real data (§2.13), enables genuine progress feedback (§2.15), and makes the concurrency lock meaningful (§2.8).

### 6.3 Add agency at the one place it pays
Keep deterministic matching as the default — it is correct for this domain. Introduce a real bounded agent loop **only** for the residual exceptions the engine cannot resolve (currently the ~51 remaining after Fix 2.1):

```
loop (max AGENT_MAX_TOOL_CALLS, max AGENT_TIMEOUT_SECONDS):
    LLM chooses a tool  ← the 4 tools in agent_tools.py already exist
    execute, append observation
    until proposal or budget exhausted
→ DeterministicVerifier re-executes the arithmetic (hard gate)
→ if verified AND confidence ≥ AUTO_APPLY_CONFIDENCE_THRESHOLD
     AND type ∈ AUTO_APPLY_ALLOWED_TYPES AND impact < materiality:
       auto-apply
  else: maker-checker queue
```
Every component named here already exists — the tools, the verifier, and all the thresholds. They just need connecting. That single change makes the "agentic" claim true and makes the dead config load-bearing.

### 6.4 Enforce tenancy at the data layer
`org_id` is on every table and enforced nowhere. Add a session-scoped filter (or Postgres row-level security) so a query cannot return another tenant's rows even if a handler forgets. Then retire `STATE` (§2.19).

### 6.5 Regression tests around the invariants that failed silently
The scale bug survived 174 batches because nothing asserted the obvious. Add:
- **Reconciliation invariant:** `gateway.amount − fee − tax == bank.credit` on the golden fixtures.
- **Golden-batch test:** the fixtures must produce ≥ N matches and ≥ 1 three-way match; fail CI if the match rate regresses.
- **Contract test:** every endpoint in `openapi.json` returns 401 without a token (allow-list `/health`, `/auth/login`).
- **Audit test:** verify passes scoped *and* unscoped across ≥ 2 batches.
- **Idempotency test:** approving twice returns 409 and writes exactly one row.
- **Smoke test:** all six agent endpoints return 200 (would have caught §2.4 on day one).
- **Startup test:** boots clean under `APP_ENV=production`.

### 6.6 Reserve green for verified success
A cross-cutting principle, violated in at least four places (§2.3, §2.5, §2.11, §2.13). In a financial control system, the UI must never assert more confidence than the system has earned. Adopt three explicit states everywhere — **Verified** (deterministically re-checked), **Unverified** (produced, not checked), **Failed** (with the reason) — and let unknown look unknown.

---

## 7. Prioritized Implementation Plan

Sequenced so each stage leaves the system in a better, shippable state. Effort assumes one engineer familiar with the codebase.

### Stage 0 — Contain (today, ~2 hours)
Do this before anything else; it is credential exposure.
1. **Revoke both Groq API keys** (§2.10). Move to env-only.
2. Purge secrets from git history; add `gitleaks` pre-commit.
3. Remove the hardcoded passwords from `app.js` (§2.2 step 1) and delete the `auth.py` backdoors (§2.6).
4. Set `DEBUG=False` and a non-default `SECRET_KEY` by default.

### Stage 1 — Make the product work and stop lying (Week 1)
The highest value-per-hour work in this report.
1. **Fix the amount scale** (§2.1) → **[VERIFIED]** 1.56% → 20.31% match rate, first three-way match ever. Add the invariant test.
2. **Fix `agents.py:60` + `:68`** (§2.4) → Agents 10–13 reachable. Add the six-endpoint smoke test.
3. **Fix `logger` NameError** and make `DATABASE_URL` absolute (§2.17) → production can start; database divergence ends.
4. **Replace all fake-success UI states with honest ones** (§2.3, §2.5) → failures become visible; add the stale-data banner and blank the hardcoded placeholders.
5. **Scope audit verification** (§2.11) → the compliance control stops crying wolf.
6. **Correct the documented credentials** (§2.18) → first-run works.

*Exit criteria:* a real batch produces a defensible match rate; every agent endpoint returns 200; no screen reports success on failure.

### Stage 2 — Security and stability (Week 2)
1. **Authenticate all endpoints + enforce `org_id` scoping** (§2.6, §6.4).
2. **Real login screen; delete `switchUserRole`; no silent re-auth** (§2.2) → dual control becomes real.
3. **Approval integrity**: terminal-state guard, `UNIQUE(proposal_id)`, role fail-closed, approver-only, maker≠checker (§2.9).
4. **Move the pipeline off the event loop** via `run_in_threadpool` (§2.7) and **fix the lock key** (§2.8).
5. `CORS` default; rate-limit the LLM endpoints.

*Exit criteria:* no unauthenticated data access; concurrent runs return 409; `/health` stays responsive under load; a proposal cannot be approved twice.

### Stage 3 — Trustworthy numbers and honest UX (Week 3–4)
1. **`BatchMetrics` single source of truth**; add `batch_id` filters; paginate `/approvals/pending` (§2.12, §6.1).
2. **Delete client-side metric derivation and category heuristics** (§2.12 steps 2, 5).
3. **Publish the three distinct match rates with clear labels** (§2.12 step 3); remove the `× 2` legs assumption.
4. **Loading states and double-submit guard** (§2.15).
5. **Replace the fabricated DAG** with an honest indicator (§2.13).
6. **Delete unearned metrics**; report "not measured" (§2.14 step 7).
7. **Responsive sidebar drawer** (§2.16).

*Exit criteria:* every KPI traces to one backend field; one batch yields one match rate; no screen claims work that did not happen; usable at 375px.

### Stage 4 — Complete the async architecture (Week 5–6)
1. `202 + batch_id`, worker execution, `batch_steps` per node, polling or SSE (§6.2).
2. Real-time DAG driven by actual node events.
3. Retire module-global `STATE`; bound the caches (§2.19).
4. Vendor Chart.js and fonts locally (§2.23c).

### Stage 5 — Make it genuinely agentic (Week 7–8)
1. **Instrument first**: persist every investigation attempt, log all provider failures (§2.14 steps 1–2). Do this before adding capability — you currently have no visibility into why the AI never ran.
2. Fix model configuration and enforce structured output (§2.14 steps 3–4).
3. Implement the **bounded tool-calling loop** over the existing four tools (§6.3).
4. Wire `AGENT_MAX_TOOL_CALLS`, `AGENT_TIMEOUT_SECONDS`, and the `AUTO_APPLY_*` policy so autonomy is genuinely bounded — or delete them (§2.14 step 6).
5. Enable auto-apply only for verified, sub-materiality, allow-listed exception types.
6. Feed the QA agent pre-computed aggregates so it quotes rather than infers (§2.23m).

*Exit criteria:* `ai_investigations` is populated; proposals differ by exception type; `DeterministicVerifier` sets `verified_by_code=1`; the "agentic" claim is defensible.

### Stage 6 — Hardening (ongoing)
Full regression suite (§6.5), Postgres for production, tenancy tests, and a calibration harness using the existing `GROUND_TRUTH_PATH` / `MIN_SAMPLES_FOR_CALIBRATION` settings.

---

### Closing note

The most encouraging finding is §1.1: **the reconciliation engine works.** One upstream line — an unconditional `× 100` where a parameter named `amount_scale` was already waiting to be used — was suppressing a 13× improvement in match rate and preventing every three-way match in the system's history. Most of what remains is not missing capability but **missing honesty in the seams**: a `catch` that paints green, a KPI bound to `items.length`, a `sleep()` where a subscription belongs, a lock keyed on a fresh UUID, and fourteen safety settings no code reads.

The domain model, matching algorithms, audit cryptography, security primitives, and visual design are all genuinely good. Fix the plumbing between them and this becomes a credible product — without changing the aesthetics or the core design.
