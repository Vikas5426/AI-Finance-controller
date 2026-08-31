# 01 — System Architecture & End-to-End Data Flow

## 4. High-level architecture

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│  BROWSER — Next.js 15 (App Router, TS, Tailwind, shadcn/ui, TanStack Query)  │
│  Dashboard │ Batches │ Transactions │ Exception Center │ Approvals │ Audit   │
└───────────────────────────────┬──────────────────────────────────────────────┘
                     HTTPS / JSON · JWT access token (15 min)
┌───────────────────────────────▼──────────────────────────────────────────────┐
│  FastAPI  (single ASGI app, uvicorn)                                         │
│  ┌────────────┬───────────────┬────────────┬──────────────┬───────────────┐  │
│  │ AuthN/AuthZ│ Ingestion API │ Recon API  │ Exception API │ Report/Q&A API│  │
│  └────────────┴───────────────┴────────────┴──────────────┴───────────────┘  │
│  Middleware: request_id · org context (RLS GUC) · rate limit · audit emitter  │
└──────┬──────────────────────┬─────────────────────────┬──────────────────────┘
       │ enqueue              │ read/write (asyncpg)    │ object put/get
┌──────▼─────────┐   ┌────────▼──────────────┐   ┌──────▼───────────────┐
│ Redis          │   │ PostgreSQL 16          │   │ Object store         │
│ • job broker   │   │ • finance data store   │   │ MinIO (dev) /        │
│ • result cache │   │ • RLS per org          │   │ S3 (prod)            │
│ • idempotency  │   │ • pgvector (v2)        │   │ • raw uploads        │
│ • rate limits  │   │ • pg_trgm (fuzzy)      │   │ • generated reports  │
└──────▲─────────┘   └────────▲──────────────┘   └──────▲───────────────┘
       │ consume              │                         │
┌──────┴──────────────────────┴─────────────────────────┴──────────────────────┐
│  WORKERS — Dramatiq (Redis broker), same codebase, separate process          │
│  ┌──────────┬──────────────┬──────────────┬────────────┬─────────────────┐   │
│  │ Ingest & │ Normalise &  │ Match Engine │ Exception  │ Report builder  │   │
│  │ validate │ dedupe       │ (P0→P5)      │ detector   │ + metrics       │   │
│  └──────────┴──────────────┴──────────────┴─────┬──────┘─────────────────┘   │
└──────────────────────────────────────────────────┼───────────────────────────┘
                                                   │ per-exception task
┌──────────────────────────────────────────────────▼───────────────────────────┐
│  AGENT RUNTIME (in-process library, called by workers & the Q&A endpoint)    │
│  ┌───────────────┐  ┌──────────────────────────┐  ┌──────────────────────┐  │
│  │ Model router  │→ │ Bounded tool-use loop     │→ │ Proposal validator   │  │
│  │ haiku/sonnet  │  │ max 6 calls · 60s · 12k tk│  │ Pydantic + re-verify │  │
│  └───────────────┘  └────────────┬─────────────┘  └──────────┬───────────┘  │
│                     READ-ONLY TOOL LAYER (typed, org-scoped, no raw SQL)     │
└──────────────────────────────────┼────────────────────────────┼─────────────┘
                                   │                            │ proposal rows
                        ┌──────────▼──────────┐      ┌──────────▼───────────┐
                        │ Gemini API           │      │ Postgres (proposals, │
                        │ (prompt caching on)  │      │ approvals, audit)    │
                        └─────────────────────┘      └──────────────────────┘
```

**Deployment shape for MVP:** 4 containers (`api`, `worker`, `postgres`, `redis`) + MinIO. One `docker compose up`. Do not introduce Kafka, Temporal, or a service mesh — see §20.

## 5. Layer-by-layer component architecture

Legend for **MVP?**: ✅ required · 🟡 thin version required · ⛔ skip for MVP.

### 5.1 Frontend
| | |
|---|---|
| **Why it exists** | The deliverable is *judgement support*: a human must see the match rate, drill into any exception, read the AI's evidence, and approve/reject. A CLI cannot demonstrate that. |
| **Inputs** | REST JSON from FastAPI; SSE stream for live batch progress. |
| **Outputs** | User actions (upload, run batch, approve, reject, override, ask question). |
| **Tech** | Next.js 15 App Router + TypeScript + Tailwind + shadcn/ui + TanStack Query + Recharts. |
| **Why** | shadcn/ui gives dense, data-table-heavy "operations console" surfaces without design work; TanStack Query handles polling/invalidations for long-running batches; Recharts is enough for 5 charts. Next.js only for routing/DX — **no SSR of financial data**, everything is client-fetched with the user's token so RLS applies. |
| **Alternatives rejected** | Streamlit (looks like a prototype — actively hurts the "real product" goal); plain Vite+React (fine, but you lose the routing/layout conventions for free); MUI/AntD (heavier, harder to make look intentional). |
| **Fails when** | Long batches → must poll or stream, never block. Large tables → server-side pagination mandatory (never ship 2,000 rows to the client at once). |
| **MVP?** | ✅ (6 pages, see §12) |

### 5.2 API gateway / backend
| | |
|---|---|
| **Why** | Single authenticated entry point; enforces org isolation, validation, idempotency, audit emission before anything touches data. |
| **Inputs** | HTTP requests + multipart file uploads. |
| **Outputs** | JSON responses; enqueued jobs; object-store writes; audit events. |
| **Tech** | FastAPI + Pydantic v2 + SQLAlchemy 2.0 (async) + Alembic + asyncpg. |
| **Why** | The agent, the matching engine (numpy/scipy/rapidfuzz), and the API must share Pydantic models — one language (Python) removes an entire class of schema-drift bugs. Pydantic v2 is the same validation layer used for LLM structured outputs, so *one* schema definition governs both the HTTP boundary and the AI boundary. |
| **Alternatives rejected** | Node/NestJS (you'd cross a language boundary for scipy/rapidfuzz); Django (ORM + admin useful, but async story and Pydantic integration are worse for this workload). |
| **Fails when** | Someone does heavy CPU work in a request handler → blocks the event loop. Rule: any operation > 500 ms is a job. |
| **MVP?** | ✅ |

### 5.3 Authentication & authorization
| | |
|---|---|
| **Why** | Financial data; also the demo story ("maker-checker" needs distinct identities). |
| **Inputs** | Credentials, refresh tokens, API keys (for machine ingestion). |
| **Outputs** | JWT access token (15 min, `sub`, `org_id`, `role`, `jti`); refresh token in httpOnly cookie (7 d, rotating). |
| **Tech** | Own implementation: `argon2id` (via `argon2-cffi`), `PyJWT`, HS256 for MVP → RS256/JWKS for prod. Roles: `viewer`, `analyst`, `approver`, `admin`. |
| **Why own** | Auth0/Clerk add an external dependency and a demo-day failure mode for ~30 lines of saved code. Roles are the interesting part and no vendor gives you finance approval limits. |
| **Fails when** | Token replay after role change → keep a Redis `jti` denylist on logout/role change. |
| **MVP?** | ✅ (roles + org isolation are the whole point) |

### 5.4 Data ingestion layer
| | |
|---|---|
| **Why** | Real finance data arrives as inconsistent CSVs with BOMs, `₹1,23,456.78`, `31/03/2026`, merged headers, and trailing total rows. Ingestion must be forgiving at the edge and strict at the core. |
| **Inputs** | Multipart upload (CSV/XLSX/JSON), or a `POST /records` batch from a "connector". |
| **Outputs** | `raw_records` rows: immutable, verbatim `payload JSONB` + `content_hash` + `source_id` + `row_number`; the original file in object storage. |
| **Tech** | `polars` for parsing (fast, strict dtypes, good CSV edge-case handling), `chardet` for encoding, streaming reads. Column mapping via a per-source `source_profile` JSON (declared column→canonical field map + parser hints). |
| **Why polars over pandas** | 5–20× faster on parse/joins, explicit null/dtype semantics (pandas silently coerces amounts to float and mangles precision — unacceptable for money). |
| **Key rule** | **Never mutate raw. Never lose raw.** Normalisation produces new rows; `raw_records` is append-only so you can always re-run the pipeline against the original bytes. This is what makes the whole thing auditable. |
| **Fails when** | Duplicate upload (→ `content_hash` unique index makes re-upload a no-op); unmapped column (→ reject file with a per-column error report, don't half-ingest); amount as float (→ parse to `Decimal`, store `NUMERIC(18,4)` plus `amount_minor BIGINT`). |
| **MVP?** | ✅ |

### 5.5 Data normalization layer
| | |
|---|---|
| **Why** | Matching is impossible across heterogeneous shapes. One canonical transaction row is the contract that every downstream component depends on. |
| **Inputs** | `raw_records`. |
| **Outputs** | `transactions` rows in the canonical schema (§9 of doc 03) + `normalization_issues`. |
| **Tech** | Pure Python transform functions per source type, registered in a `SourceAdapter` registry; `Decimal` money; `zoneinfo` for tz; deterministic `reference_keys` extraction (regex battery over description fields). |
| **Design note** | Normalisation is **deterministic and versioned** (`normalizer_version` column). When you change a regex, you re-run and can diff outcomes — this is how you prove an accuracy improvement rather than claiming one. |
| **Fails when** | Timezone-naive timestamps → force UTC storage + keep `source_timezone`. Sign conventions differ (bank debits negative, gateway refunds positive) → normalise to signed `amount_minor` + explicit `direction` enum. |
| **MVP?** | ✅ |

### 5.6 Finance data store
| | |
|---|---|
| **Why** | Money needs ACID, exact decimals, real constraints, and set-based candidate generation. |
| **Tech** | **PostgreSQL 16**, extensions `pg_trgm` (fuzzy text), `btree_gin`, `pgcrypto`; `pgvector` only in v2. |
| **Why Postgres, decisively** | You need: exact `NUMERIC`, transactions around multi-row match writes, `JSONB` for heterogeneous raw payloads, trigram indexes for candidate generation, window functions for the metrics, **row-level security for org isolation**, and later vector search — all in one engine. Mongo loses constraints and decimal safety; SQLite loses RLS/trigram/concurrency; a separate vector DB is an unnecessary second store (see §14). |
| **MVP?** | ✅ |

### 5.7 Reconciliation engine
| | |
|---|---|
| **Why** | The core product. Produces matches and, by subtraction, the exception list. |
| **Inputs** | `transactions` for a batch (all sources). |
| **Outputs** | `matches` (+ `match_legs`), `match_candidates` (scored, retained for explainability), residual unmatched set. |
| **Tech** | Python: SQL for blocking, `rapidfuzz` for string similarity, `numpy` for the score matrix, `scipy.optimize.linear_sum_assignment` for optimal assignment, custom bounded subset-sum for N:1. |
| **Why not ML here** | You have no labelled production data, and a learned model can't be explained to an auditor. A weighted score with published weights + a proof-carrying assignment is both stronger evidence and better engineering at this scale. ML is worth it only at millions of pairs (§7.9). |
| **Fails when** | O(n²) candidate explosion (→ blocking is mandatory); ambiguous ties (→ assignment solves globally; residual ties become exceptions, never coin flips). |
| **MVP?** | ✅ (full detail in doc 02) |

### 5.8 Rules engine
| | |
|---|---|
| **Why** | Tolerances, fee models, materiality, auto-resolve policy, and expected settlement lags must be **data, not code** — so they can be versioned, shown in the UI, cited in the audit trail, and tuned without redeploy. |
| **Inputs** | `rules` rows (org-scoped, versioned, effective-dated). |
| **Outputs** | Evaluated tolerance decisions, exception classifications, routing decisions — each returning the `rule_id` + `rule_version` that fired. |
| **Tech** | **Declarative JSON rule rows evaluated by a small hand-written interpreter** over a typed context object. ~200 lines. No DSL, no `eval`, no Drools. |
| **Why not a Python-expression DSL** | `eval()` on org-supplied strings is an RCE. A closed set of operators (`eq, neq, lt, lte, gt, gte, in, between, pct_of, abs_diff, regex_match, days_between`) over a whitelisted field set covers 100% of what you need and is trivially safe + serialisable to the UI. |
| **Example rule row** | `{"id":"R-AMT-FEE","when":[{"field":"abs_diff_minor","op":"between","value":[1,50000]},{"field":"diff_pct_of_gross","op":"between","value":[0.0150,0.0250]}],"then":{"classification":"FEE_DISCREPANCY","severity":"LOW","auto_resolve":true}}` |
| **MVP?** | ✅ (10–15 rules is plenty; hardcoding tolerances is the single most common mistake) |

### 5.9 AI agent layer
| | |
|---|---|
| **Why** | ~15–25% of records won't match deterministically. Human triage of those is the actual cost being automated. The agent reads the deterministic evidence and produces a classification + cause + proposed resolution + citations. |
| **Inputs** | An `exception_id` (+ pre-fetched deterministic context), or a scoped natural-language question. |
| **Outputs** | A validated `InvestigationResult` JSON → `ai_investigations` + `resolution_proposals` rows. Never a direct mutation of financial state. |
| **Tech** | Anthropic Python SDK tool-use loop (`claude-haiku-4-5` triage → `claude-sonnet-5` investigation), own orchestration, Pydantic-validated structured output. |
| **MVP?** | ✅ (full detail in doc 03) |

### 5.10 RAG / knowledge layer
| | |
|---|---|
| **Why (limited)** | Resolution proposals should cite *policy* ("SOP-04: fee variance within 0.25% of MDR → auto-adjust to fee expense"), not invent it. |
| **MVP decision** | **No vector DB.** The policy corpus is ~20 short documents (< 8k tokens total). Load the *relevant* SOPs by deterministic tag lookup (`exception_type → sop_ids`) and put them in the prompt inside a cached block. Retrieval accuracy = 100%, latency = 0, cost ≈ 0. |
| **v2** | `pgvector` + `voyage-3.5-lite` embeddings when the corpus exceeds ~50 docs or you add free-text policy Q&A. Detail in doc 05 §14. |
| **MVP?** | 🟡 (tag-based policy injection: yes. Vector search: no.) |

### 5.11 Exception management system
| | |
|---|---|
| **Why** | The deliverable *is* the exception list. Exceptions need identity, lifecycle, ownership, evidence, and closure — i.e. they are the primary work object, not a log line. |
| **Inputs** | Residual unmatched records; matched-but-discrepant pairs; rule violations. |
| **Outputs** | `exceptions` rows with state, type, severity, financial impact, links to evidence and proposals. |
| **Tech** | Postgres state machine, transitions enforced in one `transition()` function with an allowed-transitions map + optimistic locking (`version` column). |
| **MVP?** | ✅ (doc 04) |

### 5.12 Approval workflow
| | |
|---|---|
| **Why** | Maker-checker (segregation of duties) is the defining control of finance systems, and the honest answer to "do you trust the AI?" |
| **Inputs** | `resolution_proposals` in `PENDING_APPROVAL`. |
| **Outputs** | `approvals` rows (approve/reject + reason), state transition, applied resolution effect. |
| **Tech** | Postgres + a policy function `required_approval(impact_minor, confidence, exception_type) → role \| None`. |
| **Hard rule** | The identity that *created* a proposal can never approve it; the AI is a distinct actor (`actor_type='agent'`) and has no approval capability at all. |
| **MVP?** | ✅ |

### 5.13 Reporting & analytics
| | |
|---|---|
| **Why** | The scored deliverable: match rate, throughput, exception list. |
| **Inputs** | Completed batch state. |
| **Outputs** | Immutable `batch_reports` row (JSONB snapshot + `report_hash`), plus CSV/PDF export in object storage. |
| **Tech** | Deterministic SQL aggregation → Pydantic `BatchReport` model → JSONB. Exports: `polars.write_csv`; PDF only if time permits (`weasyprint`). |
| **Design note** | Snapshot the report, don't recompute it on read. A report that changes after the fact is not a report. |
| **MVP?** | ✅ |

### 5.14 Audit logging
| | |
|---|---|
| **Why** | Answers "what happened, why, on whose authority" — the reason a finance team can adopt this at all. |
| **Inputs** | Every state-changing operation + every agent run + every data access by the agent. |
| **Outputs** | Append-only `audit_events` with a per-org SHA-256 **hash chain** (`prev_hash` → `event_hash`). |
| **Tech** | Postgres table with `REVOKE UPDATE, DELETE`; a `BEFORE UPDATE OR DELETE` trigger that raises; hash computed over canonical JSON in the app. Verifier endpoint walks the chain. |
| **Why hash chain** | Cheap (one sha256 per event), makes tampering detectable, and is a genuinely impressive 40-line feature that maps to real audit requirements. |
| **MVP?** | ✅ (this is high value per line of code) |

### 5.15 Background jobs / workflow engine
| | |
|---|---|
| **Why** | A 2,000-record batch takes 10–60 s deterministic + 30–120 s of AI calls. That cannot live in a request. |
| **Tech** | **Dramatiq + Redis** for MVP/portfolio. Pipeline orchestrated by an explicit `batch_steps` table (a persisted DAG), *not* by chained task callbacks. |
| **Why Dramatiq over Celery** | Simpler configuration, sane defaults, better failure semantics, ~1/3 the surface area; Celery's flexibility buys nothing here. Why not Temporal: it is the right production answer for durable multi-day workflows with human waits, but for a 2-minute pipeline it adds a server, a worker SDK, and a mental model that will consume days you need elsewhere. Why not `arq`: fine, but Dramatiq's middleware/retry story is better documented. Why not FastAPI `BackgroundTasks`: dies with the process, no retries, no visibility — unacceptable. |
| **Idempotency** | Every step is keyed `(batch_id, step_name)` with a status; work claimed via `SELECT … FOR UPDATE SKIP LOCKED`. Re-running a completed step is a no-op. |
| **MVP?** | ✅ |

### 5.16 Monitoring & observability
| | |
|---|---|
| **Why** | You must be able to say "P95 investigation latency 3.4 s, cost ₹0.42/batch, 0 tool errors" — measured, not guessed. |
| **Tech** | `structlog` JSON logs with `request_id`/`batch_id`/`agent_run_id` on every line; OpenTelemetry traces (auto-instrument FastAPI + SQLAlchemy + httpx) → Jaeger locally; Prometheus counters/histograms via `prometheus-fastapi-instrumentator` → Grafana. Sentry for exceptions if you want one hosted thing. |
| **Domain metrics to expose** | `recon_match_rate`, `recon_records_per_second`, `exceptions_open`, `agent_tokens_total{model}`, `agent_cost_inr`, `agent_tool_errors_total`, `proposal_rejected_by_validator_total`, `human_override_rate`. |
| **MVP?** | 🟡 (structlog + the domain metrics table in Postgres. OTel/Grafana = portfolio tier.) |

### 5.17 Security layer
| | |
|---|---|
| **Why** | Sensitive financial records + an LLM that reads attacker-influenceable text (CSV description fields). |
| **Tech** | Postgres RLS keyed on `app.current_org_id`; typed tool layer with **no LLM-authored SQL**; Pydantic validation both directions; envelope encryption for source credentials; secrets from env/Docker secrets (never DB, never repo). |
| **MVP?** | ✅ (doc 06 — the threat model is short and worth every token) |

## 6. End-to-end data flow (concrete, one settlement traced through)

### 6.1 Ingestion flow

```text
User picks 3 files ──► POST /v1/sources/{id}/uploads  (multipart, Idempotency-Key)
                        │
                        ├─ 1. Stream to object store: s3://raw/{org}/{upload_id}/gateway.csv
                        ├─ 2. sha256 of bytes → uploads.file_hash (dup upload → 200 + existing id)
                        ├─ 3. Parse header, validate against source_profiles.column_map
                        │      ✗ unmapped/missing column → 422 with per-column detail, NOTHING ingested
                        ├─ 4. Insert raw_records (payload JSONB, row_number, content_hash)
                        │      content_hash = sha256(source_id ‖ canonical_json(payload))
                        │      ON CONFLICT DO NOTHING  ← row-level idempotency
                        └─ 5. 202 {upload_id, rows_accepted, rows_duplicate, rows_rejected}

User clicks "Run reconciliation" ──► POST /v1/batches {source_upload_ids, period}
                        └─ create batch + batch_steps(PENDING) ──► enqueue run_batch(batch_id)
```

### 6.2 Example raw inputs (verbatim source shapes)

**(a) Payment gateway export** — gross amounts, one row per customer payment:
```json
{"payment_id":"pay_LtPk29Xq7","order_id":"ord_88213","amount":118000,"currency":"INR",
 "fee":2360,"tax":425,"status":"captured","method":"upi","captured_at":"2026-03-31T23:58:12+05:30",
 "settlement_id":"setl_9KA22","customer_email":"r***@acme.co","description":"Invoice INV-2026-0412"}
```
*(`amount` in paise — gateways use minor units. 118000 paise = ₹1,180.00.)*

**(b) Bank statement CSV** — net, one row per settlement wire, description is mangled:
```csv
Txn Date,Value Date,Description,Debit,Credit,Balance,Ref No
02/04/2026,02/04/2026,"NEFT-RAZORPAY SOFTWARE PVT-SETL9KA22-CR",,483210.55,2914773.10,N2604029912
```

**(c) Internal ledger / GL export** — double-entry, booked on payment date:
```csv
je_id,line_no,posted_at,account_code,account_name,debit,credit,memo,doc_ref
JE-4471,1,2026-03-31,1210,Payment Gateway Receivable,1180.00,,"UPI capture INV-2026-0412",INV-2026-0412
JE-4471,2,2026-03-31,4010,Revenue - SaaS,,1000.00,"Rev INV-2026-0412",INV-2026-0412
JE-4471,3,2026-03-31,2310,GST Output Payable,,180.00,"GST INV-2026-0412",INV-2026-0412
```

**(d) Settlement report** — the PSP's own reconciliation of what it wired:
```json
{"settlement_id":"setl_9KA22","settled_at":"2026-04-02","gross":501400,"fees":10028,
 "tax_on_fees":1805,"refunds":6200,"chargebacks":0,"adjustments":-157,"net":483210,
 "payment_count":37,"currency":"INR","utr":"N2604029912"}
```

### 6.3 Normalised form (the canonical row every component speaks)

All four collapse into one shape. Money is stored as signed minor units (`BIGINT`) **and** `NUMERIC(18,4)`; never float.

| field | (a) gateway payment | (b) bank credit | (c) GL line 1 | (d) settlement |
|---|---|---|---|---|
| `id` | `txn_01HB…` | `txn_01HC…` | `txn_01HD…` | `txn_01HE…` |
| `source_kind` | `GATEWAY` | `BANK` | `LEDGER` | `SETTLEMENT` |
| `external_id` | `pay_LtPk29Xq7` | `N2604029912` | `JE-4471:1` | `setl_9KA22` |
| `txn_type` | `PAYMENT` | `SETTLEMENT_CREDIT` | `JOURNAL_DEBIT` | `SETTLEMENT` |
| `direction` | `INFLOW` | `INFLOW` | `DEBIT` | `INFLOW` |
| `amount_minor` | `118000` | `48321055` | `118000` | `48321000` |
| `gross_minor` / `fee_minor` / `tax_minor` | `118000` / `2360` / `425` | `null` / `null` / `null` | `null` | `50140000` / `1002800` / `180500` |
| `currency` | `INR` | `INR` | `INR` | `INR` |
| `occurred_at` (UTC) | `2026-03-31T18:28:12Z` | `2026-04-02T00:00:00Z` | `2026-03-31T00:00:00Z` | `2026-04-02T00:00:00Z` |
| `value_date` | `2026-04-02` | `2026-04-02` | `2026-03-31` | `2026-04-02` |
| `counterparty_raw` | `r***@acme.co` | `RAZORPAY SOFTWARE PVT` | `—` | `RAZORPAY` |
| `counterparty_norm` | `acme` | `razorpay` | `null` | `razorpay` |
| `description_norm` | `invoice inv 2026 0412` | `neft razorpay softwar…` | `upi capture inv 2026 0412` | `settlement setl 9ka22` |
| `reference_keys` (JSONB) | `{"invoice":["INV-2026-0412"],"order":["ord_88213"],"settlement":["setl_9KA22"]}` | `{"settlement":["SETL9KA22"],"utr":["N2604029912"]}` | `{"invoice":["INV-2026-0412"],"je":["JE-4471"]}` | `{"settlement":["setl_9KA22"],"utr":["N2604029912"]}` |
| `account_code` | `null` | `1010 Bank` | `1210` | `null` |
| `status` | `CAPTURED` | `POSTED` | `POSTED` | `SETTLED` |

**Normalisation strategy:**
1. **Money:** parse with `Decimal`, detect minor-vs-major units from the source profile (`amount_scale: 100`), store both `amount_minor` (canonical for all comparisons) and `amount` (display). Sign convention: inflow positive, outflow negative, GL uses separate `direction` because debit/credit is not the same axis as inflow/outflow.
2. **Dates:** parse with an explicit per-source format list (never `dateutil` guessing — `02/04/2026` is 2 Apr in India and 4 Feb in the US; guessing here silently destroys your date tolerance logic). Store UTC `occurred_at` + `value_date DATE` + `source_timezone`.
3. **Reference key extraction** — the highest-leverage 60 lines in the codebase. A regex battery over every text field yields typed keys:
   `INV-\d{4}-\d{4}` → invoice · `pay_[A-Za-z0-9]{9,}` → payment · `setl_?[A-Za-z0-9]+` (case/hyphen-insensitive) → settlement · `ord_\d+` → order · `[NR]\d{11,}` → UTR · `JE-\d+` → journal.
   Store as `JSONB {type: [values]}` with a GIN index. Matching then becomes a set-intersection over typed keys, which is what makes `SETL9KA22` in a bank narration find `setl_9KA22` in the gateway.
4. **Text:** lowercase → strip punctuation → collapse whitespace → drop a stoplist of bank noise tokens (`neft`, `imps`, `upi`, `rtgs`, `cr`, `dr`, `ref`, `pvt`, `ltd`) → `description_norm`. Keep the original; never overwrite.
5. **Counterparty:** lookup in `counterparty_aliases` (org-scoped, `alias_norm → canonical_id`); on miss, leave `null` and let the agent propose an alias (human confirms → alias row created → future runs are deterministic). This is the correct pattern for AI in a deterministic system: **AI writes rules, code applies them.**

### 6.4 The reconciliation pipeline, traced

```text
P0 DEDUPE ──────────────────────────────────────────────────────────────────────
  within each source: group by (source_id, external_id) and by
  (amount_minor, value_date, counterparty_norm, direction) fingerprint
  → 2 identical bank rows found → 1 kept, 1 → exception DUPLICATE_RECORD (LOW)

P1 EXACT KEY MATCH ────────────────────────────────────────────────────────────
  join on reference_keys intersection where key type is unique-by-construction
  GATEWAY.reference_keys.settlement ∩ BANK.reference_keys.settlement
  → 37 gateway payments and 1 bank credit both carry setl_9KA22
  → this is NOT a 1:1 match: flag the group for P4, not P1
  GATEWAY.reference_keys.invoice ∩ LEDGER.reference_keys.invoice
  → pay_LtPk29Xq7 ↔ JE-4471:1  score 1.00  method=EXACT_ID  → matches row, CONFIRMED

P2 RULE-BASED DETERMINISTIC ───────────────────────────────────────────────────
  for residuals: (currency ==) ∧ (direction ==) ∧ (|Δamount| ≤ tol) ∧ (Δdays ≤ lag_window)
  ∧ unique candidate → match, method=RULE, score 0.95–0.99

P3 FUZZY / SCORED ASSIGNMENT ──────────────────────────────────────────────────
  blocking → score matrix → Hungarian → threshold
  (full detail in doc 02 §7)

P4 N:1 SETTLEMENT SOLVER ──────────────────────────────────────────────────────
  bank credit 48321055 paise, value_date 2026-04-02
  candidate pool: gateway payments with settlement_date 2026-04-02 ± 1d (n=41)
  fee model from rules: fee = 2.00% · gross + ₹2.00 fixed, GST 18% on fee
  solve:  Σgross − Σfee − Σtax − refunds + adjustments = net
          50140000 − 1002800 − 180500 − 620000 + (−15700) = 48321000
  residual vs bank: 48321055 − 48321000 = 55 paise
  → within rounding tolerance (₹1.00) → MATCH method=NET_SETTLEMENT
     legs: 37 gateway + 1 refund + 1 bank + 1 settlement-report row
     score 0.97, evidence = the arithmetic above, stored verbatim
  → 4 of the 41 candidates excluded by the solver → carried to P5

P5 RESIDUAL CLASSIFICATION ────────────────────────────────────────────────────
  every remaining record → rules engine → exception with a type
  4 leftover gateway payments:
    • 2 → TIMING_DIFFERENCE (settlement_date 2026-04-04, next batch)   auto-resolve
    • 1 → MISSING_BANK_RECORD (settled 6 days ago, no wire)            HIGH severity
    • 1 → AMOUNT_MISMATCH, Δ = ₹47.20 on ₹1,180 gross                  → AI investigation
```

### 6.5 AI boundary on one exception

**Input handed to the agent (deterministically pre-fetched, so the agent starts informed):**
```json
{"exception_id":"exc_01HF7…","type":"AMOUNT_MISMATCH","severity":"MEDIUM",
 "impact_minor":4720,"currency":"INR",
 "primary_record":{"id":"txn_01HB…","source":"GATEWAY","amount_minor":118000,"fee_minor":2360,"tax_minor":425,"ref":"INV-2026-0412"},
 "counter_record":{"id":"txn_01HD…","source":"LEDGER","amount_minor":113280,"ref":"INV-2026-0412"},
 "deterministic_findings":{"abs_diff_minor":4720,"diff_pct_of_gross":0.0400,
   "expected_fee_plus_tax_minor":2785,"diff_matches_fee_model":false,
   "diff_equals_gst_on_gross":false,"candidate_matches":[]},
 "applicable_rules":["R-AMT-TOL-001","R-AMT-FEE"],
 "policy_excerpts":["SOP-04 §2: fee variance within 0.25% of MDR may be auto-adjusted…"]}
```

**What the agent is allowed to do:** call read-only tools (≤6), reason, then emit one validated JSON object. It may *not* compute the difference (already given), may *not* write, may *not* see other orgs' data.

**Agent output (schema-validated):**
```json
{"exception_id":"exc_01HF7…","classification":"FEE_AND_TAX_BOOKED_NET",
 "likely_cause":"Ledger line 1210 was booked net of MDR (₹23.60) and GST on fee (₹4.25) — total ₹27.85 — plus a ₹19.35 UPI surcharge appearing in gateway row `fee_breakup.surcharge` that the ledger omitted entirely. 23.60+4.25+19.35 = 47.20, exactly the difference.",
 "candidate_match_ids":["txn_01HD…"],
 "recommended_action":"ADJUST_LEDGER_FEE_SPLIT",
 "confidence":0.88,
 "evidence":[{"tool":"get_transaction_details","record_id":"txn_01HB…","field":"fee_breakup","value":"{mdr:2360,gst:425,surcharge:1935}"},
             {"tool":"get_reconciliation_rules","rule_id":"R-AMT-FEE"}],
 "requires_human_review":true,
 "citations":["SOP-04 §2"]}
```

**Deterministic verification before this is allowed to persist as a proposal:**
`sum(fee_breakup) == abs_diff_minor` → 2360+425+1935 = 4720 ✓. The claim is *arithmetically re-checked in code*. If it failed, the proposal is rejected, `proposal_rejected_by_validator_total` increments, and the exception routes to human review with the failed check attached. The LLM's arithmetic is never trusted — it is only ever *confirmed*.

**Then:** impact ₹47.20 < materiality ₹500 **but** confidence 0.88 < auto threshold 0.93 → `HUMAN_REVIEW`. Approver sees the evidence, one-click approves → `approvals` row → resolution applied → exception `CLOSED` → 5 audit events chained.

### 6.6 Where each piece of state lives

| Stage | Written to | Mutable? | Retained |
|---|---|---|---|
| Uploaded bytes | object store | no | 7 y (config) |
| Parsed row | `raw_records` | **no** (append-only) | 7 y |
| Canonical row | `transactions` | only by re-normalisation (new `normalizer_version`) | 7 y |
| Scored pair | `match_candidates` | no | 90 d (prunable) |
| Accepted link | `matches` + `match_legs` | supersede-only (`superseded_by`) | 7 y |
| Break | `exceptions` | state transitions only, `version`-locked | 7 y |
| Agent run | `agent_runs` + `agent_tool_calls` | no | 1 y |
| AI conclusion | `ai_investigations` | no | 7 y |
| Proposal | `resolution_proposals` | status only | 7 y |
| Human decision | `approvals` | **no** | 7 y |
| Everything | `audit_events` (hash-chained) | **no** | 7 y |
| Batch outcome | `batch_reports` (snapshot + hash) | **no** | 7 y |

**The invariant that makes it auditable:** nothing that represents a *decision* is ever updated in place. Corrections are new rows that supersede old ones. Only `exceptions.state` and `resolution_proposals.status` move, and every movement emits a chained audit event.








