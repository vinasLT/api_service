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


def test_empty_slug_uses_lot():
    path = _lot_path(_row(year=None, make=None, model=None, vin=None))

    assert path == "/lot/iaai/45790487/lot"


def test_thousands_separator_stays_a_hyphen():
    path = _lot_path(
        _row(year=2025, make="Others", model="20 X 10,000 Psi Air Pumps", vin="38912120")
    )

    assert path.endswith("/2025-others-20-x-10-000-psi-air-pumps-38912120")


def test_non_decomposable_letters_are_dropped():
    path = _lot_path(_row(year=1997, make="Lexus", model="S\u0421 300", vin=None))

    assert path.endswith("/1997-lexus-s-300")


def test_html_entities_are_kept_as_text():
    path = _lot_path(
        _row(
            year=2015,
            make="Changzhou",
            model="8&#39; Sa Utility Traile",
            vin="LN2UT1111FZ211575",
        )
    )

    assert path.endswith("/2015-changzhou-8-39-sa-utility-traile-ln2ut1111fz211575")


def test_accents_are_stripped():
    path = _lot_path(_row(year=2012, make="\u0160koda", model="Octavia", vin=None))

    assert path.endswith("/2012-skoda-octavia")
