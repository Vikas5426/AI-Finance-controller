import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from app.core.config import settings
from app.core.security import get_current_user
from app.db.database import get_db_context
from app.db import schema
from app.models.schemas import SourceKind
from app.services.ingestion import IngestionService
from app.services.normalizer import NormalizerService

router = APIRouter(prefix="/sources", tags=["Sources & Uploads"])

@router.get("/profiles")
def get_source_profiles(current_user: Dict[str, Any] = Depends(get_current_user)):
    with get_db_context() as db:
        profiles = db.query(schema.SourceProfile).filter_by(org_id=current_user["org_id"]).all()
        if profiles:
            return [
                {
                    "id": p.id,
                    "name": p.name,
                    "source_kind": p.source_kind,
                    "column_mapping": p.column_mapping,
                    "amount_scale": p.amount_scale,
                    "is_active": p.is_active
                }
                for p in profiles
            ]
        
        # Fallback default source profiles
        return [
            {
                "id": "prof_gateway_razorpay",
                "name": "Razorpay Standard Gateway",
                "source_kind": "GATEWAY",
                "column_mapping": {"payment_id": "payment_id", "amount": "amount", "fee": "fee", "tax": "tax", "date": "captured_at"}
            },
            {
                "id": "prof_bank_hdfc",
                "name": "HDFC Current Account",
                "source_kind": "BANK",
                "column_mapping": {"date": "Value Date", "credit": "Credit", "debit": "Debit", "ref": "Ref No"}
            },
            {
                "id": "prof_gl_netsuite",
                "name": "NetSuite General Ledger",
                "source_kind": "LEDGER",
                "column_mapping": {"je_id": "je_id", "debit": "debit", "credit": "credit", "doc_ref": "doc_ref"}
            }
        ]

@router.get("/uploads")
def get_uploads_list(
    limit: int = 50,
    offset: int = 0,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    org_id = current_user["org_id"]
    with get_db_context() as db:
        org_uploads = db.query(schema.Upload).filter(schema.Upload.org_id == org_id)
        uploads = org_uploads.order_by(schema.Upload.created_at.desc()).offset(offset).limit(limit).all()
        return {
            "total": org_uploads.count(),
            "items": [
                {
                    "id": u.id,
                    "file_name": u.file_name,
                    "file_size_bytes": u.file_size_bytes,
                    "file_hash": u.file_hash,
                    "total_rows": u.total_rows,
                    "accepted_rows": u.accepted_rows,
                    "status": u.status,
                    "created_at": u.created_at.isoformat() if u.created_at else None
                }
                for u in uploads
            ]
        }

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    source_kind: SourceKind = Form(...),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    file_hash = IngestionService.compute_file_hash(content)
    upload_id = str(uuid.uuid4())
    filename = file.filename or f"upload_{upload_id}.csv"
    save_path = os.path.join(settings.UPLOAD_DIR, f"{upload_id}_{filename}")
    
    with open(save_path, "wb") as f:
        f.write(content)

    # Parse and extract rows
    try:
        raw_rows = IngestionService.parse_file(save_path, source_kind)
        total_rows = len(raw_rows)
    except Exception as e:
        total_rows = 0

    # Persist Upload record to DB
    with get_db_context() as db:
        prof = db.query(schema.SourceProfile).filter_by(
            source_kind=source_kind.value, org_id=current_user["org_id"]
        ).first()
        prof_id = prof.id if prof else f"prof_{source_kind.value.lower()}"

        upload_record = schema.Upload(
            id=upload_id,
            # get_current_user guarantees both claims, so no fabricated
            # defaults: attributing an upload to "usr_analyst_01" when the
            # real actor is unknown falsifies the audit trail.
            org_id=current_user["org_id"],
            source_profile_id=prof_id,
            file_name=filename,
            file_size_bytes=len(content),
            file_hash=file_hash,
            storage_path=save_path,
            total_rows=total_rows,
            accepted_rows=total_rows,
            status="COMPLETED",
            uploaded_by=current_user["user_id"]
        )
        db.add(upload_record)
        db.commit()

    ledger_note = None
    if (source_kind == SourceKind.LEDGER or getattr(source_kind, "value", None) == "LEDGER") and total_rows > 0:
        je_ids = {str(NormalizerService._first_present(r, "je_id", "journal_id", "entry_id", "id") or "") for r in raw_rows}
        je_count = len([j for j in je_ids if j]) or len(raw_rows)
        ledger_note = f"{total_rows} journal lines collapsed into {je_count} economic entries"

    resp: Dict[str, Any] = {
        "upload_id": upload_id,
        "file_name": filename,
        "file_hash": file_hash,
        "file_size": len(content),
        "total_rows": total_rows,
        "accepted_rows": total_rows,
        "source_kind": source_kind,
        "status": "ACCEPTED"
    }
    if ledger_note:
        resp["note"] = ledger_note
    return resp

@router.post("/upload-batch")
async def upload_batch(
    files: List[UploadFile] = File(...),
    source_kinds: Optional[List[str]] = Form(None),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Ingests multiple financial CSV files simultaneously for multi-source reconciliation."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided for upload.")

    results = []
    for idx, file in enumerate(files):
        content = await file.read()
        if not content:
            continue

        file_hash = IngestionService.compute_file_hash(content)
        upload_id = str(uuid.uuid4())
        filename = file.filename or f"upload_{upload_id}.csv"
        save_path = os.path.join(settings.UPLOAD_DIR, f"{upload_id}_{filename}")

        with open(save_path, "wb") as f:
            f.write(content)

        # Determine source kind from form list or filename heuristics
        kind_str = None
        if source_kinds and idx < len(source_kinds):
            kind_str = source_kinds[idx]

        if not kind_str or kind_str == "AUTO":
            fn_lower = filename.lower()
            if "gateway" in fn_lower or "razorpay" in fn_lower or "stripe" in fn_lower or "pay" in fn_lower:
                kind_str = "GATEWAY"
            elif "bank" in fn_lower or "statement" in fn_lower or "hdfc" in fn_lower or "mt940" in fn_lower:
                kind_str = "BANK"
            elif "ledger" in fn_lower or "gl" in fn_lower or "netsuite" in fn_lower or "journal" in fn_lower:
                kind_str = "LEDGER"
            elif "settle" in fn_lower or "clearing" in fn_lower:
                kind_str = "SETTLEMENT"
            else:
                kind_str = "GATEWAY"

        try:
            s_kind = SourceKind(kind_str.upper())
        except Exception:
            s_kind = SourceKind.GATEWAY

        try:
            raw_rows = IngestionService.parse_file(save_path, s_kind)
            total_rows = len(raw_rows)
        except Exception:
            total_rows = 0

        with get_db_context() as db:
            prof = db.query(schema.SourceProfile).filter_by(
                source_kind=s_kind.value, org_id=current_user["org_id"]
            ).first()
            prof_id = prof.id if prof else f"prof_{s_kind.value.lower()}"

            upload_record = schema.Upload(
                id=upload_id,
                org_id=current_user["org_id"],
                source_profile_id=prof_id,
                file_name=filename,
                file_size_bytes=len(content),
                file_hash=file_hash,
                storage_path=save_path,
                total_rows=total_rows,
                accepted_rows=total_rows,
                status="COMPLETED",
                uploaded_by=current_user["user_id"]
            )
            db.add(upload_record)
            db.commit()

        ledger_note = None
        if (s_kind == SourceKind.LEDGER or getattr(s_kind, "value", None) == "LEDGER") and total_rows > 0:
            je_ids = {str(NormalizerService._first_present(r, "je_id", "journal_id", "entry_id", "id") or "") for r in raw_rows}
            je_count = len([j for j in je_ids if j]) or len(raw_rows)
            ledger_note = f"{total_rows} journal lines collapsed into {je_count} economic entries"

        res_item: Dict[str, Any] = {
            "upload_id": upload_id,
            "file_name": filename,
            "file_hash": file_hash,
            "file_size": len(content),
            "total_rows": total_rows,
            "source_kind": s_kind.value
        }
        if ledger_note:
            res_item["note"] = ledger_note
        results.append(res_item)

    return {
        "status": "SUCCESS",
        "uploaded_count": len(results),
        "items": results
    }

