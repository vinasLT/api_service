import logging
from abc import abstractmethod
from typing import List

from pydantic import BaseModel
from auction_api import EndpointSchema
from auction_api.utils import AuctionApiUtils
from exptions import BadRequestException
from .types import BaseClientIn
import httpx

# Настройка логгера
logger = logging.getLogger("auction_api.client")
logger.setLevel(logging.INFO)  # Можно заменить на DEBUG для подробного логгирования

handler = logging.StreamHandler()
formatter = logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


class BaseClient:
    def __init__(self, data: BaseClientIn):
        self.api_key = data.api_key
        self.header_name = data.header_name
        self.base_url = str(data.base_url)

    def _build_url(self, url: str) -> str:
        return f"{self.base_url.rstrip('/')}/{url.lstrip('/')}"

    async def _make_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = {self.header_name: self.api_key}
        logger.info(f"📤 Sending {method} request to {url}")
        logger.debug(f"Headers: {headers}")
        logger.debug(f"Request kwargs: {kwargs}")

        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, headers=headers, **kwargs)

        logger.info(f"📥 Received response with status {response.status_code} from {url}")
        if response.status_code != httpx.codes.OK:
            logger.warning(f"⚠️ Response body: {response.text}")
        return response

    async def request_with_schema(self, schema: EndpointSchema, data: BaseModel) -> BaseModel | List[BaseModel]:
        url = self._build_url(AuctionApiUtils.set_value_in_path(schema.endpoint, data))
        payload = data.model_dump(exclude_none=True)

        logger.info(f"🔁 Performing request for schema: {schema}")
        logger.debug(f"Payload: {payload}")

        if schema.method == "GET":
            response = await self._make_request("GET", url, params=payload)
        elif schema.method == "POST":
            response = await self._make_request("POST", url, json=payload)
        else:
            raise ValueError(f"Unsupported method: {schema.method}")

        try:
            response_data = response.json()
        except Exception as e:
            logger.error(f"❌ Failed to parse JSON response: {e}")
            raise BadRequestException("Invalid response format", "bad_format")

        if response.status_code != httpx.codes.OK:
            raise BadRequestException("Lot not found", "not_found")

        logger.debug(f"✅ Processed response data: {response_data}")
        return self.process_response(response_data, schema)

    @abstractmethod
    def process_response(self, response_data: dict | list, schema: EndpointSchema) -> BaseModel | List[BaseModel]:
        ...
