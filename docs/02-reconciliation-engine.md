# 02 — Reconciliation Engine (the core of the product)

## 7.1 Design principles

1. **Passes are ordered by decreasing certainty.** Once a record is matched by a higher-certainty pass it is removed from the pool. Never let fuzzy logic re-open an exact ID match.
2. **Every match carries its proof.** `method`, `score`, per-feature scores, and the rule/solver evidence go into the row. A match you can't explain is a liability.
3. **Blocking before scoring.** Never build an n×m matrix over the full batch.
4. **Global assignment, not greedy.** Locally-best is not globally-best when amounts repeat.
5. **Everything unmatched becomes a typed exception.** There is no "leftover" bucket.

## 7.2 Pass structure

| Pass | Name | Technique | Typical yield | Score range | Auto? |
|---|---|---|---|---|---|
| P0 | Intra-source dedupe | fingerprint grouping | 1–3% flagged | — | flag only |
| P1 | Exact key match | typed reference-key intersection | 55–70% | 1.00 | ✅ auto |
| P2 | Rule-based deterministic | amount+date+ccy+direction, unique candidate | 10–20% | 0.95–0.99 | ✅ auto |
| P3 | Fuzzy scored assignment | blocking → weighted score → Hungarian | 5–12% | 0.60–0.95 | ≥0.90 auto |
| P4 | N:1 / M:N settlement solver | bounded subset-sum with fee model | 5–15% of value | 0.90–0.99 | ≥0.95 auto |
| P5 | Residual classification | rules engine → exception types | remainder | — | per policy |

Order note: **P4 must run before P3's residuals are declared exceptions**, and the settlement group must be detected in P1 (shared settlement key) so its members are excluded from 1:1 scoring. Getting this ordering wrong is the most common source of a bad match rate.

## 7.3 P1 — Exact matching

Match on **typed** reference keys, not on any-field string equality.

```sql
-- Candidate exact links via typed reference key intersection (GIN index on reference_keys)
WITH pairs AS (
  SELECT a.id AS a_id, b.id AS b_id, k.key_type, k.key_value
  FROM transactions a
  CROSS JOIN LATERAL jsonb_each(a.reference_keys) AS j(key_type, vals)
  CROSS JOIN LATERAL jsonb_array_elements_text(j.vals) AS k2(key_value)
  CROSS JOIN LATERAL (SELECT j.key_type, k2.key_value) k
  JOIN transactions b
    ON b.batch_id = a.batch_id
   AND b.source_kind <> a.source_kind
   AND b.reference_keys -> k.key_type ? k.key_value
  WHERE a.batch_id = :batch_id AND a.match_status = 'UNMATCHED'
)
SELECT a_id, b_id, key_type, count(*) OVER (PARTITION BY a_id) AS a_fanout,
       count(*) OVER (PARTITION BY b_id) AS b_fanout
FROM pairs;
```

Decision table on the fan-out:

| a_fanout | b_fanout | Meaning | Action |
|---|---|---|---|
| 1 | 1 | clean 1:1 | match, score 1.00, `EXACT_ID` |
| 1 | N | one record ↔ many | candidate group → **P4** |
| N | 1 | many ↔ one (settlement) | candidate group → **P4** |
| N | M | shared key is not unique (e.g. same invoice on 3 sources) | resolve per key type: unique-by-construction types (`payment`, `utr`, `je`) escalate as data error; shared types (`invoice`) → P3 with a strong ID prior |

**Key uniqueness must be declared, not assumed.** `reference_key_types` config: `{payment: UNIQUE, utr: UNIQUE, settlement: GROUP, invoice: SHARED, order: SHARED, je: UNIQUE}`. Treating a `GROUP` key as `UNIQUE` is how you produce false matches.

## 7.4 P2 — Rule-based deterministic matching

Hard gates (any failure ⇒ not a candidate, ever):

| Gate | Rule | Why hard |
|---|---|---|
| Currency | `a.currency == b.currency` | Cross-currency needs FX handling, never a silent match |
| Direction | `sign(a) == sign(b)` for cross-source inflow, or valid debit/credit pairing for GL | An inflow can't match an outflow; this catches sign-convention bugs |
| Amount | within tolerance (below) | — |
| Date | `|a.value_date − b.value_date| ≤ lag_window(source_pair)` | Prevents matching March to September |
| Not already matched | both `UNMATCHED` | pool discipline |
| Same batch/org | always | isolation |

**Amount tolerance is source-pair specific** (from `rules`, not code):

| Source pair | Tolerance | Rationale |
|---|---|---|
| GATEWAY ↔ LEDGER | ₹0 on gross; fee/tax compared separately | Both are internal, should agree exactly |
| GATEWAY ↔ BANK | net-of-fee model, ±₹1 rounding | Bank sees net only |
| SETTLEMENT ↔ BANK | ±₹1 | PSP's own net vs the wire |
| LEDGER ↔ BANK | ±₹1 or ±0.05% (whichever greater) | rounding + FX |

**Date lag windows:** `GATEWAY→BANK: 0..3d` (T+2 plus weekend), `LEDGER→BANK: −1..+4d`, `GATEWAY→LEDGER: ±1d`. Windows are asymmetric and directional — a settlement never precedes its payment, so a negative lag is itself a signal (`SUSPECT_ORDERING` exception).

## 7.5 P3 — Fuzzy matching: blocking, scoring, assignment

### Step 1 — Blocking (candidate generation)

Purpose: reduce n×m to n×k with k ≈ 5–30, without losing true pairs. Union of three cheap SQL-indexable strategies:

```sql
-- Block A: amount band + date window + currency + direction  (btree composite index)
SELECT b.id FROM transactions b
WHERE b.batch_id = :batch AND b.match_status='UNMATCHED'
  AND b.source_kind = :other_source
  AND b.currency = :ccy AND b.direction = :dir
  AND b.value_date BETWEEN :d_lo AND :d_hi
  AND b.amount_minor BETWEEN :amt_lo AND :amt_hi;   -- ±max(200 paise, 3% )

-- Block B: trigram similarity on normalised description (GIN gin_trgm_ops)
SELECT b.id, similarity(b.description_norm, :desc) AS sim FROM transactions b
WHERE b.batch_id=:batch AND b.description_norm % :desc          -- % uses pg_trgm threshold
ORDER BY sim DESC LIMIT 20;

-- Block C: partial reference-key overlap (any key type, including SHARED types)
SELECT b.id FROM transactions b
WHERE b.batch_id=:batch AND b.reference_keys ?| :all_key_values;
```
Union the three, cap at 40 candidates per record (keep highest Block-B sim on overflow), then apply hard gates from §7.4. Records with **zero** candidates go straight to `MISSING_COUNTERPART` — cheap and correct.

### Step 2 — Feature scoring

Six features, each normalised to [0,1]:

| Feature | Formula | Notes |
|---|---|---|
| `s_id` | `1.0` if any UNIQUE key matches; `0.7` if a SHARED key matches; `0.4` if a normalised substring of one appears in the other's description; else `0.0` | The substring case is what catches `SETL9KA22` inside a bank narration |
| `s_amt` | `exp(-Δ / max(tol_abs, tol_pct·max(|a|,|b|)))` where `Δ=|a−b|` in minor units | Exponential, not linear: ₹1 off ≈ 1.0, ₹100 off decays hard. Special case: if `Δ` matches the fee model within ±₹1 → `s_amt = 0.97` and set `fee_explained=true` |
| `s_date` | `exp(-max(0, Δdays − grace) / τ)`, `grace=1`, `τ=2.0` | Grace absorbs cut-off; τ from observed lag distribution |
| `s_desc` | `rapidfuzz.fuzz.token_set_ratio(a.desc_norm, b.desc_norm)/100` | `token_set_ratio` is the right choice: order-insensitive and robust to one side having extra tokens (bank narrations always do) |
| `s_cp` | `1.0` alias-table hit; else `token_set_ratio` on counterparty; `0.5` if either is null | Null must not be penalised as a mismatch — GL rows often have no counterparty |
| `s_ctx` | `+1` if `account_code` is the expected control account for this pair type; `0.5` unknown | Cheap domain signal most people omit |

### Step 3 — Weights per source pair

```python
WEIGHTS = {
  ("GATEWAY","LEDGER"): dict(s_id=0.45, s_amt=0.25, s_date=0.10, s_desc=0.10, s_cp=0.05, s_ctx=0.05),
  ("GATEWAY","BANK"):   dict(s_id=0.30, s_amt=0.35, s_date=0.20, s_desc=0.10, s_cp=0.05, s_ctx=0.00),
  ("BANK","LEDGER"):    dict(s_id=0.25, s_amt=0.30, s_date=0.15, s_desc=0.15, s_cp=0.10, s_ctx=0.05),
  ("SETTLEMENT","BANK"):dict(s_id=0.50, s_amt=0.35, s_date=0.10, s_desc=0.05, s_cp=0.00, s_ctx=0.00),
}
score = sum(w[f] * s[f] for f in w)          # then hard gates applied as a 0/1 multiplier
```
Weights differ by pair because the *available evidence* differs: bank rows have no IDs but reliable amounts; ledger rows have IDs but unreliable amounts (booked net/gross inconsistently). Using one global weight vector is the most common quality bug in reconciliation code.

### Step 4 — Global optimal assignment

```python
import numpy as np
from scipy.optimize import linear_sum_assignment

def assign(left_ids, right_ids, pairs, tau_auto=0.90, tau_review=0.65):
    """pairs: {(i, j): score} sparse from blocking. Returns accepted, ambiguous, unmatched."""
    n, m = len(left_ids), len(right_ids)
    NEG = -1e6                                  # forbid non-candidate pairs
    C = np.full((n, m), NEG, dtype=np.float64)
    for (i, j), s in pairs.items():
        C[i, j] = s
    rows, cols = linear_sum_assignment(C, maximize=True)

    accepted, ambiguous = [], []
    for i, j in zip(rows, cols):
        s = C[i, j]
        if s <= 0:
            continue
        # runner-up margin: how much better is this than the next best for either side?
        row_best2 = np.partition(C[i], -2)[-2] if m > 1 else NEG
        col_best2 = np.partition(C[:, j], -2)[-2] if n > 1 else NEG
        margin = s - max(row_best2, col_best2)
        if s >= tau_auto and margin >= 0.05:
            accepted.append((i, j, s, margin))
        elif s >= tau_review:
            ambiguous.append((i, j, s, margin))   # → AI investigation / human review
    return accepted, ambiguous
```

Why this matters concretely: three ₹1,180.00 payments on the same day from three customers, and three matching bank lines. Greedy matching assigns the first bank line to whichever payment it scores first — a coin flip that is *wrong 2/3 of the time* on customer attribution, while still reporting a 100% match rate. Hungarian maximises total score, and the **runner-up margin** exposes the ambiguity instead of hiding it: low margin ⇒ `AMBIGUOUS_MATCH` exception, which is the honest outcome. This one feature is worth explicitly demoing.

Complexity: Hungarian is O(k³) on the dense sub-block. Run it **per blocking cluster**, not on the whole batch — cluster by `(currency, direction, value_date week)` so each solve is ≤ 200×200. 2,000 records → ~20 solves → milliseconds.

## 7.6 P4 — N:1 and M:N settlement solver

The finance-authentic core. A bank credit equals many gateway payments, net of fees, refunds, chargebacks and adjustments.

### Fee model
From `rules`, per PSP + payment method:
```
net_i = gross_i − fee_i − tax_i
fee_i = round(pct · gross_i) + fixed        # pct=0.0200, fixed=200 paise
tax_i = round(gst_rate · fee_i)             # gst_rate=0.18
```
So for a candidate subset S of size k:
```
predicted_net(S) = Σ_{i∈S} (gross_i − round(pct·gross_i) − fixed − round(gst·(round(pct·gross_i)+fixed)))
                   − Σ refunds(S) − Σ chargebacks(S) + adjustments
```
**Do not** algebraically simplify to `Σgross·(1−pct) − k·fixed`. Per-row rounding is not distributive; PSPs round each row, and the ±k·0.5-paise error is exactly what produces phantom "amount mismatch" exceptions. Compute per row.

### Solver strategy — three tiers, cheapest first

```python
def solve_settlement(bank_amount_minor, candidates, tol=100):   # tol = ₹1.00
    # Tier 1: settlement key is present → the subset is DECLARED, just verify arithmetic. ~90% of cases.
    if key_group := group_by_settlement_key(candidates):
        pred = predicted_net(key_group)
        if abs(pred - bank_amount_minor) <= tol:
            return Solution(key_group, method="NET_SETTLEMENT_DECLARED", score=0.99,
                            evidence=arith_trace(key_group, pred, bank_amount_minor))
        return Partial(key_group, residual=bank_amount_minor - pred)   # → SETTLEMENT_VARIANCE exception

    # Tier 2: no key → bounded subset-sum DP over net values, cents-quantised.
    #  Pool restricted by settlement_date window; |pool| capped at 60.
    return subset_sum_dp(bank_amount_minor, candidates, tol)
```

**Tier 2 DP** — pseudo-polynomial over the amount axis, quantised to reduce state:
```python
def subset_sum_dp(target, cands, tol, q=100):      # q = quantise to ₹1
    nets = [predicted_net_single(c) for c in cands]
    T = target // q
    reach = {0: ()}                                 # quantised_sum -> chosen index tuple
    for idx, v in enumerate(nets):
        vq = v // q
        for s, chosen in list(reach.items()):
            ns = s + vq
            if ns <= T + 2 and ns not in reach:      # prune above target
                reach[ns] = chosen + (idx,)
    best = min((s for s in reach if abs(s - T) * q <= tol + len(reach[s]) * q),
               key=lambda s: abs(s - T), default=None)
    ...
```
Guards that keep this from exploding: cap pool at 60 (sort by |amount| desc, take top 60 by value coverage), cap `reach` dict at 2e6 states, hard 5-second timeout per bank line, and **prune any sum exceeding the target** (all amounts same-sign after refund separation). If the solver bails: `UNRESOLVED_SETTLEMENT_GROUP` exception with the pool attached — an honest exception, which is exactly what the track asks for. Never fabricate a match to improve the headline number.

**Ambiguity check (critical):** if the DP finds ≥2 distinct subsets hitting the target within tolerance, the match is **not** accepted — emit `AMBIGUOUS_SETTLEMENT_GROUP`. With 40 similar amounts, coincidental subsets are common; accepting the first one silently creates a false match. Count solutions, don't just find one.

### Cardinality taxonomy

| Cardinality | Real-world case | Detection | Representation |
|---|---|---|---|
| **1:1** | one payment ↔ one GL line | P1/P2/P3 | `matches` + 2 `match_legs` |
| **1:N** | one payment refunded in 3 tranches; one invoice paid in installments | primary record's amount ≈ Σ of N | 1 + N legs, `match_type='ONE_TO_MANY'` |
| **N:1** | 37 payments → 1 bank settlement wire | P4 | N + 1 legs, `NET_SETTLEMENT` |
| **N:M** | two settlement wires covering three days of payments with a rolling reserve | P4 on the combined pool, or split by declared keys | `MANY_TO_MANY`, requires human confirm ≥ materiality |
| **1:0** | payment with no bank credit | zero candidates after all passes | exception, no match row |

**Every match is a group, not a pair.** Model it that way from day one:
```
matches(id, batch_id, match_type, method, score, confidence, evidence JSONB, status)
match_legs(match_id, transaction_id, role, signed_amount_minor)
    role ∈ {PRIMARY, COUNTERPART, FEE, TAX, REFUND, CHARGEBACK, ADJUSTMENT, ROUNDING}
```
Invariant enforced in code and asserted in tests: `Σ signed_amount_minor over legs == 0` (within rounding tolerance, with a `ROUNDING` leg carrying the remainder). This is a **double-entry-style balance check on every match** — it makes it structurally impossible to record a match that doesn't actually balance. Strongest single design idea in the engine after the solver; mention it in the demo.

## 7.7 Confidence — score is not probability

Raw score ∈ [0,1] is an arbitrary weighted sum. Confidence must be a **calibrated probability of correctness**, because thresholds are set on it.

```python
# Offline, using the synthetic generator's ground truth:
from sklearn.isotonic import IsotonicRegression
iso = IsotonicRegression(out_of_bounds="clip").fit(scores, is_correct)   # is_correct ∈ {0,1}
# Persisted as calibration_models(version, pair_type, knots JSONB); applied at match time:
confidence = float(iso.predict([score])[0])
```
Report **Expected Calibration Error** over 10 bins and show a reliability curve in the UI:
`ECE = Σ_b (n_b/N)·|acc(b) − conf(b)|`. Target ECE < 0.05.

Why this is the highest-value 30 lines in the project: it converts "I picked 0.9 because it felt right" into "at confidence ≥ 0.93, observed precision is 99.4% on 1,840 labelled pairs, ECE 0.021". That is *measured accuracy*, exactly the bar. Fit per source-pair type; fall back to identity if a pair type has < 100 labelled examples.

## 7.8 Exception generation from residuals (P5)

Deterministic classification, in priority order — first match wins:

| Order | Condition | Exception type | Severity |
|---|---|---|---|
| 1 | duplicate fingerprint within source | `DUPLICATE_RECORD` | LOW |
| 2 | two bank credits with same settlement key | `DUPLICATE_SETTLEMENT` | **CRITICAL** |
| 3 | matched pair, `Δ` explained by fee model | `FEE_DISCREPANCY` | LOW |
| 4 | matched pair, `Δ` unexplained, `Δ ≤ materiality` | `IMMATERIAL_VARIANCE` | LOW |
| 5 | matched pair, `Δ` unexplained, `Δ > materiality` | `AMOUNT_MISMATCH` | MED/HIGH by size |
| 6 | candidate exists but `Δdays` beyond window, and outside period | `TIMING_DIFFERENCE` | LOW |
| 7 | currencies differ but everything else matches | `CURRENCY_MISMATCH` | HIGH |
| 8 | gateway payment settled, no bank line, past expected lag | `MISSING_BANK_RECORD` | HIGH |
| 9 | bank credit, no gateway/settlement source | `UNKNOWN_BANK_CREDIT` | HIGH |
| 10 | gateway payment, no GL entry | `MISSING_LEDGER_ENTRY` | MED |
| 11 | settlement group solved partially | `PARTIAL_SETTLEMENT` | MED |
| 12 | ≥2 subsets or margin < 0.05 | `AMBIGUOUS_MATCH` | MED |
| 13 | refund with no original payment | `ORPHAN_REFUND` | HIGH |
| 14 | chargeback not booked in GL | `UNBOOKED_CHARGEBACK` | HIGH |
| 15 | GL group where debits ≠ credits | `UNBALANCED_JOURNAL` | **CRITICAL** |
| 16 | anything else | `UNCLASSIFIED` → always AI + human | MED |

`UNCLASSIFIED` must exist and must be visible in the report. A taxonomy that never falls through is a taxonomy that is lying.

<!--NEXT-->



