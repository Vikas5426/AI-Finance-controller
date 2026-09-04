"""
Dedicated External CSV Reconciliation Test Harness
Strictly isolated from synthetic benchmarks:
- Never imports or invokes SyntheticDataGenerator
- Never overwrites input files
- Never calculates synthetic benchmark metrics without ground truth
- Ingests and reconciles only exact external CSV files
"""

import os
import sys
import csv
import json
import time
import hashlib
import argparse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "backend")))

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.core.config import settings
from app.db.database import init_db
from app.db.database_service import DatabaseService
from app.models.schemas import SourceKind, CanonicalTransaction
from app.services.ingestion import IngestionService
from app.services.validation_service import DataValidationService
from app.services.context_builder import TransactionContextBuilder
from app.services.batch_orchestrator import WindowedBatchOrchestrator
from app.services.agent_runtime import AIAgentRuntime
from app.services.audit_chain import AuditHashChain


def compute_sha256(file_path: str) -> str:
    """Computes SHA-256 cryptographic hash of a file on disk."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


def count_raw_csv_rows(file_path: str) -> int:
    """Counts non-empty data rows in a CSV file (excluding the header)."""
    count = 0
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        try:
            next(reader) # Skip header
        except StopIteration:
            return 0
        for row in reader:
            if row and any(field.strip() for field in row):
                count += 1
    return count


def verify_file_exists(file_path: str, label: str) -> str:
    """Strictly checks file existence or raises explicit error."""
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
        raise FileNotFoundError(
            f"USER_INPUT_FILE_NOT_FOUND: {label} file not found at '{abs_path}'"
        )
    return abs_path


def run_external_reconciliation(
    gateway_path: str,
    bank_path: str,
    ledger_path: str,
    window_size: int = 24,
    output_json_path: str = "data/external_reconciliation_report.json"
) -> Dict[str, Any]:
    t_start = time.time()
    batch_id = f"BATCH-EXT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    org_id = settings.DEFAULT_ORG_ID

    # 1. Verify existence
    gw_abs = verify_file_exists(gateway_path, "Gateway")
    bk_abs = verify_file_exists(bank_path, "Bank")
    gl_abs = verify_file_exists(ledger_path, "General Ledger")

    # 2. Compute Hashes & Sizes
    gw_sha = compute_sha256(gw_abs)
    bk_sha = compute_sha256(bk_abs)
    gl_sha = compute_sha256(gl_abs)

    gw_size = os.path.getsize(gw_abs)
    bk_size = os.path.getsize(bk_abs)
    gl_size = os.path.getsize(gl_abs)

    # 3. Count raw rows
    gw_raw_rows = count_raw_csv_rows(gw_abs)
    bk_raw_rows = count_raw_csv_rows(bk_abs)
    gl_raw_rows = count_raw_csv_rows(gl_abs)

    # 4. Ingest and Normalize
    gw_txns, gw_parsed = IngestionService.ingest_and_normalize(gw_abs, SourceKind.GATEWAY, org_id, batch_id)
    bk_txns, bk_parsed = IngestionService.ingest_and_normalize(bk_abs, SourceKind.BANK, org_id, batch_id)
    gl_txns, gl_parsed = IngestionService.ingest_and_normalize(gl_abs, SourceKind.LEDGER, org_id, batch_id)

    # Extract sample IDs
    gw_sample_ids = [t.external_id for t in gw_txns[:3]]
    bk_sample_ids = [t.external_id for t in bk_txns[:3]]
    gl_sample_ids = [t.external_id for t in gl_txns[:3]]

    # -------------------------------------------------------------------------
    # Required Pre-Reconciliation Diagnostic Banner
    # -------------------------------------------------------------------------
    print("=" * 80)
    print("EXTERNAL TEST MODE")
    print("Synthetic generator: DISABLED")
    print("=" * 80)
    print(f"Gateway file: {gw_abs}")
    print(f"  • SHA256:     {gw_sha}")
    print(f"  • File size:  {gw_size} bytes")
    print(f"  • Raw rows:   {gw_raw_rows}")
    print(f"  • Normalized: {len(gw_txns)}")
    print()
    print(f"Bank file:    {bk_abs}")
    print(f"  • SHA256:     {bk_sha}")
    print(f"  • File size:  {bk_size} bytes")
    print(f"  • Raw rows:   {bk_raw_rows}")
    print(f"  • Normalized: {len(bk_txns)}")
    print()
    print(f"Ledger file:  {gl_abs}")
    print(f"  • SHA256:     {gl_sha}")
    print(f"  • File size:  {gl_size} bytes")
    print(f"  • Raw rows:   {gl_raw_rows}")
    print(f"  • Normalized: {len(gl_txns)}")
    print()
    print("Sample Identifiers:")
    print("Gateway IDs:")
    for sid in gw_sample_ids:
        print(f"  • {sid}")
    print()
    print("Bank IDs:")
    for sid in bk_sample_ids:
        print(f"  • {sid}")
    print()
    print("Ledger IDs:")
    for sid in gl_sample_ids:
        print(f"  • {sid}")
    print("=" * 80)

    # 5. Pre-flight Validation
    all_txns = gw_txns + bk_txns + gl_txns
    total_records = len(all_txns)
    val_results = DataValidationService.validate_batch(all_txns)
    valid_count = sum(1 for v in val_results.values() if v.status == "VALID")
    flagged_count = sum(1 for v in val_results.values() if v.status == "INVALID")

    # 6. Context Synthesis
    contexts = {t.id: TransactionContextBuilder.build_context(t, all_txns) for t in all_txns}

    # 7. Production 6-Pass Matching Pipeline
    orchestrator = WindowedBatchOrchestrator(org_id=org_id, batch_id=batch_id, window_size=window_size)
    summary = orchestrator.run_windowed_pipeline(all_txns)

    # 8. AI Agent Investigation on Material Exceptions (Scoped & Priority-Gated)
    agent_runtime = AIAgentRuntime()
    agent_runtime.reset_stats()
    investigations = []
    
    for exc in orchestrator.exceptions:
        primary = next((t for t in all_txns if t.id == exc.primary_txn_id), None)
        counterpart = next((t for t in all_txns if t.id == exc.counterpart_txn_id), None) if exc.counterpart_txn_id else None
        if primary:
            exc_type_str = exc.exception_type if isinstance(exc.exception_type, str) else exc.exception_type.value
            severity_str = exc.severity if isinstance(exc.severity, str) else exc.severity.value
            has_det_rule = exc_type_str in (
                "TIMING_DIFFERENCE_PERIOD_CUTOFF",
                "DUPLICATE_GATEWAY_WEBHOOK",
                "DUPLICATE_LEDGER_POSTING",
                "AMOUNT_TOLERANCE_MINOR"
            )
            inv = agent_runtime.investigate_exception(
                exception_id=exc.id,
                exception_type=exc_type_str,
                impact_minor=exc.impact_minor,
                primary_txn=primary.model_dump(),
                counterpart_txn=counterpart.model_dump() if counterpart else None,
                available_txns=[t.model_dump() for t in all_txns],
                severity=severity_str,
                has_deterministic_rule=has_det_rule
            )
            investigations.append(inv)

    ai_audit_stats = agent_runtime.get_audit_summary()

    # 10. Audit Chain Verification
    chain_valid, broken_seq = AuditHashChain.verify_chain_integrity(orchestrator.audit_events)

    # 11. Database Persistence
    init_db()
    DatabaseService.save_batch_run(
        org_id=org_id,
        batch_id=batch_id,
        canonical_txns=all_txns,
        matches=orchestrator.matches,
        exceptions=orchestrator.exceptions,
        decisions=orchestrator.decisions,
        proposals=orchestrator.proposals,
        audit_events=orchestrator.audit_events,
        summary=summary
    )

    wall_clock = time.time() - t_start

    # 12. Build Detailed JSON Report
    report = {
        "execution_metadata": {
            "harness_name": "External CSV Reconciliation Test Harness",
            "execution_mode": "EXTERNAL_USER_FILES_ONLY",
            "synthetic_generator": "DISABLED",
            "batch_id": batch_id,
            "organization_id": org_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "wall_clock_seconds": round(wall_clock, 2),
            "files": {
                "gateway": {
                    "path": gw_abs,
                    "sha256": gw_sha,
                    "file_size_bytes": gw_size,
                    "raw_rows": gw_raw_rows,
                    "normalized_count": len(gw_txns),
                    "sample_ids": gw_sample_ids
                },
                "bank": {
                    "path": bk_abs,
                    "sha256": bk_sha,
                    "file_size_bytes": bk_size,
                    "raw_rows": bk_raw_rows,
                    "normalized_count": len(bk_txns),
                    "sample_ids": bk_sample_ids
                },
                "ledger": {
                    "path": gl_abs,
                    "sha256": gl_sha,
                    "file_size_bytes": gl_size,
                    "raw_rows": gl_raw_rows,
                    "normalized_count": len(gl_txns),
                    "sample_ids": gl_sample_ids
                }
            }
        },
        "reconciliation_summary": {
            "total_input_rows": gw_raw_rows + bk_raw_rows + gl_raw_rows,
            "total_canonical_transactions": total_records,
            "matched_pairs_count": len(orchestrator.matches),
            "exact_matches": summary.get("exact_matches", 0),
            "contextual_matches": summary.get("contextual_matches", 0),
            "exceptions_count": len(orchestrator.exceptions),
            "proposals_count": len(orchestrator.proposals),
            "deterministic_match_rate": summary.get("match_rate", 0.0),
            "audit_blocks_chained": len(orchestrator.audit_events),
            "audit_chain_tamper_proof": chain_valid
        },
        "ai_usage_audit": ai_audit_stats,
        "matches": [m.model_dump() for m in orchestrator.matches],
        "exceptions": [e.model_dump() for e in orchestrator.exceptions],
        "proposals": orchestrator.proposals,
        "ai_investigations": [inv.model_dump() for inv in investigations]
    }

    os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print("\n" + "-" * 80)
    print("EXTERNAL RECONCILIATION EXECUTION COMPLETE")
    print("-" * 80)
    print(f"Total Transactions Processed: {total_records} (GW: {len(gw_txns)}, Bank: {len(bk_txns)}, GL: {len(gl_txns)})")
    print(f"Matched Pairs Count:          {len(orchestrator.matches)}")
    print(f"Exceptions Detected:          {len(orchestrator.exceptions)}")
    print(f"Maker-Checker Proposals:      {len(orchestrator.proposals)}")
    print(f"Audit Trail Integrity:        {'VERIFIED (100% Tamper-Proof)' if chain_valid else 'FAILED'}")
    print()
    print("AI USAGE & TELEMETRY AUDIT:")
    print(f"  • Total Exceptions:                    {ai_audit_stats['total_exceptions']}")
    print(f"  • Deterministically Resolved (No AI):  {ai_audit_stats['deterministically_resolved']}")
    print(f"  • AI Investigated (Ambiguity/Root-Cause): {ai_audit_stats['ai_investigated']}")
    print(f"  • Manual Review Queue:                 {ai_audit_stats['manual_review']}")
    print(f"  • Unnecessary AI Calls Avoided:        {ai_audit_stats['ai_avoided']}")
    print(f"  • Cache Hits (L1 Memory):              {ai_audit_stats['cache_hits']}")
    print(f"Execution Duration:                      {wall_clock:.2f}s")
    print(f"Report JSON Saved:                       {output_json_path}")
    print("-" * 80 + "\n")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="External CSV Reconciliation Test Harness")
    parser.add_argument("--gateway", default="data/gateway.csv", help="Path to Gateway CSV")
    parser.add_argument("--bank", default="data/bank.csv", help="Path to Bank Statement CSV")
    parser.add_argument("--ledger", default="data/general_ledger.csv", help="Path to General Ledger CSV")
    parser.add_argument("--window-size", type=int, default=24, help="Window size for orchestrator")
    parser.add_argument("--output", default="data/external_reconciliation_report.json", help="Path for output JSON report")
    args = parser.parse_args()

    run_external_reconciliation(
        gateway_path=args.gateway,
        bank_path=args.bank,
        ledger_path=args.ledger,
        window_size=args.window_size,
        output_json_path=args.output
    )
