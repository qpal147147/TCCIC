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
    Job ID response schema
    """
    job_id: str
    list_id: Optional[str] = None
    bank_code: Optional[str] = None
    card_name: Optional[str] = None
    card_id: Optional[str] = None