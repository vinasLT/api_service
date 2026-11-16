from datetime import datetime, timezone

import pytest
from botocore.exceptions import ClientError

from config import settings
from jobs.sitemap_generator import (
    SitemapChunkWriter,
    _lot_batch_statement,
    _lot_path,
    _require_site_url,
    publish_sitemap,
)
from tests.test_sitemap_paths import _row


class MemoryS3:
    def __init__(self):
        self.objects: dict[str, dict] = {}
        self.uploads = 0

    def head_object(self, **params):
        item = self.objects.get(params["Key"])
        if item is None:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"Metadata": item["metadata"]}

    def upload_fileobj(self, fileobj, Bucket, Key, ExtraArgs=None):
        self.uploads += 1
        self.objects[Key] = {
            "body": fileobj.read(),
            "metadata": dict((ExtraArgs or {}).get("Metadata") or {}),
        }


@pytest.fixture
def bucket(monkeypatch):
    monkeypatch.setattr(settings, "SITEMAP_BUCKET", "vinas-files")
    monkeypatch.setattr(settings, "SITEMAP_PREFIX", "sitemaps/")


def test_lot_batches_are_ordered_by_lot_and_site():
    compiled = str(
        _lot_batch_statement().compile(compile_kwargs={"literal_binds": True})
    ).lower().replace('"', "")

    assert "order by saved_lots.lot_id, saved_lots.site" in compiled


def test_same_rows_produce_the_same_sitemap_bytes():
    def build(lot_ids: list[str]) -> list[bytes]:
        writer = SitemapChunkWriter("en")
        for lot_id in lot_ids:
            path = _lot_path(_row(lot_id=lot_id))
            writer.add(f"<url><loc>https://vinas.lt/en{path}</loc></url>\n".encode())
        writer.finish()
        return [chunk.data.getvalue() for chunk in writer.chunks]

    ordered = ["1", "2", "3"]
    assert build(ordered) == build(ordered)
    assert build(ordered) != build(list(reversed(ordered)))


def test_unchanged_upload_keeps_the_previous_lastmod(bucket):
    s3 = MemoryS3()
    data = b"<urlset></urlset>\n"
    previous = datetime(2026, 1, 1, tzinfo=timezone.utc)
    current = datetime(2026, 11, 16, tzinfo=timezone.utc)

    publish_sitemap(s3, "sitemap-lots-en-1.xml", data, previous)
    lastmod, uploaded = publish_sitemap(s3, "sitemap-lots-en-1.xml", data, current)

    assert uploaded is False
    assert lastmod == previous
    assert s3.uploads == 1


def test_changed_upload_uses_the_run_lastmod(bucket):
    s3 = MemoryS3()
    previous = datetime(2026, 1, 1, tzinfo=timezone.utc)
    current = datetime(2026, 11, 16, tzinfo=timezone.utc)
    publish_sitemap(s3, "sitemap-lots-en-1.xml", b"<urlset></urlset>\n", previous)

    lastmod, uploaded = publish_sitemap(
        s3, "sitemap-lots-en-1.xml", b"<urlset><url></url></urlset>\n", current
    )

    assert uploaded is True
    assert lastmod == current
    assert s3.uploads == 2
    stored = s3.objects["sitemaps/sitemap-lots-en-1.xml"]["metadata"]["lastmod"]
    assert stored == "2026-11-16T00:00:00+00:00"


def test_byte_guard_starts_a_new_chunk(monkeypatch):
    import jobs.sitemap_generator as generator

    entry = b"<url><loc>https://vinas.lt/en/lot/x</loc></url>\n"
    probe = SitemapChunkWriter("en")
    probe._open_next()
    limit = probe._current.data.tell() + len(entry) + len(generator._URLSET_CLOSE)
    monkeypatch.setattr(generator, "MAX_SITEMAP_BYTES", limit)

    writer = SitemapChunkWriter("en")
    assert writer.add(entry) is None
    finished = writer.add(entry)

    assert finished is not None
    assert finished.url_count == 1
    tail = writer.finish()
    assert tail is not None
    assert tail.url_count == 1
    assert len(writer.chunks) == 2
    assert finished.size <= limit
    assert tail.size <= limit


def test_site_url_must_be_an_absolute_origin(monkeypatch):
    monkeypatch.setattr(settings, "SITE_URL", "vinas.lt/sitemaps")
    with pytest.raises(RuntimeError, match="absolute http"):
        _require_site_url()

    monkeypatch.setattr(settings, "SITE_URL", "https://vinas.lt/")
    assert _require_site_url() == "https://vinas.lt"

    monkeypatch.setattr(settings, "SITE_URL", "http://localhost")
    assert _require_site_url() == "http://localhost"
