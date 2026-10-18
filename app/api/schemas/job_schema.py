from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class JobStatusResponse(BaseModel):
    """
    Live view of one crawl execution, for either spider type.

    `queued` and `running` are reported separately on purpose: a caller seeing
    "queued" for a long time knows the backlog is deep, whereas a long "running"
    points at a stuck crawl. Collapsing both into one state hides that.
    """
    job_id: str
    job_type: Literal["card_list", "card_feature"]
    status: Literal["queued", "running", "completed", "error", "config_broken"]
    bank_code: str
    target_url: str
    card_key: Optional[str] = None
    batch_id: Optional[str] = None
    error: Optional[str] = None
    stats: Optional[dict] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    @classmethod
    def from_job(cls, job) -> "JobStatusResponse":
        return cls(
            job_id=job.job_id,
            job_type=job.job_type,
            status=job.status,
            bank_code=job.bank_code,
            target_url=job.target_url,
            card_key=job.card_key,
            batch_id=job.batch_id,
            error=job.error,
            stats=job.stats_json,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )


class CardFeatureResult(BaseModel):
    """
    Outcome of a card-feature job. The crawled content itself lives in Milvus,
    so what is returned here is the handle to it plus what the run produced.
    """
    card_key: str
    card_name: Optional[str] = None
    bank_code: str
    stats: Optional[dict] = None
