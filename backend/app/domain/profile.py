from pydantic import BaseModel, Field


class Identity(BaseModel):
    organization_name: str = Field(alias="organizationName")
    persona: str = "receptionist"  # e.g. "hotel receptionist"; keeps domain wording in config
    greeting: str
    voice_style: str = Field("conversational", alias="voiceStyle")
    timezone: str = "UTC"
    language: str = "en"

    model_config = {"populate_by_name": True}


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
