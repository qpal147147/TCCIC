"""
Engine, session factory and the `Store` facade for the metadata store.

Deliberately synchronous: crawl workers already run in threads via
`asyncio.to_thread`, and SQLite operations are microsecond-scale, so a sync
session keeps one code path instead of two. Blocking the event loop for that
long inside an async endpoint is not measurable next to an LLM call.
"""

import logging
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.store.models import Base
from app.services.store.repositories import (
    CardRepository,
    ChunkRepository,
    JobRepository,
    SummaryCacheRepository,
)

logger = logging.getLogger(__name__)

def _apply_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """
    Applied to every new pooled connection.

    journal_mode=WAL lets API threads read job status while a worker thread
    writes it, instead of the two blocking each other. busy_timeout replaces an
    instant "database is locked" error with a short wait, which is what makes
    concurrent workers safe on one file. synchronous=NORMAL skips an fsync per
    commit — transactions stay atomic either way, the trade is that a few
    committed rows could be lost on OS crash or power loss, which is acceptable
    for a store whose contents can all be recomputed.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def create_db_engine(db_path: str) -> Engine:
    """Build an SQLite engine configured for multi-threaded access."""
    if db_path == ":memory:":
        # An in-memory database belongs to its connection, so without StaticPool
        # every session would open a fresh empty one and lose the schema.
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            f"sqlite:///{db_path}",
            # Connections are handed between threads by the pool; SQLite is safe
            # here because the pool guarantees one user at a time.
            connect_args={"check_same_thread": False},
        )

    event.listen(engine, "connect", _apply_sqlite_pragmas)
    return engine


class Store:
    """
    Entry point to the metadata store. Holds the engine and exposes one
    repository per table.

    Repositories open and close their own short-lived session per call, so an
    instance is safe to share across threads. Returned ORM objects are detached
    but fully loaded (there are no relationships, hence no lazy loading); mutate
    through repository methods rather than by assigning to them.
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.engine = create_db_engine(db_path)
        self.session_factory = sessionmaker(
            bind=self.engine,
            # Detached instances keep their loaded values, so callers can read a
            # returned object after its session has closed.
            expire_on_commit=False,
            class_=Session,
        )

        self.cards = CardRepository(self.session_factory)
        self.jobs = JobRepository(self.session_factory)
        self.chunks = ChunkRepository(self.session_factory)
        self.summaries = SummaryCacheRepository(self.session_factory)

        logger.info(f"Metadata store opened at '{db_path}'.")

    def create_all(self) -> None:
        """
        Create tables straight from the models.

        For tests and first-run bootstrap only — Alembic owns the schema in
        normal operation so migrations stay the single history of changes.
        """
        Base.metadata.create_all(self.engine)

    def close(self) -> None:
        self.engine.dispose()
