"""
Comprehensive 50-Record Test Dataset Generator: Payment Gateway Charges, Tax Discrepancies, and Edge Cases.

Generates 3 coordinated CSV files:
1. data/test_fixtures/gateway_50.csv (minor units / paise)
2. data/test_fixtures/bank_50.csv (major units / rupees)
3. data/test_fixtures/ledger_50.csv (major units / rupees, multi-line double-entry)
plus ground-truth benchmark metadata.
"""

import os
import csv
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

def generate_50_edge_case_datasets(output_dir: str = "data/test_fixtures") -> dict:
    os.makedirs(output_dir, exist_ok=True)
    
    gw_file = os.path.join(output_dir, "gateway_50.csv")
    bk_file = os.path.join(output_dir, "bank_50.csv")
    gl_file = os.path.join(output_dir, "ledger_50.csv")
    truth_file = os.path.join(output_dir, "ground_truth_50.json")

    gateway_rows = []
    bank_rows = []
    ledger_rows = []
    ground_truth = []

    # Helper functions
    def format_ts(d: date, hour: int = 11, minute: int = 0) -> str:
        return datetime(d.year, d.month, d.day, hour, minute, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))).isoformat()

    def paise_to_rs(paise: int) -> str:
        return f"{paise / 100:.2f}"

    base_date = date(2026, 3, 20)

    # --------------------------------------------------------------------------
    # COHORT 1: Standard Gateway Fees & Taxes (Records 1 to 10)
    # Contractual 2.0% MDR + 18% GST (Records 1-7) & 1.5% Enterprise (Records 8-10)
    # --------------------------------------------------------------------------
    std_amounts_rs = [500.0, 1000.0, 2500.0, 5000.0, 7500.0, 10000.0, 12000.0]
    for idx, amt_rs in enumerate(std_amounts_rs, start=1):
        gross_paise = int(amt_rs * 100)
        # 2.0% MDR + 18% GST on MDR
        fee_paise = int(Decimal(str(gross_paise)) * Decimal("0.02"))
        tax_paise = int(Decimal(str(fee_paise)) * Decimal("0.18"))
        total_ded = fee_paise + tax_paise
        net_paise = gross_paise - total_ded

        d = base_date + timedelta(days=(idx % 5))
        pay_id = f"pay_STD_{idx:03d}"
        ord_id = f"ord_STD_{idx:03d}"
        inv_id = f"INV-2026-STD{idx:03d}"
        utr_id = f"UTR2026STD{idx:03d}"
        je_id = f"JE-STD-{idx:03d}"
        settle_id = f"SETL_STD_{idx:03d}"

        # 1. Gateway
        gateway_rows.append({
            "payment_id": pay_id,
            "order_id": ord_id,
            "amount": gross_paise,
            "currency": "INR",
            "fee": fee_paise,
            "tax": tax_paise,
            "status": "captured",
            "method": "card" if idx % 2 == 0 else "upi",
            "captured_at": format_ts(d, 10, idx * 5),
            "settlement_id": settle_id,
            "customer_email": f"corp_client_{idx}@example.com",
            "description": f"Standard B2B subscription {inv_id} via {pay_id}"
        })

        # 2. Bank (settled net)
        bank_rows.append({
            "txn_id": f"BANK-STD-{idx:03d}",
            "txn_date": d.isoformat(),
            "value_date": (d + timedelta(days=1)).isoformat(),
            "description": f"NEFT-RAZORPAY-{pay_id}-CR {inv_id}",
            "credit": paise_to_rs(net_paise),
            "debit": "",
            "balance": f"{1000000.0 + (net_paise / 100):.2f}",
            "ref_no": utr_id
        })

        # 3. Ledger (Double-entry: AR, Revenue, GST Output)
        rev_rs = round(amt_rs / 1.18, 2)
        gst_out_rs = round(amt_rs - rev_rs, 2)
        ledger_rows.append({
            "je_id": je_id, "line_no": 1, "posted_at": d.isoformat(),
            "account_code": "1210", "account_name": "Gateway Receivable",
            "debit": f"{amt_rs:.2f}", "credit": "",
            "memo": f"B2B capture {inv_id}", "doc_ref": inv_id
        })
        ledger_rows.append({
            "je_id": je_id, "line_no": 2, "posted_at": d.isoformat(),
            "account_code": "4000", "account_name": "Revenue",
            "debit": "", "credit": f"{rev_rs:.2f}",
            "memo": f"Revenue {inv_id}", "doc_ref": inv_id
        })
        ledger_rows.append({
            "je_id": je_id, "line_no": 3, "posted_at": d.isoformat(),
            "account_code": "2310", "account_name": "GST Output",
            "debit": "", "credit": f"{gst_out_rs:.2f}",
            "memo": f"GST 18% on {inv_id}", "doc_ref": inv_id
        })

        ground_truth.append({
            "record_index": idx,
            "cohort": "STANDARD_MDR_18_GST",
            "payment_id": pay_id,
            "gross_minor": gross_paise,
            "expected_fee_minor": fee_paise,
            "expected_tax_minor": tax_paise,
            "net_minor": net_paise,
            "expected_tier": "RESOLVED_WITH_EXPLANATION"
        })

    # Records 8-10: Enterprise 1.5% MDR + 18% GST
    ent_amounts_rs = [20000.0, 35000.0, 50000.0]
    for offset, amt_rs in enumerate(ent_amounts_rs, start=8):
        gross_paise = int(amt_rs * 100)
        fee_paise = int(Decimal(str(gross_paise)) * Decimal("0.015"))
        tax_paise = int(Decimal(str(fee_paise)) * Decimal("0.18"))
        net_paise = gross_paise - (fee_paise + tax_paise)

        d = base_date + timedelta(days=2)
        pay_id = f"pay_ENT_{offset:03d}"
        inv_id = f"INV-2026-ENT{offset:03d}"
        utr_id = f"UTR2026ENT{offset:03d}"
        je_id = f"JE-ENT-{offset:03d}"

        gateway_rows.append({
            "payment_id": pay_id,
            "order_id": f"ord_ENT_{offset:03d}",
            "amount": gross_paise,
            "currency": "INR",
            "fee": fee_paise,
            "tax": tax_paise,
            "status": "captured",
            "method": "netbanking",
            "captured_at": format_ts(d, 12, offset),
            "settlement_id": f"SETL_ENT_{offset:03d}",
            "customer_email": f"ent_client_{offset}@acme.com",
            "description": f"Enterprise invoice {inv_id} via {pay_id}"
        })
        bank_rows.append({
            "txn_id": f"BANK-ENT-{offset:03d}",
            "txn_date": d.isoformat(),
            "value_date": (d + timedelta(days=1)).isoformat(),
            "description": f"NEFT-RAZORPAY-{pay_id}-CR {inv_id}",
            "credit": paise_to_rs(net_paise),
            "debit": "",
            "balance": "1500000.00",
            "ref_no": utr_id
        })
        rev_rs = round(amt_rs / 1.18, 2)
        gst_out_rs = round(amt_rs - rev_rs, 2)
        ledger_rows.append({
            "je_id": je_id, "line_no": 1, "posted_at": d.isoformat(),
            "account_code": "1210", "account_name": "Gateway Receivable",
            "debit": f"{amt_rs:.2f}", "credit": "",
            "memo": f"Enterprise capture {inv_id}", "doc_ref": inv_id
        })
        ledger_rows.append({
            "je_id": je_id, "line_no": 2, "posted_at": d.isoformat(),
            "account_code": "4000", "account_name": "Revenue",
            "debit": "", "credit": f"{rev_rs:.2f}",
            "memo": f"Rev {inv_id}", "doc_ref": inv_id
        })
        ledger_rows.append({
            "je_id": je_id, "line_no": 3, "posted_at": d.isoformat(),
            "account_code": "2310", "account_name": "GST Output",
            "debit": "", "credit": f"{gst_out_rs:.2f}",
            "memo": f"GST on {inv_id}", "doc_ref": inv_id
        })
        ground_truth.append({
            "record_index": offset,
            "cohort": "ENTERPRISE_MDR_18_GST",
            "payment_id": pay_id,
            "gross_minor": gross_paise,
            "expected_fee_minor": fee_paise,
            "expected_tax_minor": tax_paise,
            "net_minor": net_paise,
            "expected_tier": "RESOLVED_WITH_EXPLANATION"
        })

    # --------------------------------------------------------------------------
    # COHORT 2: Tax Discrepancies (Records 11 to 18)
    # Explicit miscalculations: 12% GST instead of 18%, 0% tax, 28% luxury, rounding
    # --------------------------------------------------------------------------
    tax_scenarios = [
        # (idx, gross_rs, fee_pct, tax_pct, error_label, desc)
        (11, 10000.0, 0.02, 0.12, "GST_RATE_12_PCT_ERROR", "Gateway applied 12% GST instead of mandatory 18%"),
        (12, 5000.0, 0.02, 0.00, "MISSING_GST_ZERO_TAX", "Zero tax charged on taxable MDR fee"),
        (13, 15000.0, 0.02, 0.28, "EXCESSIVE_TAX_28_PCT", "28% luxury rate charged on standard payment processing"),
        (14, 8500.0, 0.02, 0.18, "PAISE_ROUNDING_ERROR", "Non-standard truncate rounding creating 85 paise variance"),
        (15, 6000.0, 0.02, 0.05, "VAT_UAE_RATE_IN_INDIA", "VAT 5% erroneously billed to Indian GST merchant"),
        (16, 12000.0, 0.02, 0.18, "DOUBLE_TAX_SURCHARGE", "Unauthorized 1% infrastructure cess added to 18% GST"),
        (17, 7000.0, 0.02, 0.00, "REVERSE_CHARGE_MDR_CONFUSION", "Reverse charge flag caused gateway to drop tax line"),
        (18, 4000.0, 0.02, 0.18, "EXEMPT_SERVICE_OVERTAXED", "Tax applied on exempt micro-transaction")
    ]

    for idx, gross_rs, fee_pct, tax_pct, err_label, err_desc in tax_scenarios:
        gross_paise = int(gross_rs * 100)
        fee_paise = int(Decimal(str(gross_paise)) * Decimal(str(fee_pct)))
        
        # Calculate actual tax applied by gateway (which contains the discrepancy)
        if err_label == "PAISE_ROUNDING_ERROR":
            actual_tax_paise = int(Decimal(str(fee_paise)) * Decimal("0.18")) - 85
        elif err_label == "DOUBLE_TAX_SURCHARGE":
            # 18% GST + 1% extra cess = 19%
            actual_tax_paise = int(Decimal(str(fee_paise)) * Decimal("0.19"))
        else:
            actual_tax_paise = int(Decimal(str(fee_paise)) * Decimal(str(tax_pct)))

        # What tax SHOULD have been under standard POL-MDR-STD-2026 (18%)
        expected_tax_paise = int(Decimal(str(fee_paise)) * Decimal("0.18"))
        tax_discrepancy_paise = actual_tax_paise - expected_tax_paise

        # Bank settles according to actual gateway deduction
        actual_net_paise = gross_paise - (fee_paise + actual_tax_paise)

        d = base_date + timedelta(days=3)
        pay_id = f"pay_TAX_{idx:03d}"
        inv_id = f"INV-2026-TAX{idx:03d}"
        utr_id = f"UTR2026TAX{idx:03d}"
        je_id = f"JE-TAX-{idx:03d}"

        # Gateway reports standard expected fee/tax for records 13 & 14 so that the bank's excessive deduction creates a true cross-source variance
        gw_reported_tax = expected_tax_paise if idx in (13, 14) else actual_tax_paise

        gateway_rows.append({
            "payment_id": pay_id,
            "order_id": f"ord_TAX_{idx:03d}",
            "amount": gross_paise,
            "currency": "INR",
            "fee": fee_paise,
            "tax": gw_reported_tax,
            "status": "captured",
            "method": "card",
            "captured_at": format_ts(d, 14, idx),
            "settlement_id": f"SETL_TAX_{idx:03d}",
            "customer_email": f"tax_test_{idx}@acme.co",
            "description": f"Tax discrepancy test {inv_id} ({err_desc}) via {pay_id}"
        })

        bank_rows.append({
            "txn_id": f"BANK-TAX-{idx:03d}",
            "txn_date": d.isoformat(),
            "value_date": (d + timedelta(days=1)).isoformat(),
            "description": f"NEFT-RAZORPAY-{pay_id}-CR {inv_id}",
            "credit": paise_to_rs(actual_net_paise),
            "debit": "",
            "balance": "2000000.00",
            "ref_no": utr_id
        })

        # Ledger booked expecting standard contractual numbers
        rev_rs = round(gross_rs / 1.18, 2)
        gst_out_rs = round(gross_rs - rev_rs, 2)
        ledger_rows.append({
            "je_id": je_id, "line_no": 1, "posted_at": d.isoformat(),
            "account_code": "1210", "account_name": "Gateway Receivable",
            "debit": f"{gross_rs:.2f}", "credit": "",
            "memo": f"Tax discrepancy entry {inv_id}", "doc_ref": inv_id
        })
        ledger_rows.append({
            "je_id": je_id, "line_no": 2, "posted_at": d.isoformat(),
            "account_code": "4000", "account_name": "Revenue",
            "debit": "", "credit": f"{rev_rs:.2f}",
            "memo": f"Rev {inv_id}", "doc_ref": inv_id
        })
        ledger_rows.append({
            "je_id": je_id, "line_no": 3, "posted_at": d.isoformat(),
            "account_code": "2310", "account_name": "GST Output",
            "debit": "", "credit": f"{gst_out_rs:.2f}",
            "memo": f"GST on {inv_id}", "doc_ref": inv_id
        })

        ground_truth.append({
            "record_index": idx,
            "cohort": "TAX_DISCREPANCY",
            "error_type": err_label,
            "payment_id": pay_id,
            "gross_minor": gross_paise,
            "fee_minor": fee_paise,
            "actual_tax_minor": actual_tax_paise,
            "expected_tax_minor": expected_tax_paise,
            "tax_discrepancy_minor": tax_discrepancy_paise,
            "net_minor": actual_net_paise,
            "expected_exception": "FEE_VARIANCE" if actual_tax_paise > 0 else "AMOUNT_MISMATCH"
        })

    # --------------------------------------------------------------------------
    # COHORT 3: Gateway Fee Overcharge / Undercharge (Records 19 to 24)
    # --------------------------------------------------------------------------
    fee_scenarios = [
        (19, 10000.0, 0.025, 0.18, "MDR_OVERCHARGE_2_5_PCT", "Charged 2.5% MDR instead of agreed 2.0% schedule"),
        (20, 15000.0, 0.030, 0.18, "MDR_OVERCHARGE_3_0_PCT", "International 3.0% rate applied to domestic card"),
        (21, 8000.0, 0.010, 0.18, "MDR_UNDERCHARGE_1_0_PCT", "Promo 1.0% rate applied instead of 2.0%"),
        (22, 12000.0, 0.020, 0.18, "UNCONTRACTED_FLAT_SURCHARGE", "Flat ₹25 surcharge added to processing fee"),
        (23, 25000.0, 0.020, 0.18, "CHARGEBACK_FEE_SURCHARGE", "Unannounced ₹150 dispute administrative fee deducted"),
        (24, 200.0, 0.020, 0.18, "MINIMUM_FEE_FLOOR_APPLIED", "Gateway applied ₹5.00 min fee floor on ₹200 micro-payment")
    ]

    for idx, gross_rs, mdr_pct, gst_pct, err_label, err_desc in fee_scenarios:
        gross_paise = int(gross_rs * 100)
        std_fee_paise = int(Decimal(str(gross_paise)) * Decimal("0.02"))
        std_tax_paise = int(Decimal(str(std_fee_paise)) * Decimal("0.18"))

        if err_label == "UNCONTRACTED_FLAT_SURCHARGE":
            actual_fee_paise = std_fee_paise + 2500
            actual_tax_paise = int(Decimal(str(actual_fee_paise)) * Decimal("0.18"))
        elif err_label == "CHARGEBACK_FEE_SURCHARGE":
            actual_fee_paise = std_fee_paise + 15000
            actual_tax_paise = std_tax_paise
        elif err_label == "MINIMUM_FEE_FLOOR_APPLIED":
            actual_fee_paise = 500  # Rs 5.00 min fee
            actual_tax_paise = 90   # 18% on Rs 5.00
        else:
            actual_fee_paise = int(Decimal(str(gross_paise)) * Decimal(str(mdr_pct)))
            actual_tax_paise = int(Decimal(str(actual_fee_paise)) * Decimal(str(gst_pct)))

        actual_net_paise = gross_paise - (actual_fee_paise + actual_tax_paise)

        d = base_date + timedelta(days=4)
        pay_id = f"pay_FEE_{idx:03d}"
        inv_id = f"INV-2026-FEE{idx:03d}"
        utr_id = f"UTR2026FEE{idx:03d}"
        je_id = f"JE-FEE-{idx:03d}"

        gw_rep_fee = std_fee_paise if idx in (19, 20) else actual_fee_paise
        gw_rep_tax = std_tax_paise if idx in (19, 20) else actual_tax_paise

        gateway_rows.append({
            "payment_id": pay_id,
            "order_id": f"ord_FEE_{idx:03d}",
            "amount": gross_paise,
            "currency": "INR",
            "fee": gw_rep_fee,
            "tax": gw_rep_tax,
            "status": "captured",
            "method": "card",
            "captured_at": format_ts(d, 15, idx),
            "settlement_id": f"SETL_FEE_{idx:03d}",
            "customer_email": f"fee_client_{idx}@acme.org",
            "description": f"Fee audit capture {inv_id} ({err_desc}) via {pay_id}"
        })

        bank_rows.append({
            "txn_id": f"BANK-FEE-{idx:03d}",
            "txn_date": d.isoformat(),
            "value_date": (d + timedelta(days=1)).isoformat(),
            "description": f"NEFT-RAZORPAY-{pay_id}-CR {inv_id}",
            "credit": paise_to_rs(actual_net_paise),
            "debit": "",
            "balance": "2500000.00",
            "ref_no": utr_id
        })

        rev_rs = round(gross_rs / 1.18, 2)
        gst_out_rs = round(gross_rs - rev_rs, 2)
        ledger_rows.append({
            "je_id": je_id, "line_no": 1, "posted_at": d.isoformat(),
            "account_code": "1210", "account_name": "Gateway Receivable",
            "debit": f"{gross_rs:.2f}", "credit": "",
            "memo": f"Fee test capture {inv_id}", "doc_ref": inv_id
        })
        ledger_rows.append({
            "je_id": je_id, "line_no": 2, "posted_at": d.isoformat(),
            "account_code": "4000", "account_name": "Revenue",
            "debit": "", "credit": f"{rev_rs:.2f}",
            "memo": f"Rev {inv_id}", "doc_ref": inv_id
        })
        ledger_rows.append({
            "je_id": je_id, "line_no": 3, "posted_at": d.isoformat(),
            "account_code": "2310", "account_name": "GST Output",
            "debit": "", "credit": f"{gst_out_rs:.2f}",
            "memo": f"GST on {inv_id}", "doc_ref": inv_id
        })

        ground_truth.append({
            "record_index": idx,
            "cohort": "GATEWAY_FEE_OVER_UNDERCHARGE",
            "error_type": err_label,
            "payment_id": pay_id,
            "gross_minor": gross_paise,
            "actual_fee_minor": actual_fee_paise,
            "expected_fee_minor": std_fee_paise,
            "fee_variance_minor": actual_fee_paise - std_fee_paise,
            "expected_exception": "FEE_VARIANCE"
        })

    # --------------------------------------------------------------------------
    # COHORT 4: Exact 1:1:1 Clean Direct Wire Matches (Records 25 to 32)
    # Zero Fee (POL-DIRECT-WIRE-2026), Gross == Net == Ledger Debit
    # --------------------------------------------------------------------------
    clean_amounts_rs = [1500.0, 3200.0, 4800.0, 6500.0, 8900.0, 11500.0, 14200.0, 18000.0]
    for offset, amt_rs in enumerate(clean_amounts_rs, start=25):
        paise = int(amt_rs * 100)
        d = base_date + timedelta(days=5)
        pay_id = f"pay_CLEAN_{offset:03d}"
        inv_id = f"INV-2026-CLN{offset:03d}"
        utr_id = f"UTR2026CLN{offset:03d}"
        je_id = f"JE-CLN-{offset:03d}"

        gateway_rows.append({
            "payment_id": pay_id,
            "order_id": f"ord_CLN_{offset:03d}",
            "amount": paise,
            "currency": "INR",
            "fee": 0,
            "tax": 0,
            "status": "captured",
            "method": "bank_transfer",
            "captured_at": format_ts(d, 9, offset),
            "settlement_id": f"SETL_CLN_{offset:03d}",
            "customer_email": f"direct_{offset}@client.com",
            "description": f"Direct gross payment {inv_id} via {pay_id}"
        })

        bank_rows.append({
            "txn_id": f"BANK-CLN-{offset:03d}",
            "txn_date": d.isoformat(),
            "value_date": d.isoformat(),
            "description": f"RTGS-INWARD-{pay_id}-CR {inv_id}",
            "credit": f"{amt_rs:.2f}",
            "debit": "",
            "balance": "3000000.00",
            "ref_no": utr_id
        })

        rev_rs = round(amt_rs / 1.18, 2)
        gst_out_rs = round(amt_rs - rev_rs, 2)
        ledger_rows.append({
            "je_id": je_id, "line_no": 1, "posted_at": d.isoformat(),
            "account_code": "1210", "account_name": "Gateway Receivable",
            "debit": f"{amt_rs:.2f}", "credit": "",
            "memo": f"Direct wire {inv_id}", "doc_ref": inv_id
        })
        ledger_rows.append({
            "je_id": je_id, "line_no": 2, "posted_at": d.isoformat(),
            "account_code": "4000", "account_name": "Revenue",
            "debit": "", "credit": f"{rev_rs:.2f}",
            "memo": f"Rev {inv_id}", "doc_ref": inv_id
        })
        ledger_rows.append({
            "je_id": je_id, "line_no": 3, "posted_at": d.isoformat(),
            "account_code": "2310", "account_name": "GST Output",
            "debit": "", "credit": f"{gst_out_rs:.2f}",
            "memo": f"GST on {inv_id}", "doc_ref": inv_id
        })

        ground_truth.append({
            "record_index": offset,
            "cohort": "CLEAN_EXACT_MATCH",
            "payment_id": pay_id,
            "gross_minor": paise,
            "fee_minor": 0,
            "tax_minor": 0,
            "net_minor": paise,
            "expected_tier": "RESOLVED"
        })

    # --------------------------------------------------------------------------
    # COHORT 5: Timing Cutoff / Period Boundary Lags (Records 33 to 37)
    # Captured March 31st 23:55, bank settles April 2nd (T+2 cutoff)
    # --------------------------------------------------------------------------
    cutoff_amounts_rs = [2360.0, 4720.0, 7080.0, 9440.0, 11800.0]
    cutoff_date = date(2026, 3, 31)
    settle_date = date(2026, 4, 2)

    for offset, amt_rs in enumerate(cutoff_amounts_rs, start=33):
        gross_paise = int(amt_rs * 100)
        fee_paise = int(Decimal(str(gross_paise)) * Decimal("0.02"))
        tax_paise = int(Decimal(str(fee_paise)) * Decimal("0.18"))
        net_paise = gross_paise - (fee_paise + tax_paise)

        pay_id = f"pay_CUT_{offset:03d}"
        inv_id = f"INV-2026-CUT{offset:03d}"
        utr_id = f"UTR2026CUT{offset:03d}"
        je_id = f"JE-CUT-{offset:03d}"

        gateway_rows.append({
            "payment_id": pay_id,
            "order_id": f"ord_CUT_{offset:03d}",
            "amount": gross_paise,
            "currency": "INR",
            "fee": fee_paise,
            "tax": tax_paise,
            "status": "captured",
            "method": "netbanking",
            "captured_at": "2026-03-31T23:55:00+05:30",
            "settlement_id": f"SETL_CUT_{offset:03d}",
            "customer_email": f"quarter_end_{offset}@corp.in",
            "description": f"Quarter-end cutoff payment {inv_id} via {pay_id}"
        })

        bank_rows.append({
            "txn_id": f"BANK-CUT-{offset:03d}",
            "txn_date": settle_date.isoformat(),
            "value_date": settle_date.isoformat(),
            "description": f"NEFT-RAZORPAY-{pay_id}-CR {inv_id}",
            "credit": paise_to_rs(net_paise),
            "debit": "",
            "balance": "3500000.00",
            "ref_no": utr_id
        })

        rev_rs = round(amt_rs / 1.18, 2)
        gst_out_rs = round(amt_rs - rev_rs, 2)
        ledger_rows.append({
            "je_id": je_id, "line_no": 1, "posted_at": cutoff_date.isoformat(),
            "account_code": "1210", "account_name": "Gateway Receivable",
            "debit": f"{amt_rs:.2f}", "credit": "",
            "memo": f"Quarter-end accrual {inv_id}", "doc_ref": inv_id
        })
        ledger_rows.append({
            "je_id": je_id, "line_no": 2, "posted_at": cutoff_date.isoformat(),
            "account_code": "4000", "account_name": "Revenue",
            "debit": "", "credit": f"{rev_rs:.2f}",
            "memo": f"Rev {inv_id}", "doc_ref": inv_id
        })
        ledger_rows.append({
            "je_id": je_id, "line_no": 3, "posted_at": cutoff_date.isoformat(),
            "account_code": "2310", "account_name": "GST Output",
            "debit": "", "credit": f"{gst_out_rs:.2f}",
            "memo": f"GST on {inv_id}", "doc_ref": inv_id
        })

        ground_truth.append({
            "record_index": offset,
            "cohort": "PERIOD_CUTOFF",
            "payment_id": pay_id,
            "gross_minor": gross_paise,
            "net_minor": net_paise,
            "expected_exception": "PERIOD_CUTOFF"
        })

    # --------------------------------------------------------------------------
    # COHORT 6: Duplicates & Webhook Retries (Records 38 to 41)
    # --------------------------------------------------------------------------
    # 38 & 39: Duplicate Gateway Webhook
    dup_gw_amt = 99900
    dup_gw_fee = 1998
    dup_gw_tax = 360
    dup_gw_net = dup_gw_amt - (dup_gw_fee + dup_gw_tax)
    d = base_date + timedelta(days=6)

    for sub_idx in (38, 39):
        gateway_rows.append({
            "payment_id": "pay_DUP_WEBHOOK_38",
            "order_id": "ord_DUP_WEBHOOK_38",
            "amount": dup_gw_amt,
            "currency": "INR",
            "fee": dup_gw_fee,
            "tax": dup_gw_tax,
            "status": "captured",
            "method": "upi",
            "captured_at": format_ts(d, 16, 0),
            "settlement_id": "SETL_DUP_38",
            "customer_email": "dup_webhook@user.org",
            "description": "Duplicate webhook capture INV-2026-DUP38"
        })
    bank_rows.append({
        "txn_id": "BANK-DUP-38",
        "txn_date": d.isoformat(),
        "value_date": (d + timedelta(days=1)).isoformat(),
        "description": "NEFT-RAZORPAY-pay_DUP_WEBHOOK_38-CR INV-2026-DUP38",
        "credit": paise_to_rs(dup_gw_net),
        "debit": "",
        "balance": "3800000.00",
        "ref_no": "UTR2026DUP038"
    })
    ledger_rows.append({
        "je_id": "JE-DUP-38", "line_no": 1, "posted_at": d.isoformat(),
        "account_code": "1210", "account_name": "Gateway Receivable",
        "debit": "999.00", "credit": "",
        "memo": "Duplicate webhook original INV-2026-DUP38", "doc_ref": "INV-2026-DUP38"
    })
    ledger_rows.append({
        "je_id": "JE-DUP-38", "line_no": 2, "posted_at": d.isoformat(),
        "account_code": "4000", "account_name": "Revenue",
        "debit": "", "credit": "846.61",
        "memo": "Rev INV-2026-DUP38", "doc_ref": "INV-2026-DUP38"
    })
    ledger_rows.append({
        "je_id": "JE-DUP-38", "line_no": 3, "posted_at": d.isoformat(),
        "account_code": "2310", "account_name": "GST Output",
        "debit": "", "credit": "152.39",
        "memo": "GST INV-2026-DUP38", "doc_ref": "INV-2026-DUP38"
    })

    # 40 & 41: Duplicate Bank Deposit (Single gateway transaction, bank credited twice)
    dup_bk_amt = 500000
    dup_bk_fee = 10000
    dup_bk_tax = 1800
    dup_bk_net = dup_bk_amt - (dup_bk_fee + dup_bk_tax)

    gateway_rows.append({
        "payment_id": "pay_DUP_BANK_40",
        "order_id": "ord_DUP_BANK_40",
        "amount": dup_bk_amt,
        "currency": "INR",
        "fee": dup_bk_fee,
        "tax": dup_bk_tax,
        "status": "captured",
        "method": "card",
        "captured_at": format_ts(d, 17, 30),
        "settlement_id": "SETL_DUP_40",
        "customer_email": "dup_bank@client.co",
        "description": "Gateway transaction for double bank credit INV-2026-DUP40"
    })
    for b_sub in (40, 41):
        bank_rows.append({
            "txn_id": f"BANK-DUP-CREDIT-{b_sub}",
            "txn_date": d.isoformat(),
            "value_date": d.isoformat(),
            "description": f"NEFT-RAZORPAY-pay_DUP_BANK_40-CR INV-2026-DUP40 copy_{b_sub}",
            "credit": paise_to_rs(dup_bk_net),
            "debit": "",
            "balance": "4000000.00",
            "ref_no": f"UTR2026DUPBK{b_sub}"
        })
    ledger_rows.append({
        "je_id": "JE-DUP-40", "line_no": 1, "posted_at": d.isoformat(),
        "account_code": "1210", "account_name": "Gateway Receivable",
        "debit": "5000.00", "credit": "",
        "memo": "JE INV-2026-DUP40", "doc_ref": "INV-2026-DUP40"
    })
    ledger_rows.append({
        "je_id": "JE-DUP-40", "line_no": 2, "posted_at": d.isoformat(),
        "account_code": "4000", "account_name": "Revenue",
        "debit": "", "credit": "4237.29",
        "memo": "Rev INV-2026-DUP40", "doc_ref": "INV-2026-DUP40"
    })
    ledger_rows.append({
        "je_id": "JE-DUP-40", "line_no": 3, "posted_at": d.isoformat(),
        "account_code": "2310", "account_name": "GST Output",
        "debit": "", "credit": "762.71",
        "memo": "GST INV-2026-DUP40", "doc_ref": "INV-2026-DUP40"
    })

    ground_truth.append({"record_index": 38, "cohort": "DUPLICATE_WEBHOOK", "expected_exception": "DUPLICATE_RECORD"})
    ground_truth.append({"record_index": 40, "cohort": "DUPLICATE_BANK_DEPOSIT", "expected_exception": "DUPLICATE_RECORD"})

    # --------------------------------------------------------------------------
    # COHORT 7: Unmatched Residuals (Records 42 to 46)
    # Unsettled Gateway captures, Unallocated Bank credits, Missing Ledger entries
    # --------------------------------------------------------------------------
    d = base_date + timedelta(days=7)
    # 42 & 43: Unsettled Gateway Captures (Missing Bank deposit)
    for u_gw in (42, 43):
        gw_amt = 500000 * (u_gw - 41)
        gateway_rows.append({
            "payment_id": f"pay_UNSETTLED_{u_gw:03d}",
            "order_id": f"ord_UNSET_{u_gw:03d}",
            "amount": gw_amt,
            "currency": "INR",
            "fee": int(gw_amt * 0.02),
            "tax": int(gw_amt * 0.02 * 0.18),
            "status": "captured",
            "method": "card",
            "captured_at": format_ts(d, 11, u_gw),
            "settlement_id": "SETL_UNSET",
            "customer_email": f"unsettled_{u_gw}@lostfunds.in",
            "description": f"Customer payment captured but never deposited INV-2026-UNSET{u_gw}"
        })
        ground_truth.append({"record_index": u_gw, "cohort": "UNSETTLED_GATEWAY", "expected_exception": "UNSETTLED_GATEWAY_RECORD"})

    # 44 & 45: Unallocated Bank Deposits (Direct credit from mystery party, no gateway/order)
    for u_bk in (44, 45):
        bk_cr = 7500.0 * (u_bk - 43)
        bank_rows.append({
            "txn_id": f"BANK-ANON-{u_bk:03d}",
            "txn_date": d.isoformat(),
            "value_date": d.isoformat(),
            "description": f"DIRECT-CREDIT-UNKNOWN-PARTY-{u_bk} NO-REF-FOUND",
            "credit": f"{bk_cr:.2f}",
            "debit": "",
            "balance": "4500000.00",
            "ref_no": f"UTR2026ANON{u_bk:03d}"
        })
        ground_truth.append({"record_index": u_bk, "cohort": "UNALLOCATED_BANK_CREDIT", "expected_exception": "UNALLOCATED_BANK_CREDIT"})

    # 46: Missing Ledger Entry (Gateway & Bank match, but Ledger entry missing)
    m_amt = 1500000  # Rs 15,000
    m_fee = 30000
    m_tax = 5400
    m_net = m_amt - (m_fee + m_tax)
    gateway_rows.append({
        "payment_id": "pay_NO_LEDGER_046",
        "order_id": "ord_NO_LEDGER_046",
        "amount": m_amt,
        "currency": "INR",
        "fee": m_fee,
        "tax": m_tax,
        "status": "captured",
        "method": "upi",
        "captured_at": format_ts(d, 13, 0),
        "settlement_id": "SETL_NOL_046",
        "customer_email": "unbooked_client@acme.com",
        "description": "Payment cleared bank but ERP entry unposted INV-2026-NOL046"
    })
    bank_rows.append({
        "txn_id": "BANK-NOL-046",
        "txn_date": d.isoformat(),
        "value_date": (d + timedelta(days=1)).isoformat(),
        "description": "NEFT-RAZORPAY-pay_NO_LEDGER_046-CR INV-2026-NOL046",
        "credit": paise_to_rs(m_net),
        "debit": "",
        "balance": "4700000.00",
        "ref_no": "UTR2026NOL046"
    })
    ground_truth.append({"record_index": 46, "cohort": "MISSING_LEDGER_ENTRY", "expected_exception": "MISSING_LEDGER"})

    # --------------------------------------------------------------------------
    # COHORT 8: N:1 Batched Settlement & Double-Entry Edge Cases (Records 47 to 50)
    # --------------------------------------------------------------------------
    # 47, 48, 49: 3 Gateway Transactions bundled into 1 Bank Payout net of MDR + GST
    batch_key = "SETL_BATCH_BUNDLE_88"
    batch_gw_amts = [400000, 600000, 1000000] # Rs 4,000 + Rs 6,000 + Rs 10,000 = Rs 20,000
    total_net_bundle = 0
    d = base_date + timedelta(days=8)

    for b_idx, b_amt in zip([47, 48, 49], batch_gw_amts):
        b_fee = int(b_amt * 0.02)
        b_tax = int(b_fee * 0.18)
        b_net = b_amt - (b_fee + b_tax)
        total_net_bundle += b_net

        pay_id = f"pay_BUNDLE_{b_idx:03d}"
        inv_id = f"INV-2026-BDL{b_idx:03d}"
        je_id = f"JE-BDL-{b_idx:03d}"

        gateway_rows.append({
            "payment_id": pay_id,
            "order_id": f"ord_BDL_{b_idx:03d}",
            "amount": b_amt,
            "currency": "INR",
            "fee": b_fee,
            "tax": b_tax,
            "status": "captured",
            "method": "upi",
            "captured_at": format_ts(d, 10, b_idx),
            "settlement_id": batch_key,
            "customer_email": f"bundle_{b_idx}@client.co",
            "description": f"Batch capture {inv_id} in payout {batch_key}"
        })

        b_gross_rs = b_amt / 100
        rev_rs = round(b_gross_rs / 1.18, 2)
        gst_out_rs = round(b_gross_rs - rev_rs, 2)
        ledger_rows.append({
            "je_id": je_id, "line_no": 1, "posted_at": d.isoformat(),
            "account_code": "1210", "account_name": "Gateway Receivable",
            "debit": f"{b_gross_rs:.2f}", "credit": "",
            "memo": f"Bundle component {inv_id}", "doc_ref": inv_id
        })
        ledger_rows.append({
            "je_id": je_id, "line_no": 2, "posted_at": d.isoformat(),
            "account_code": "4000", "account_name": "Revenue",
            "debit": "", "credit": f"{rev_rs:.2f}",
            "memo": f"Rev {inv_id}", "doc_ref": inv_id
        })
        ledger_rows.append({
            "je_id": je_id, "line_no": 3, "posted_at": d.isoformat(),
            "account_code": "2310", "account_name": "GST Output",
            "debit": "", "credit": f"{gst_out_rs:.2f}",
            "memo": f"GST on {inv_id}", "doc_ref": inv_id
        })

    # The 1 Single Bank Deposit for the 3 bundled payments
    bank_rows.append({
        "txn_id": "BANK-BUNDLE-SETL-88",
        "txn_date": d.isoformat(),
        "value_date": (d + timedelta(days=1)).isoformat(),
        "description": f"NEFT-RAZORPAY-{batch_key}-CR 3-BATCH-SETTLEMENT",
        "credit": paise_to_rs(total_net_bundle),
        "debit": "",
        "balance": "5000000.00",
        "ref_no": "UTR2026BUNDLE88"
    })
    ground_truth.append({
        "record_index": [47, 48, 49],
        "cohort": "N_TO_1_BATCH_SETTLEMENT",
        "settlement_key": batch_key,
        "combined_net_minor": total_net_bundle,
        "expected_tier": "RESOLVED_WITH_EXPLANATION"
    })

    # Record 48, 49, 50: Additional Advanced Financial Edge Cases
    # Record 48: Instant Payout / T+0 Immediate Settlement Surcharge
    inst_amt = 2500000 # Rs 25,000
    inst_fee = int(inst_amt * 0.02) + 5000 # 2% MDR + Rs 50 instant fee
    inst_tax = int(inst_fee * 0.18)
    inst_net = inst_amt - (inst_fee + inst_tax)
    gateway_rows.append({
        "payment_id": "pay_INSTANT_048",
        "order_id": "ord_INSTANT_048",
        "amount": inst_amt,
        "currency": "INR",
        "fee": inst_fee,
        "tax": inst_tax,
        "status": "captured",
        "method": "upi",
        "captured_at": format_ts(d, 18, 15),
        "settlement_id": "SETL_INSTANT_048",
        "customer_email": "instant_merchant@acme.co",
        "description": "Instant T+0 settlement payout with fast-transfer surcharge INV-2026-INST48"
    })
    bank_rows.append({
        "txn_id": "BANK-INSTANT-048",
        "txn_date": d.isoformat(),
        "value_date": d.isoformat(),
        "description": "NEFT-RAZORPAY-pay_INSTANT_048-CR INV-2026-INST48 INSTANT-T0",
        "credit": paise_to_rs(inst_net),
        "debit": "",
        "balance": "5200000.00",
        "ref_no": "UTR2026INST048"
    })

    # Record 49: Partial Refund / Chargeback Adjustment (Gross Rs 10,000, Partial Refund Rs 2,500)
    ref_amt = 1000000 # Rs 10,000
    ref_fee = int(ref_amt * 0.02)
    ref_tax = int(ref_fee * 0.18)
    ref_refund = 250000 # Rs 2,500
    ref_net = ref_amt - (ref_fee + ref_tax) - ref_refund # Rs 7,264
    gateway_rows.append({
        "payment_id": "pay_REFUND_PARTIAL_049",
        "order_id": "ord_REF_049",
        "amount": ref_amt,
        "currency": "INR",
        "fee": ref_fee,
        "tax": ref_tax,
        "status": "captured",
        "method": "card",
        "captured_at": format_ts(d, 18, 30),
        "settlement_id": "SETL_REF_049",
        "customer_email": "refunded_buyer@store.org",
        "description": "Capture with partial refund deduction INV-2026-REF49"
    })
    bank_rows.append({
        "txn_id": "BANK-REF-049",
        "txn_date": d.isoformat(),
        "value_date": (d + timedelta(days=1)).isoformat(),
        "description": "NEFT-RAZORPAY-pay_REFUND_PARTIAL_049-CR INV-2026-REF49 NET-OF-REFUND",
        "credit": paise_to_rs(ref_net),
        "debit": "",
        "balance": "5250000.00",
        "ref_no": "UTR2026REF049"
    })

    # Record 50b (completing 50 Gateway Records): Cross-Border International Card Surcharge
    intl_amt = 850000 # Rs 8,500
    intl_fee = int(intl_amt * 0.035) # 3.5% International cross-border fee
    intl_tax = int(intl_fee * 0.18)
    intl_net = intl_amt - (intl_fee + intl_tax)
    gateway_rows.append({
        "payment_id": "pay_INTL_CROSSBORDER_050",
        "order_id": "ord_INTL_050",
        "amount": intl_amt,
        "currency": "INR",
        "fee": intl_fee,
        "tax": intl_tax,
        "status": "captured",
        "method": "international_card",
        "captured_at": format_ts(d, 19, 15),
        "settlement_id": "SETL_INTL_050",
        "customer_email": "global_buyer@overseas.com",
        "description": "Cross-border payment with international processing surcharge INV-2026-INTL50"
    })
    bank_rows.append({
        "txn_id": "BANK-INTL-050",
        "txn_date": d.isoformat(),
        "value_date": (d + timedelta(days=1)).isoformat(),
        "description": "NEFT-RAZORPAY-pay_INTL_CROSSBORDER_050-CR INV-2026-INTL50 CROSS-BORDER",
        "credit": paise_to_rs(intl_net),
        "debit": "",
        "balance": "5350000.00",
        "ref_no": "UTR2026INTL050"
    })

    # Record 50: Unbalanced Double-Entry Failure in Ledger
    # Gateway capture Rs 5,000; Bank net Rs 4,882; Ledger has Debit Rs 5,000 but Credit only Rs 4,700 (missing Rs 300)
    unb_amt = 500000
    unb_fee = int(unb_amt * 0.02)
    unb_tax = int(unb_fee * 0.18)
    unb_net = unb_amt - (unb_fee + unb_tax)

    gateway_rows.append({
        "payment_id": "pay_UNBAL_GL_050",
        "order_id": "ord_UNBAL_GL_050",
        "amount": unb_amt,
        "currency": "INR",
        "fee": unb_fee,
        "tax": unb_tax,
        "status": "captured",
        "method": "card",
        "captured_at": format_ts(d, 19, 0),
        "settlement_id": "SETL_UNBAL_050",
        "customer_email": "accounting_flaw@corp.com",
        "description": "Transaction with unbalanced double-entry ledger entry INV-2026-UNB050"
    })
    bank_rows.append({
        "txn_id": "BANK-UNBAL-050",
        "txn_date": d.isoformat(),
        "value_date": (d + timedelta(days=1)).isoformat(),
        "description": "NEFT-RAZORPAY-pay_UNBAL_GL_050-CR INV-2026-UNB050",
        "credit": paise_to_rs(unb_net),
        "debit": "",
        "balance": "5300000.00",
        "ref_no": "UTR2026UNB050"
    })
    # Deliberate imbalance: Debit 5000.00 vs Credit 4700.00 (Rs 300 out of balance!)
    ledger_rows.append({
        "je_id": "JE-UNB-050", "line_no": 1, "posted_at": d.isoformat(),
        "account_code": "1210", "account_name": "Gateway Receivable",
        "debit": "5000.00", "credit": "",
        "memo": "Unbalanced entry INV-2026-UNB050", "doc_ref": "INV-2026-UNB050"
    })
    ledger_rows.append({
        "je_id": "JE-UNB-050", "line_no": 2, "posted_at": d.isoformat(),
        "account_code": "4000", "account_name": "Revenue",
        "debit": "", "credit": "4700.00",
        "memo": "Flawed credit INV-2026-UNB050", "doc_ref": "INV-2026-UNB050"
    })
    ground_truth.append({
        "record_index": 50,
        "cohort": "UNBALANCED_JOURNAL_ENTRY",
        "expected_imbalance_rs": 300.0
    })

    # --------------------------------------------------------------------------
    # WRITE OUT CSV FILES
    # --------------------------------------------------------------------------
    # 1. Gateway CSV
    gw_fields = ["payment_id", "order_id", "amount", "currency", "fee", "tax", "status", "method", "captured_at", "settlement_id", "customer_email", "description"]
    with open(gw_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=gw_fields)
        writer.writeheader()
        writer.writerows(gateway_rows)

    # 2. Bank CSV
    bk_fields = ["txn_id", "txn_date", "value_date", "description", "credit", "debit", "balance", "ref_no"]
    with open(bk_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=bk_fields)
        writer.writeheader()
        writer.writerows(bank_rows)

    # 3. Ledger CSV
    gl_fields = ["je_id", "line_no", "posted_at", "account_code", "account_name", "debit", "credit", "memo", "doc_ref"]
    with open(gl_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=gl_fields)
        writer.writeheader()
        writer.writerows(ledger_rows)

    # 4. Ground Truth JSON
    with open(truth_file, "w", encoding="utf-8") as f:
        json.dump(ground_truth, f, indent=2)

    return {
        "gateway_path": gw_file,
        "bank_path": bk_file,
        "ledger_path": gl_file,
        "ground_truth_path": truth_file,
        "gateway_records": len(gateway_rows),
        "bank_records": len(bank_rows),
        "ledger_lines": len(ledger_rows),
    }


if __name__ == "__main__":
    res = generate_50_edge_case_datasets()
    print("Generated 50-record edge-case test datasets:")
    print(json.dumps(res, indent=2))
