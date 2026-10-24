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
    otp_minutes: int = 10  # how long an emailed one-time code stays valid
    otp_max_attempts: int = 5
    otp_resend_seconds: int = 30
    app_base_url: str = "http://localhost:5173"  # used for the login link in emails
    email_from: str = ""  # sender address; must be verified in SendGrid
    sendgrid_api_key: str = ""  # empty = log emails instead of sending (dev only)
    twilio_account_sid: str = ""  # empty = log SMS / WhatsApp messages instead of sending them (dev only)
    twilio_auth_token: str = ""
    twilio_sms_from: str = ""  # E.164 number or messaging service sender, e.g. +14155550100
    # How a caller is texted automatically after a phone booking: "sms", "whatsapp" or "" to turn it off.
    booking_confirmation_channel: str = "sms"
    twilio_whatsapp_from: str = ""  # E.164 number enabled for WhatsApp (sandbox: +14155238886)
    # Public https URL of this backend (e.g. an ngrok URL in development): Twilio calls it, and it is what the signature
    # of a Twilio request is checked against.
    public_base_url: str = ""
    phone_stream_token_seconds: int = 60  # how long the signed link between a call's webhook and its audio stream lives
    # Phone calls through Vapi (Vapi does telephony, speech and barge-in; this server is its custom LLM).
    vapi_webhook_secret: str = ""  # the credential Vapi sends with every server message; empty = Vapi calls are refused
    vapi_llm_token_seconds: int = 7200  # how long a call's LLM URL stays valid: longer than any call
    mcp_secret_key: str = ""  # Fernet key for stored MCP access tokens; derived from JWT_SECRET when empty
    mcp_allow_private_hosts: bool = False  # allow MCP URLs on loopback/private networks (local development)
    mcp_max_servers_per_tenant: int = 5
    # Docker development: "localhost" in an MCP URL means this container, so map it to the host machine
    mcp_localhost_alias: str = ""
    superadmin_email: str = ""
    superadmin_password: str = ""

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
