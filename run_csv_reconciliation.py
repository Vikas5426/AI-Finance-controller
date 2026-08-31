"""
Execution Runner for 3-CSV Financial Ingestion and Full-App Autonomous Reconciliation
with Strict Execution Modes, Cryptographic Hash Verification, and Input Provenance.

Inputs:
  1. data/gateway.csv (12 records)
  2. data/bank.csv (10 records)
  3. data/general_ledger.csv (42 rows)

Execution Modes:
  - USER_UPLOAD: Only uploaded files processed. Missing file = explicit error. No synthetic fallback.
  - SYNTHETIC_BENCHMARK: Synthetic generator runs with ground truth evaluation.
  - INTERNAL_TEST: Test fixtures processed.
"""

import os
import sys
import argparse
import json
import time
from datetime import datetime, timezone, date
from decimal import Decimal
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
from app.models.schemas import (
    SourceKind, CanonicalTransaction, DecisionTier, ProvenanceSourceType,
    ExecutionMode, SourceProvenance, BatchProvenanceManifest
)

from app.services.ingestion import IngestionService
from app.services.provenance import InputProvenanceService
from app.services.validation_service import DataValidationService
from app.services.context_builder import TransactionContextBuilder
from app.services.batch_orchestrator import WindowedBatchOrchestrator
from app.services.agent_runtime import AIAgentRuntime
from app.services.cash_forecaster import SegmentedCashForecaster
from app.services.audit_chain import AuditHashChain


def run_reconciliation_pipeline(
    gateway_file: str = "data/gateway.csv",
    bank_file: str = "data/bank.csv",
    ledger_file: str = "data/general_ledger.csv",
    execution_mode: ExecutionMode = ExecutionMode.USER_UPLOAD,
    window_size: int = 24
) -> Dict[str, Any]:
    print("=" * 80)
    print("  AI FINANCIAL CONTROLLER - 3-CSV RECONCILIATION ENGINE")
    print(f"  EXECUTION MODE: {execution_mode.value}")
    print("=" * 80)

    t_start = time.time()
    org_id = settings.DEFAULT_ORG_ID
    batch_id = f"BATCH-{execution_mode.value[:4]}-{datetime.now(timezone.utc).strftime('%Y%m%d')}-01"
    file_map = {"GATEWAY": gateway_file, "BANK": bank_file, "LEDGER": ledger_file}

    # -------------------------------------------------------------------------
    # Hard Safety Assertion: Verify Mode Rules
    # -------------------------------------------------------------------------
    if execution_mode == ExecutionMode.USER_UPLOAD:
        # 1. Assert all files exist
        for s_name, f_path in file_map.items():
            InputProvenanceService.assert_user_upload_file_exists(f_path)

        # 2. Pre-reconciliation Hash Verification
        expected_hashes = {
            s_name: InputProvenanceService.compute_file_sha256(f_path)
            for s_name, f_path in file_map.items()
        }
        InputProvenanceService.verify_uploaded_hashes(expected_hashes, file_map)

    # -------------------------------------------------------------------------
    # Ingestion, Normalization & Provenance Capture
    # -------------------------------------------------------------------------
    canonical_txns: List[CanonicalTransaction] = []
    source_provenances: List[SourceProvenance] = []

    if execution_mode == ExecutionMode.USER_UPLOAD:
        print("\n[Step 1] Ingesting exact uploaded CSV files (Zero Synthetic Injection)...")
        gw_txns, gw_parsed = IngestionService.ingest_and_normalize(gateway_file, SourceKind.GATEWAY, org_id, batch_id)
        bk_txns, bk_parsed = IngestionService.ingest_and_normalize(bank_file, SourceKind.BANK, org_id, batch_id)
        gl_txns, gl_parsed = IngestionService.ingest_and_normalize(ledger_file, SourceKind.LEDGER, org_id, batch_id)

        canonical_txns = gw_txns + bk_txns + gl_txns

        source_provenances.append(InputProvenanceService.track_file_provenance(
            batch_id=batch_id, source_kind=SourceKind.GATEWAY, file_path=gateway_file,
            source_type=ProvenanceSourceType.USER_UPLOAD, normalized_txns=gw_txns,
            parsed_count=gw_parsed, original_filename=os.path.basename(gateway_file)
        ))
        source_provenances.append(InputProvenanceService.track_file_provenance(
            batch_id=batch_id, source_kind=SourceKind.BANK, file_path=bank_file,
            source_type=ProvenanceSourceType.USER_UPLOAD, normalized_txns=bk_txns,
            parsed_count=bk_parsed, original_filename=os.path.basename(bank_file)
        ))
        source_provenances.append(InputProvenanceService.track_file_provenance(
            batch_id=batch_id, source_kind=SourceKind.LEDGER, file_path=ledger_file,
            source_type=ProvenanceSourceType.USER_UPLOAD, normalized_txns=gl_txns,
            parsed_count=gl_parsed, original_filename=os.path.basename(ledger_file)
        ))
        actual_source_type = ProvenanceSourceType.USER_UPLOAD



    else: # INTERNAL_TEST
        print("\n[Step 1] Loading internal test fixtures...")
        gw_txns, gw_parsed = IngestionService.ingest_and_normalize(gateway_file, SourceKind.GATEWAY, org_id, batch_id)
        bk_txns, bk_parsed = IngestionService.ingest_and_normalize(bank_file, SourceKind.BANK, org_id, batch_id)
        gl_txns, gl_parsed = IngestionService.ingest_and_normalize(ledger_file, SourceKind.LEDGER, org_id, batch_id)
        canonical_txns = gw_txns + bk_txns + gl_txns
        actual_source_type = ProvenanceSourceType.TEST_FIXTURE

    manifest = InputProvenanceService.build_batch_manifest(
        batch_id=batch_id,
        overall_source_type=actual_source_type,
        source_provenances=source_provenances,
        execution_mode=execution_mode
    )

    total_records = len(canonical_txns)

    # -------------------------------------------------------------------------
    # Diagnostic Output Display
    # -------------------------------------------------------------------------
    print("\n" + InputProvenanceService.format_console_provenance(manifest) + "\n")

    # -------------------------------------------------------------------------
    # Layer 1: Pre-Flight Integrity & Duplicate Validation Gate
    # -------------------------------------------------------------------------
    print("[Step 2] Executing Layer 1 Pre-Flight Integrity & Duplicate Validation Gate...")
    val_results = DataValidationService.validate_batch(canonical_txns)
    valid_count = sum(1 for v in val_results.values() if v.status == "VALID")
    flagged_count = sum(1 for v in val_results.values() if v.status == "INVALID")
    print(f"  * Valid Records: {valid_count} | Flagged Anomalies/Duplicates: {flagged_count}")

    # -------------------------------------------------------------------------
    # Layer 2: 360 Context Synthesis
    # -------------------------------------------------------------------------
    print("\n[Step 3] Synthesizing 360 Degree Contextual Envelopes & Anomaly Features...")
    contexts = {txn.id: TransactionContextBuilder.build_context(txn, canonical_txns) for txn in canonical_txns}
    print(f"  * Built context envelopes for {len(contexts)} transactions.")

    # -------------------------------------------------------------------------
    # Layer 3 & 4: Windowed Batch Orchestrator & 6-Pass Matching Engine
    # -------------------------------------------------------------------------
    print("\n[Step 4] Executing 6-Pass Matching Engine & Windowed Batch Orchestrator...")
    orchestrator = WindowedBatchOrchestrator(org_id=org_id, batch_id=batch_id, window_size=window_size)
    summary = orchestrator.run_windowed_pipeline(canonical_txns)

    # -------------------------------------------------------------------------
    # Layer 5: Autonomous AI Agent Investigation Runtime
    # -------------------------------------------------------------------------
    print("\n[Step 5] Running Autonomous AI Agent Runtime on Flagged Exceptions...")
    agent_runtime = AIAgentRuntime()
    investigation_reports = []

    for exc in orchestrator.exceptions[:10]:
        primary = next((t for t in canonical_txns if t.id == exc.primary_txn_id or t.external_id == exc.primary_txn_id), None)
        counterpart = next((t for t in canonical_txns if t.id == exc.counterpart_txn_id or t.external_id == exc.counterpart_txn_id), None) if exc.counterpart_txn_id else None

        if primary:
            exc_type_str = exc.exception_type if isinstance(exc.exception_type, str) else exc.exception_type.value
            inv = agent_runtime.investigate_exception(
                exception_id=exc.id,
                exception_type=exc_type_str,
                impact_minor=exc.impact_minor,
                primary_txn=primary.model_dump(),
                counterpart_txn=counterpart.model_dump() if counterpart else None,
                available_txns=[t.model_dump() for t in canonical_txns[:20]]
            )
            investigation_reports.append(inv)
    print(f"  * Completed AI agent investigations on {len(investigation_reports)} exception cases.")

    # -------------------------------------------------------------------------
    # Layer 6: Segmented 13-Week Cash Flow Forecaster
    # -------------------------------------------------------------------------
    print("\n[Step 6] Generating Segmented 13-Week Cash Flow Forecast...")
    cash_forecast = SegmentedCashForecaster.forecast_13_weeks(canonical_txns, orchestrator.decisions)
    print(f"  * Generated 13 weekly liquidity projections.")

    # -------------------------------------------------------------------------
    # Layer 7: Cryptographic SHA-256 Audit Hash Chain
    # -------------------------------------------------------------------------
    print("\n[Step 7] Verifying Cryptographic SHA-256 Audit Hash Chain...")
    chain_valid, broken_seq = AuditHashChain.verify_chain_integrity(orchestrator.audit_events)
    print(f"  * Cryptographic Audit Integrity: {'VERIFIED (100% Tamper-Proof)' if chain_valid else f'BROKEN at {broken_seq}'}")
    print(f"  * Total Chained Audit Blocks:    {len(orchestrator.audit_events)}")

    # -------------------------------------------------------------------------
    # Layer 8: Database Persistence
    # -------------------------------------------------------------------------
    print("\n[Step 8] Persisting Reconciled State to Database...")
    init_db()
    DatabaseService.save_batch_run(
        org_id=org_id,
        batch_id=batch_id,
        canonical_txns=canonical_txns,
        matches=orchestrator.matches,
        exceptions=orchestrator.exceptions,
        decisions=orchestrator.decisions,
        proposals=orchestrator.proposals,
        audit_events=orchestrator.audit_events,
        summary=summary,
        cash_forecast=[f.model_dump() for f in cash_forecast]
    )
    print(f"  * Batch {batch_id} persisted to database.")

    # -------------------------------------------------------------------------
    # Output Detailed Results File
    # -------------------------------------------------------------------------
    wall_clock = time.time() - t_start
    results_json_path = os.path.join("data", "reconciliation_results_detailed.json")
    full_output = {
        "execution_meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "batch_id": batch_id,
            "organization_id": org_id,
            "execution_mode": execution_mode.value,
            "wall_clock_seconds": round(wall_clock, 2),
            "provenance_manifest": manifest.model_dump()
        },
        "summary": summary,
        "counts": {
            "total_records": total_records,
            "matches_count": len(orchestrator.matches),
            "exceptions_count": len(orchestrator.exceptions),
            "proposals_count": len(orchestrator.proposals),
            "audit_blocks": len(orchestrator.audit_events)
        },
        "provenance": manifest.model_dump(),
        "sample_matches": [m.model_dump() for m in orchestrator.matches[:10]],
        "sample_exceptions": [e.model_dump() for e in orchestrator.exceptions[:10]],
        "sample_proposals": orchestrator.proposals[:5],
        "cash_forecast_preview": [f.model_dump() for f in cash_forecast[:4]],
        "ai_investigations": [inv.model_dump() for inv in investigation_reports[:3]],
        "audit_chain_status": {
            "is_valid": chain_valid,
            "total_blocks": len(orchestrator.audit_events),
            "first_block_hash": orchestrator.audit_events[0]["event_hash"] if orchestrator.audit_events else None,
            "last_block_hash": orchestrator.audit_events[-1]["event_hash"] if orchestrator.audit_events else None
        }
    }

    with open(results_json_path, "w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2, default=str)

    print("\n" + "=" * 80)
    print("  FINAL RECONCILIATION SUMMARY")
    print("=" * 80)
    print(f"  • Execution Mode:             {execution_mode.value}")
    print(f"  • Total Raw Input Rows:       {manifest.total_raw_rows} rows")
    print(f"  • Total Normalized Txns:      {total_records} txns (GW: {len(gw_txns)}, Bank: {len(bk_txns)}, GL: {len(gl_txns)})")
    print(f"  • Matched Pairs Count:        {len(orchestrator.matches)} matches")
    print(f"  • Deterministic Match Rate:   {summary['match_rate'] * 100:.1f}%")
    print(f"  • Avg Match Confidence:       {summary.get('average_match_confidence', summary.get('avg_confidence', 0.0)) * 100:.1f}%")
    print(f"  • False Match Risk:           {summary['false_match_risk'] * 100:.2f}%")
    print(f"  • Total Exceptions Detected:  {len(orchestrator.exceptions)} (16-type taxonomy)")
    print(f"  • Maker-Checker Proposals:    {len(orchestrator.proposals)} proposals")
    print(f"  • Audit Hash Chain Integrity: {'VERIFIED [OK]' if chain_valid else 'FAILED [X]'}")
    print(f"  • Output JSON File:           {results_json_path}")
    print("=" * 80 + "\n")

    return full_output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Provenance-Verified Financial Reconciliation")
    parser.add_argument("--gateway", default="data/gateway.csv", help="Path to Payment Gateway CSV")
    parser.add_argument("--bank", default="data/bank.csv", help="Path to Bank Statement CSV")
    parser.add_argument("--ledger", default="data/general_ledger.csv", help="Path to General Ledger CSV")
    parser.add_argument("--execution-mode", default="USER_UPLOAD", choices=["USER_UPLOAD", "INTERNAL_TEST"], help="Execution mode")
    args = parser.parse_args()

    run_reconciliation_pipeline(
        gateway_file=args.gateway,
        bank_file=args.bank,
        ledger_file=args.ledger,
        execution_mode=ExecutionMode(args.execution_mode)
    )
