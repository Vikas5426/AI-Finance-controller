# 04 — Exception Management, Lifecycle & Rules Engine

## 11. Exception Taxonomy & Lifecycle Management

In an enterprise reconciliation pipeline, exceptions are not log lines; they are **first-class financial work objects**. Every unresolved transaction or variance is categorized into a strictly governed taxonomy, evaluated for financial impact, and driven through a deterministic state machine.

### 11.1 Comprehensive 16-Type Exception Taxonomy

| Code | Exception Type | Severity | Description | Auto-Resolution Policy |
|---|---|---|---|---|
| `E01` | `DUPLICATE_RECORD` | LOW | Duplicate transaction fingerprint within the same source. | Keep first, mark second duplicate. |
| `E02` | `DUPLICATE_SETTLEMENT` | **CRITICAL** | Multiple bank credits referencing the same settlement UTR. | Never auto-resolve. Flag fraud/bank error. |
| `E03` | `FEE_DISCREPANCY` | LOW | Amount discrepancy exactly matches the MDR + GST fee model. | Auto-resolve if within ±0.25% of gross. |
| `E04` | `IMMATERIAL_VARIANCE` | LOW | Unexplained variance $\le$ Materiality threshold (e.g. ₹500). | Auto-write-off to suspense/rounding account. |
| `E05` | `AMOUNT_MISMATCH` | HIGH | Unexplained variance $>$ Materiality threshold. | Route to AI investigation + human approval. |
| `E06` | `TIMING_DIFFERENCE` | LOW | Matched across cut-off boundary (T+2 lag outside period). | Auto-accrue to "In-Transit" clearing account. |
| `E07` | `CURRENCY_MISMATCH` | HIGH | Match candidate has conflicting ISO currency code. | Require human confirmation with FX rate. |
| `E08` | `MISSING_BANK_RECORD` | HIGH | Gateway captured payment with no settlement credit after T+5. | Escalate to Treasury / PSP ops. |
| `E09` | `UNKNOWN_BANK_CREDIT` | HIGH | Direct deposit or credit without matching invoice or gateway row. | Park in Unidentified Receipts suspense account. |
| `E10` | `MISSING_LEDGER_ENTRY` | MEDIUM | Gateway or bank row present, but missing from sub-ledger. | AI proposes adjusting journal entry. |
| `E11` | `PARTIAL_SETTLEMENT` | MEDIUM | N:1 settlement solver captured only subset of batch value. | Allocate matched legs, create residual exception. |
| `E12` | `AMBIGUOUS_MATCH` | MEDIUM | Hungarian runner-up margin $< 0.05$ or $\ge 2$ subset-sum solutions. | AI analyzes context to rank candidates. |
| `E13` | `ORPHAN_REFUND` | HIGH | Refund or credit note with no parent payment record. | Require analyst investigation. |
| `E14` | `UNBOOKED_CHARGEBACK` | HIGH | Dispute debit on bank statement not booked in GL. | Propose chargeback journal + dispute fee. |
| `E15` | `UNBALANCED_JOURNAL` | **CRITICAL** | General ledger transaction where Debits $\neq$ Credits. | Block period close. Escalate immediately. |
| `E16` | `UNCLASSIFIED` | MEDIUM | Residual that meets no deterministic rule conditions. | Mandatory AI triage + Human Review. |

### 11.2 Exception Lifecycle State Machine

```text
               ┌───────────────┐
               │   DETECTED    │
               └───────┬───────┘
                       │ P5 Classification
                       ▼
               ┌───────────────┐
         ┌────►│    TRIAGED    │◄────────────────┐
         │     └───────┬───────┘                 │
         │             │ Severity / Complexity   │
         │             ▼                         │
         │     ┌───────────────┐                 │
         │     │ INVESTIGATING │ (AI Agent Run)  │
         │     └───────┬───────┘                 │
         │             │ Proposal Generated      │
         │             ▼                         │
         │     ┌───────────────┐                 │
         │     │   PROPOSED    │                 │
         │     └───────┬───────┘                 │
         │             │ Verifier PASSED         │
         │             ▼                         │
         │     ┌───────────────────┐             │
         │     │ PENDING_APPROVAL  │             │
         │     └───┬───────────┬───┘             │
Reopened │         │           │                 │ Rejected
         │Approved │           │ Rejected        │
         │         ▼           ▼                 │
         │ ┌───────────────┐ ┌───────────────┐   │
         │ │   RESOLVED    │ │   REJECTED    ├───┘
         │ └───────┬───────┘ └───────┬───────┘
         │         │                 │
         │         ▼                 ▼
         │ ┌───────────────┐ ┌───────────────┐
         │ │    CLOSED     │ │   ESCALATED   │
         │ └───────────────┘ └───────────────┘
         └───────────────────────────────────────
```

### 11.3 State Transition Matrix

Every transition is executed within a transaction, incrementing `version` and emitting an immutable hash-chained audit event.

```python
ALLOWED_TRANSITIONS = {
    "DETECTED": ["TRIAGED", "ESCALATED"],
    "TRIAGED": ["INVESTIGATING", "RESOLVED", "ESCALATED"],
    "INVESTIGATING": ["PROPOSED", "ESCALATED", "TRIAGED"],
    "PROPOSED": ["PENDING_APPROVAL", "REJECTED"],
    "PENDING_APPROVAL": ["RESOLVED", "REJECTED", "ESCALATED"],
    "RESOLVED": ["CLOSED", "TRIAGED"], # Re-openable on audit dispute
    "REJECTED": ["TRIAGED", "ESCALATED", "CLOSED"],
    "ESCALATED": ["TRIAGED", "CLOSED"],
    "CLOSED": ["TRIAGED"], # Reopen requires Admin approval
    "SUPERSEDED": [] # Terminal state
}

def transition_exception_state(
    current_state: str,
    target_state: str,
    current_version: int
) -> bool:
    if target_state not in ALLOWED_TRANSITIONS.get(current_state, []):
        raise ValueError(f"Illegal state transition from {current_state} to {target_state}")
    return True
```

---

## 12. Declarative JSON Rules Engine Specification

To ensure auditability and dynamic configurability without code redeployments, all tolerances, fee formulas, and exception routing rules are declared in a structured JSON grammar.

### 12.1 Rule Grammar & Supported Operators

A rule consists of a list of `when` conditions (evaluated as logical `AND`) and a `then` action block.

| Operator | Syntax | Description | Example |
|---|---|---|---|
| `eq` | `{"field": f, "op": "eq", "value": v}` | Exact equality | `{"field": "currency", "op": "eq", "value": "INR"}` |
| `neq` | `{"field": f, "op": "neq", "value": v}` | Inequality | `{"field": "direction", "op": "neq", "value": "DEBIT"}` |
| `lt`, `lte` | `{"field": f, "op": "lt", "value": v}` | Less than / Less than or equal | `{"field": "abs_diff_minor", "op": "lte", "value": 100}` |
| `gt`, `gte` | `{"field": f, "op": "gt", "value": v}` | Greater than / Greater or equal | `{"field": "abs_diff_minor", "op": "gt", "value": 50000}` |
| `between` | `{"field": f, "op": "between", "value": [min, max]}` | Inclusive range | `{"field": "diff_pct_of_gross", "op": "between", "value": [0.015, 0.025]}` |
| `in` | `{"field": f, "op": "in", "value": [...]}` | Set membership | `{"field": "source_kind", "op": "in", "value": ["GATEWAY", "BANK"]}` |
| `pct_of` | `{"field": f, "op": "pct_of", "base": b, "max_pct": p}` | Relative percentage bound | `{"field": "abs_diff_minor", "op": "pct_of", "base": "gross_minor", "max_pct": 0.02}` |
| `days_between`| `{"field": f1, "op": "days_between", "target": f2, "max_days": d}`| Date distance | `{"field": "value_date", "op": "days_between", "target": "occurred_at", "max_days": 3}` |
| `regex_match` | `{"field": f, "op": "regex_match", "pattern": r}` | Regular expression match | `{"field": "description_raw", "op": "regex_match", "pattern": "^NEFT-"}` |

### 12.2 Python Rules Engine Implementation

```python
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

class RuleEvaluator:
    """Zero-dependency, deterministic rule evaluator over typed contexts."""

    @staticmethod
    def evaluate_condition(cond: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
        field = cond.get("field")
        op = cond.get("op")
        expected = cond.get("value")
        actual = ctx.get(field)

        if op == "eq":
            return actual == expected
        elif op == "neq":
            return actual != expected
        elif op == "lt":
            return actual is not None and actual < expected
        elif op == "lte":
            return actual is not None and actual <= expected
        elif op == "gt":
            return actual is not None and actual > expected
        elif op == "gte":
            return actual is not None and actual >= expected
        elif op == "between":
            return actual is not None and expected[0] <= actual <= expected[1]
        elif op == "in":
            return actual in expected
        elif op == "pct_of":
            base_val = ctx.get(cond["base"], 0)
            if base_val == 0:
                return False
            pct = abs(float(actual or 0) / float(base_val))
            return pct <= cond["max_pct"]
        elif op == "days_between":
            d1 = ctx.get(field)
            d2 = ctx.get(cond["target"])
            if not isinstance(d1, (date, datetime)) or not isinstance(d2, (date, datetime)):
                return False
            delta = abs((d1 - d2).days) if isinstance(d1, date) and isinstance(d2, date) else abs((d1.date() - d2.date()).days)
            return delta <= cond["max_days"]
        elif op == "regex_match":
            if not actual or not isinstance(actual, str):
                return False
            return bool(re.search(cond["pattern"], actual, re.IGNORECASE))
        return False

    @classmethod
    def evaluate_rule(cls, rule: Dict[str, Any], ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        conditions = rule.get("when", [])
        for cond in conditions:
            if not cls.evaluate_condition(cond, ctx):
                return None
        return rule.get("then")
```

### 12.3 Canonical Standard Finance Rules

```json
[
  {
    "id": "R-FEE-RAZORPAY-STD",
    "name": "Standard Razorpay Fee Discrepancy",
    "when": [
      {"field": "source_kind", "op": "eq", "value": "GATEWAY"},
      {"field": "abs_diff_minor", "op": "between", "value": [1, 50000]},
      {"field": "diff_pct_of_gross", "op": "between", "value": [0.0190, 0.0240]}
    ],
    "then": {
      "classification": "FEE_DISCREPANCY",
      "severity": "LOW",
      "auto_resolve": true,
      "target_account": "5110 Payment Processing Fees"
    }
  },
  {
    "id": "R-MAT-WRITE-OFF",
    "name": "Immaterial Rounding Variance Write-Off",
    "when": [
      {"field": "abs_diff_minor", "op": "lte", "value": 100},
      {"field": "currency", "op": "eq", "value": "INR"}
    ],
    "then": {
      "classification": "IMMATERIAL_VARIANCE",
      "severity": "LOW",
      "auto_resolve": true,
      "target_account": "6990 Rounding & Suspense"
    }
  },
  {
    "id": "R-TIMING-CUTOFF",
    "name": "Month-End Timing Cutoff Grace",
    "when": [
      {"field": "days_lag", "op": "between", "value": [1, 3]},
      {"field": "is_period_boundary", "op": "eq", "value": true}
    ],
    "then": {
      "classification": "TIMING_DIFFERENCE",
      "severity": "LOW",
      "auto_resolve": true,
      "target_account": "1290 In-Transit Clearing"
    }
  },
  {
    "id": "R-CRIT-UNBALANCED",
    "name": "Unbalanced Journal Critical Escalation",
    "when": [
      {"field": "source_kind", "op": "eq", "value": "LEDGER"},
      {"field": "debit_credit_diff_minor", "op": "neq", "value": 0}
    ],
    "then": {
      "classification": "UNBALANCED_JOURNAL",
      "severity": "CRITICAL",
      "auto_resolve": false,
      "escalation_target": "FINANCE_DIRECTOR"
    }
  }
]
```

---

## 13. Maker-Checker Approval Workflow & Segregation of Duties

The defining control of any financial operations system is **Maker-Checker** (four-eyes principle). The system strictly enforces the following governance matrix:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                    APPROVAL POLICY ROUTING MATRIX                      │
│                                                                        │
│  Exception Resolution Proposal                                         │
│  ├── Financial Impact (Paise)                                          │
│  ├── Confidence Score (Isotonic calibrated)                            │
│  └── Exception Classification                                          │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ DECISION LOGIC:                                                  │  │
│  │ 1. Impact <= ₹500 AND Confidence >= 0.93 AND Auto-Policy Enabled  │  │
│  │    ──► AUTO-APPLY (Actor: System, Zero Human Wait)               │  │
│  │                                                                  │  │
│  │ 2. Impact <= ₹10,000 OR Standard Fee/Timing                      │  │
│  │    ──► ANALYST REVIEW (Single Maker-Checker Approval)            │  │
│  │                                                                  │  │
│  │ 3. Impact > ₹10,000 AND <= ₹1,00,000                             │  │
│  │    ──► APPROVER ROLE (Senior Controller Sign-Off)                │  │
│  │                                                                  │  │
│  │ 4. Impact > ₹1,00,000 OR Exception == CRITICAL                   │  │
│  │    ──► ADMIN / DUAL APPROVAL (2 Distinct Authorizers Required)   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

### 13.1 Strict Segregation Invariants
1. **Agent Identity Isolation:** The AI agent (`actor_type='agent'`) can only generate proposals (`resolution_proposals`). It has 0 capabilities to approve or apply them.
2. **Authorizer Segregation:** A user who manually created or modified a proposal cannot approve it.
3. **Immutability of Decisions:** Once an approval or rejection is recorded in `approvals`, the row can never be altered or deleted.
