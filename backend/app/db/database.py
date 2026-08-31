from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import settings

# SQLite / Postgres Engine
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _apply_lightweight_migrations() -> None:
    """
    Brings an existing database up to the current schema.

    ``create_all`` only creates missing tables; it never adds a column or an index
    to a table that already exists. This project has no migration tool, so each
    change is expressed here as an idempotent statement. Failures are reported
    rather than swallowed: a constraint that silently fails to apply is worse than
    one that was never written, because the code above it assumes it holds.
    """
    import sqlalchemy

    additive = [
        ("audit_events.batch_id", "ALTER TABLE audit_events ADD COLUMN batch_id VARCHAR(36)"),
        ("resolution_proposals.created_by", "ALTER TABLE resolution_proposals ADD COLUMN created_by VARCHAR(36)"),
    ]

    with engine.connect() as conn:
        for label, stmt in additive:
            try:
                conn.execute(sqlalchemy.text(stmt))
                conn.commit()
                print(f"[migration] added {label}")
            except Exception as exc:
                # "duplicate column" means the migration already ran, which is the
                # expected steady state. Anything else is surfaced.
                conn.rollback()
                msg = str(exc).lower()
                if "duplicate column" not in msg and "already exists" not in msg:
                    print(f"[migration] WARNING: could not add {label}: {exc}")

        # One approval per proposal. Applied as a unique index because neither
        # SQLite nor an existing Postgres table accepts ADD CONSTRAINT portably.
        try:
            dupes = conn.execute(sqlalchemy.text(
                "SELECT proposal_id, COUNT(*) c FROM approvals GROUP BY proposal_id HAVING c > 1"
            )).fetchall()
            if dupes:
                # Deleting historical approval rows is not something this code will
                # do unprompted; an operator has to decide which decision stands.
                print(
                    "[migration] WARNING: approvals(proposal_id) is not unique for "
                    f"{len(dupes)} proposal(s): {', '.join(str(d[0]) for d in dupes[:5])}. "
                    "The uq_approvals_proposal_id index was NOT created. Reconcile the "
                    "duplicate decisions, then restart. The API-level terminal-state "
                    "guard remains in force in the meantime."
                )
            else:
                conn.execute(sqlalchemy.text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_approvals_proposal_id ON approvals (proposal_id)"
                ))
                conn.commit()
        except Exception as exc:
            conn.rollback()
            print(f"[migration] WARNING: could not enforce unique approvals(proposal_id): {exc}")


def init_db():
    from app.db import schema
    from app.db.database_service import DatabaseService
    Base.metadata.create_all(bind=engine)
    _apply_lightweight_migrations()
    DatabaseService.seed_default_data()
