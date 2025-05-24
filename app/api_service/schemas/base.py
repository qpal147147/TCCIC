from typing import Generic, TypeVar, Optional, Literal

from pydantic import BaseModel

DataT = TypeVar('DataT')

class BaseResponse(BaseModel, Generic[DataT]):
    """
    Generic API response schema
    """
    status: str = Literal["success", "fail"]
    message: str = ""
    error: Optional[str]
    data: Optional[dict]