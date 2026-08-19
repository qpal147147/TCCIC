"""
Metadata store — the system of record for jobs, the card catalog, card
composition and cached LLM summaries.

Milvus holds only a projection of this data and can be rebuilt from
`card_chunks` joined with `summary_cache`, which is what makes changing the
embedding model or the collection schema an offline, zero-LLM-cost operation.

Usage:
    store = Store(global_settings.METADATA_DB_PATH)
    job = store.jobs.create(job_id, "card_feature", bank_code, card_url)
"""

from app.services.store.database import Store, create_db_engine
from app.services.store.models import (
    Base,
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
from app.services.store.repositories import (
    CardRepository,
    ChunkInput,
    ChunkRepository,
    JobRepository,
    SummaryCacheRepository,
)

__all__ = [
    "Store",
    "create_db_engine",
    "Base",
    "Card",
    "CrawlJob",
    "CardChunk",
    "SummaryCache",
    "JobType",
    "JobStatus",
    "CardStatus",
    "CallbackStatus",
    "utcnow",
    "CardRepository",
    "JobRepository",
    "ChunkRepository",
    "SummaryCacheRepository",
    "ChunkInput",
]
