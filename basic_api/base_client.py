from abc import abstractmethod
from typing import List, TYPE_CHECKING

from pydantic import BaseModel


from exptions import BadRequestException
from .types import BaseClientIn
import httpx

if TYPE_CHECKING:
    from auction_api.api import EndpointSchema




class BaseClient:
    def __init__(self, data: BaseClientIn):
        self.api_key = data.api_key
        self.header_name = data.header_name
        self.base_url = str(data.base_url)

    def _build_url(self, url: str) -> str:
        return f"{self.base_url.rstrip('/')}/{url.lstrip('/')}"

    async def _make_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = {self.header_name: self.api_key}
        async with httpx.AsyncClient(timeout=10) as client:
            return await client.request(method, url, headers=headers, **kwargs)

    async def request_with_schema(self, schema: "EndpointSchema", data: BaseModel, **kwargs) -> BaseModel | List[BaseModel]:
        url = self._build_url(schema.endpoint.format(**kwargs))
        payload = data.model_dump(exclude_none=True)
        print(payload)

        if schema.method == "GET":
            response = await self._make_request("GET", url, params=payload)
        elif schema.method == "POST":
            response = await self._make_request("POST", url, json=payload)
        else:
            raise ValueError(f"Unsupported method: {schema.method}")

        response_data = response.json()
        print(response_data)

        if response.status_code != httpx.codes.OK:
            raise BadRequestException('Lot not found', 'not_found')

        return self.process_response(response_data, schema)

    @abstractmethod
    def process_response(self, response_data: dict | list, schema: "EndpointSchema") -> BaseModel | List[BaseModel]:
        ...




