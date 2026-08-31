"""
Quality-First Synthetic Financial Dataset Generator (240 Records)
Generates multi-source records (Gateway, Bank, Ledger, Settlement) with 12 realistic
financial topologies: Clean 1:1, MDR 2.0% & 1.5% splits, T+2 period cutoffs, N:1 netting,
duplicate ingestion, missing settlements, partial settlements, anonymous bank lines, and reversals.
"""

import random
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional, Tuple

class SyntheticDataGenerator:
    """Generates 240 structured, multi-source financial records with ground truth links."""

    def __init__(self, seed: int = 42, execution_mode: Optional[Any] = None):
        if execution_mode is not None:
            mode_str = execution_mode.value if hasattr(execution_mode, "value") else str(execution_mode)
            if mode_str == "USER_UPLOAD":
                raise RuntimeError("Synthetic data is forbidden during USER_UPLOAD execution")
        random.seed(seed)
        self.seed = seed
        self.gateway_records: List[Dict[str, Any]] = []
        self.bank_records: List[Dict[str, Any]] = []
        self.ledger_records: List[Dict[str, Any]] = []
        self.settlement_records: List[Dict[str, Any]] = []
        self.ground_truth_links: List[Dict[str, Any]] = []

    def generate(self, count: int = 240, execution_mode: Optional[Any] = None) -> Dict[str, Any]:
        """Generates the master 240-record dataset."""
        if execution_mode is not None:
            mode_str = execution_mode.value if hasattr(execution_mode, "value") else str(execution_mode)
            if mode_str == "USER_UPLOAD":
                raise RuntimeError("Synthetic data is forbidden during USER_UPLOAD execution")
        self.gateway_records.clear()
        self.bank_records.clear()
        self.ledger_records.clear()
        self.settlement_records.clear()
        self.ground_truth_links.clear()

        # Amounts pool in paise (INR minor units)
        amounts = [49900, 99900, 118000, 149900, 236000, 500000, 850000]

        # ---------------------------------------------------------------------
        # 0. Test Case 2 - MDR Fee Match (pay_1002)
        # ---------------------------------------------------------------------
        self.gateway_records.append({
            "payment_id": "pay_1002",
            "order_id": "ord_1002",
            "amount": 1000000, # 10,000 INR in paise
            "currency": "INR",
            "fee": 20000, # 2% = 200 INR
            "tax": 3600, # 18% on fee = 36 INR
            "status": "captured",
            "method": "card",
            "captured_at": "2026-03-25T14:30:00+05:30",
            "customer_email": "test@acme.co",
            "description": "Test Case MDR Fee Match pay_1002"
        })
        
        self.bank_records.append({
            "txn_id": "BANK-TEST-1002",
            "txn_date": "2026-03-25",
            "value_date": "2026-03-25",
            "description": "NEFT-RAZORPAY-pay_1002-CR",
            "credit": 9764.0, # 9,764 INR
            "debit": None,
            "balance": 100000.0,
            "ref_no": "pay_1002"
        })

        self.ledger_records.append({
            "je_id": "JE-1002-REV",
            "line_no": 1,
            "posted_at": "2026-03-25",
            "account_code": "4000",
            "account_name": "Revenue",
            "debit": None,
            "credit": 10000.0, # 10,000 INR
            "memo": "Revenue pay_1002",
            "doc_ref": "pay_1002"
        })
        self.ledger_records.append({
            "je_id": "JE-1002-FEE",
            "line_no": 2,
            "posted_at": "2026-03-25",
            "account_code": "5010",
            "account_name": "Processing Fee",
            "debit": 236.0, # 236 INR
            "credit": None,
            "memo": "Fee pay_1002",
            "doc_ref": "pay_1002"
        })
        self.ledger_records.append({
            "je_id": "JE-1002-BANK",
            "line_no": 3,
            "posted_at": "2026-03-25",
            "account_code": "1000",
            "account_name": "Bank",
            "debit": 9764.0, # 9,764 INR
            "credit": None,
            "memo": "Bank pay_1002",
            "doc_ref": "pay_1002"
        })

        # ---------------------------------------------------------------------
        # 1. Clean 1:1 Invoices (60 Gateway Payments + 60 GL Control Lines = 120 recs)
        # ---------------------------------------------------------------------
        for i in range(1, 61):
            inv_id = f"INV-2026-{1000 + i}"
            pay_id = f"pay_G8x{i:04d}"
            ord_id = f"ord_99{i:04d}"
            amt = random.choice(amounts)
            fee = round(amt * 0.02)
            tax = round(fee * 0.18)

            gw_row = {
                "payment_id": pay_id,
                "order_id": ord_id,
                "amount": amt,
                "currency": "INR",
                "fee": fee,
                "tax": tax,
                "status": "captured",
                "method": "upi",
                "captured_at": "2026-03-25T14:30:00+05:30",
                "customer_email": f"customer_{i}@acme.co",
                "description": f"Invoice {inv_id} subscription fee"
            }
            self.gateway_records.append(gw_row)

            gl_row = {
                "je_id": f"JE-{5000 + i}",
                "line_no": 1,
                "posted_at": "2026-03-25",
                "account_code": "1210",
                "account_name": "Gateway Receivable",
                "debit": amt / 100.0,
                "credit": None,
                "memo": f"UPI capture for {inv_id}",
                "doc_ref": inv_id
            }
            self.ledger_records.append(gl_row)

            self.ground_truth_links.append({
                "type": "1:1_CLEAN",
                "source_id": pay_id,
                "target_id": f"JE-{5000 + i}_1",
                "key": inv_id
            })

        # ---------------------------------------------------------------------
        # 2. MDR Fee Discrepancies (30 Records: 15 Gateway + 15 GL Entries)
        # ---------------------------------------------------------------------
        for i in range(1, 16):
            inv_id = f"INV-2026-{2000 + i}"
            pay_id = f"pay_FEE{i:04d}"
            amt = 236000 # ₹2,360.00
            
            # Enterprise 1.5% tier vs Standard 2.0% tier
            if i <= 10:
                fee = round(amt * 0.015)
                tax = round(fee * 0.18)
                tier_desc = "Enterprise Tier (1.5% MDR)"
            else:
                fee = round(amt * 0.02)
                tax = round(fee * 0.18)
                tier_desc = "Standard Tier (2.0% MDR)"

            gw_row = {
                "payment_id": pay_id,
                "order_id": f"ord_FEE{i:04d}",
                "amount": amt,
                "currency": "INR",
                "fee": fee,
                "tax": tax,
                "status": "captured",
                "method": "card",
                "captured_at": "2026-03-28T10:15:00+05:30",
                "description": f"Invoice {inv_id} [{tier_desc}]"
            }
            self.gateway_records.append(gw_row)

            # GL booked net of fee
            gl_row = {
                "je_id": f"JE-FEE-{i}",
                "line_no": 1,
                "posted_at": "2026-03-28",
                "account_code": "1210",
                "account_name": "Gateway Receivable",
                "debit": (amt - fee - tax) / 100.0, # Booked net variance!
                "credit": None,
                "memo": f"Card payment for {inv_id}",
                "doc_ref": inv_id
            }
            self.ledger_records.append(gl_row)

        # ---------------------------------------------------------------------
        # 3. T+2 Period Boundary Lag (25 Records: 15 Gateway + 10 Bank entries)
        # ---------------------------------------------------------------------
        for i in range(1, 16):
            inv_id = f"INV-2026-0412" if i == 1 else f"INV-2026-{3000 + i}"
            pay_id = f"pay_CUTOFF_{i:03d}"
            amt = 118000 # ₹1,180.00
            
            gw_row = {
                "payment_id": pay_id,
                "order_id": f"ord_CUT_{i}",
                "amount": amt,
                "currency": "INR",
                "fee": 2360,
                "tax": 425,
                "status": "captured",
                "method": "upi",
                "captured_at": "2026-03-31T23:58:12+05:30", # Captured 2 min before period end!
                "settlement_id": f"setl_9KA{i:02d}",
                "description": f"Invoice {inv_id} T+2 settlement lag"
            }
            self.gateway_records.append(gw_row)

            if i <= 10:
                # Bank credits in subsequent period (April 2, 2026)
                net = amt - 2360 - 425
                bk_row = {
                    "txn_id": f"BANK-CUT-{i:03d}",
                    "txn_date": "2026-04-02",
                    "value_date": "2026-04-02",
                    "description": f"NEFT-RAZORPAY SOFTWARE-SETL9KA{i:02d}-CR",
                    "credit": net / 100.0,
                    "debit": None,
                    "balance": 8450000.0,
                    "ref_no": f"UTR-CUT-{i:04d}"
                }
                self.bank_records.append(bk_row)

        # ---------------------------------------------------------------------
        # 4. N:1 Bulk Settlement Batches (40 Gateway Txns netted into 2 Bank Wires = 42 recs)
        # ---------------------------------------------------------------------
        for s_idx in range(1, 3):
            setl_id = f"SETL-BULK-{s_idx:02d}"
            setl_gross = 0
            setl_fees = 0
            setl_tax = 0

            for j in range(1, 21):
                p_id = f"pay_BLK{s_idx}_{j:02d}"
                amt = 50000 # ₹500.00
                fee = 1000  # ₹10.00
                tax = 180   # ₹1.80
                setl_gross += amt
                setl_fees += fee
                setl_tax += tax

                self.gateway_records.append({
                    "payment_id": p_id,
                    "order_id": f"ord_BLK{s_idx}_{j:02d}",
                    "amount": amt,
                    "currency": "INR",
                    "fee": fee,
                    "tax": tax,
                    "status": "captured",
                    "method": "upi",
                    "captured_at": "2026-03-29T16:00:00+05:30",
                    "settlement_id": setl_id,
                    "description": f"Bulk collection batch {setl_id}"
                })

            setl_net = setl_gross - setl_fees - setl_tax
            self.bank_records.append({
                "txn_id": f"BANK-BULK-WIRE-{s_idx}",
                "txn_date": "2026-03-31",
                "value_date": "2026-03-31",
                "description": f"NEFT-RAZORPAY BULK SETTLEMENT-{setl_id}-CR",
                "credit": setl_net / 100.0,
                "debit": None,
                "balance": 9200000.0,
                "ref_no": f"UTR-BULK-{s_idx:04d}"
            })

        # ---------------------------------------------------------------------
        # 5. Duplicate Ingestions (6 Records)
        # ---------------------------------------------------------------------
        for i in range(1, 4):
            dup_pay = f"pay_DUP_00{i}"
            gw_dup = {
                "payment_id": dup_pay,
                "order_id": f"ord_DUP_{i}",
                "amount": 99900,
                "currency": "INR",
                "fee": 1998,
                "tax": 360,
                "status": "captured",
                "method": "card",
                "captured_at": "2026-03-30T11:00:00+05:30",
                "description": f"Duplicate subscription webhook {dup_pay}"
            }
            self.gateway_records.append(gw_dup)
            self.gateway_records.append(gw_dup.copy()) # Ingested twice!

        # ---------------------------------------------------------------------
        # 6. Unsettled / Missing Bank Credit (8 Records: Gateway captures, zero Bank credit)
        # ---------------------------------------------------------------------
        for i in range(1, 9):
            pay_id = f"pay_MISS_BANK_{i:02d}"
            self.gateway_records.append({
                "payment_id": pay_id,
                "order_id": f"ord_MISS_{i}",
                "amount": 500000, # ₹5,000.00 high impact!
                "currency": "INR",
                "fee": 10000,
                "tax": 1800,
                "status": "captured",
                "method": "netbanking",
                "captured_at": "2026-03-24T09:00:00+05:30",
                "description": f"Enterprise license fee (UNSETTLED) {pay_id}"
            })

        # ---------------------------------------------------------------------
        # 7. Anonymous Bank Credits (4 Records: Bank received NEFT without order ref)
        # ---------------------------------------------------------------------
        for i in range(1, 5):
            self.bank_records.append({
                "txn_id": f"BANK-ANON-{i:02d}",
                "txn_date": "2026-03-30",
                "value_date": "2026-03-30",
                "description": f"DIRECT-DEP-UNKNOWN-COUNTERPARTY-{i:02d}",
                "credit": 15000.0,
                "debit": None,
                "balance": 9800000.0,
                "ref_no": f"UTR-ANON-{i:04d}"
            })

        # ---------------------------------------------------------------------
        # 8. Partial Settlements & Chargeback Reserves (4 Records)
        # ---------------------------------------------------------------------
        for i in range(1, 5):
            inv_id = f"INV-DISPUTE-{i:02d}"
            self.gateway_records.append({
                "payment_id": f"pay_DISP_{i:02d}",
                "order_id": f"ord_DISP_{i}",
                "amount": 100000, # ₹1,000.00
                "currency": "INR",
                "fee": 2000,
                "tax": 360,
                "status": "disputed",
                "method": "card",
                "captured_at": "2026-03-27T12:00:00+05:30",
                "description": f"Chargeback reserve withheld for {inv_id}"
            })

        # ---------------------------------------------------------------------
        # 9. Reversals / Customer Refunds (3 Records: Gateway negative amount)
        # ---------------------------------------------------------------------
        for i in range(1, 4):
            self.gateway_records.append({
                "payment_id": f"rfnd_REV_{i:02d}",
                "order_id": f"ord_REV_{i}",
                "amount": 49900,
                "currency": "INR",
                "fee": -998,
                "tax": -180,
                "status": "refunded",
                "method": "upi",
                "captured_at": "2026-03-29T18:30:00+05:30",
                "description": f"Customer refund reversal for ord_REV_{i}"
            })

        return {
            "gateway_records": self.gateway_records,
            "bank_records": self.bank_records,
            "ledger_records": self.ledger_records,
            "settlement_records": self.settlement_records,
            "ground_truth_links": self.ground_truth_links,
            "total_records": (
                len(self.gateway_records) +
                len(self.bank_records) +
                len(self.ledger_records) +
                len(self.settlement_records)
            )
        }
