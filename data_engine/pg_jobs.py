"""PostgreSQL-backed job store.

It has the same three methods as the in-memory JobStore (create / get / update) and returns
the same kind of dictionaries, so the API does not know which one it is talking to.
The difference: jobs are rows in a database, so they survive a server restart.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, String, Text, create_engine, update as sql_update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    """One row per job. `params` and `result` are JSONB: queryable JSON stored in a column."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seconds: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)


UPDATABLE = {"status", "finished_at", "seconds", "error", "result"}


def _iso(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec = "seconds") if moment else None


def _to_dict(row):
    # Same shape and the same timestamp format (ISO strings) as the in-memory store.
    return {
        "id": row.id,
        "status": row.status,
        "params": row.params,
        "created_at": _iso(row.created_at),
        "finished_at": _iso(row.finished_at),
        "seconds": row.seconds,
        "error": row.error,
        "result": row.result,
    }

class PostgresJobStore:
    def __init__(self, url):
        # pool_pre_ping checks a pooled connection is still alive before using it,
        # so a database restart does not leave the API holding dead connections.
        self._engine = create_engine(url, pool_pre_ping=True)
        self._sessions = sessionmaker(self._engine, expire_on_commit=False)

    def init_schema(self):
        """Create the jobs table if it is missing. (Real schema migrations come later.)"""
        Base.metadata.create_all(self._engine)

    def dispose(self):
        """Close the connection pool."""
        self._engine.dispose()

    def create(self, params):
        row = JobRow(
            id=uuid.uuid4().hex,
            status="queued",
            params=params,
            created_at=datetime.now(timezone.utc),
        )
        with self._sessions.begin() as session:  # commits when the block ends
            session.add(row)
        return _to_dict(row)

    def get(self, job_id):
        with self._sessions() as session:
            row = session.get(JobRow, job_id)
            return _to_dict(row) if row else None

    def update(self, job_id, **fields):
        unknown = set(fields) - UPDATABLE
        if unknown:
            raise ValueError(f"cannot update unknown job fields: {sorted(unknown)}")
        if isinstance(fields.get("finished_at"), str):
            fields["finished_at"] = datetime.fromisoformat(fields["finished_at"])
        with self._sessions.begin() as session:
            outcome = session.execute(sql_update(JobRow).where(JobRow.id == job_id).values(**fields))
            if outcome.rowcount == 0:
                raise KeyError(job_id)