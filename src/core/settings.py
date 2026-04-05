from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Literal

class Settings(BaseSettings):
    APP_NAME: str = "CAD Content API"
    APP_VERSION: str = "1.0.0"
    APP_DESCRIPTION: str = "A simple API for managing CAD content"
    ENVIROMENT: Literal["development", "production"] = "development"

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()