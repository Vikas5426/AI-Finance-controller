import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

class AuditHashChain:
    """Provides cryptographic tamper-evident logging for financial actions."""

    GENESIS_HASH = "0" * 64

    @staticmethod
    def canonical_json(data: Dict[str, Any]) -> str:
        """Deterministically serializes JSON for hashing without whitespace."""
        return json.dumps(data, sort_keys=True, separators=(',', ':'), default=str)

    @classmethod
    def compute_event_hash(
        cls,
        prev_hash: str,
        org_id: str,
        event_seq: int,
        event_type: str,
        entity_id: str,
        actor_id: str,
        payload: Dict[str, Any],
        created_at: Any
    ) -> str:
        from datetime import datetime, timezone
        if isinstance(created_at, str):
            ts_str = created_at
        elif isinstance(created_at, datetime):
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            ts_str = created_at.astimezone(timezone.utc).isoformat()
        else:
            ts_str = str(created_at)

        payload_str = cls.canonical_json(payload)
        preimage = f"{prev_hash}|{org_id}|{event_seq}|{event_type}|{entity_id}|{actor_id}|{ts_str}|{payload_str}"
        return hashlib.sha256(preimage.encode("utf-8")).hexdigest()

    @classmethod
    def verify_chain_integrity(cls, events: List[Dict[str, Any]]) -> Tuple[bool, Optional[int]]:
        """
        Validates the entire hash chain sequentially.
        Returns (True, None) if valid, or (False, broken_sequence_number).
        """
        expected_prev_hash = cls.GENESIS_HASH
        
        for event in events:
            # 1. Verify prev_hash matches prior block
            if event["prev_hash"] != expected_prev_hash:
                return False, event["event_seq"]

            # 2. Re-compute hash
            ts = event.get("created_at")
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except Exception:
                    ts = datetime.now()

            org_id_val = str(event.get("org_id", "00000000-0000-0000-0000-000000000001"))
            recomputed = cls.compute_event_hash(
                prev_hash=event.get("prev_hash", cls.GENESIS_HASH),
                org_id=org_id_val,
                event_seq=event.get("event_seq", 1),
                event_type=event.get("event_type", "BATCH_EVENT"),
                entity_id=str(event.get("entity_id", "")),
                actor_id=str(event.get("actor_id", "usr_system")),
                payload=event.get("payload", {}),
                created_at=ts
            )

            # 3. Verify event_hash equality
            if recomputed != event.get("event_hash"):
                return False, event.get("event_seq")

            expected_prev_hash = event.get("event_hash")

        return True, None
