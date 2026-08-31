import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

DEFAULT_RULES = [
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
            "auto_resolve": True,
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
            "auto_resolve": True,
            "target_account": "6990 Rounding & Suspense"
        }
    },
    {
        "id": "R-TIMING-CUTOFF",
        "name": "Month-End Timing Cutoff Grace",
        "when": [
            {"field": "days_lag", "op": "between", "value": [1, 3]},
            {"field": "is_period_boundary", "op": "eq", "value": True}
        ],
        "then": {
            "classification": "TIMING_DIFFERENCE",
            "severity": "LOW",
            "auto_resolve": True,
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
            "auto_resolve": False,
            "escalation_target": "FINANCE_DIRECTOR"
        }
    }
]

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
            d1_date = d1 if isinstance(d1, date) and not isinstance(d1, datetime) else d1.date()
            d2_date = d2 if isinstance(d2, date) and not isinstance(d2, datetime) else d2.date()
            delta = abs((d1_date - d2_date).days)
            return delta <= cond["max_days"]
        elif op == "regex_match":
            if not actual or not isinstance(actual, str):
                return False
            return bool(re.search(cond["pattern"], actual, re.IGNORECASE))
        return False

    @classmethod
    def evaluate_rules(cls, rules: List[Dict[str, Any]], ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Evaluates rules in priority order. Returns the first matching rule's action."""
        for rule in rules:
            conditions = rule.get("when", [])
            match = True
            for cond in conditions:
                if not cls.evaluate_condition(cond, ctx):
                    match = False
                    break
            if match:
                action = rule.get("then", {}).copy()
                action["rule_id"] = rule.get("id")
                return action
        return None
