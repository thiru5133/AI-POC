from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


def _clean(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("This field cannot be blank")
    return value


class BookingRequest(BaseModel):
    session_id: int = Field(ge=1, description="Class session id, from the sessions list")
    member_name: str = Field(min_length=1, max_length=120)
    member_email: EmailStr

    @field_validator("member_name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean(value)


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class GymIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    city: str = Field(min_length=1, max_length=80)
    country: str = Field(min_length=1, max_length=80)
    address: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=500)
    code: str | None = Field(default=None, max_length=40, description="URL-safe id; generated from the name when omitted")

    @field_validator("name", "city", "country")
    @classmethod
    def _text(cls, value: str) -> str:
        return _clean(value)


class GymPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    city: str | None = Field(default=None, min_length=1, max_length=80)
    country: str | None = Field(default=None, min_length=1, max_length=80)
    address: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    active: bool | None = None


class ClassTypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    code: str | None = Field(default=None, max_length=30)
    description: str = Field(default="", max_length=300)
    duration_min: int = Field(ge=5, le=480)
    price: int = Field(ge=0, le=100000, description="USD per class")

    @field_validator("name")
    @classmethod
    def _text(cls, value: str) -> str:
        return _clean(value)


class ClassTypePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=300)
    duration_min: int | None = Field(default=None, ge=5, le=480)
    price: int | None = Field(default=None, ge=0, le=100000)
    active: bool | None = None


class SessionIn(BaseModel):
    class_type_id: int
    starts_at: datetime
    capacity: int = Field(ge=1, le=500)
    trainer: str = Field(default="", max_length=80)


class SessionPatch(BaseModel):
    starts_at: datetime | None = None
    capacity: int | None = Field(default=None, ge=1, le=500)
    trainer: str | None = Field(default=None, max_length=80)
    active: bool | None = None


class UserIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=128)
    role: Literal["superadmin", "admin"] = "admin"

    @field_validator("name")
    @classmethod
    def _text(cls, value: str) -> str:
        return _clean(value)


class UserPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: Literal["superadmin", "admin"] | None = None
    active: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=1, max_length=128)
