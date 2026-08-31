# 07 — Synthetic Data Generator & Evaluation Benchmark Suite

## 21. Realistic Synthetic Data Generator Specification

To satisfy the core requirement of **"throughput plus measured accuracy plus an honest exception list"**, the testing harness generates **2,000+ realistic multi-source transaction records** paired with an immutable **Ground Truth Link Manifest**.

```text
┌────────────────────────────────────────────────────────────────────────┐
│                   SYNTHETIC DATA GENERATION PIPELINE                   │
│                                                                        │
│  [ Ground Truth Scenario Generator ]                                  │
│  ├── 1,400 Clean 1:1 Payments (UPI, Cards, NetBanking)                │
│  ├── 450 N:1 Settlement Batches (Net of 2% MDR + 18% GST)              │
│  ├── 50 Split Refunds & Chargebacks                                    │
│  ├── 60 Timing Cutoff Differences (Month-end T+2 crossing)             │
│  └── 40 Injected Financial Anomalies & Errors                          │
│                                                                        │
│       │                                                        │       │
│       ▼                                                        ▼       │
│  [ Ingestion Files (Emitted) ]                    [ Ground Truth Manifest ]
│  ├── 1. gateway_export.json                       └── ground_truth_links.json
│  ├── 2. bank_statement.csv                            (Explicit link pairs,
│  ├── 3. general_ledger.csv                             expected scores &
│  └── 4. settlement_report.json                         exception types)
└────────────────────────────────────────────────────────────────────────┘
```

### 21.1 Generated Data Structure & Scenarios

1. **Clean 1:1 Payments (~70%):** Standard customer charges matching invoices in the GL with exact reference keys.
2. **N:1 Settlement Bundles (~20%):** Gateway payments grouped into daily settlement wires. Bank amounts equal $\sum \text{Gross} - \sum \text{MDR} - \sum \text{GST} - \text{Refunds}$.
3. **Timing Cutoffs (~3%):** Charges captured on March 31st that settle in the bank on April 2nd.
4. **Controlled Anomalies & Residuals (~7%):**
   - *Duplicate Records:* Identical bank statement lines.
   - *Fee Discrepancies:* Undocumented surcharge or fee tier mismatch.
   - *Amount Mismatches:* Minor unit rounding errors or manual bookkeeper entry errors.
   - *Missing Bank Records:* Captured gateway payments that were delayed or failed bank transmission.
   - *Orphan Refunds:* Customer refunds with no matching original debit.
   - *Unbalanced Journals:* GL entry where Debits $\neq$ Credits.

### 21.2 Synthetic Generator Implementation (Python)

```python
import json
import random
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List

class SyntheticDataGenerator:
    def __init__(self, seed: int = 42):
        random.seed(seed)
        self.gateway_records = []
        self.bank_records = []
        self.ledger_records = []
        self.settlement_records = []
        self.ground_truth_links = []

    def generate_dataset(self, total_payments: int = 2000):
        start_date = datetime(2026, 3, 25, 0, 0, 0)
        
        # 1. Generate 37-payment Settlement Batch
        setl_id = "setl_9KA22"
        utr_no = "N2604029912"
        setl_gross = 0
        setl_fees = 0
        setl_tax = 0
        
        for i in range(37):
            amt = random.choice([59000, 118000, 236000, 500000]) # paise
            fee = int(amt * 0.02) # 2% MDR
            tax = int(fee * 0.18) # 18% GST
            setl_gross += amt
            setl_fees += fee
            setl_tax += tax
            
            pay_id = f"pay_L{random.randint(100000, 999999)}"
            inv_id = f"INV-2026-{1000 + i}"
            
            gw_row = {
                "payment_id": pay_id,
                "order_id": f"ord_{random.randint(10000, 99999)}",
                "amount": amt,
                "currency": "INR",
                "fee": fee,
                "tax": tax,
                "status": "captured",
                "method": "upi",
                "captured_at": (start_date + timedelta(hours=i)).isoformat(),
                "settlement_id": setl_id,
                "customer_email": f"user{i}@acme.co",
                "description": f"Invoice {inv_id}"
            }
            self.gateway_records.append(gw_row)
            
            # Matching GL Journal Entry
            self.ledger_records.extend([
                {"je_id": f"JE-{4000+i}", "line_no": 1, "posted_at": "2026-03-31", "account_code": "1210", "account_name": "Gateway Receivable", "debit": amt / 100.0, "credit": None, "memo": f"UPI capture {inv_id}", "doc_ref": inv_id},
                {"je_id": f"JE-{4000+i}", "line_no": 2, "posted_at": "2026-03-31", "account_code": "4010", "account_name": "Revenue - SaaS", "debit": None, "credit": (amt - (amt * 18 // 118)) / 100.0, "memo": f"Rev {inv_id}", "doc_ref": inv_id},
                {"je_id": f"JE-{4000+i}", "line_no": 3, "posted_at": "2026-03-31", "account_code": "2310", "account_name": "GST Output", "debit": None, "credit": (amt * 18 // 118) / 100.0, "memo": f"GST {inv_id}", "doc_ref": inv_id},
            ])

        setl_net = setl_gross - setl_fees - setl_tax
        
        # Bank Statement Settlement Credit
        self.bank_records.append({
            "Txn Date": "02/04/2026",
            "Value Date": "02/04/2026",
            "Description": f"NEFT-RAZORPAY SOFTWARE PVT-SETL9KA22-CR",
            "Debit": None,
            "Credit": setl_net / 100.0,
            "Balance": 2914773.10,
            "Ref No": utr_no
        })

        # Ground truth link
        self.ground_truth_links.append({
            "scenario": "N_TO_ONE_SETTLEMENT",
            "settlement_id": setl_id,
            "bank_ref": utr_no,
            "payment_count": 37,
            "gross_paise": setl_gross,
            "net_paise": setl_net,
            "expected_method": "NET_SETTLEMENT"
        })

        return {
            "gateway_records": self.gateway_records,
            "bank_records": self.bank_records,
            "ledger_records": self.ledger_records,
            "ground_truth_links": self.ground_truth_links
        }
```

---

## 22. Evaluation Benchmark Suite & Metrics

The system's performance is rigorously evaluated across four quantitative dimensions:

### 22.1 Evaluation Metric Formulations

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        BENCHMARK EVALUATION BAR                        │
│                                                                        │
│  1. Match Accuracy (Against Ground Truth Manifest)                     │
│     • Precision: TP / (TP + FP)  ──► Target: >= 99.0%                  │
│     • Recall:    TP / (TP + FN)  ──► Target: >= 95.0%                  │
│     • F1-Score:  2 * (P * R) / (P + R) ──► Target: >= 97.0%            │
│                                                                        │
│  2. Pipeline Throughput & Latency                                      │
│     • Deterministic Throughput: >= 300 records / second                │
│     • End-to-End Wall-Clock (2,000 txns): <= 15 seconds               │
│                                                                        │
│  3. Confidence Calibration                                             │
│     • Expected Calibration Error (ECE): <= 0.05                        │
│     • Brier Score: (1/N) * sum((confidence_i - is_correct_i)^2)       │
│                                                                        │
│  4. AI Safety & Cost Envelope                                          │
│     • Deterministic Verifier Rejection Rate: <= 2.0%                   │
│     • Tool Error Rate: 0.0%                                            │
│     • Mean Cost per Batch: <= ₹5.00 INR (Anthropic prompt cached)      │
└────────────────────────────────────────────────────────────────────────┘
```

### 22.2 Python Benchmark Evaluation Runner

```python
from decimal import Decimal
from typing import Any, Dict, List
import numpy as np

class BenchmarkEvaluator:
    """Calculates precision, recall, F1, and Expected Calibration Error."""

    @staticmethod
    def compute_calibration_error(confidences: List[float], outcomes: List[int], num_bins: int = 10) -> float:
        """Computes Expected Calibration Error (ECE) across N confidence bins"""
        conf_arr = np.array(confidences)
        out_arr = np.array(outcomes)
        bins = np.linspace(0.0, 1.0, num_bins + 1)
        ece = 0.0
        n = len(confidences)

        for i in range(num_bins):
            bin_lower, bin_upper = bins[i], bins[i + 1]
            in_bin = (conf_arr > bin_lower) & (conf_arr <= bin_upper)
            bin_size = np.sum(in_bin)
            
            if bin_size > 0:
                bin_acc = np.mean(out_arr[in_bin])
                bin_conf = np.mean(conf_arr[in_bin])
                ece += (bin_size / n) * abs(bin_acc - bin_conf)

        return float(ece)

    @classmethod
    def evaluate_reconciliation_run(
        cls,
        matched_pairs: List[Dict[str, Any]],
        ground_truth: List[Dict[str, Any]],
        wall_clock_seconds: float
    ) -> Dict[str, Any]:
        """Calculates benchmark metrics against ground truth manifest"""
        gt_pairs = {(gt["source_id"], gt["target_id"]) for gt in ground_truth}
        pred_pairs = {(m["source_id"], m["target_id"]) for m in matched_pairs}

        tp = len(pred_pairs.intersection(gt_pairs))
        fp = len(pred_pairs - gt_pairs)
        fn = len(gt_pairs - pred_pairs)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

        confidences = [m["confidence"] for m in matched_pairs]
        outcomes = [1 if (m["source_id"], m["target_id"]) in gt_pairs else 0 for m in matched_pairs]
        ece = cls.compute_calibration_error(confidences, outcomes) if confidences else 0.0

        total_txns = len(ground_truth)
        records_per_sec = total_txns / wall_clock_seconds if wall_clock_seconds > 0 else 0.0

        return {
            "total_records": total_txns,
            "wall_clock_seconds": round(wall_clock_seconds, 2),
            "records_per_second": round(records_per_sec, 2),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1_score": round(f1, 4),
            "expected_calibration_error": round(ece, 4),
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn
        }
```
