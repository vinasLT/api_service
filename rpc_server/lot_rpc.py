import traceback
from typing import Optional, Any

import grpc
import redis.asyncio as redis
from rfc9457 import NotFoundProblem

from auction_api.api import AuctionApiClient
from auction_api.types.search import SiteEnum
from auction_api.utils import get_lot_vin_or_lot_id
from config import settings
from core.logger import logger
from rpc_server.cache import RedisCache, CacheKeyBuilder
from rpc_server.gen.python.auction.v1 import lot_pb2
from auction.v1 import lot_pb2_grpc
from request_schemas.lot import LotByIDIn



class LotRpc(lot_pb2_grpc.LotServiceServicer):
    TTL_LOT = 10 * 60
    TTL_CURRENT_BID = 10 * 60
    TTL_SALE_HISTORY = 60 * 60
    TTL_VIN_LOOKUP = 30 * 60

    def __init__(self):
        self.api = AuctionApiClient()
        self.redis_client = None
        self.cache = None
        self._init_redis()

    def _init_redis(self):
        try:
            if settings.REDIS_URL:
                self.redis_client = redis.from_url(
                    settings.REDIS_URL,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True,
                    retry_on_error=[ConnectionError, TimeoutError],
                    max_connections=50
                )
                self.cache = RedisCache(self.redis_client)
                logger.info("Redis cache initialized successfully")
            else:
                logger.warning("Redis URL not configured, caching disabled")
        except Exception as e:
            logger.error(f"Failed to initialize Redis: {e}")
            self.cache = None

    @staticmethod
    def _parse_site_enum(site: str) -> Optional[SiteEnum]:
        return SiteEnum(site) if site else None

    def _create_lot_by_id_data(self, lot_id: int, site: str) -> LotByIDIn:
        site_enum = self._parse_site_enum(site)
        return LotByIDIn(lot_id=lot_id, site=site_enum)

    @staticmethod
    def _set_not_found_error(context, message: str = 'Lot not found'):
        context.set_code(grpc.StatusCode.NOT_FOUND)
        context.set_details(message)

    @staticmethod
    def _set_invalid_argument_error(context, message: str):
        context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
        context.set_details(message)

    @staticmethod
    def _set_internal_error(context, message: str = 'Internal server error'):
        context.set_code(grpc.StatusCode.INTERNAL)
        context.set_details(message)

    def _convert_to_lot_proto(self, lot_data) -> lot_pb2.Lot:
        # Handle both dict and model instances
        if hasattr(lot_data, 'model_dump'):
            lot_dict = lot_data.model_dump(mode='json', exclude_none=True)
        else:
            lot_dict = lot_data
        return lot_pb2.Lot(**lot_dict)

    def _process_lot_response(self, lot, response_class):
        if isinstance(lot, list):
            logger.debug(f'Received list of lots, count: {len(lot)}')
            lots = [self._convert_to_lot_proto(item) for item in lot]
            return response_class(lot=lots)

        response_lot = self._convert_to_lot_proto(lot)
        return response_class(lot=[response_lot])

    @staticmethod
    def _log_request(method_name: str, **kwargs):
        logger.debug(f'Request {method_name} using gRPC', extra=kwargs)

    @staticmethod
    def _log_error(error_type: str, error: Exception, **kwargs):
        logger_method = logger.error if error_type == 'error' else logger.warning
        logger_method(f'{error_type} in {kwargs.get("method", "unknown method")}', extra={
            'error': str(error),
            'traceback': traceback.format_exc(),
            **kwargs
        })

    async def _get_from_cache(self, key: str) -> Optional[Any]:
        if self.cache:
            cached_data = await self.cache.get(key)
            if cached_data:
                logger.debug(f"Cache hit for key: {key}")
                return cached_data
            logger.debug(f"Cache miss for key: {key}")
        return None

    async def _set_to_cache(self, key: str, value: Any, ttl: int) -> None:
        """Set data to cache"""
        if self.cache and value is not None:
            await self.cache.set(key, value, ttl)
            logger.debug(f"Cached data for key: {key} with TTL: {ttl}s")

    async def _invalidate_lot_cache(self, lot_id: int, site: Optional[str] = None):
        """Invalidate all cache entries related to a specific lot"""
        if self.cache:
            keys_to_delete = [
                CacheKeyBuilder.lot_by_id(lot_id, site),
                CacheKeyBuilder.current_bid(lot_id, site),
                CacheKeyBuilder.sale_history(lot_id, site),
            ]
            for key in keys_to_delete:
                await self.cache.delete(key)
            logger.debug(f"Invalidated cache for lot {lot_id}")

    async def GetLot(self, request: lot_pb2.GetLotRequest, context):
        try:
            if not request.lot_id:
                self._set_invalid_argument_error(context, 'Lot ID is required')
                return lot_pb2.GetLotResponse()

            self._log_request('get lot by id', lot_id=request.lot_id, site=request.site)

            cache_key = CacheKeyBuilder.lot_by_id(request.lot_id, request.site)
            cached_lot = await self._get_from_cache(cache_key)

            if cached_lot:
                return self._process_lot_response(cached_lot, lot_pb2.GetLotResponse)

            data = self._create_lot_by_id_data(request.lot_id, request.site)
            lot = await self.api.request_with_schema(
                AuctionApiClient.GET_LOT_BY_ID_FOR_ALL_TIME,
                data
            )

            if not lot:
                self._set_not_found_error(context)
                return lot_pb2.GetLotResponse()

            lot_for_cache = lot if isinstance(lot, list) else [lot]
            cache_data = [
                item.model_dump(mode='json', exclude_none=True) if hasattr(item, 'model_dump') else item
                for item in lot_for_cache
            ]

            await self._set_to_cache(cache_key, cache_data, self.TTL_LOT)

            return self._process_lot_response(lot, lot_pb2.GetLotResponse)

        except NotFoundProblem as e:
            self._log_error('warning', e, method='GetLot',
                            lot_id=request.lot_id, site=request.site)
            self._set_not_found_error(context)
            return lot_pb2.GetLotResponse()

        except ValueError as e:
            self._log_error('warning', e, method='GetLot',
                            lot_id=request.lot_id, site=request.site)
            self._set_invalid_argument_error(context, f'Invalid parameters: {e}')
            return lot_pb2.GetLotResponse()

        except Exception as e:
            self._log_error('error', e, method='GetLot',
                            lot_id=request.lot_id, site=request.site)
            self._set_internal_error(context)
            return lot_pb2.GetLotResponse()

    async def GetCurrentBid(self, request: lot_pb2.GetCurrentBidRequest, context):
        try:
            cache_key = CacheKeyBuilder.current_bid(request.lot_id, request.site)
            cached_bid = await self._get_from_cache(cache_key)

            if cached_bid:
                response_bid = lot_pb2.CurrentBid(**cached_bid)
                return lot_pb2.GetCurrentBidResponse(current_bid=response_bid)

            data = self._create_lot_by_id_data(request.lot_id, request.site)
            current_bid = await self.api.request_with_schema(
                self.api.GET_CURRENT_BID_FOR_LOT,
                data
            )

            if not current_bid:
                self._set_not_found_error(context)
                return lot_pb2.GetCurrentBidResponse()

            current_bid_data = current_bid.model_dump(mode='json', exclude_none=True)

            await self._set_to_cache(cache_key, current_bid_data, self.TTL_CURRENT_BID)

            response_bid = lot_pb2.CurrentBid(**current_bid_data)
            return lot_pb2.GetCurrentBidResponse(current_bid=response_bid)

        except NotFoundProblem:
            self._set_not_found_error(context)
            return lot_pb2.GetCurrentBidResponse()

        except Exception as e:
            self._log_error('error', e, method='GetCurrentBid',
                            lot_id=request.lot_id, site=request.site)
            self._set_internal_error(context)
            return lot_pb2.GetCurrentBidResponse()

    async def GetLotByVinOrLot(self, request: lot_pb2.GetLotByVinOrLotRequest, context):
        try:
            vin_or_lot = request.vin_or_lot_id.replace(" ", "").upper()
            self._log_request('get lot by vin or lot id',
                              vin_or_lot_id=request.vin_or_lot_id)

            cache_key = CacheKeyBuilder.lot_by_vin_or_id(vin_or_lot, request.site)
            cached_lot = await self._get_from_cache(cache_key)

            if cached_lot:
                return self._process_lot_response(cached_lot, lot_pb2.GetLotByVinOrLotResponse)

            site_enum = self._parse_site_enum(request.site)
            lot = await get_lot_vin_or_lot_id(self.api, site_enum, vin_or_lot)

            if not lot:
                self._set_not_found_error(context)
                return lot_pb2.GetLotByVinOrLotResponse()

            lot_for_cache = lot if isinstance(lot, list) else [lot]
            cache_data = [
                item.model_dump(mode='json', exclude_none=True) if hasattr(item, 'model_dump') else item
                for item in lot_for_cache
            ]

            await self._set_to_cache(cache_key, cache_data, self.TTL_VIN_LOOKUP)

            return self._process_lot_response(lot, lot_pb2.GetLotByVinOrLotResponse)

        except NotFoundProblem:
            self._set_not_found_error(context)
            return lot_pb2.GetLotByVinOrLotResponse()

        except Exception as e:
            self._log_error('error', e, method='GetLotByVinOrLot',
                            vin_or_lot_id=request.vin_or_lot_id, site=request.site)
            self._set_internal_error(context)
            return lot_pb2.GetLotByVinOrLotResponse()

    async def GetSaleHistory(self, request: lot_pb2.GetSaleHistoryRequest, context):
        try:
            cache_key = CacheKeyBuilder.sale_history(request.lot_id, request.site)
            cached_history = await self._get_from_cache(cache_key)

            if cached_history:
                response_lot = lot_pb2.Lot(**cached_history)
                return lot_pb2.GetSaleHistoryResponse(lot=[response_lot])

            data = self._create_lot_by_id_data(request.lot_id, request.site)
            lot = await self.api.request_with_schema(
                AuctionApiClient.GET_LOT_HISTORY_BY_ID,
                data
            )

            if not lot:
                self._set_not_found_error(context)
                return lot_pb2.GetSaleHistoryResponse()

            lot_data = lot.model_dump(mode='json', exclude_none=True)

            await self._set_to_cache(cache_key, lot_data, self.TTL_SALE_HISTORY)

            response_lot = lot_pb2.Lot(**lot_data)
            return lot_pb2.GetSaleHistoryResponse(lot=[response_lot])

        except NotFoundProblem:
            self._set_not_found_error(context)
            return lot_pb2.GetSaleHistoryResponse()

        except Exception as e:
            self._log_error('error', e, method='GetSaleHistory',
                            lot_id=request.lot_id, site=request.site)
            self._set_internal_error(context)
            return lot_pb2.GetSaleHistoryResponse()

    async def close(self):
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis connection closed")