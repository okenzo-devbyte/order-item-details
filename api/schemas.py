from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class FilterModel(BaseModel):
    store_code: list[str] = Field(default_factory=list)
    order_type: list[str] = Field(default_factory=list)
    vip_group: list[str] = Field(default_factory=list)
    dept: list[int] = Field(default_factory=list)
    class_code: list[int] = Field(default_factory=list)
    subclass_code: list[int] = Field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None

    @field_validator("date_from", "date_to")
    @classmethod
    def _iso_date(cls, value: str | None) -> str | None:
        if value is not None and not _ISO_DATE.fullmatch(value):
            raise ValueError("date must be ISO YYYY-MM-DD")
        return value


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SearchRequest(BaseModel):
    q: str = Field(default="", max_length=200)
    mode: Literal["auto", "customer", "product"] = "auto"
    filters: FilterModel | None = None
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None


class SuggestRequest(BaseModel):
    q: str = Field(default="", max_length=200)
    limit: int = Field(default=8, ge=1, le=20)


class RollbackRequest(BaseModel):
    version_id: int


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    role: Literal["staff", "admin"] = "staff"


class UserPatchRequest(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=256)
    role: Literal["staff", "admin"] | None = None
    is_active: bool | None = None
