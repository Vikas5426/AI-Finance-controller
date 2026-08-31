"""
Database Persistence & Repository Service for AI Financial Controller.
Handles atomic transaction writes, batch management, maker-checker audit chains,
and default organization/user seeding with Argon2 password hashing.
"""

import logging
import os
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select, func, desc, and_, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.database import get_db_context
from app.db import schema
from app.models.schemas import (
    CanonicalTransaction, SourceKind, DecisionTier, BatchWindowSummary,
    MatchSchema, ExceptionSchema, ExceptionSeverity, ExceptionState,
    ReconciliationDecision
)
from app.services.audit_chain import AuditHashChain

logger = logging.getLogger(__name__)

class DatabaseService:
    """Enterprise repository layer for financial batch processing & reconciliation."""

    @staticmethod
    def seed_default_data():
        """Seeds default Organization, SourceProfiles, and Controller accounts if not present."""
        with get_db_context() as db:
            # 1. Seed Organization
            org = db.query(schema.Organization).filter_by(id=settings.DEFAULT_ORG_ID).first()
            if not org:
                org = schema.Organization(
                    id=settings.DEFAULT_ORG_ID,
                    name=settings.DEFAULT_ORG_NAME,
                    base_currency=settings.BASE_CURRENCY,
                    materiality_threshold_minor=settings.MATERIALITY_THRESHOLD_MINOR
                )
                db.add(org)
                db.flush()

            # 2. Seed Default Controller Users with secure Argon2 hashes (Dev / Test only)
            if settings.APP_ENV.lower() in ("production", "prod") and not getattr(settings, "ALLOW_DEMO_SEED", False):
                logger.info("Production environment: Skipping demo user seed.")
            else:
                default_users = [
                    {
                        "id": "usr_analyst_01",
                        "email": "analyst@acme.co",
                        "full_name": "Senior Financial Analyst (Maker)",
                        "role": "analyst",
                        "approval_limit_minor": 500000,
                        "password": "Analyst@2026!"
                    },
                    {
                        "id": "usr_approver_01",
                        "email": "approver@acme.co",
                        "full_name": "Controller & Dual Approver (Checker)",
                        "role": "approver",
                        "approval_limit_minor": 50000000,
                        "password": "Approver@2026!"
                    },
                    {
                        "id": "usr_admin_01",
                        "email": "admin@acme.co",
                        "full_name": "System Administrator",
                        "role": "admin",
                        "approval_limit_minor": 100000000,
                        "password": "Admin@2026!"
                    }
                ]

                for u_data in default_users:
                    existing_user = db.query(schema.User).filter_by(email=u_data["email"]).first()
                    if not existing_user:
                        user_obj = schema.User(
                            id=u_data["id"],
                            org_id=settings.DEFAULT_ORG_ID,
                            email=u_data["email"],
                            password_hash=get_password_hash(u_data["password"]),
                            full_name=u_data["full_name"],
                            role=u_data["role"],
                            approval_limit_minor=u_data["approval_limit_minor"]
                        )
                        db.add(user_obj)

            # 3. Seed Source Profiles
            default_profiles = [
                {
                    "id": "prof_gateway_razorpay",
                    "name": "Razorpay Standard Gateway",
                    "source_kind": "GATEWAY",
                    "column_mapping": {"payment_id": "payment_id", "amount": "amount", "fee": "fee", "tax": "tax", "date": "captured_at", "order_id": "order_id"},
                    "date_formats": ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]
                },
                {
                    "id": "prof_bank_hdfc",
                    "name": "HDFC Current Account MT940",
                    "source_kind": "BANK",
                    "column_mapping": {"date": "Value Date", "credit": "Credit", "debit": "Debit", "ref": "Ref No", "description": "Description"},
                    "date_formats": ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]
                },
                {
                    "id": "prof_gl_netsuite",
                    "name": "NetSuite General Ledger ERP",
                    "source_kind": "LEDGER",
                    "column_mapping": {"je_id": "je_id", "debit": "debit", "credit": "credit", "doc_ref": "doc_ref", "account_code": "account_code", "date": "posting_date"},
                    "date_formats": ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S"]
                },
                {
                    "id": "prof_settlement_clearing",
                    "name": "Processor Settlement Batch Summary",
                    "source_kind": "SETTLEMENT",
                    "column_mapping": {"settlement_id": "settlement_id", "net_amount": "net_amount", "gross_amount": "gross_amount", "fee": "fee", "tax": "tax", "settled_at": "settled_at"},
                    "date_formats": ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S"]
                }
            ]

            for prof_data in default_profiles:
                existing_prof = db.query(schema.SourceProfile).filter_by(id=prof_data["id"]).first()
                if not existing_prof:
                    prof_obj = schema.SourceProfile(
                        id=prof_data["id"],
                        org_id=settings.DEFAULT_ORG_ID,
                        name=prof_data["name"],
                        source_kind=prof_data["source_kind"],
                        column_mapping=prof_data["column_mapping"],
                        date_formats=prof_data["date_formats"]
                    )
                    db.add(prof_obj)

            db.commit()

    @staticmethod
    def save_batch_run(
        org_id: str,
        batch_id: str,
        canonical_txns: List[CanonicalTransaction],
        matches: List[MatchSchema],
        exceptions: List[ExceptionSchema],
        decisions: Dict[str, ReconciliationDecision],
        proposals: List[Dict[str, Any]],
        audit_events: List[Dict[str, Any]],
        summary: Dict[str, Any],
        cash_forecast: List[Dict[str, Any]],
        created_by: Optional[str] = None,
        investigations: Optional[Dict[str, Any]] = None
    ) -> schema.Batch:
        """Atomically persists all entities generated during a reconciliation batch execution."""
        with get_db_context() as db:
            # 1. Upsert Batch
            batch_record = db.query(schema.Batch).filter_by(id=batch_id).first()
            if batch_record and batch_record.status == "COMPLETED":
                raise ValueError(
                    f"IMMUTABLE_BATCH_VIOLATION: Batch '{batch_id}' is already completed and immutable in the financial ledger. "
                    "Historical audited records cannot be overwritten. Please run with a unique batch ID."
                )

            if not batch_record:
                matched_records_val = summary.get("matched_records")
                if matched_records_val is None:
                    matched_records_val = summary.get("exact_matches", 0) * 2 + summary.get("contextual_matches", 0) * 2

                p_dates = []
                for t in canonical_txns:
                    if getattr(t, "occurred_at", None):
                        p_dates.append(t.occurred_at.date() if isinstance(t.occurred_at, datetime) else t.occurred_at)
                    if getattr(t, "value_date", None):
                        p_dates.append(t.value_date.date() if isinstance(t.value_date, datetime) else t.value_date)
                p_start = min(p_dates) if p_dates else date(2026, 3, 1)
                p_end = max(p_dates) if p_dates else date(2026, 3, 31)

                batch_record = schema.Batch(
                    id=batch_id,
                    org_id=org_id,
                    period_start=p_start,
                    period_end=p_end,
                    status="COMPLETED",
                    total_records=len(canonical_txns),
                    matched_records=matched_records_val,
                    exception_records=len(exceptions),
                    match_rate=Decimal(str(round(summary.get("match_rate", 0.0), 4))),
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc)
                )
                db.add(batch_record)
            else:
                matched_records_val = summary.get("matched_records")
                if matched_records_val is None:
                    matched_records_val = summary.get("exact_matches", 0) * 2 + summary.get("contextual_matches", 0) * 2

                batch_record.status = "COMPLETED"
                batch_record.total_records = len(canonical_txns)
                batch_record.matched_records = matched_records_val
                batch_record.exception_records = len(exceptions)
                batch_record.match_rate = Decimal(str(round(summary.get("match_rate", 0.0), 4)))
                batch_record.completed_at = datetime.now(timezone.utc)

            db.flush()

            # 2. Bulk Insert Transactions
            db_txns = []
            for t in canonical_txns:
                dec = decisions.get(t.id)
                status_str = dec.tier.value if dec and hasattr(dec.tier, "value") else (t.match_status.value if hasattr(t.match_status, "value") else str(t.match_status))
                
                # Format occurred_at
                occ_dt = t.occurred_at
                if isinstance(occ_dt, str):
                    try:
                        occ_dt = datetime.fromisoformat(occ_dt.replace("Z", "+00:00"))
                    except Exception:
                        occ_dt = datetime.now(timezone.utc)

                val_d = t.value_date
                if isinstance(val_d, str):
                    try:
                        val_d = date.fromisoformat(val_d)
                    except Exception:
                        val_d = date(2026, 3, 31)

                raw_txn_type = getattr(t, "txn_type", None)
                if raw_txn_type:
                    txn_type_str = raw_txn_type.value if hasattr(raw_txn_type, "value") else str(raw_txn_type)
                else:
                    txn_type_str = "PAYMENT" if t.direction.value == "INFLOW" else "SETTLEMENT"

                db_txn = schema.Transaction(
                    id=t.id,
                    org_id=org_id,
                    batch_id=batch_id,
                    source_kind=t.source_kind.value if hasattr(t.source_kind, "value") else str(t.source_kind),
                    external_id=t.external_id,
                    txn_type=txn_type_str,
                    direction=t.direction.value if hasattr(t.direction, "value") else str(t.direction),
                    amount_minor=t.amount_minor,
                    amount=Decimal(str(round(t.amount_minor / 100.0, 4))),
                    gross_minor=t.gross_minor,
                    fee_minor=t.fee_minor,
                    tax_minor=t.tax_minor,
                    currency=t.currency,
                    occurred_at=occ_dt,
                    value_date=val_d,
                    source_timezone=t.source_timezone,
                    counterparty_raw=t.counterparty_raw,
                    counterparty_norm=t.counterparty_norm,
                    description_raw=t.description_raw,
                    description_norm=t.description_norm,
                    reference_keys=t.reference_keys.model_dump() if hasattr(t.reference_keys, "model_dump") else (t.reference_keys if isinstance(t.reference_keys, dict) else {}),
                    account_code=t.account_code,
                    match_status=status_str,
                    normalizer_version="v1.0.0"
                )
                db_txns.append(db_txn)
            
            db.bulk_save_objects(db_txns)
            db.flush()

            # 3. Insert Matches & Legs
            for m in matches:
                status_val = m.decision_tier.value if hasattr(m, "decision_tier") else getattr(m, "status", "RESOLVED")
                db_m = schema.Match(
                    id=m.id,
                    org_id=org_id,
                    batch_id=batch_id,
                    match_type=m.match_type.value if hasattr(m.match_type, "value") else str(m.match_type),
                    method=m.method.value if hasattr(m.method, "value") else str(m.method),
                    score=Decimal(str(round(m.score, 4))),
                    confidence=Decimal(str(round(m.confidence, 4))),
                    status=status_val
                )
                db.add(db_m)
                db.flush()

                for leg in m.legs:
                    leg_id = getattr(leg, "id", str(uuid.uuid4()))
                    role_str = leg.role.value if hasattr(leg.role, "value") else str(leg.role)
                    db_leg = schema.MatchLeg(
                        id=leg_id,
                        match_id=m.id,
                        transaction_id=leg.transaction_id,
                        role=role_str,
                        signed_amount_minor=leg.signed_amount_minor
                    )
                    db.add(db_leg)

            # 4. Insert Exceptions
            for exc in exceptions:
                exc_state_str = exc.state.value if hasattr(exc.state, "value") else str(exc.state)
                db_exc = schema.ExceptionRecord(
                    id=exc.id,
                    org_id=org_id,
                    batch_id=batch_id,
                    primary_txn_id=exc.primary_txn_id,
                    counterpart_txn_id=exc.counterpart_txn_id,
                    exception_type=exc.exception_type,
                    severity=exc.severity.value if hasattr(exc.severity, "value") else str(exc.severity),
                    state=exc_state_str,
                    impact_minor=exc.impact_minor,
                    currency=exc.currency
                )
                db.add(db_exc)
            db.flush()

            # 5. Insert AI Investigations
            if investigations:
                for inv_key, inv_obj in investigations.items():
                    if hasattr(inv_obj, "exception_id"):
                        inv_id = f"INV-{inv_obj.exception_id}"
                        exc_id = inv_obj.exception_id
                        model_name = inv_obj.telemetry.get("model", "rule_engine_v1") if hasattr(inv_obj, "telemetry") and inv_obj.telemetry else "rule_engine_v1"
                        classification = inv_obj.classification
                        likely_cause = inv_obj.likely_cause
                        confidence = Decimal(str(round(inv_obj.confidence, 4)))
                        evidence = [e.model_dump() if hasattr(e, "model_dump") else e for e in inv_obj.evidence]
                        policy_citations = inv_obj.citations
                        tokens_prompt = inv_obj.telemetry.get("tokens_est", 0) if hasattr(inv_obj, "telemetry") and inv_obj.telemetry else 0
                        tokens_completion = inv_obj.telemetry.get("tokens_est", 0) if hasattr(inv_obj, "telemetry") and inv_obj.telemetry else 0
                        duration_ms = int(inv_obj.telemetry.get("latency_ms", 0)) if hasattr(inv_obj, "telemetry") and inv_obj.telemetry else 0
                    elif isinstance(inv_obj, dict):
                        inv_id = inv_obj.get("id", f"INV-{inv_obj.get('exception_id', inv_key)}")
                        exc_id = inv_obj.get("exception_id", inv_key)
                        model_name = inv_obj.get("model", "rule_engine_v1")
                        classification = inv_obj.get("classification", "AI_INVESTIGATION")
                        likely_cause = inv_obj.get("likely_cause", "")
                        confidence = Decimal(str(round(inv_obj.get("confidence", 0.90), 4)))
                        evidence = inv_obj.get("evidence", [])
                        policy_citations = inv_obj.get("policy_citations", [])
                        tokens_prompt = inv_obj.get("tokens_prompt", 0)
                        tokens_completion = inv_obj.get("tokens_completion", 0)
                        duration_ms = inv_obj.get("duration_ms", 0)
                    else:
                        continue

                    db_inv = schema.AIInvestigation(
                        id=inv_id,
                        org_id=org_id,
                        exception_id=exc_id,
                        model=model_name,
                        classification=classification,
                        likely_cause=likely_cause,
                        confidence=confidence,
                        evidence=evidence,
                        policy_citations=policy_citations,
                        tokens_prompt=tokens_prompt,
                        tokens_completion=tokens_completion,
                        duration_ms=duration_ms,
                        cost_inr=Decimal("0.0"),
                        created_at=datetime.now(timezone.utc)
                    )
                    db.add(db_inv)
                db.flush()

            # 6. Insert Proposals
            for p in proposals:
                inv_fk = p.get("investigation_id")
                if not inv_fk and investigations and p["exception_id"] in investigations:
                    inv_fk = f"INV-{p['exception_id']}"

                db_prop = schema.ResolutionProposal(
                    id=p["id"],
                    org_id=org_id,
                    exception_id=p["exception_id"],
                    investigation_id=inv_fk,
                    action=p["action"],
                    recommended_parameters=p.get("recommended_parameters", {}),
                    justification=p.get("justification", ""),
                    confidence=Decimal(str(round(p.get("confidence", 0.90), 4))),
                    requires_human_review=p.get("requires_human_review", True),
                    status=p.get("status", "PENDING_APPROVAL"),
                    verified_by_code=p.get("verified_by_code", False),
                    # The user who ran the batch is the maker of every voucher it
                    # raises. Recording it here is what lets the approval handler
                    # refuse a checker who is also the maker.
                    created_by=created_by
                )
                db.add(db_prop)
            db.flush()

            # 6. Insert Audit Events (if not already logged for this batch)
            existing_seqs = {e.event_seq for e in db.query(schema.AuditEvent.event_seq).filter_by(org_id=org_id, batch_id=batch_id).all()}
            for ev in audit_events:
                seq = ev.get("event_seq", 1)
                if seq not in existing_seqs:
                    ev_created = ev.get("created_at")
                    if isinstance(ev_created, str):
                        try:
                            ev_created = datetime.fromisoformat(ev_created)
                        except Exception:
                            ev_created = datetime.now(timezone.utc)
                    elif not isinstance(ev_created, datetime):
                        ev_created = datetime.now(timezone.utc)

                    db_ev = schema.AuditEvent(
                        id=str(uuid.uuid4()),
                        org_id=org_id,
                        batch_id=batch_id,
                        event_seq=seq,
                        event_type=ev.get("event_type", "BATCH_EVENT"),
                        entity_type=ev.get("entity_type", "BATCH"),
                        entity_id=ev.get("entity_id", batch_id),
                        actor_id=ev.get("actor_id", "usr_system"),
                        actor_type=ev.get("actor_type", "system"),
                        action=ev.get("action", "PROCESS"),
                        payload=ev.get("payload", {}),
                        prev_hash=ev.get("prev_hash", AuditHashChain.GENESIS_HASH),
                        event_hash=ev.get("event_hash", ""),
                        created_at=ev_created
                    )
                    db.add(db_ev)

            # 7. Upsert Batch Report
            import hashlib
            import json
            
            clean_summary = json.loads(json.dumps(summary, default=str))
            clean_forecast = json.loads(json.dumps(cash_forecast, default=str))

            rep_record = db.query(schema.BatchReport).filter_by(batch_id=batch_id).first()
            if not rep_record:
                rep_record = schema.BatchReport(
                    id=str(uuid.uuid4()),
                    org_id=org_id,
                    batch_id=batch_id,
                    report_json={"summary": clean_summary, "cash_forecast": clean_forecast},
                    report_hash=summary.get("report_hash", hashlib.sha256(b"report").hexdigest()),
                    match_rate=Decimal(str(round(summary.get("match_rate", 0.0), 4))),
                    precision_rate=Decimal(str(round(summary["precision_rate"], 4))) if summary.get("precision_rate") is not None else None,
                    recall_rate=Decimal(str(round(summary["recall_rate"], 4))) if summary.get("recall_rate") is not None else None,
                    f1_score=Decimal(str(round(summary["f1_score"], 4))) if summary.get("f1_score") is not None else None,
                    ece=Decimal(str(round(summary["ece"], 4))) if summary.get("ece") is not None else None,
                    records_per_second=Decimal(str(round(summary.get("records_per_second", len(canonical_txns) / max(0.001, summary.get("wall_clock_seconds", 0.05))), 2))),
                    total_exceptions=len(exceptions)
                )
                db.add(rep_record)
            else:
                rep_record.report_json = {"summary": clean_summary, "cash_forecast": clean_forecast}
                rep_record.match_rate = Decimal(str(round(summary.get("match_rate", 0.0), 4)))

            db.commit()
            return batch_record

    @staticmethod
    def get_batch_stats(batch_id: Optional[str] = None) -> Dict[str, Any]:
        """Calculates dynamic stats directly from the database."""
        with get_db_context() as db:
            target_batch = None
            if batch_id:
                target_batch = db.query(schema.Batch).filter_by(id=batch_id).first()
            if not target_batch:
                target_batch = db.query(schema.Batch).order_by(desc(schema.Batch.created_at)).first()

            if not target_batch:
                return {}

            b_id = target_batch.id
            total_txns = db.query(func.count(schema.Transaction.id)).filter_by(batch_id=b_id).scalar() or 0
            total_excs = db.query(func.count(schema.ExceptionRecord.id)).filter_by(batch_id=b_id).scalar() or 0
            pending_apprs = db.query(func.count(schema.ResolutionProposal.id)).join(
                schema.ExceptionRecord, schema.ResolutionProposal.exception_id == schema.ExceptionRecord.id
            ).filter(schema.ExceptionRecord.batch_id == b_id, schema.ResolutionProposal.status == "PENDING_APPROVAL").scalar() or 0
            audit_count = db.query(func.count(schema.AuditEvent.id)).filter_by(batch_id=b_id).scalar() or 0

            return {
                "batch_id": b_id,
                "total_records": total_txns,
                "total_exceptions": total_excs,
                "pending_approvals": pending_apprs,
                "audit_blocks_count": audit_count,
                "match_rate": float(target_batch.match_rate) if target_batch.match_rate else 0.0
            }

    @staticmethod
    def load_batch_context(org_id: str, batch_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Rebuilds a completed batch's reporting context from the database.

        The dashboard, executive summary and QA agent used to read this out of the
        process-global in-memory STATE dict, so every figure reverted to zero/None
        after a restart even though the run was fully persisted. This is the durable
        source of truth: same shape as STATE, but survives a restart and is scoped
        to one organisation.

        Returns a dict with ``batch`` set to None when the org has no batches.
        """
        empty: Dict[str, Any] = {
            "batch": None, "batch_id": None, "summary": {}, "quality_metrics": {},
            "windows": [], "cash_forecast": [], "stats": {},
            "exception_breakdown": {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0},
        }
        with get_db_context() as db:
            q = db.query(schema.Batch).filter(schema.Batch.org_id == org_id)
            if batch_id:
                b = q.filter(schema.Batch.id == batch_id).first()
            else:
                b = q.order_by(desc(schema.Batch.created_at)).first()
            if not b:
                return empty

            b_id = b.id
            report = db.query(schema.BatchReport).filter_by(batch_id=b_id, org_id=org_id).first()
            rep_json = (report.report_json if report and report.report_json else {}) or {}
            summary = rep_json.get("summary", {}) or {}

            def _sev(sev: str) -> int:
                return db.query(func.count(schema.ExceptionRecord.id)).filter_by(
                    org_id=org_id, batch_id=b_id, severity=sev
                ).scalar() or 0

            breakdown = {s: _sev(s) for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}
            total_excs = sum(breakdown.values())
            total_txns = db.query(func.count(schema.Transaction.id)).filter_by(
                org_id=org_id, batch_id=b_id
            ).scalar() or 0
            pending = db.query(func.count(schema.ResolutionProposal.id)).join(
                schema.ExceptionRecord, schema.ResolutionProposal.exception_id == schema.ExceptionRecord.id
            ).filter(
                schema.ExceptionRecord.batch_id == b_id,
                schema.ExceptionRecord.org_id == org_id,
                schema.ResolutionProposal.status == "PENDING_APPROVAL"
            ).scalar() or 0
            audit_count = db.query(func.count(schema.AuditEvent.id)).filter_by(
                org_id=org_id, batch_id=b_id
            ).scalar() or 0
            match_rate = float(b.match_rate) if b.match_rate is not None else summary.get("match_rate", 0.0)

            batch = {
                "id": b_id,
                "org_id": org_id,
                "period_start": b.period_start.isoformat() if b.period_start else None,
                "period_end": b.period_end.isoformat() if b.period_end else None,
                "status": b.status,
                "total_records": b.total_records or total_txns,
                "matched_records": b.matched_records or 0,
                "match_rate": match_rate,
                "execution_time_sec": summary.get("wall_clock_seconds", 0.0),
                "created_at": b.created_at.isoformat() if b.created_at else None,
            }

            quality_metrics = {
                "average_match_confidence": summary.get("average_match_confidence", summary.get("avg_confidence", 0.0)),
                "avg_confidence": summary.get("avg_confidence", 0.0),
                "false_match_risk": summary.get("false_match_risk", 0.0),
                "avg_investigation_depth": summary.get("avg_investigation_depth", 0.0),
                "exact_matches": summary.get("exact_matches", 0),
                "contextual_matches": summary.get("contextual_matches", 0),
                "needs_review_count": summary.get("needs_review_count", 0),
                "unresolved_exceptions": summary.get("unresolved_exceptions", total_excs),
                "critical_high_unresolved": summary.get("critical_high_unresolved", breakdown["CRITICAL"] + breakdown["HIGH"]),
                "total_unresolved_records": summary.get("total_unresolved_records", total_excs),
                "total_exceptions": summary.get("total_exceptions", total_excs),
                "safeguards_triggered_count": summary.get("safeguards_triggered_count", 0),
                "safeguards_breakdown": summary.get("safeguards_breakdown", []),
                "tier_breakdown": summary.get("tier_breakdown", {}),
                "match_rate": match_rate,
            }

            return {
                "batch": batch,
                "batch_id": b_id,
                "summary": summary,
                "quality_metrics": quality_metrics,
                "windows": summary.get("windows", []),
                "cash_forecast": rep_json.get("cash_forecast", []),
                "exception_breakdown": breakdown,
                "stats": {
                    "total_records": batch["total_records"],
                    "exact_matches": quality_metrics["exact_matches"],
                    "contextual_matches": quality_metrics["contextual_matches"],
                    "needs_review": quality_metrics["needs_review_count"],
                    "unresolved_exceptions": quality_metrics["unresolved_exceptions"],
                    "critical_high_unresolved": quality_metrics["critical_high_unresolved"],
                    "total_unresolved_records": quality_metrics["total_unresolved_records"],
                    "total_exceptions": quality_metrics["total_exceptions"],
                    "safeguards_triggered_count": quality_metrics["safeguards_triggered_count"],
                    "pending_approvals": pending,
                    "audit_blocks_count": audit_count,
                },
            }
