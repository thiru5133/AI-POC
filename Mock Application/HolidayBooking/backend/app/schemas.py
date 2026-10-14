from datetime import date
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


def _clean(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("This field cannot be blank")
    return value


class BookingRequest(BaseModel):
    hotel: str = Field(min_length=1, max_length=40, description="Hotel code, e.g. holiday-colombo")
    category: str = Field(min_length=1, max_length=30, description="Room type code, e.g. deluxe")
    guest_name: str = Field(min_length=1, max_length=120)
    guest_email: EmailStr
    check_in: date
    check_out: date
    guests: int = Field(default=1, ge=1, le=20)

    @field_validator("guest_name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean(value)


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class HotelIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    city: str = Field(min_length=1, max_length=80)
    country: str = Field(min_length=1, max_length=80)
    address: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=500)
    stars: int = Field(default=3, ge=1, le=5)
    code: str | None = Field(default=None, max_length=40, description="URL-safe id; generated from the name when omitted")

    @field_validator("name", "city", "country")
    @classmethod
    def _text(cls, value: str) -> str:
        return _clean(value)


class HotelPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    city: str | None = Field(default=None, min_length=1, max_length=80)
    country: str | None = Field(default=None, min_length=1, max_length=80)
    address: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    stars: int | None = Field(default=None, ge=1, le=5)
    active: bool | None = None


class RoomTypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    code: str | None = Field(default=None, max_length=30)
    description: str = Field(default="", max_length=300)
    price_per_night: int = Field(ge=1, le=100000, description="USD per night")
    max_guests: int = Field(ge=1, le=20)

    @field_validator("name")
    @classmethod
    def _text(cls, value: str) -> str:
        return _clean(value)


class RoomTypePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=300)
    price_per_night: int | None = Field(default=None, ge=1, le=100000)
    max_guests: int | None = Field(default=None, ge=1, le=20)
    active: bool | None = None


class RoomsIn(BaseModel):
    """Either an explicit list of room numbers, or `start` + `count` for a consecutive run (e.g. 201..210)."""

    room_type_id: int
    numbers: list[str] | None = None
    start: int | None = Field(default=None, ge=0, le=99999)
    count: int | None = Field(default=None, ge=1, le=200)


class RoomPatch(BaseModel):
    room_type_id: int | None = None
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
