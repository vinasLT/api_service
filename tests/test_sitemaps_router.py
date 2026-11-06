import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

import routers.v1.sitemaps as sitemaps
from config import Settings, settings
from main import app


class StubS3:
    def __init__(self, error_code: str | None = None):
        self.error_code = error_code
        self.calls: list[tuple[str, dict]] = []

    def head_object(self, **params):
        self.calls.append(("head_object", params))
        if self.error_code:
            raise ClientError({"Error": {"Code": self.error_code}}, "HeadObject")

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.calls.append((operation, {**Params, "ExpiresIn": ExpiresIn}))
        return f"https://s3.example/{Params['Bucket']}/{Params['Key']}?signed"


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setattr(settings, "SITEMAP_BUCKET", "vinas-files")
    monkeypatch.setattr(settings, "SITEMAP_PREFIX", "sitemaps/")

    def install(error_code: str | None = None) -> StubS3:
        stub = StubS3(error_code)
        monkeypatch.setattr(sitemaps, "_s3_client", lambda: stub)
        return stub

    return install


@pytest.fixture
def client():
    return TestClient(app, follow_redirects=False)


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


def test_existing_sitemap_redirects_to_presigned_url(s3, client):
    stub = s3()

    response = client.get("/public/v1/sitemaps/sitemap-index.xml")

    assert response.status_code == 302
    assert response.headers["location"] == (
        "https://s3.example/vinas-files/sitemaps/sitemap-index.xml?signed"
    )
    assert response.headers["cache-control"] == "no-store"
    assert stub.calls[0] == (
        "head_object",
        {"Bucket": "vinas-files", "Key": "sitemaps/sitemap-index.xml"},
    )
    assert stub.calls[1][1]["ExpiresIn"] == settings.SITEMAP_URL_TTL_SECONDS


def test_nested_static_sitemap_path_is_allowed(s3, client):
    s3()

    response = client.get("/public/v1/sitemaps/static_sitemaps/pages.xml.gz")

    assert response.status_code == 302
    assert response.headers["location"].endswith("sitemaps/static_sitemaps/pages.xml.gz?signed")


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
