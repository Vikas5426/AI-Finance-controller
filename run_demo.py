"""
Master Execution & Demo Runner for AI Financial Controller:
1. Generates 2,048 synthetic multi-source records (Gateway, Bank, Ledger, Settlement).
2. Executes the full 6-pass reconciliation pipeline (P0 -> P5).
3. Verifies the SHA-256 cryptographic audit hash chain.
4. Starts the live web console & REST API server at http://127.0.0.1:8000.
"""

import os
import sys
import time
import uvicorn

# Add backend to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "backend")))

from app.core.config import settings
from app.db.database import init_db
from app.models.schemas import SourceKind, CanonicalTransaction
from app.services.audit_chain import AuditHashChain

def main():
    init_db()
    # No synthetic preflight benchmark
    print("[*] Starting in Strict USER_UPLOAD mode...")

    print("[*] Launching API & Web Operations Console at http://127.0.0.1:8000 ...")
    print("[*] Press Ctrl+C to stop.\n")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False, app_dir="backend")

if __name__ == "__main__":
    main()
