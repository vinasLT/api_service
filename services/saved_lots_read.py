"""Read indexed lots from saved_lots, fetching a sold lot's sale history from the provider once."""

from datetime import datetime, timezone

from pydantic import ValidationError
from rfc9457 import NotFoundProblem
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auction_api.api import AuctionApiClient
from auction_api.types.common import SiteEnum
from auction_api.types.lot import BasicHistoryLot, BasicLot, FormGetType, SaleHistoryItem
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
    statement = select(SavedLots).where(SavedLots.lot_id == str(lot_id))
    site_num = site_number(site)
    if site_num is not None:
        statement = statement.where(SavedLots.site == site_num)
    statement = statement.order_by(SavedLots.is_deleted.asc(), SavedLots.id.desc())
    result = await db.execute(statement)
    return result.scalars().first()


async def find_saved_lots_by_vin(db: AsyncSession, vin: str) -> list[SavedLots]:
    result = await db.execute(
        select(SavedLots)
        .where(func.upper(SavedLots.vin) == vin.strip().upper())
        .order_by(SavedLots.is_deleted.asc(), SavedLots.lot_id, SavedLots.site)
    )
    return list(result.scalars().all())


async def find_saved_vin_or_lot(
    db: AsyncSession, site: object, vin_or_lot: str
) -> list[SavedLots]:
    vin_or_lot = vin_or_lot.replace(" ", "").upper()
    if vin_or_lot.isdigit():
        statement = select(SavedLots).where(SavedLots.lot_id == vin_or_lot)
        site_num = site_number(site)
        if site_num is not None:
            statement = statement.where(SavedLots.site == site_num)
        statement = statement.order_by(
            SavedLots.is_deleted.asc(),
            SavedLots.auction_date.desc().nulls_last(),
            SavedLots.id.desc(),
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    rows = await find_saved_lots_by_vin(db, vin_or_lot)
    site_num = site_number(site)
    if site_num is not None:
        rows = [row for row in rows if row.site == site_num]
    return rows


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


_BODY_SKIP = frozenset(
    {
        "id",
        "created_at",
        "updated_at",
        "is_deleted",
        "deleted_at",
        "form_get_type",
        "price_reserve",
        "manufacturer_country",
        "sale_history",
        "sale_status",
        "sale_date",
        "purchase_price",
        "sale_history_fetched_at",
        "sale_count",
    }
)
_SAVED_COLUMNS = {column.name for column in SavedLots.__table__.columns}


def _plain(value):
    if value is None or isinstance(value, (str, int, float, bool, datetime)):
        return value
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return str(value)


def _assign_body(row: SavedLots, lot: BasicHistoryLot) -> None:
    for name in _SAVED_COLUMNS:
        if name in _BODY_SKIP or not hasattr(lot, name):
            continue
        value = getattr(lot, name)
        if value is None:
            continue
        if name == "lot_id":
            value = str(value)
        else:
            value = _plain(value)
        setattr(row, name, value)


def apply_sale_fields(row: SavedLots, history: BasicHistoryLot | None) -> None:
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
            first = items[0]
            row.purchase_price = getattr(first, "purchase_price", None)
            row.sale_status = row.sale_status or getattr(first, "sale_status", None)
            row.sale_date = row.sale_date or getattr(first, "sale_date", None)
    row.sale_history_fetched_at = datetime.now(timezone.utc)


def _coerce_lot(item) -> BasicHistoryLot | None:
    try:
        if isinstance(item, BasicHistoryLot):
            lot = item
        elif isinstance(item, dict):
            lot = BasicHistoryLot.model_validate(item)
        elif isinstance(item, BasicLot):
            lot = BasicHistoryLot.model_validate(item.model_dump())
        else:
            return None
    except ValidationError:
        logger.warning("Skipping provider lot that failed validation")
        return None
    if lot.lot_id is None or lot.site is None:
        return None
    return lot


def _coerce_lots(lots) -> list[BasicHistoryLot]:
    if lots is None:
        return []
    items = lots if isinstance(lots, list) else [lots]
    parsed = []
    for item in items:
        lot = _coerce_lot(item)
        if lot is not None:
            parsed.append(lot)
    return parsed


async def _store_lots(db: AsyncSession, lots, writer) -> None:
    parsed = _coerce_lots(lots)
    if not parsed:
        return
    for lot in parsed:
        await writer(db, lot)
    await db.commit()


async def store_archival_lots(db: AsyncSession, lots) -> None:
    """Save a sale-histories payload. An existing row only gains sale fields."""
    try:
        await _store_lots(db, lots, _write_archival_lot)
    except Exception:
        logger.exception("Could not store archival sale history")
        await db.rollback()


async def _write_archival_lot(db: AsyncSession, lot: BasicHistoryLot) -> None:
    row = await find_saved_lot(db, lot.lot_id, lot.site)
    if row is None:
        row = SavedLots(
            lot_id=str(lot.lot_id),
            site=int(lot.site),
            is_deleted=True,
            deleted_at=datetime.now(timezone.utc),
        )
        _assign_body(row, lot)
        db.add(row)
    apply_sale_fields(row, lot)


async def store_catalog_lot(db: AsyncSession, lots) -> None:
    """Write sale_count onto an existing row. A catalog miss does not insert a lot."""
    try:
        await _store_lots(db, lots, _write_catalog_lot)
    except Exception:
        logger.exception("Could not store catalog lot")
        await db.rollback()


async def _write_catalog_lot(db: AsyncSession, lot: BasicHistoryLot) -> None:
    row = await find_saved_lot(db, lot.lot_id, lot.site)
    if row is None or lot.sale_count is None:
        return
    row.sale_count = lot.sale_count


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

    if isinstance(history, list):
        history = next((item for item in history if isinstance(item, BasicHistoryLot)), None)
    if history is not None and not isinstance(history, BasicHistoryLot):
        logger.warning(
            "Sale history lookup returned an unexpected payload for lot {} site {}",
            row.lot_id,
            row.site,
        )
        return row
    apply_sale_fields(row, history)
    await db.commit()
    await db.refresh(row)
    return row
