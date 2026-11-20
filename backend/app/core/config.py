from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str
    frontend_origin: str = "http://localhost:5173"
    cookie_secure: bool = False
    seed_password: str = ""
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")


settings = Settings()
if len(settings.jwt_secret) < 32:
    raise ValueError("JWT_SECRET must have at least 32 characters")
