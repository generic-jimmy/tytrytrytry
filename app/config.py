from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All credentials and secrets live in .env locally, or in the hosting
    platform's env var / secrets UI in production. Nothing here is hardcoded
    and nothing here should ever be committed to git."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    telegram_bot_token: str
    telegram_bot_username: str  # no leading @, used by the web login widget
    webhook_secret: str  # random string embedded in the webhook URL path
    base_url: str  # public URL of this deployment

    # Database — Supabase connection string (session pooler, see .env.example)
    database_url: str

    # OpenRouter
    openrouter_api_key: str

    # Web dashboard
    session_secret: str  # signs session cookies
    port: int = 8080

    # Bot allowlist — comma-separated usernames (no @) allowed to be in the
    # group besides this bot itself. Any other bot detected joining gets
    # banned automatically. Default includes Rose (@MissRose_bot).
    allowed_bot_usernames: str = "MissRose_bot"


settings = Settings()
