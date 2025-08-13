from enum import Enum

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

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


    #Redis
    REDIS_URL: str

    #Auction API
    AUCTION_API_KEY: str

settings = Settings()