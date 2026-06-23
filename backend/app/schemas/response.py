from typing import Generic, TypeVar
from enum import IntEnum
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ErrorCode(IntEnum):
    SUCCESS = 0
    PARAM_ERROR = 1001
    DATA_NOT_FOUND = 1002
    INTERNAL_ERROR = 5001


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: T | None = None

    model_config = ConfigDict(from_attributes=True)


def success(data: T | None = None, message: str = "success") -> dict:
    return {"code": ErrorCode.SUCCESS, "message": message, "data": data}


def error(
    code: int = ErrorCode.INTERNAL_ERROR,
    message: str = "系统内部错误",
    data: T | None = None,
) -> dict:
    return {"code": code, "message": message, "data": data}
