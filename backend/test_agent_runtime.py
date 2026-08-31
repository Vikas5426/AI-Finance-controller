import os
import sys
from dotenv import load_dotenv

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.services.agent_runtime import AIAgentRuntime

print("=" * 60)
print("  TESTING AI FINANCIAL AGENT RUNTIME INVESTIGATION")
print("=" * 60)

runtime = AIAgentRuntime()

sample_exception_id = "EXC-TEST-001"
sample_type = "AMOUNT_MISMATCH"
sample_impact = 23600 # ₹236.00 variance

primary_txn = {
    "id": "txn_gw_1002",
    "external_id": "pay_1002",
    "amount_minor": 1000000, # ₹10,000.00
    "gross_minor": 1000000,
    "fee_minor": 20000,
    "tax_minor": 3600,
    "source_kind": "GATEWAY",
    "description_raw": "Invoice INV-2026-1002"
}

counterpart_txn = {
    "id": "txn_bank_1002",
    "external_id": "BANK-1002",
    "amount_minor": 976400, # ₹9,764.00
    "source_kind": "BANK",
    "description_raw": "NEFT-RAZORPAY-pay_1002-CR"
}

available_txns = [primary_txn, counterpart_txn]

result = runtime.investigate_exception(
    exception_id=sample_exception_id,
    exception_type=sample_type,
    impact_minor=sample_impact,
    primary_txn=primary_txn,
    counterpart_txn=counterpart_txn,
    available_txns=available_txns
)

import sys
sys.stdout.reconfigure(encoding='utf-8')

print(f"\nInvestigation Result:")
print(f"[+] Exception ID:        {result.exception_id}")
print(f"[+] Classification:      {result.classification}")
print(f"[+] Likely Cause:        {result.likely_cause}")
print(f"[+] Recommended Action:  {result.recommended_action}")
print(f"[+] Confidence:          {result.confidence * 100:.1f}%")
print(f"[+] Candidate Match IDs: {result.candidate_match_ids}")
print(f"[+] Requires Review:     {result.requires_human_review}")
print(f"[+] Citations:           {result.citations}")
print(f"[+] Evidence Count:      {len(result.evidence)}")
print("\n" + "=" * 60)

