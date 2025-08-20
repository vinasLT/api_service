import traceback

import grpc
from pygments.lexers import q
from rfc9457 import NotFoundProblem

from auction_api.api import AuctionApiClient
from auction_api.types.search import SiteEnum
from core.logger import logger
from rpc_server.gen.python.auction.v1 import lot_pb2
from auction.v1 import lot_pb2_grpc
from request_schemas.lot import LotByIDIn


class LotRpc(lot_pb2_grpc.LotServiceServicer):
    def __init__(self):
        self.api = AuctionApiClient()

    async def GetLot(self, request: lot_pb2.GetLotRequest, context):
        try:
            lot_id = request.lot_id
            site = request.site

            if not lot_id:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details('Lot ID is required')
                return lot_pb2.GetLotResponse()

            site_enum = SiteEnum(site) if site else None
            data = LotByIDIn(lot_id=lot_id, site=site_enum)

            logger.debug('Request get lot by id using gRPC', extra={
                'lot_id': lot_id,
                'site': site
            })

            lot = await self.api.request_with_schema(
                AuctionApiClient.GET_LOT_BY_ID_FOR_ALL_TIME,
                data
            )

            if isinstance(lot, list):
                logger.debug(f'Received list of lots, count: {len(lot)}')
                if not lot:
                    context.set_code(grpc.StatusCode.NOT_FOUND)
                    context.set_details('Lot not found')
                    return lot_pb2.GetLotResponse()
                lot = lot[0]

            lot_data = lot.model_dump(mode='json', exclude_none=True)
            response_lot = lot_pb2.Lot(**lot_data)

            return lot_pb2.GetLotResponse(lot=response_lot)

        except NotFoundProblem as e:
            logger.warning('Lot not found', extra={
                'error': str(e),
                'lot_id': request.lot_id,
                'site': request.site,
                'traceback': traceback.format_exc()
            })
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details('Lot not found')
            return lot_pb2.GetLotResponse()

        except ValueError as e:
            logger.warning('Invalid request parameters', extra={
                'error': str(e),
                'lot_id': request.lot_id,
                'site': request.site,
                'traceback': traceback.format_exc()
            })
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(f'Invalid parameters: {e}')
            return lot_pb2.GetLotResponse()

        except Exception as e:
            logger.error('Error in GetLot', extra={
                'error': str(e),
                'lot_id': request.lot_id,
                'site': request.site,
                'traceback': traceback.format_exc()
            })
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details('Internal server error')
            return lot_pb2.GetLotResponse()
