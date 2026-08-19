"""
SQLAlchemy models for the TCCIC metadata store.

This relational store is the system of record for everything that is *not* a vector:
job lifecycle, the card catalog, which chunks currently compose a card, and the
LLM summary cache. Milvus holds only a projection that can be rebuilt at any time
from `card_chunks` joined with `summary_cache`.

Timestamps are stored as UTC. SQLite returns them as naive datetimes on read;
they are always to be interpreted as UTC.
"""

import hashlib
from datetime import datetime, timezone
from typing import Literal, Optional

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# --- status vocabularies -----------------------------------------------------
# Kept as Literal aliases rather than DB-level CHECK constraints: only the
# repository layer writes these columns, so it is the enforcement point, and
# adding a state stays a code-only change (SQLite cannot alter a CHECK without
# rebuilding the table).

JobType = Literal["card_list", "card_feature"]
JobStatus = Literal["queued", "running", "completed", "error", "config_broken"]
CardStatus = Literal["active", "delisted"]
CallbackStatus = Literal["pending", "delivered", "failed"]

ACTIVE_JOB_STATUSES: frozenset[str] = frozenset({"queued", "running"})


def utcnow() -> datetime:
    """Current UTC time. Single source of truth so tests can patch one place."""
    return datetime.now(timezone.utc)


class UtcDateTime(TypeDecorator):
    """
    A datetime column that always round-trips as timezone-aware UTC.

    SQLite discards tzinfo on write, so a value just created in Python would be
    aware while the same value read back is naive — and comparing the two fails
    even though they are the same instant. Normalising on both sides keeps every
    timestamp in the store directly comparable, and stays correct on Postgres
    (timestamptz) if the store is ever moved there.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: Optional[datetime], dialect) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class Card(Base):
    """
    Card catalog — one row per real-world credit card, keyed by a stable natural key.

    `card_key` is derived from (bank_code, card_url) so that re-crawling the same
    card always lands on the same row. This is what makes "delete then re-insert"
    a safe whole-card rebuild in Milvus, and what external systems can hold on to
    permanently.

    Business attributes live in `facts_json` rather than in dedicated columns:
    adding a new filter dimension then costs a Pydantic field plus a WHERE branch,
    never an ALTER TABLE. Promote a fact to an expression index if it ever gets hot.
    """

    __tablename__ = "cards"

    card_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    bank_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    card_name: Mapped[str] = mapped_column(String(128), nullable=False)
    card_url: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)

    facts_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    first_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    last_crawled_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime, nullable=True)
    # Last time the crawled content actually differed from the previous crawl,
    # as opposed to merely being re-crawled and found unchanged.
    last_changed_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime, nullable=True)

    @staticmethod
    def make_key(bank_code: str, card_url: str) -> str:
        """Stable identity for a card. Same bank + same URL always yields the same key."""
        return hashlib.sha1(f"{bank_code}|{card_url}".encode("utf-8")).hexdigest()

    def __repr__(self) -> str:
        return f"<Card {self.card_key[:8]} {self.bank_code}/{self.card_name}>"


class CrawlJob(Base):
    """
    One crawl execution. Replaces feature_job_status.txt + FileLock.

    Serves both spider types so a single status endpoint can cover them, and
    carries the observability (`stats_json`) that breakage detection and cache
    accounting read back later.
    """

    __tablename__ = "crawl_jobs"

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Shared by every job submitted in one batch request; NULL for single submissions.
    batch_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

    bank_code: Mapped[str] = mapped_column(String(32), nullable=False)
    # Indexed via the composite idx_jobs_card_status below, whose leftmost column
    # this is — a separate single-column index would be redundant.
    card_key: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    target_url: Mapped[str] = mapped_column(String(1024), nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    artifact_dir: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # e.g. {"images": 15, "llm_calls": 3, "cache_hits": 12} — read by breakage detection
    stats_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    callback_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    callback_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime, nullable=True)

    __table_args__ = (
        # Backs the idempotency check: "is this card already queued or running?"
        Index("idx_jobs_card_status", "card_key", "status"),
    )

    def __repr__(self) -> str:
        return f"<CrawlJob {self.job_id[:8]} {self.job_type} {self.status}>"


class CardChunk(Base):
    """
    What a card currently consists of, in order.

    summary_cache is content-addressed and therefore cannot say which summaries
    belong to which card; this table supplies exactly that, which is what makes
    "rebuild Milvus from SQLite" possible (join on content_hash). Rows for a card
    are replaced wholesale on every successful crawl, mirroring the whole-card
    rebuild done in the vector store.

    `seq` completes the primary key so one card can hold many chunks, and keeps
    their original order stable across rebuilds.

    No FK to summary_cache on purpose: cache eviction must never cascade into
    deleting a card's composition.
    """

    __tablename__ = "card_chunks"

    card_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Topic section (C2): 優惠活動 / 年費 / 申請資格 ... NULL until chunk splitting lands.
    section: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    page_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return f"<CardChunk {self.card_key[:8]}#{self.seq} {self.section}>"


class SummaryCache(Base):
    """
    Content-addressed LLM summary cache — the mechanism that makes monthly
    re-crawls cheap: crawl every time, pay the vision model only for content
    that actually changed.

    The primary key is composite on (content_hash, model_name, prompt_ver) rather
    than filtering on those columns, so switching Gemini models back and forth
    (as quota dictates) keeps every model's cache intact and instantly reusable.
    `prompt_ver` is expected to be a hash of the prompt text, so editing the
    prompt invalidates automatically with no version number to remember to bump.

    There is no "invalid" flag by design: changed content yields a different
    content_hash and a different model or prompt yields a different key, so a
    stale row simply stops matching. Keeping it costs a little space and pays off
    if the same model is selected again later.

    `hit_count` / `last_hit_at` are observability only — they record reuse during
    vectorization (Q&A never touches this table) so cache savings can be measured.
    """

    __tablename__ = "summary_cache"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    prompt_ver: Mapped[str] = mapped_column(String(32), primary_key=True)

    summary: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    last_hit_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime, nullable=True)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<SummaryCache {self.content_hash[:8]} {self.model_name} hits={self.hit_count}>"
