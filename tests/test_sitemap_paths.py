from types import SimpleNamespace

from config import settings
from jobs.sitemap_generator import _lot_path


def _row(**overrides):
    values = {
        "base_site": "IAAI",
        "lot_id": "45790487",
        "year": 2008,
        "make": "FORD",
        "model": "EDGE",
        "vin": "2FMDK48CX8BA91950",
    }
    return SimpleNamespace(**{**values, **overrides})


def test_lot_path_matches_frontend_route():
    assert _lot_path(_row()) == "/lot/iaai/45790487/2008-ford-edge-2fmdk48cx8ba91950"


def test_lot_slug_is_url_safe_and_skips_missing_parts():
    path = _lot_path(_row(base_site="copart", make="Chevrolet", model="C/K 1500", vin=None))

    assert path == "/lot/copart/45790487/2008-chevrolet-c-k-1500"


def test_default_sitemap_languages_are_en_and_lt():
    assert settings.SITEMAP_LANGUAGES == ["en", "lt"]
