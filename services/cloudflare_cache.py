"""Purge cached lot pages when a lot is marked sold. No-op until Cloudflare credentials are set."""

from collections.abc import Iterable

import httpx

from config import settings
from core.logger import logger
from jobs.sitemap_generator import lot_public_path

_PURGE_URL = "https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache"
_BATCH = 30


def cloudflare_configured() -> bool:
    return bool(settings.CLOUDFLARE_API_TOKEN and settings.CLOUDFLARE_ZONE_ID and settings.SITE_URL)


def lot_page_urls(row) -> list[str]:
    if not getattr(row, "base_site", None) or not settings.SITE_URL:
        return []
    origin = settings.SITE_URL.rstrip("/")
    path = lot_public_path(row)
    return [f"{origin}/{lang}{path}" for lang in settings.SITEMAP_LANGUAGES]


async def purge_lot_urls(rows: Iterable) -> None:
    if not cloudflare_configured():
        return

    urls = [url for row in rows for url in lot_page_urls(row)]
    if not urls:
        return

    endpoint = _PURGE_URL.format(zone_id=settings.CLOUDFLARE_ZONE_ID)
    headers = {
        "Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            for start in range(0, len(urls), _BATCH):
                batch = urls[start : start + _BATCH]
                response = await client.post(endpoint, headers=headers, json={"files": batch})
                if response.status_code >= 300:
                    logger.warning(
                        "Cloudflare purge failed",
                        extra={
                            "data": {
                                "status_code": response.status_code,
                                "urls": len(batch),
                            }
                        },
                    )
                    return
        logger.info("Purged {} lot page URLs from Cloudflare", len(urls))
    except httpx.HTTPError as exc:
        logger.warning(f"Cloudflare purge request failed: {exc}")
