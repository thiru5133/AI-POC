from pathlib import Path

import pytest
from pydantic import ValidationError

from app.conversation.context import ConversationContext
from app.conversation.prompt import REFUSAL, build_system_prompt
from app.domain.loader import load_profile_file, parse_profile


def test_hotel_profile_loads_and_validates():
    profile = parse_profile(load_profile_file("hotel"))
    assert profile.identity.organization_name == "Demo Hotel"
    assert profile.booking_workflow.required_fields == ["checkIn", "checkOut", "guests", "roomType"]
    assert any("2 PM" in f.answer for f in profile.knowledge_base.faqs)


def test_invalid_profile_rejected():
    with pytest.raises(ValidationError):
        parse_profile({"identity": {"greeting": "hi"}})


def test_prompt_is_built_from_profile():
    profile = parse_profile(load_profile_file("hotel"))
    ctx = ConversationContext(session_id="s", tenant_id="t", domain_profile_id="p")
    prompt = build_system_prompt(profile, ctx)
    assert "Demo Hotel" in prompt and "Check-in starts at 2 PM." in prompt
    assert REFUSAL in prompt


def test_prompt_changes_with_profile():
    config = load_profile_file("hotel")
    config["identity"].update(organizationName="City Clinic", persona="clinic receptionist")
    config["knowledgeBase"] = {"faqs": [{"question": "Visiting hours?", "answer": "9 to 5."}], "info": {}}
    prompt = build_system_prompt(
        parse_profile(config), ConversationContext(session_id="s", tenant_id="t", domain_profile_id="p")
    )
    assert "City Clinic" in prompt and "9 to 5." in prompt and "swimming" not in prompt


def test_engine_code_has_no_hotel_terminology():
    root = Path(__file__).parent.parent / "app"
    banned = ("hotel", "room", "check-in", "checkin", "guest")
    for sub in ("conversation", "ai", "tools"):
        for path in (root / sub).glob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            for word in banned:
                assert word not in text, f"{word!r} found in {path.name}"


def test_the_assistant_is_told_not_to_blame_the_system_for_unclear_speech():
    from app.conversation.context import ConversationContext
    from app.conversation.prompt import build_system_prompt
    from app.domain.loader import load_profile_file, parse_profile

    profile = parse_profile(load_profile_file("hotel"))
    ctx = ConversationContext(session_id="s", tenant_id="t", domain_profile_id="p", channel="phone")
    prompt = build_system_prompt(profile, ctx, tools_available=True)
    assert "Only say there is a problem with the system when a tool has just returned an error" in prompt
    assert "ask them politely to repeat" in prompt
