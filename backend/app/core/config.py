from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./dev.db"

    llm_provider: str = "groq"  # groq | anthropic | openai_compatible | fake
    llm_model: str = ""  # empty = provider default
    llm_base_url: str = ""  # openai_compatible only
    llm_api_key: str = ""  # openai_compatible only
    groq_api_key: str = ""
    anthropic_api_key: str = ""

    deepgram_api_key: str = ""
    deepgram_stt_model: str = "nova-2"
    deepgram_tts_model: str = "aura-asteria-en"

    default_tenant_id: str = "00000000-0000-0000-0000-000000000001"
    default_domain_profile_id: str = "00000000-0000-0000-0000-0000000000a1"

    jwt_secret: str = "dev-insecure-change-me"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cookie_secure: bool = False
    superadmin_email: str = ""
    superadmin_password: str = ""

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
