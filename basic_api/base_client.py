from abc import abstractmethod, ABC
from typing import TYPE_CHECKING, Type, TypeVar, Any

from pydantic import BaseModel
from rfc9457 import BadRequestProblem, NotFoundProblem

from core.logger import logger, log_async_execution_time
from services.provider_usage import record_provider_call
from .types import BaseClientIn
import httpx

if TYPE_CHECKING:
    from auction_api.api import EndpointSchema


T = TypeVar("T", bound=BaseModel)

# A lot lookup accepts site=all. The provider call leaves site off so it is not
# filtered to one auction. Search calls still ask both auctions.
_ALL_SITE_VALUES = {"all", "3"}
_OMIT_SITE_ENDPOINTS = {
    "cars/{lot_id}",
    "cars/lot-id/web",
    "cars/current-bid",
    "sale-histories/lot-id",
}


def provider_params(schema: "EndpointSchema", data: BaseModel) -> dict:
    payload = data.model_dump(exclude_none=True, mode="json")
    site_val = payload.get("site")
    if site_val is None:
        return payload
    if str(site_val).lower() not in _ALL_SITE_VALUES:
        return payload
    endpoint = getattr(schema.endpoint, "value", schema.endpoint)
    if endpoint in _OMIT_SITE_ENDPOINTS:
        payload.pop("site", None)
    else:
        payload["site"] = [1, 2]
    return payload


class BaseClient(ABC):
    def __init__(self, data: BaseClientIn):
        self.api_key = data.api_key
        self.header_name = data.header_name
        self.base_url = str(data.base_url)
        self._http_client: httpx.AsyncClient | None = None

    def _build_url(self, url: str) -> str:
        return f"{self.base_url.rstrip('/')}/{url.lstrip('/')}"

    async def _make_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = {self.header_name: self.api_key}
        try:
            if self._http_client is not None:
                return await self._http_client.request(method, url, headers=headers, **kwargs)
            async with httpx.AsyncClient(timeout=10) as client:
                return await client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as e:
            # Headers contain the provider API key, so they stay out of the log.
            logger.error(f"Request to API Failed", exc_info=e, extra={
                'data': {
                    'url': url,
                    'error': str(e),
                }
            })
            raise BadRequestProblem(detail='Request to API Failed') from e

    @log_async_execution_time('Request to external API')
    async def request_with_schema(self, schema: "EndpointSchema", data: BaseModel, **kwargs) -> Type[T]:
        url = self._build_url(schema.endpoint.format(**kwargs))

        payload = provider_params(schema, data)

        logger.debug(f"Request payload: {payload}, url: {url}, data: {data}")
        endpoint = schema.endpoint.value
        logger.info(
            "Provider call",
            extra={
                "data": {
                    "endpoint": endpoint,
                    "cache_result": "miss",
                }
            },
        )
        await record_provider_call(endpoint)

        response = await self._make_request("GET", url, params=payload)

        response_data = self._safe_json(response)
        logger.debug(
            "Response received",
            extra={
                "data": {
                    "status_code": response.status_code,
                    "url": url,
                    "has_json": response_data is not None,
                    "content_length": len(response.content or b""),
                }
            },
        )

        if response.status_code != httpx.codes.OK:
            logger.warning(f"Request failed, lot not found or smth", extra={
                'data': {
                    'url': url,
                    'payload': payload,
                    'response': response_data if response_data is not None else response.text
                }
            })
            raise NotFoundProblem('Lot not found')

        if response_data is None:
            logger.error("Expected JSON response, got empty or invalid JSON", extra={
                "data": {
                    "url": url,
                    "status_code": response.status_code,
                    "payload": payload,
                    "response_text": response.text,
                }
            })
            raise BadRequestProblem(detail='Invalid JSON response from API')

        return self.process_response(response_data, schema)

    @abstractmethod
    def process_response(self, response_data: dict | list, schema: "EndpointSchema") -> Type[T]:
        ...

    def _safe_json(self, response: httpx.Response) -> Any | None:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None



