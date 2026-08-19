"""
Repository layer over the metadata store.

Callers (routers, RAG, spiders) go through these classes and never write SQL or
touch a session directly. Each method owns a short-lived session, which is why a
repository instance is safe to use from several threads.

Status vocabularies are enforced here rather than by DB constraints — this layer
is the only writer, so it is the enforcement point.
"""

import logging
from typing import Optional, Literal, get_args

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.services.store.models import (
    ACTIVE_JOB_STATUSES,
    CallbackStatus,
    Card,
    CardChunk,
    CardStatus,
    CrawlJob,
    JobStatus,
    JobType,
    SummaryCache,
    utcnow,
)

logger = logging.getLogger(__name__)

# Derived from the Literal aliases so the vocabulary is defined in one place.
_JOB_TYPES = frozenset(get_args(JobType))
_JOB_STATUSES = frozenset(get_args(JobStatus))
_CARD_STATUSES = frozenset(get_args(CardStatus))
_CALLBACK_STATUSES = frozenset(get_args(CallbackStatus))


def _require(value: str, allowed: frozenset[str]) -> str:
    if value not in allowed:
        raise ValueError(f"Invalid '{value}'. Allowed: {sorted(allowed)}.")
    return value


class ChunkInput(BaseModel):
    """One unit of a card's content, as produced by a crawl."""
    seq: int
    page_url: str
    content_hash: str
    section: Optional[str] = None


class _BaseRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory


class CardRepository(_BaseRepository):
    """Card catalog — the stable identity layer that job records and vectors hang off."""

    def upsert(self, bank_code: str, card_name: str, card_url: str) -> Card:
        """
        Register a card, or refresh its name if already known.

        Returns the row either way, so callers can treat "first crawl" and
        "re-crawl" identically and just read `card_key` off the result.
        """
        card_key = Card.make_key(bank_code, card_url)
        with self._session_factory() as session:
            card = session.get(Card, card_key)
            if card is None:
                card = Card(
                    card_key=card_key,
                    bank_code=bank_code,
                    card_name=card_name,
                    card_url=card_url,
                    first_seen_at=utcnow(),
                )
                session.add(card)
                logger.info(f"Registered new card '{card_name}' ({bank_code}) as {card_key[:8]}.")
            elif card.card_name != card_name:
                # Banks rename cards; identity is the URL, so follow the rename.
                card.card_name = card_name
            session.commit()
            return card

    def get(self, card_key: str) -> Optional[Card]:
        with self._session_factory() as session:
            return session.get(Card, card_key)

    def get_by_url(self, card_url: str) -> Optional[Card]:
        with self._session_factory() as session:
            return session.scalar(select(Card).where(Card.card_url == card_url))

    def list(self, bank_code: Optional[str] = None, status: Optional[str] = "active") -> list[Card]:
        """List cards, by default only those still on sale."""
        stmt = select(Card)
        if bank_code:
            stmt = stmt.where(Card.bank_code == bank_code)
        if status:
            stmt = stmt.where(Card.status == _require(status, _CARD_STATUSES))
        stmt = stmt.order_by(Card.bank_code, Card.card_name)
        with self._session_factory() as session:
            return list(session.scalars(stmt))

    def update_facts(self, card_key: str, facts: dict) -> Optional[Card]:
        """Store the structured attributes extracted by the LLM (E1)."""
        with self._session_factory() as session:
            card = session.get(Card, card_key)
            if card is None:
                return None
            card.facts_json = facts
            session.commit()
            return card

    def mark_crawled(self, card_key: str, content_changed: bool = False) -> Optional[Card]:
        """
        Record that a crawl finished.

        `content_changed` separates "we looked" from "it actually differed",
        which is what makes it possible to tell a stale card from a stable one.
        """
        now = utcnow()
        with self._session_factory() as session:
            card = session.get(Card, card_key)
            if card is None:
                return None
            card.last_crawled_at = now
            if content_changed:
                card.last_changed_at = now
            session.commit()
            return card

    def set_status(self, card_key: str, status: str) -> Optional[Card]:
        """Mark a card active or delisted. Delisted cards are kept, never deleted."""
        _require(status, _CARD_STATUSES)
        with self._session_factory() as session:
            card = session.get(Card, card_key)
            if card is None:
                return None
            card.status = status
            session.commit()
            return card


class JobRepository(_BaseRepository):
    """Crawl job lifecycle."""

    def create(
        self,
        job_id: str,
        job_type: str,
        bank_code: str,
        target_url: str,
        card_key: Optional[str] = None,
        batch_id: Optional[str] = None,
        callback_url: Optional[str] = None,
    ) -> CrawlJob:
        _require(job_type, _JOB_TYPES)
        with self._session_factory() as session:
            job = CrawlJob(
                job_id=job_id,
                job_type=job_type,
                bank_code=bank_code,
                target_url=target_url,
                card_key=card_key,
                batch_id=batch_id,
                callback_url=callback_url,
                callback_status="pending" if callback_url else None,
                status="queued",
                created_at=utcnow(),
            )
            session.add(job)
            session.commit()
            return job

    def get(self, job_id: str) -> Optional[CrawlJob]:
        with self._session_factory() as session:
            return session.get(CrawlJob, job_id)

    def mark_running(self, job_id: str) -> Optional[CrawlJob]:
        with self._session_factory() as session:
            job = session.get(CrawlJob, job_id)
            if job is None:
                return None
            job.status = "running"
            job.started_at = utcnow()
            session.commit()
            return job

    def mark_completed(
        self,
        job_id: str,
        stats: Optional[dict] = None,
        artifact_dir: Optional[str] = None,
    ) -> Optional[CrawlJob]:
        with self._session_factory() as session:
            job = session.get(CrawlJob, job_id)
            if job is None:
                return None
            job.status = "completed"
            job.finished_at = utcnow()
            if stats is not None:
                job.stats_json = stats
            if artifact_dir is not None:
                job.artifact_dir = artifact_dir
            session.commit()
            return job

    def mark_failed(
        self,
        job_id: str,
        error: str,
        status: Literal["error", "config_broken"] = "error",
        stats: Optional[dict] = None,
    ) -> Optional[CrawlJob]:
        """
        End a job unsuccessfully.

        `status` distinguishes a plain failure from `config_broken`, which means
        the crawl ran but the bank's selectors no longer match anything.
        """
        _require(status, _JOB_STATUSES)
        with self._session_factory() as session:
            job = session.get(CrawlJob, job_id)
            if job is None:
                return None
            job.status = status
            job.error = error
            job.finished_at = utcnow()
            if stats is not None:
                job.stats_json = stats
            session.commit()
            return job

    def find_active_by_card_key(self, card_key: str) -> Optional[CrawlJob]:
        """
        The queued-or-running job for a card, if any.

        Backs the idempotency rule: a duplicate submission returns the existing
        job instead of crawling the same card twice and having both fight over
        the same vectors.
        """
        stmt = (
            select(CrawlJob)
            .where(CrawlJob.card_key == card_key, CrawlJob.status.in_(ACTIVE_JOB_STATUSES))
            .order_by(CrawlJob.created_at)
        )
        with self._session_factory() as session:
            return session.scalars(stmt).first()

    def last_completed_for_card(self, card_key: str) -> Optional[CrawlJob]:
        """
        The most recent successful job for a card — the baseline that breakage
        detection compares this run's stats against.
        """
        stmt = (
            select(CrawlJob)
            .where(CrawlJob.card_key == card_key, CrawlJob.status == "completed")
            .order_by(CrawlJob.finished_at.desc())
        )
        with self._session_factory() as session:
            return session.scalars(stmt).first()

    def list_by_batch(self, batch_id: str) -> list[CrawlJob]:
        stmt = select(CrawlJob).where(CrawlJob.batch_id == batch_id).order_by(CrawlJob.created_at)
        with self._session_factory() as session:
            return list(session.scalars(stmt))

    def set_callback_status(self, job_id: str, status: str) -> Optional[CrawlJob]:
        _require(status, _CALLBACK_STATUSES)
        with self._session_factory() as session:
            job = session.get(CrawlJob, job_id)
            if job is None:
                return None
            job.callback_status = status
            session.commit()
            return job


class ChunkRepository(_BaseRepository):
    """
    Which chunks currently compose each card.

    Together with the summary cache this is what allows the vector store to be
    rebuilt offline — no crawling and no LLM calls.
    """

    def replace_for_card(self, card_key: str, chunks: list[ChunkInput]) -> int:
        """
        Swap a card's entire composition in one transaction.

        Whole-card replacement mirrors how the vectors are rebuilt, so the two
        stores cannot drift into disagreeing about what a card contains.
        """
        now = utcnow()
        with self._session_factory() as session:
            session.query(CardChunk).filter(CardChunk.card_key == card_key).delete()
            session.add_all([
                CardChunk(
                    card_key=card_key,
                    seq=chunk.seq,
                    section=chunk.section,
                    page_url=chunk.page_url,
                    content_hash=chunk.content_hash,
                    updated_at=now,
                )
                for chunk in chunks
            ])
            session.commit()
            return len(chunks)

    def list_for_card(self, card_key: str) -> list[CardChunk]:
        stmt = select(CardChunk).where(CardChunk.card_key == card_key).order_by(CardChunk.seq)
        with self._session_factory() as session:
            return list(session.scalars(stmt))

    def delete_for_card(self, card_key: str) -> int:
        with self._session_factory() as session:
            deleted = session.query(CardChunk).filter(CardChunk.card_key == card_key).delete()
            session.commit()
            return deleted


class SummaryCacheRepository(_BaseRepository):
    """Content-addressed cache of LLM summaries."""

    def get(
        self,
        content_hash: str,
        model_name: str,
        prompt_ver: str,
        touch: bool = True,
    ) -> Optional[str]:
        """
        Return a cached summary, or None to mean "call the model".

        `touch` records the reuse; pass False when merely inspecting the cache so
        the savings figures stay honest.
        """
        with self._session_factory() as session:
            entry = session.get(SummaryCache, (content_hash, model_name, prompt_ver))
            if entry is None:
                return None
            if touch:
                entry.hit_count += 1
                entry.last_hit_at = utcnow()
                session.commit()
            return entry.summary

    def put(self, content_hash: str, model_name: str, prompt_ver: str, summary: str) -> SummaryCache:
        """Store a freshly generated summary, overwriting any entry for the same key."""
        with self._session_factory() as session:
            entry = session.get(SummaryCache, (content_hash, model_name, prompt_ver))
            if entry is None:
                entry = SummaryCache(
                    content_hash=content_hash,
                    model_name=model_name,
                    prompt_ver=prompt_ver,
                    summary=summary,
                    created_at=utcnow(),
                )
                session.add(entry)
            else:
                entry.summary = summary
            session.commit()
            return entry

    def stats(self) -> dict:
        """Entry count and total reuse — how much the cache has actually saved."""
        with self._session_factory() as session:
            entries = session.scalar(select(func.count()).select_from(SummaryCache)) or 0
            hits = session.scalar(select(func.coalesce(func.sum(SummaryCache.hit_count), 0))) or 0
            return {"entries": int(entries), "total_hits": int(hits)}
