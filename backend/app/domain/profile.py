from pydantic import BaseModel, Field, field_validator

from app.domain.hours import validate_hours


class Identity(BaseModel):
    organization_name: str = Field(alias="organizationName")
    persona: str = "receptionist"  # e.g. "hotel receptionist"; keeps domain wording in config
    greeting: str
    voice_style: str = Field("conversational", alias="voiceStyle")
    timezone: str = "UTC"
    language: str = "en"
    hours: dict[str, str] = {}  # empty = always open; see app/domain/hours.py
    after_hours_message: str = Field("", alias="afterHoursMessage")

    model_config = {"populate_by_name": True}

    @field_validator("hours")
    @classmethod
    def _check_hours(cls, value: dict[str, str]) -> dict[str, str]:
        return validate_hours(value)


class FAQ(BaseModel):
    question: str
    answer: str


class KnowledgeBase(BaseModel):
    faqs: list[FAQ] = []
    info: dict[str, str] = {}  # free-form labelled facts (address, hours, ...)


class BookingWorkflow(BaseModel):
    resource_type: str = Field(alias="resourceType")
    required_fields: list[str] = Field(alias="requiredFields")

    model_config = {"populate_by_name": True}


class DomainProfile(BaseModel):
    """Complete configuration that turns the shared engine into a domain receptionist."""

    identity: Identity
    knowledge_base: KnowledgeBase = Field(KnowledgeBase(), alias="knowledgeBase")
    intents: list[str] = ["GREETING", "ASK_FAQ", "HUMAN_REQUEST", "UNKNOWN"]
    booking_workflow: BookingWorkflow | None = Field(None, alias="bookingWorkflow")
    enabled_tools: list[str] = Field([], alias="enabledTools")

    model_config = {"populate_by_name": True}
