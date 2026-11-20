"""Read indexed lots from saved_lots, fetching a sold lot's sale history from the provider once."""

from datetime import datetime, timezone

from pydantic import ValidationError
from rfc9457 import NotFoundProblem
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auction_api.api import AuctionApiClient
from auction_api.types.common import SiteEnum
from auction_api.types.lot import BasicHistoryLot, FormGetType, SaleHistoryItem
from auction_api.utils import AuctionApiUtils
from core.logger import logger
from database.models.saved_lots import SavedLots
from request_schemas.lot import LotByIDIn
from schemas.sale_history import SaleHistoryOut
from services.provider_cache import cached_provider_call, sale_history_ttl

_URL_FIELDS = ("link", "link_img_hd", "link_img_small", "video", "iaai_360")


def site_number(site: object) -> int | None:
    if site is None:
        return None
    if isinstance(site, SiteEnum):
        if site in {SiteEnum.ALL, SiteEnum.ALL_NUM}:
            return None
        return int(site.value)
    normalized = str(getattr(site, "value", site))
    if normalized in {SiteEnum.ALL.value, SiteEnum.ALL_NUM.value, "all", "3"}:
        return None
    return int(AuctionApiUtils.normalize_auction_to_num(normalized))


async def find_saved_lot(db: AsyncSession, lot_id: int | str, site: object) -> SavedLots | None:
    site_num = site_number(site)
    if site_num is None:
        return None
    result = await db.execute(
        select(SavedLots).where(
            SavedLots.lot_id == str(lot_id),
            SavedLots.site == site_num,
        )
    )
    return result.scalar_one_or_none()


async def find_saved_lots_by_vin(db: AsyncSession, vin: str) -> list[SavedLots]:
    result = await db.execute(
        select(SavedLots)
        .where(func.upper(SavedLots.vin) == vin.strip().upper())
        .order_by(SavedLots.lot_id, SavedLots.site)
    )
    return list(result.scalars().all())


def saved_lot_to_model(row: SavedLots) -> BasicHistoryLot:
    payload = {}
    for name in BasicHistoryLot.model_fields:
        if name == "form_get_type" or not hasattr(row, name):
            continue
        value = getattr(row, name)
        if value is not None:
            payload[name] = value

    lot_id = payload.get("lot_id")
    if isinstance(lot_id, str) and lot_id.isdigit():
        payload["lot_id"] = int(lot_id)
    payload["form_get_type"] = (
        FormGetType.HISTORY if row.is_deleted else FormGetType.ACTIVE
    )
    if row.is_deleted:
        payload.pop("auction_date", None)

    try:
        lot = BasicHistoryLot.model_validate(payload)
    except ValidationError:
        for name in _URL_FIELDS:
            payload.pop(name, None)
        lot = BasicHistoryLot.model_validate(payload)

    if row.is_deleted:
        lot.form_get_type = FormGetType.HISTORY
    return lot


def sales_from_history(history: BasicHistoryLot | None) -> list[SaleHistoryOut]:
    if history is None:
        return []
    sales: list[SaleHistoryOut] = []
    for item in history.sale_history or []:
        record = item if isinstance(item, SaleHistoryItem) else SaleHistoryItem.model_validate(item)
        sales.append(
            SaleHistoryOut(
                auction=AuctionApiUtils.num_to_auction_name(record.site).upper()
                if record.site
                else None,
                buyer_country=record.buyer_country,
                date=record.sale_date,
                final_bid=record.purchase_price,
                lot_id=record.lot_id,
                status=record.sale_status,
                is_buy_now=record.is_buynow,
                vin=record.vin,
            )
        )
    return sales


def sales_from_row(row: SavedLots) -> list[SaleHistoryOut]:
    return sales_from_history(saved_lot_to_model(row))


async def ensure_sale_history(
    db: AsyncSession,
    api: AuctionApiClient,
    row: SavedLots,
) -> SavedLots:
    """Fetch sale-histories/lot-id once for a sold lot and store it on the row."""
    if not row.is_deleted or row.sale_history_fetched_at is not None:
        return row

    request = LotByIDIn(lot_id=int(row.lot_id), site=str(row.site))
    try:
        history = await cached_provider_call(
            api,
            AuctionApiClient.GET_LOT_HISTORY_BY_ID,
            request,
            ttl=sale_history_ttl,
        )
    except NotFoundProblem:
        history = None
    except Exception:
        logger.exception(
            "Sale history lookup failed for saved lot {} site {}",
            row.lot_id,
            row.site,
        )
        return row

    if history is None:
        row.sale_history = []
    else:
        items = history.sale_history or []
        row.sale_history = [
            item.model_dump(mode="json") if isinstance(item, SaleHistoryItem) else item
            for item in items
        ]
        row.sale_status = history.sale_status
        row.sale_date = history.sale_date
        row.purchase_price = history.purchase_price
        if row.purchase_price is None and items:
            row.purchase_price = items[0].purchase_price
            row.sale_status = row.sale_status or items[0].sale_status
            row.sale_date = row.sale_date or items[0].sale_date
    row.sale_history_fetched_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row
