"""
Ground-Truth Dataset Generator (2,000+ Records) for Empirical Accuracy & ECE Calibration Evaluation
Generates synthetic multi-feed financial transactions with verifiable ground-truth link labels.
"""

import json
import os
import random
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Tuple

from app.models.schemas import SourceKind, TxnDirection


def generate_dataset_2000(output_path: str = "data/benchmark_2000.json") -> Dict[str, Any]:
    random.seed(42)  # Deterministic seed for reproducible evaluation
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    base_date = date(2026, 3, 1)
    transactions: List[Dict[str, Any]] = []
    ground_truth_links: List[Dict[str, Any]] = []

    gw_count = 0
    bk_count = 0
    gl_count = 0

    # 1. Generate 500 Exact 1:1 Triplet Sets (1,500 transactions: 500 GW, 500 Bank, 500 Ledger)
    for i in range(1, 501):
        amt_rs = random.randint(50, 5000)
        amt_minor = amt_rs * 100
        days_offset = random.randint(0, 25)
        txn_date = base_date + timedelta(days=days_offset)
        iso_ts = datetime(txn_date.year, txn_date.month, txn_date.day, 10, 0, 0, tzinfo=timezone.utc).isoformat()

        inv_id = f"INV-2026-{i:05d}"
        pay_id = f"PAY-2026-{i:05d}"
        utr_id = f"UTR-2026-{i:05d}"
        je_id = f"JE-2026-{i:05d}"

        gw_id = f"gw_{i:05d}"
        bk_id = f"bk_{i:05d}"
        gl_id = f"gl_{i:05d}"

        # Gateway transaction
        transactions.append({
            "id": gw_id,
            "source_kind": "GATEWAY",
            "external_id": pay_id,
            "amount_minor": amt_minor,
            "currency": "INR",
            "direction": "INFLOW",
            "occurred_at": iso_ts,
            "value_date": txn_date.isoformat(),
            "description_raw": f"Online subscription payment {inv_id} via {pay_id}",
            "description_norm": f"online subscription payment {inv_id.lower()} via {pay_id.lower()}",
            "counterparty_raw": "Acme Customer",
            "counterparty_norm": "acme customer",
            "account_code": "1200",
            "reference_keys": {"invoice": [inv_id], "payment": [pay_id], "utr": [], "order": [], "je": [], "settlement": []}
        })

        # Bank statement
        transactions.append({
            "id": bk_id,
            "source_kind": "BANK",
            "external_id": utr_id,
            "amount_minor": amt_minor,
            "currency": "INR",
            "direction": "INFLOW",
            "occurred_at": iso_ts,
            "value_date": txn_date.isoformat(),
            "description_raw": f"NEFT CR {pay_id} {inv_id} {utr_id}",
            "description_norm": f"payment cr {pay_id.lower()} {inv_id.lower()} {utr_id.lower()}",
            "counterparty_raw": "HDFC BANK",
            "counterparty_norm": "hdfc bank",
            "account_code": "1010",
            "reference_keys": {"invoice": [inv_id], "payment": [pay_id], "utr": [utr_id], "order": [], "je": [], "settlement": []}
        })

        # General ledger journal entry
        transactions.append({
            "id": gl_id,
            "source_kind": "LEDGER",
            "external_id": f"{je_id}:1",
            "amount_minor": amt_minor,
            "currency": "INR",
            "direction": "INFLOW",
            "occurred_at": iso_ts,
            "value_date": txn_date.isoformat(),
            "description_raw": f"Bank settlement receipt for invoice {inv_id}",
            "description_norm": f"bank settlement receipt for invoice {inv_id.lower()}",
            "counterparty_raw": "CUSTOMER_RECEIVABLES",
            "counterparty_norm": "customer receivables",
            "account_code": "1010",
            "reference_keys": {"invoice": [inv_id], "payment": [pay_id], "utr": [], "order": [], "je": [je_id], "settlement": []}
        })

        # Ground truth links
        ground_truth_links.append({"source_id": gw_id, "target_id": bk_id, "type": "EXACT_1_TO_1"})

    gw_count += 500
    bk_count += 500
    gl_count += 500

    # 2. Generate 100 Contextual Fee Matches (200 records: 100 Gateway, 100 Bank net of 2.0% MDR + 18% GST)
    for j in range(1, 101):
        idx = 500 + j
        gross_rs = random.randint(100, 10000)
        gross_minor = gross_rs * 100
        # 2% MDR + 18% GST -> 2.36% deduction
        mdr_fee = int(Decimal(str(gross_minor)) * Decimal("0.020"))
        gst_tax = int(Decimal(str(mdr_fee)) * Decimal("0.180"))
        net_minor = gross_minor - mdr_fee - gst_tax

        days_offset = random.randint(0, 25)
        txn_date = base_date + timedelta(days=days_offset)
        iso_ts = datetime(txn_date.year, txn_date.month, txn_date.day, 14, 0, 0, tzinfo=timezone.utc).isoformat()

        inv_id = f"INV-2026-FEE-{j:04d}"
        pay_id = f"PAY-2026-FEE-{j:04d}"
        utr_id = f"UTR-2026-FEE-{j:04d}"

        gw_id = f"gw_fee_{j:04d}"
        bk_id = f"bk_fee_{j:04d}"

        # Gateway transaction (Gross)
        transactions.append({
            "id": gw_id,
            "source_kind": "GATEWAY",
            "external_id": pay_id,
            "amount_minor": gross_minor,
            "currency": "INR",
            "direction": "INFLOW",
            "occurred_at": iso_ts,
            "value_date": txn_date.isoformat(),
            "description_raw": f"Razorpay checkout {inv_id} {pay_id}",
            "description_norm": f"razorpay checkout {inv_id.lower()} {pay_id.lower()}",
            "counterparty_raw": "Razorpay PG",
            "counterparty_norm": "razorpay pg",
            "account_code": "1200",
            "reference_keys": {"invoice": [inv_id], "payment": [pay_id], "utr": [], "order": [], "je": [], "settlement": []}
        })

        # Bank transaction (Net)
        transactions.append({
            "id": bk_id,
            "source_kind": "BANK",
            "external_id": utr_id,
            "amount_minor": net_minor,
            "currency": "INR",
            "direction": "INFLOW",
            "occurred_at": iso_ts,
            "value_date": txn_date.isoformat(),
            "description_raw": f"Razorpay Settlement Net of MDR {pay_id} {inv_id}",
            "description_norm": f"razorpay settlement net of mdr {pay_id.lower()} {inv_id.lower()}",
            "counterparty_raw": "RAZORPAY SOFTWARE",
            "counterparty_norm": "razorpay software",
            "account_code": "1010",
            "reference_keys": {"invoice": [inv_id], "payment": [pay_id], "utr": [utr_id], "order": [], "je": [], "settlement": []}
        })

        ground_truth_links.append({"source_id": gw_id, "target_id": bk_id, "type": "CONTEXTUAL_FEE_2PCT"})

    gw_count += 100
    bk_count += 100

    # 3. Generate 50 N:1 Settlement Batches (4 payments each = 200 GW txns + 50 Bank credits = 250 records)
    for k in range(1, 51):
        setl_key = f"SETL-2026-N1-{k:04d}"
        days_offset = random.randint(0, 24)
        txn_date = base_date + timedelta(days=days_offset)
        bank_date = txn_date + timedelta(days=2) # T+2 settlement

        gw_items = []
        total_gross = 0
        total_net = 0

        for p_idx in range(1, 5):
            p_rs = random.randint(200, 3000)
            p_minor = p_rs * 100
            total_gross += p_minor

            fee = int(Decimal(str(p_minor)) * Decimal("0.020"))
            tax = int(Decimal(str(fee)) * Decimal("0.180"))
            p_net = p_minor - fee - tax
            total_net += p_net

            p_id = f"PAY-N1-{k:04d}-{p_idx}"
            inv_id = f"INV-N1-{k:04d}-{p_idx}"
            gw_id = f"gw_n1_{k:04d}_{p_idx}"

            transactions.append({
                "id": gw_id,
                "source_kind": "GATEWAY",
                "external_id": p_id,
                "amount_minor": p_minor,
                "currency": "INR",
                "direction": "INFLOW",
                "occurred_at": datetime(txn_date.year, txn_date.month, txn_date.day, 12, p_idx * 10, 0, tzinfo=timezone.utc).isoformat(),
                "value_date": txn_date.isoformat(),
                "description_raw": f"Grouped batch payment {inv_id} for batch {setl_key}",
                "description_norm": f"grouped batch payment {inv_id.lower()} for batch {setl_key.lower()}",
                "counterparty_raw": "Razorpay PG",
                "counterparty_norm": "razorpay pg",
                "account_code": "1200",
                "reference_keys": {"invoice": [inv_id], "payment": [p_id], "utr": [], "order": [], "je": [], "settlement": [setl_key]}
            })
            gw_items.append(gw_id)

        bk_id = f"bk_n1_{k:04d}"
        utr_id = f"UTR-N1-{k:04d}"
        transactions.append({
            "id": bk_id,
            "source_kind": "BANK",
            "external_id": utr_id,
            "amount_minor": total_net,
            "currency": "INR",
            "direction": "INFLOW",
            "occurred_at": datetime(bank_date.year, bank_date.month, bank_date.day, 16, 0, 0, tzinfo=timezone.utc).isoformat(),
            "value_date": bank_date.isoformat(),
            "description_raw": f"Settlement Batch Credit {setl_key} {utr_id}",
            "description_norm": f"settlement batch credit {setl_key.lower()} {utr_id.lower()}",
            "counterparty_raw": "RAZORPAY",
            "counterparty_norm": "razorpay",
            "account_code": "1010",
            "reference_keys": {"invoice": [], "payment": [], "utr": [utr_id], "order": [], "je": [], "settlement": [setl_key]}
        })

        for g_id in gw_items:
            ground_truth_links.append({"source_id": g_id, "target_id": bk_id, "type": "N_TO_1_SETTLEMENT"})

    gw_count += 200
    bk_count += 50

    # 4. Generate 50 Cutoff Timing Differences (50 records, no bank credit in current month)
    for c in range(1, 51):
        cutoff_date = date(2026, 3, 31)
        amt_minor = random.randint(100, 2000) * 100
        inv_id = f"INV-2026-CUT-{c:04d}"
        pay_id = f"PAY-2026-CUT-{c:04d}"
        gw_id = f"gw_cut_{c:04d}"

        transactions.append({
            "id": gw_id,
            "source_kind": "GATEWAY",
            "external_id": pay_id,
            "amount_minor": amt_minor,
            "currency": "INR",
            "direction": "INFLOW",
            "occurred_at": "2026-03-31T23:45:00+00:00",
            "value_date": "2026-03-31",
            "description_raw": f"End of period cutoff subscription {inv_id}",
            "description_norm": f"end of period cutoff subscription {inv_id.lower()}",
            "counterparty_raw": "Acme Direct",
            "counterparty_norm": "acme direct",
            "account_code": "1200",
            "reference_keys": {"invoice": [inv_id], "payment": [pay_id], "utr": [], "order": [], "je": [], "settlement": []}
        })
    gw_count += 50

    dataset_payload = {
        "metadata": {
            "name": "Financial Controller Empirical Ground Truth Benchmark (2,000+)",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_transactions": len(transactions),
            "gateway_count": gw_count,
            "bank_count": bk_count,
            "ledger_count": gl_count,
            "total_ground_truth_links": len(ground_truth_links)
        },
        "transactions": transactions,
        "ground_truth_links": ground_truth_links
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset_payload, f, indent=2)

    return dataset_payload


if __name__ == "__main__":
    data = generate_dataset_2000()
    print(f"Generated {data['metadata']['total_transactions']} transactions with {data['metadata']['total_ground_truth_links']} verifiable ground-truth links.")
