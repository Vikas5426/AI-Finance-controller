# 00 — Executive Recommendation, Use-Case Choice, Product Definition

## 1. Executive recommendation

**Build a three-way settlement reconciliation controller: Payment Gateway ↔ Bank Statement ↔ General Ledger, settlement-aware (N:1 batches, fees, refunds, chargebacks, FX), with an AI investigator that only ever *proposes* resolutions.**

The track's bar is *"throughput plus measured accuracy plus an honest exception list. One cherry-picked match proves nothing."* Three design consequences, which drive everything else in this blueprint:

| Bar | What it forces | Design consequence |
|---|---|---|
| Throughput | Batch must be big enough that manual matching is implausible | Generate **2,000+ records** (not 50). Report records/sec and wall-clock. Deterministic engine must be O(n·k), not O(n²). |
| Measured accuracy | You need **labelled ground truth** | The synthetic data generator emits a `ground_truth_links` manifest. Precision/recall/F1 are computed against it, not asserted. |
| Honest exception list | Every unresolved record enumerated with a reason | Exceptions are first-class DB rows with a state machine; the report lists 100% of residuals, never a sample. |

Three decisions that separate this from the 90% of submissions that will look identical:

1. **Global optimal assignment, not greedy matching.** Score all viable candidate pairs, then run the Hungarian algorithm (`scipy.optimize.linear_sum_assignment`) for the optimal 1:1 assignment. Greedy first-best matching is what everyone else will do, and it demonstrably mis-assigns near-duplicate amounts.
2. **A real N:1 settlement solver.** A bank credit of ₹4,83,210 is *not* any single gateway payment — it's 37 payments minus MDR fees minus one refund. Solving that as a bounded subset-sum over cents with a fee model is the single most finance-authentic piece of engineering in the project. Most submissions silently drop these to "unmatched".
3. **Calibrated confidence.** Because ground truth exists, fit score → P(correct) and report expected calibration error (ECE) + a reliability curve. "Confidence 0.87" then means something. This is the answer to *"how do you know your thresholds are right?"* — the question that ends most demos.

**Non-negotiable safety posture:** the LLM has zero write access to financial state. It emits schema-validated proposals; a deterministic verifier re-checks every proposal against hard gates before anything is applied. State that explicitly in the demo — it is the difference between a finance tool and a toy.

## 2. Which of the four directions to build

Scored 1–5 (5 = best) on your criteria.

| Criterion | Multi-source recon | Settlement Q&A | Cash forecasting | Tax-line matching |
|---|---|---|---|---|
| Fits "match rate + exceptions" bar | **5** — the metric *is* match rate | 2 — no natural denominator | 1 — no match rate at all | 4 |
| Measurable with ground truth | **5** — generator knows the true links | 3 — needs a hand-written Q&A eval set | 2 — needs a future you don't have | 4 |
| Technical depth | **5** — assignment, subset-sum, calibration | 2 — retrieval + prompt | 3 — stats, weak AI story | 3 — rules-heavy, less algorithmic |
| AI genuinely useful (not decorative) | 4 — explains/classifies residuals | **5** — AI is the product | 2 — regression beats an LLM | 3 |
| Finance relevance / recognisability | **5** — every finance team does this daily | 4 | 4 | 3 — jurisdiction-specific |
| Works on synthetic data | **5** | 4 — needs recon output to be interesting | 2 — synthetic seasonality is fake | 4 |
| Demo legibility in 3 minutes | **5** — "2,000 records, 96.4% matched, 71 exceptions, here they are" | 3 — chat demos feel unfalsifiable | 2 — a line chart proves nothing | 3 |
| Interview value | **5** — maps to real Stripe/Adyen/ERP problems | 3 | 3 | 4 |
| Scope risk | 3 — must resist gold-plating | **5** | 4 | 3 |

**Verdict:**

- **Core product = Multi-source settlement reconciliation.** It is the only direction where the required deliverable (match rate + honest exception list) falls out of the system naturally rather than being bolted on.
- **Secondary feature = Settlement investigation & Q&A agent.** Do *not* build it as a standalone chatbot. Build it as the **exception investigator** that runs inside the pipeline, and expose the same tool-calling agent through an ask-box scoped to a batch. You get the Q&A direction for ~15% extra effort because it reuses the identical tool layer, and it converts the demo from "a table of numbers" to "ask it why line 4,417 didn't match".
- **Optional advanced = 13-week forward cash forecast**, derived from reconciled data (expected settlement dates + open receivables + observed lag distribution). Build it *last*, deterministically (no LLM), as one page. It is the "controller" half of the track name ("run the books **and the cash position**") and costs one afternoon once recon works — but it is worthless if recon is weak.
- **Drop tax-line matching.** It is the same algorithm with more jurisdiction-specific rules you'd have to invent, and it dilutes the demo.

**Scope discipline rule:** if a feature does not move match rate, exception quality, or measured accuracy, it does not go in the MVP.

## 3. Product definition

### 3.1 What a traditional financial controller actually does

Not a CFO. The controller owns the *accuracy and closability of the books*. Daily/monthly:

| Duty | Concretely |
|---|---|
| Reconciliation | Prove that cash in the bank equals what the sub-ledgers say it should be, line by line. |
| Close the period | Drive month-end close: cut-off decisions, accruals, journal entries, sub-ledger→GL tie-out. |
| Exception clearing | Chase every unexplained difference until it's explained, reclassified, written off, or escalated. |
| Controls | Enforce segregation of duties, approval limits, materiality thresholds, evidence retention. |
| Reporting | Produce the trial balance, cash position, and variance explanations auditors will interrogate. |

The job is 70% **verification labour**: proving a number is right, and documenting *why* you believe it. That is exactly the labour an LLM+deterministic-engine hybrid can absorb.

### 3.2 Finance vocabulary you'll need (only what this system touches)

| Term | Meaning here |
|---|---|
| **Gateway / PSP** | Payment service provider (Razorpay, Stripe, Adyen). Records the *gross* customer charge. |
| **Settlement** | The PSP wires you money later (T+1/T+2), usually **netted**: many payments − fees − refunds − chargebacks = one bank credit. |
| **Gross vs net** | Gross = customer paid ₹1,000. Net = ₹1,000 − MDR fee ₹20 − GST on fee ₹3.60 = ₹976.40 hits the bank. |
| **MDR** | Merchant discount rate — the PSP's percentage cut, often `pct·gross + fixed`. The #1 cause of "amount mismatch" false alarms. |
| **Chargeback** | Customer disputes; PSP claws money back, often weeks later, plus a fixed penalty. |
| **GL / general ledger** | Double-entry books. Every event is ≥2 rows summing to zero (debits = credits). |
| **Sub-ledger** | Detailed ledger (AR, payments) that must tie out to a GL control account. |
| **Clearing / suspense account** | Temporary GL account holding money in flight (e.g. "funds in transit") or unexplained differences. Correct destination for unresolved exceptions. |
| **Cut-off / timing difference** | Payment on 31 Mar 23:58 IST settles 2 Apr. Not an error — a period-boundary artifact. Must be classified as timing, never as a break. |
| **Materiality** | The threshold below which a difference is not worth human time (e.g. ₹500 or 0.5% of batch value). Drives auto-write-off policy. |
| **Three-way match** | Agreeing three independent sources (here: gateway, bank, GL). Much stronger evidence than two-way. |
| **FX revaluation** | A USD invoice booked at one rate, settled at another → a real, expected difference (FX gain/loss), not a break. |

### 3.3 Category boundaries (these get asked in interviews)

| Category | Owns | Autonomy | Failure blast radius |
|---|---|---|---|
| **Reconciliation system** | Matching records across sources. Pure algorithm, no judgement. | None — rules only. | Wrong match rate. |
| **Finance-ops automation (RPA-ish)** | Moving files, running jobs, sending reminders. No reasoning. | Scripted. | Missed job. |
| **AI Financial Controller** ← *this project* | Recon + exception explanation + classification + proposed resolution + auditable evidence + close-readiness reporting. | Proposes; auto-applies only inside a narrow, provably-safe envelope. | Bad journal proposal — caught by verifier + approval. |
| **AI CFO** | Strategy: capital allocation, pricing, hiring, fundraising, board narrative. Forward-looking, judgement-heavy. | Advisory only. Should never be automated. | Bad strategic advice. |
| **Autonomous finance agent** | Initiates payments, moves money, closes the books unattended. | Full write authority. | **Irreversible financial loss.** Requires controls far beyond a hackathon; deliberately out of scope. |

Say this out loud in the demo: *"This is a controller, not an autonomous agent. It can explain and propose; it cannot move money or post to the ledger without a human."*

### 3.4 Decision rights — who is allowed to decide what

The single most important table in this document. Every component maps to one of these three columns.

| Decision | Deterministic code | AI | Human |
|---|---|---|---|
| Arithmetic, sums, balances, fee recomputation | **Yes — always** | Never | — |
| ID/reference equality, currency equality, sign/direction | **Yes** | Never | — |
| Date-window tolerance checks | **Yes** | Never | — |
| Candidate generation (blocking) | **Yes** | Never | — |
| Similarity scoring & final assignment | **Yes** | Never | — |
| Subset-sum / N:1 settlement decomposition | **Yes** | Never | — |
| Threshold application (auto vs review) | **Yes (policy table)** | Never | Sets the policy |
| Access control, org isolation, approval limits | **Yes** | Never | — |
| Ledger writes / journal posting | **Yes (on approval)** | Never | Approves |
| Normalising messy free-text descriptions | Regex first | **Yes — fallback** | — |
| Counterparty alias resolution ("AMZN MKTPLC*2K1" → Amazon) | Alias table first | **Yes — fallback, writes alias suggestion** | Confirms new aliases |
| Classifying an exception into a taxonomy | Rules cover ~80% | **Yes — the rest** | Overrides |
| Explaining *why* a break happened, in prose | No | **Yes** | Reads |
| Ranking/choosing among deterministic candidate matches | Score ranks | **Yes — tie-break with evidence** | Approves |
| Proposing a resolution (reclassify / write-off / link / escalate) | Templates | **Yes — selects + justifies** | Approves |
| Answering "why didn't invoice X settle?" | No | **Yes — via read-only tools** | — |
| Accepting a resolution above materiality | No | Never | **Yes — required** |

**Why the boundary matters:** LLMs are non-deterministic and cannot be audited arithmetically. If the LLM computes a sum, you cannot reproduce it, cannot prove it, and cannot let an auditor rely on it. If the LLM *explains* a sum that code computed, you get the benefit with none of the risk. Every design choice downstream follows from this.

### 3.5 Exact project scope

**In scope:** 3 sources (gateway CSV/JSON, bank statement CSV, GL CSV) → ingestion → normalisation → dedupe → deterministic matching (exact, rule, fuzzy, N:1 settlement) → exception detection & taxonomy → AI investigation with tools → proposal validation → auto-resolve / approval queue → immutable audit trail → batch report with match rate + full exception list → evaluation harness against ground truth → dashboard + scoped Q&A.

**Out of scope (say so explicitly):** real bank/PSP API connectors, actual journal posting to a real ERP, payment initiation, multi-currency GAAP-correct FX revaluation, tax filing, SSO/SCIM, multi-region.



