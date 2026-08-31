"""
Durable Database-Backed Advisory Lock Manager.

Provides fail-closed, multi-process distributed locking for state-changing
reconciliation runs, approvals, and financial ledger writes.
Ensures single-run exclusivity across nodes even when Redis is unavailable.
"""

import uuid
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional, Tuple

from app.db.database import get_db_context
from app.db import schema

logger = logging.getLogger("finance_controller.lock")


class DatabaseLockManager:
    """Durable ACID lock manager using distributed_locks database table."""

    @classmethod
    def acquire_lock(cls, lock_key: str, timeout_sec: int = 45) -> Tuple[bool, Optional[str]]:
        """
        Attempts to acquire a durable database lock.
        Returns (True, owner_token) if acquired, (False, None) if currently held by another process.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        expires_at = now + timedelta(seconds=timeout_sec)
        token = str(uuid.uuid4())

        try:
            with get_db_context() as db:
                existing = db.query(schema.DistributedLock).filter_by(lock_key=lock_key).first()
                if existing:
                    # Check if the lock has expired (stale worker crash)
                    if existing.expires_at < now:
                        existing.owner_token = token
                        existing.expires_at = expires_at
                        existing.created_at = now
                        db.commit()
                        logger.info(f"db_lock_acquired (stale override): '{lock_key}' by token {token}")
                        return True, token
                    else:
                        logger.warning(f"db_lock_contended: Lock '{lock_key}' is actively held until {existing.expires_at}")
                        return False, None
                else:
                    new_lock = schema.DistributedLock(
                        lock_key=lock_key,
                        owner_token=token,
                        expires_at=expires_at,
                        created_at=now
                    )
                    db.add(new_lock)
                    db.commit()
                    logger.info(f"db_lock_acquired: '{lock_key}' by token {token}")
                    return True, token
        except Exception as e:
            logger.error(f"db_lock_error: Failed to acquire lock '{lock_key}': {e}")
            return False, None

    @classmethod
    def release_lock(cls, lock_key: str, token: str) -> bool:
        """
        Releases the lock only if the owner_token matches.
        """
        try:
            with get_db_context() as db:
                existing = db.query(schema.DistributedLock).filter_by(lock_key=lock_key, owner_token=token).first()
                if existing:
                    db.delete(existing)
                    db.commit()
                    logger.info(f"db_lock_released: '{lock_key}'")
                    return True
                return False
        except Exception as e:
            logger.warning(f"db_lock_release_error: Failed to release lock '{lock_key}': {e}")
            return False


@asynccontextmanager
async def acquire_durable_lock(
    lock_key: str,
    timeout_sec: int = 45
) -> AsyncGenerator[Tuple[bool, Optional[str]], None]:
    """
    Fail-closed async context manager for state-changing batch and approval operations.
    Yields (acquired: bool, token: Optional[str]).
    """
    acquired, token = DatabaseLockManager.acquire_lock(lock_key, timeout_sec=timeout_sec)
    try:
        yield acquired, token
    finally:
        if acquired and token:
            DatabaseLockManager.release_lock(lock_key, token)
