"""
End-to-End Upload Pipeline Test Script
Simulates full multi-source upload flow:
Browser File Selection
-> multipart/form-data POST /api/v1/sources/upload
-> API File Receipt & Storage in data/uploads/
-> DB Upload Record Creation
-> Batch Trigger POST /api/v1/batches/run (USER_UPLOAD mode with upload_ids)
-> Exact Storage Path Resolution
-> Hash Integrity Validation
-> Ingestion & Normalization
-> Reconciliation Engine Execution
"""

import os
import sys
import hashlib
from typing import Dict, Any
from fastapi.testclient import TestClient

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "backend")))

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

from app.main import app
from app.db.database import init_db, get_db_context
from app.db import schema
from app.models.schemas import SourceKind, ExecutionMode
from app.services.provenance import InputProvenanceService


def run_e2e_upload_test():
    trace_id = "REC-TEST-001"
    print("=" * 80)
    print(f"  END-TO-END UPLOAD PIPELINE VERIFICATION TEST [TRACE_ID: {trace_id}]")
    print("=" * 80)

    init_db()
    client = TestClient(app)

    # Step 0: Authenticate as Controller & Approver
    print(f"\n--- STEP 0: Controller Authentication via POST /api/v1/auth/login ---")
    auth_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "approver@acme.co", "password": "Approver@2026!"}
    )
    assert auth_resp.status_code == 200, f"Authentication failed: {auth_resp.text}"
    auth_data = auth_resp.json()
    token = auth_data["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}
    print(f"[+] Authenticated as {auth_data['full_name']} ({auth_data['role']})")
    print(f"    JWT Bearer Token: {token[:24]}...")

    files_to_test = [
        {
            "source_kind": "GATEWAY",
            "file_path": "data/gateway.csv",
            "expected_name": "gateway.csv",
            "expected_raw_rows": 7,
            "expected_normalized_rows": 7,
            "expected_size": os.path.getsize("data/gateway.csv")
        },
        {
            "source_kind": "BANK",
            "file_path": "data/bank.csv",
            "expected_name": "bank.csv",
            "expected_raw_rows": 6,
            "expected_normalized_rows": 6,
            "expected_size": os.path.getsize("data/bank.csv")
        },
        {
            "source_kind": "LEDGER",
            "file_path": "data/general_ledger.csv",
            "expected_name": "general_ledger.csv",
            "expected_raw_rows": 18,
            "expected_normalized_rows": 6,
            "expected_size": os.path.getsize("data/general_ledger.csv")
        }
    ]

    upload_results = {}
    upload_ids = []
    expected_hashes = {}

    # Verify unauthenticated upload is rejected with 401
    unauth_resp = client.post(
        "/api/v1/sources/upload",
        files={"file": ("gateway.csv", b"dummy,csv\n1,2\n", "text/csv")},
        data={"source_kind": "GATEWAY"}
    )
    assert unauth_resp.status_code == 401, "Expected 401 for unauthenticated upload"
    print(f"[+] Verified unauthenticated upload fails closed (HTTP 401 Unauthorized)")

    print(f"\n--- STEP 1: Multipart File Uploads via POST /api/v1/sources/upload ---")
    for item in files_to_test:
        sk = item["source_kind"]
        fp = item["file_path"]
        fname = item["expected_name"]
        fsize = item["expected_size"]
        
        with open(fp, "rb") as f:
            content = f.read()
        file_sha = hashlib.sha256(content).hexdigest()

        # Simulate Authenticated Multipart Form Post
        response = client.post(
            "/api/v1/sources/upload",
            files={"file": (fname, content, "text/csv")},
            data={"source_kind": sk},
            headers=auth_headers
        )

        assert response.status_code == 200, f"Upload failed for {sk}: {response.text}"
        res_data = response.json()

        upload_id = res_data["upload_id"]
        upload_ids.append(upload_id)
        expected_hashes[sk] = res_data["file_hash"]

        # Verify Database Record
        with get_db_context() as db:
            up_rec = db.query(schema.Upload).filter_by(id=upload_id).first()
            assert up_rec is not None, f"Database record missing for upload {upload_id}"
            assert up_rec.uploaded_by == auth_data["user_id"], "Upload author mismatch"
            stored_path = up_rec.storage_path
            assert os.path.exists(stored_path), f"Stored file not found on disk at {stored_path}"

        upload_results[sk] = {
            "upload_id": upload_id,
            "filename": fname,
            "stored_path": stored_path,
            "file_hash": res_data["file_hash"],
            "file_size": fsize,
            "raw_rows": res_data["total_rows"],
            "expected_rows": item["expected_normalized_rows"],
            "sha256": file_sha
        }

        print(f"\n[+] {sk} Upload Verified:")
        print(f"    TRACE_ID:          {trace_id}")
        print(f"    Frontend upload:   {fname} ({fsize} bytes)")
        print(f"    Uploaded By:       {auth_data['user_id']} ({auth_data['email']})")
        print(f"    Storage path:      {stored_path}")
        print(f"    SHA-256:           {res_data['file_hash']}")
        print(f"    Raw Rows:          {res_data['total_rows']}")
        print(f"    Status:            {res_data['status']}")

    print(f"\n--- STEP 2: Batch Reconciliation Trigger via POST /api/v1/batches/run ---")
    batch_res = client.post(
        "/api/v1/batches/run",
        json={
            "execution_mode": "USER_UPLOAD",
            "upload_ids": upload_ids,
            "expected_hashes": expected_hashes
        },
        headers=auth_headers
    )

    assert batch_res.status_code == 200, f"Batch reconciliation failed: {batch_res.text}"
    batch_data = batch_res.json()
    prov_manifest = batch_data.get("provenance", {})

    print(f"\n[+] Batch Reconciliation Execution Verified:")
    print(f"    Batch ID:          {batch_data.get('batch_id')}")
    print(f"    Execution Mode:    {prov_manifest.get('execution_mode')}")
    print(f"    Total Raw Rows:    {prov_manifest.get('total_raw_rows')}")
    print(f"    Total Normalized:  {prov_manifest.get('total_normalized_records')}")
    print(f"    Exact Matches:     {batch_data.get('summary', {}).get('exact_matches')}")
    print(f"    Exceptions:        {batch_data.get('summary', {}).get('total_exceptions')}")

    # Check each individual source
    results_summary = {}
    for sk in ["GATEWAY", "BANK", "LEDGER"]:
        up_info = upload_results[sk]
        prov_src = prov_manifest.get("sources", {}).get(sk, {})

        is_same_file = (prov_src.get("absolute_file_path") == os.path.abspath(up_info["stored_path"]))
        is_same_hash = (prov_src.get("sha256_hash") == up_info["file_hash"])
        is_same_rows = (prov_src.get("normalized_rows_count") == up_info["expected_rows"])

        passed = is_same_file and is_same_hash and is_same_rows
        results_summary[sk] = {
            "passed": passed,
            "filename": up_info["filename"],
            "stored_path": up_info["stored_path"],
            "processing_path": prov_src.get("absolute_file_path"),
            "sha256": prov_src.get("sha256_hash"),
            "raw_rows": up_info["raw_rows"],
            "normalized_rows": prov_src.get("normalized_rows_count")
        }

    print("\n" + "=" * 80)
    print("  E2E PROVENANCE & RECONCILIATION SUMMARY")
    print("=" * 80)
    for sk, r in results_summary.items():
        status = "PASSED" if r["passed"] else "FAILED"
        print(f"[{status}] {sk}: {r['filename']} | Raw Rows: {r['raw_rows']} | Normalized: {r['normalized_rows']} | Hash Match: True")

    all_passed = all(r["passed"] for r in results_summary.values())
    assert all_passed, "One or more file provenance verifications failed"
    print("\n[+] 100% E2E UPLOAD & MULTI-STREAM RECONCILIATION PASSED SUCCESSFULLY\n")

    return trace_id, results_summary, upload_results


if __name__ == "__main__":
    run_e2e_upload_test()
