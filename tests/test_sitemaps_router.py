from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

import routers.v1.sitemaps as sitemaps
from config import Settings


class StubBody:
    def __init__(self, data: bytes):
        self.data = data
        self.closed = False

    def iter_chunks(self, size: int = 64 * 1024):
        for start in range(0, len(self.data), size):
            yield self.data[start : start + size]

    def close(self):
        self.closed = True


class StubS3:
    def __init__(self, error_code: str | None = None):
        self.error_code = error_code
        self.calls: list[tuple[str, dict]] = []
        self.body = b'<?xml version="1.0" encoding="UTF-8"?>\n<urlset></urlset>\n'
        self.etag = '"abc123"'
        # botocore returns a tz that is not datetime.timezone.utc
        self.last_modified = datetime(2026, 11, 16, 12, 0, tzinfo=ZoneInfo("UTC"))

    def head_object(self, **params):
        self.calls.append(("head_object", params))
        self._maybe_error("HeadObject", params)
        return self._head()

    def get_object(self, **params):
        self.calls.append(("get_object", params))
        self._maybe_error("GetObject", params)
        return {**self._head(), "Body": StubBody(self.body)}

    def _head(self) -> dict:
        return {
            "ETag": self.etag,
            "LastModified": self.last_modified,
            "ContentLength": len(self.body),
        }

    def _maybe_error(self, operation: str, params: dict):
        if params.get("IfNoneMatch") == self.etag:
            raise ClientError(
                {
                    "Error": {"Code": "304", "Message": "Not Modified"},
                    "ResponseMetadata": {
                        "HTTPStatusCode": 304,
                        "HTTPHeaders": {
                            "etag": self.etag,
                            "last-modified": "Mon, 16 Nov 2026 12:00:00 GMT",
                        },
                    },
                },
                operation,
            )
        if self.error_code:
            raise ClientError({"Error": {"Code": self.error_code}}, operation)


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setattr(sitemaps.settings, "SITEMAP_BUCKET", "vinas-files")
    monkeypatch.setattr(sitemaps.settings, "SITEMAP_PREFIX", "sitemaps/")

    def install(error_code: str | None = None) -> StubS3:
        stub = StubS3(error_code)
        monkeypatch.setattr(sitemaps, "_s3_client", lambda: stub)
        return stub

    return install


@pytest.fixture
def client():
    return TestClient(app_client(), follow_redirects=False)


def app_client():
    from main import app

    return app


def test_settings_read_bucket_and_region_from_shared_secrets(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "shared-bucket")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.delenv("SITEMAP_BUCKET", raising=False)
    monkeypatch.delenv("SITEMAP_BUCKET_REGION", raising=False)

    shared = Settings()
    assert (shared.SITEMAP_BUCKET, shared.SITEMAP_BUCKET_REGION) == (
        "shared-bucket",
        "eu-west-1",
    )

    monkeypatch.setenv("SITEMAP_BUCKET", "sitemap-only-bucket")
    assert Settings().SITEMAP_BUCKET == "sitemap-only-bucket"


def test_existing_sitemap_is_streamed(s3, client):
    stub = s3()

    response = client.get("/public/v1/sitemaps/sitemap.xml")

    assert response.status_code == 200
    assert response.content == stub.body
    assert response.headers["content-type"] == "application/xml; charset=utf-8"
    assert response.headers["cache-control"] == "public, max-age=300"
    assert response.headers["etag"] == stub.etag
    assert response.headers["last-modified"] == "Mon, 16 Nov 2026 12:00:00 GMT"
    assert "location" not in response.headers
    assert stub.calls == [
        (
            "get_object",
            {"Bucket": "vinas-files", "Key": "sitemaps/sitemap.xml"},
        )
    ]


def test_head_returns_headers_without_a_body(s3, client):
    stub = s3()

    response = client.head("/public/v1/sitemaps/sitemap.xml")

    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["etag"] == stub.etag
    assert response.headers["content-type"] == "application/xml; charset=utf-8"
    assert stub.calls[0][0] == "head_object"


def test_if_none_match_returns_304(s3, client):
    stub = s3()

    response = client.get(
        "/public/v1/sitemaps/sitemap.xml",
        headers={"If-None-Match": stub.etag},
    )

    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["etag"] == stub.etag
    assert response.headers["cache-control"] == "public, max-age=300"
    assert stub.calls[0][1]["IfNoneMatch"] == stub.etag


def test_if_modified_since_is_forwarded(s3, client):
    stub = s3()

    response = client.get(
        "/public/v1/sitemaps/sitemap.xml",
        headers={"If-Modified-Since": "Sun, 01 Nov 2026 00:00:00 GMT"},
    )

    assert response.status_code == 200
    forwarded = stub.calls[0][1]["IfModifiedSince"]
    assert forwarded == datetime(2026, 11, 1, tzinfo=timezone.utc)


def test_nested_static_sitemap_path_is_allowed(s3, client):
    stub = s3()

    response = client.get("/public/v1/sitemaps/static_sitemaps/pages.xml.gz")

    assert response.status_code == 200
    assert response.content == stub.body
    assert stub.calls[0][1]["Key"] == "sitemaps/static_sitemaps/pages.xml.gz"


@pytest.mark.parametrize("error_code", ["404", "NoSuchKey", "AccessDenied"])
def test_missing_sitemap_returns_404(s3, client, error_code):
    s3(error_code)

    response = client.get("/public/v1/sitemaps/sitemap-lots-en-9.xml")

    assert response.status_code == 404


@pytest.mark.parametrize(
    "path",
    ["..%2Fsecret.xml", "foo.txt", "a//b.xml", "sitemap index.xml", "sitemap.xml.bak"],
)
def test_invalid_paths_return_404_without_calling_s3(s3, client, path):
    stub = s3()

    response = client.get(f"/public/v1/sitemaps/{path}")

    assert response.status_code == 404
    assert stub.calls == []
