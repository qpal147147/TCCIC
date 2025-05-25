from typing import Generic, TypeVar, Optional, Literal

from pydantic import BaseModel

DataT = TypeVar('DataT')

class BaseResponse(BaseModel, Generic[DataT]):
    """
    Generic API response schema
    """
    status: Literal["success", "fail"] = "fail"
    message: str = ""
    error: Optional[str] = None
    data: Optional[DataT] = None