from enum import Enum
from typing import Annotated

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

load_dotenv()


class Environment(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"

class Settings(BaseSettings):
    #Application
    APP_NAME: str = "auction-api-service"
    DEBUG: bool = True
    ROOT_PATH: str = ''
    ENVIRONMENT: Environment = Environment.DEVELOPMENT

    @property
    def enable_docs(self) -> bool:
        return self.ENVIRONMENT in [Environment.DEVELOPMENT]

    # Database
    DB_HOST: str = "localhost"
    DB_PORT: str = "5432"
    DB_NAME: str = "test_db"
    DB_USER: str = "postgres"
    DB_PASS: str = "testpass"

    # gRPC
    GRPC_SERVER_PORT: str = "50051"

    #Redis
    REDIS_URL: str = "redis://localhost:6379"

    #Auction API
    AUCTION_API_KEY: str

    # Sitemaps
    SITE_URL: str = ""
    SITEMAP_BUCKET: str = Field(
        default="", validation_alias=AliasChoices("SITEMAP_BUCKET", "S3_BUCKET")
    )
    SITEMAP_BUCKET_REGION: str = Field(
        default="eu-central-1",
        validation_alias=AliasChoices("SITEMAP_BUCKET_REGION", "AWS_REGION"),
    )
    SITEMAP_PREFIX: str = "sitemaps/"
    SITEMAP_PUBLIC_BASE_URL: str = ""
    SITEMAP_URL_TTL_SECONDS: int = 3600
    SITEMAP_LANGUAGES: Annotated[list[str], NoDecode] = ["en", "lt"]

    @field_validator("SITEMAP_LANGUAGES", mode="before")
    @classmethod
    def _split_languages(cls, value):
        if isinstance(value, str):
            return [lang.strip() for lang in value.split(",") if lang.strip()]
        return value

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
