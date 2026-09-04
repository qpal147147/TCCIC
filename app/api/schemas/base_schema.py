from typing import Generic, TypeVar, Optional, Literal

from pydantic import BaseModel

DataT = TypeVar('DataT')

class BaseResponse(BaseModel, Generic[DataT]):
    """
    Generic API response schema
    """
    status: Literal["success", "fail"] = "fail"
    message: str = ""
    data: Optional[DataT] = None
    error: Optional[str] = None

class JobIDResponse(BaseModel):
    """
    Acknowledgement returned when a crawl job is accepted.

    `job_id` identifies this execution and is the only handle needed to poll
    status or fetch results. `card_key` identifies the card itself and stays the
    same across re-crawls, so callers can store it permanently.
    """
    job_id: str
    bank_code: Optional[str] = None
    card_name: Optional[str] = None
    card_key: Optional[str] = None