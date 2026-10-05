import json
from pathlib import Path

from app.domain.profile import DomainProfile

PROFILES_DIR = Path(__file__).parent / "profiles"


def load_profile_file(name: str) -> dict:
    return json.loads((PROFILES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def parse_profile(config: dict) -> DomainProfile:
    return DomainProfile.model_validate(config)
