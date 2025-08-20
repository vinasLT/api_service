from abc import abstractmethod, ABC
from typing import List, TYPE_CHECKING

from pydantic import BaseModel
from rfc9457 import BadRequestProblem, NotFoundProblem

from core.logger import logger
from .types import BaseClientIn
import httpx

if TYPE_CHECKING:
    from auction_api.api import EndpointSchema




class BaseClient(ABC):
    def __init__(self, data: BaseClientIn):
        self.api_key = data.api_key
        self.header_name = data.header_name
        self.base_url = str(data.base_url)

    def _build_url(self, url: str) -> str:
        return f"{self.base_url.rstrip('/')}/{url.lstrip('/')}"

    async def _make_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = {self.header_name: self.api_key}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                return await client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as e:
            logger.error(f"Request to API Failed", exc_info=e, extra={
                'data': {
                    'url': url,
                    'headers': headers,
                    'kwargs': kwargs,
                    'error': e
                }
            })
            raise BadRequestProblem(detail='Request to API Failed') from e

    async def request_with_schema(self, schema: "EndpointSchema", data: BaseModel, **kwargs) -> BaseModel | List[BaseModel]:
        url = self._build_url(schema.endpoint.format(**kwargs))

        payload = data.model_dump(exclude_none=True, mode='json')
        logger.debug(f"Request payload: {payload}, url: {url}, data: {data}")

        if schema.method == "GET":
            response = await self._make_request("GET", url, params=payload)
            logger.debug(f"Response: {response.json()}, len: {len(response.json())}")
        elif schema.method == "POST":
            response = await self._make_request("POST", url, json=payload)
        else:
            logger.error(f"Unsupported method: {schema.method}")
            raise ValueError(f"Unsupported method: {schema.method}")

        if response.status_code != httpx.codes.OK:
            logger.warning(f"Request failed, lot not found or smth", extra={
                'data': {
                    'url': url,
                    'payload': payload,
                    'response': response.json() if response.content else None
                }
            })
            raise NotFoundProblem('Lot not found')

        response_data = response.json()

        return self.process_response(response_data, schema)

    @abstractmethod
    def process_response(self, response_data: dict | list, schema: "EndpointSchema") -> BaseModel | List[BaseModel]:
        ...




