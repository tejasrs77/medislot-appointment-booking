from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Register(Input):
    email: EmailStr
    name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=12, max_length=128)
    role: Literal["PATIENT", "DOCTOR"] = "PATIENT"
    specialization_id: int | None = None
    clinic_id: int | None = None


class Login(Input):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class PasswordChange(Input):
    current_password: str
    new_password: str = Field(min_length=12, max_length=128)


class Profile(Input):
    name: str = Field(min_length=2, max_length=100)


class DoctorProfile(Input):
    qualifications: str = Field(max_length=200)
    experience: int = Field(ge=0, le=80)
    fee: int = Field(ge=0, le=100000)
    biography: str = Field(max_length=4000)
    specialization_id: int


class Rule(Input):
    clinic_id: int
    weekday: int = Field(ge=0, le=6)
    start_minute: int = Field(ge=0, le=1439)
    end_minute: int = Field(ge=1, le=1440)
    duration: int = Field(ge=5, le=180)

    @model_validator(mode="after")
    def interval(self):
        if self.end_minute - self.start_minute < self.duration:
            raise ValueError("Working period must fit an appointment")
        return self


class Schedule(Input):
    rules: list[Rule] = Field(max_length=42)

    @model_validator(mode="after")
    def no_overlap(self):
        for i, a in enumerate(self.rules):
            for b in self.rules[i + 1:]:
                if a.weekday == b.weekday and a.start_minute < b.end_minute and b.start_minute < a.end_minute:
                    raise ValueError("Working periods must not overlap; use separate periods for breaks")
        return self


class Leave(Input):
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def interval(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Leave must end after it starts")
        return self


class Booking(Input):
    doctor_id: int
    clinic_id: int
    starts_at: AwareDatetime


class Transition(Input):
    status: Literal["CHECKED_IN", "IN_PROGRESS", "COMPLETED", "NO_SHOW", "CANCELLED"]


class ClinicInput(Input):
    name: str = Field(min_length=2, max_length=100)
    location: str = Field(min_length=2, max_length=150)
    timezone: str

    @field_validator("timezone")
    @classmethod
    def timezone_valid(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError("Use an IANA time zone") from None
        return value


class Association(Input):
    clinic_id: int


# Explicit public response models keep accidental ORM fields out of API responses.
class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    doctor_status: str | None = None


class Slot(BaseModel):
    starts_at: datetime
    ends_at: datetime
    clinic_id: int
    timezone: str


class AvailabilityOut(BaseModel):
    date: date
    slots: list[Slot]
