import csv
from datetime import datetime, timezone, date
from app.models.schemas import SourceKind, CanonicalTransaction, TxnDirection, ReferenceKeys
from app.services.normalizer import NormalizerService
from app.services.matching_engine import ReconciliationEngine
from app.services.ingestion import IngestionService

org_id = "ORG-TEST"
batch_id = "BATCH-USER-01"

# 1. Ingest & Normalize
with open("data/gateway.csv", "r", encoding="utf-8") as f:
    gw_rows = list(csv.DictReader(f))
for i, r in enumerate(gw_rows, start=1):
    r["__row_num__"] = i

with open("data/bank.csv", "r", encoding="utf-8") as f:
    bk_rows = list(csv.DictReader(f))
for i, r in enumerate(bk_rows, start=1):
    r["__row_num__"] = i

with open("data/general_ledger.csv", "r", encoding="utf-8") as f:
    gl_rows = list(csv.DictReader(f))
for i, r in enumerate(gl_rows, start=1):
    r["__row_num__"] = i

print(f"Raw CSV Row Counts: Gateway={len(gw_rows)}, Bank={len(bk_rows)}, GL={len(gl_rows)}, Total={len(gw_rows) + len(bk_rows) + len(gl_rows)}")

# Normalize Gateway
gw_txns = [NormalizerService.normalize_row(r, SourceKind.GATEWAY, org_id, batch_id) for r in gw_rows]
# Normalize Bank
bk_txns = [NormalizerService.normalize_row(r, SourceKind.BANK, org_id, batch_id) for r in bk_rows]
# Normalize GL (aggregated)
gl_txns = NormalizerService.aggregate_gl_lines(gl_rows, org_id, batch_id)

print(f"Canonical Entity Counts: Gateway={len(gw_txns)}, Bank={len(bk_txns)}, GL={len(gl_txns)}, Total Canonical={len(gw_txns) + len(bk_txns) + len(gl_txns)}")

all_txns = gw_txns + bk_txns + gl_txns

# Calculate Gross Flow Volume (Unique economic flow: unique gateway + unmatched bank)
unique_gw = {}
for g in gw_txns:
    if g.external_id not in unique_gw:
        unique_gw[g.external_id] = g.amount_minor
unique_gross_paise = sum(unique_gw.values())
print(f"Unique Gateway Gross Volume: Rs. {unique_gross_paise / 100:.2f}")

engine = ReconciliationEngine(org_id=org_id, batch_id=batch_id)
summary = engine.run_full_pipeline(all_txns)

print("\n--- RECONCILIATION SUMMARY ---")
print(f"Matches count: {len(engine.matches)}")
print(f"Exceptions count: {len(engine.exceptions)}")
for exc in engine.exceptions:
    print(f"  Exception: {exc.id} | Type: {exc.exception_type} | Amount: Rs. {exc.impact_minor / 100:.2f} | Txn: {exc.primary_txn_id}")

total_exc_impact = sum(e.impact_minor for e in engine.exceptions)
print(f"Total Exception Exposure: Rs. {total_exc_impact / 100:.2f}")

print("\n--- MATCHES ---")
for m in engine.matches:
    print(f"  Match {m.id[:8]} | Type: {m.match_type} | Method: {m.method} | Evidence: {m.solver_evidence.get('tier') or m.solver_evidence.get('classification')}")
