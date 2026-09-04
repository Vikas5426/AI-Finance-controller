"""
Single source of truth for the reporting period.

Before this module the codebase carried six mutually contradictory hardcoded
period anchors:

    matching_engine.py     gw.value_date.month == 8 and gw.value_date.day == 31
    agent_runtime.py       "2026-03-31" in str(p_date)
    database_service.py    period_start=date(2026, 3, 1), period_end=date(2026, 3, 31)
    batches.py  STATE      "period_start": "2026-08-01", "period_end": "2026-08-31"
    context_builder.py     day in (28, 29, 30, 31) and hour >= 20
    normalizer.py          default_d: date = date(2026, 8, 20)

Each one silently disagreed with the others, so "is this a period cut-off
timing difference?" had a different answer depending on which module asked.

The period is now DERIVED from the data being reconciled (the min/max
value_date actually present), with an optional explicit config override.
Nothing else in the system is permitted to decide what the period is.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from app.core.config import settings


@dataclass(frozen=True)
class ReportingPeriod:
    """An immutable, explicitly-sourced reporting period."""

    start: date
    end: date
    source: str  # "CONFIG_OVERRIDE" | "DERIVED_FROM_DATA" | "FALLBACK_TODAY"

    # ------------------------------------------------------------------
    # Cut-off semantics — one definition, used everywhere
    # ------------------------------------------------------------------
    def is_cutoff_date(self, d: Optional[date], window_days: int = 1) -> bool:
        """
        True when `d` sits within `window_days` of either period boundary.

        This is the ONLY definition of "period cut-off" in the system. A
        transaction dated on or immediately around a boundary is the classic
        T+1/T+2 timing difference: booked in one period, settled in the next.
        """
        if d is None:
            return False
        d = _as_date(d)
        if d is None:
            return False
        return (
            abs((d - self.end).days) <= window_days
            or abs((d - self.start).days) <= window_days
        )

    def contains(self, d: Optional[date]) -> bool:
        d = _as_date(d)
        return d is not None and self.start <= d <= self.end

    def days(self) -> int:
        return (self.end - self.start).days + 1

    def next_period_start(self) -> date:
        return self.end + timedelta(days=1)

    def to_dict(self) -> dict:
        return {
            "period_start": self.start.isoformat(),
            "period_end": self.end.isoformat(),
            "period_source": self.source,
            "period_days": self.days(),
        }


def _as_date(val: Any) -> Optional[date]:
    """Coerce datetime / date / ISO string to a date without inventing one."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        txt = val.strip()
        if not txt:
            return None
        try:
            return datetime.fromisoformat(txt.replace("Z", "+00:00")).date()
        except Exception:
            try:
                return date.fromisoformat(txt[:10])
            except Exception:
                return None
    return None


def _config_override() -> Optional[ReportingPeriod]:
    s = _as_date(settings.PERIOD_START_OVERRIDE)
    e = _as_date(settings.PERIOD_END_OVERRIDE)
    if s and e and s <= e:
        return ReportingPeriod(start=s, end=e, source="CONFIG_OVERRIDE")
    return None


def derive_period(transactions: Iterable[Any]) -> ReportingPeriod:
    """
    Derive the reporting period from the transactions actually being reconciled.

    Uses the calendar month(s) spanned by the observed `value_date` values, so a
    batch of August data yields 2026-08-01 → 2026-08-31 regardless of which
    module is asking. An explicit config override always wins.

    Falls back to the current calendar month only when the batch carries no
    parseable dates at all — and says so via `source`, rather than quietly
    substituting an anchor.
    """
    override = _config_override()
    if override:
        return override

    observed: list[date] = []
    for txn in transactions or []:
        if isinstance(txn, dict):
            val = txn.get("value_date") or txn.get("occurred_at") or txn.get("date")
        else:
            val = getattr(txn, "value_date", None) or getattr(txn, "occurred_at", None)
        d = _as_date(val)
        if d is not None:
            observed.append(d)

    if not observed:
        today = datetime.now(timezone.utc).date()
        last_day = calendar.monthrange(today.year, today.month)[1]
        return ReportingPeriod(
            start=today.replace(day=1),
            end=today.replace(day=last_day),
            source="FALLBACK_TODAY",
        )

    lo, hi = min(observed), max(observed)
    last_day = calendar.monthrange(hi.year, hi.month)[1]
    return ReportingPeriod(
        start=lo.replace(day=1),
        end=hi.replace(day=last_day),
        source="DERIVED_FROM_DATA",
    )


def period_from_bounds(start: Any, end: Any, source: str = "DERIVED_FROM_DATA") -> Optional[ReportingPeriod]:
    """Rebuild a period from persisted bounds (e.g. a Batch row) without re-deriving."""
    s, e = _as_date(start), _as_date(end)
    if s and e and s <= e:
        return ReportingPeriod(start=s, end=e, source=source)
    return None
