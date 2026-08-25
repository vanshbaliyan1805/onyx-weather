import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/onyx_weather"
    
    # API & App configuration
    PROJECT_NAME: str = "Onyx Weather Backend"
    API_V1_STR: str = "/api/v1"
    
    # Security
    ADMIN_API_KEY: str = "hackathon-secret-key-change-me"
    
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

settings = Settings()
