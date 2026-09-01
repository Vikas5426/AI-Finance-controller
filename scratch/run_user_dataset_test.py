import csv
from datetime import datetime, timezone, date
from app.models.schemas import SourceKind, CanonicalTransaction, TxnDirection, ReferenceKeys
from app.services.normalizer import NormalizerService
from app.services.matching_engine import ReconciliationEngine
from app.services.ingestion import IngestionService

org_id = "ORG-TEST"
batch_id = "BATCH-USER-01"

gw_txns, gw_raw_count = IngestionService.ingest_and_normalize("data/gateway.csv", SourceKind.GATEWAY, org_id, batch_id)
bk_txns, bk_raw_count = IngestionService.ingest_and_normalize("data/bank.csv", SourceKind.BANK, org_id, batch_id)
gl_txns, gl_raw_count = IngestionService.ingest_and_normalize("data/general_ledger.csv", SourceKind.LEDGER, org_id, batch_id)

print("=== INGESTION SUMMARY ===")
print(f"Raw CSV Rows: Gateway={gw_raw_count}, Bank={bk_raw_count}, GL={gl_raw_count}, Total Raw={gw_raw_count + bk_raw_count + gl_raw_count}")
print(f"Canonical Entities: Gateway={len(gw_txns)}, Bank={len(bk_txns)}, GL={len(gl_txns)}, Total Canonical={len(gw_txns) + len(bk_txns) + len(gl_txns)}")

all_txns = gw_txns + bk_txns + gl_txns

# Compute unique gateway flow
unique_gw = {}
for t in gw_txns:
    if t.external_id not in unique_gw:
        unique_gw[t.external_id] = t.amount_minor
print(f"Unique Gateway IDs: {list(unique_gw.keys())}")
print(f"Unique Gateway Gross Flow: Rs. {sum(unique_gw.values())/100:.2f}")

engine = ReconciliationEngine(org_id=org_id, batch_id=batch_id)
summary = engine.run_full_pipeline(all_txns)

print("\n=== RECONCILIATION SUMMARY ===")
print("Matches Count:", len(engine.matches))
for m in engine.matches:
    print(f"  Match ID: {m.id[:8]} | Type: {m.match_type} | Method: {m.method} | Legs: {len(m.legs)} | Proof: {m.solver_evidence.get('tier') or m.solver_evidence.get('classification')}")

print("\nExceptions Count:", len(engine.exceptions))
for exc in engine.exceptions:
    p_t = next((t for t in all_txns if t.id == exc.primary_txn_id), None)
    ext = p_t.external_id if p_t else exc.primary_txn_id
    src = p_t.source_kind.value if p_t else "UNKNOWN"
    print(f"  Exception ID: {exc.id} | Type: {exc.exception_type} | Severity: {exc.severity} | Amount: Rs. {exc.impact_minor/100:.2f} | Source: {src} ({ext})")

print("\nReconciliation Graph Stats:")
print(summary["reconciliation_graph"])
