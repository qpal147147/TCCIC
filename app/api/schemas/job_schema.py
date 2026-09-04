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


class CardFeatureResult(BaseModel):
    """
    Outcome of a card-feature job. The crawled content itself lives in Milvus,
    so what is returned here is the handle to it plus what the run produced.
    """
    card_key: str
    card_name: Optional[str] = None
    bank_code: str
    stats: Optional[dict] = None
