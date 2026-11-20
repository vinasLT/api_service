from enum import Enum

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Environment(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class Permissions(str, Enum):
    SEO_JOBS = 'api_service.seo_jobs.all:read'

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
    SITE_URL: str = Field(
        default="", validation_alias=AliasChoices("SITE_URL", "COMPANY_LINK")
    )
    SITEMAP_BUCKET: str = Field(
        default="", validation_alias=AliasChoices("SITEMAP_BUCKET", "S3_BUCKET")
    )
    SITEMAP_BUCKET_REGION: str = Field(
        default="eu-central-1",
        validation_alias=AliasChoices("SITEMAP_BUCKET_REGION", "AWS_REGION"),
    )
    SITEMAP_PREFIX: str = "sitemaps/"
    # Languages are code-configured, not an env override.
    SITEMAP_LANGUAGES: list[str] = ["en", "lt"]

    # Optional. When both are set, sold-lot URL changes are purged from Cloudflare.
    CLOUDFLARE_API_TOKEN: str = ""
    CLOUDFLARE_ZONE_ID: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
