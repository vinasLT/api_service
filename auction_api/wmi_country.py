"""
WMI (World Manufacturer Identifier) to country decoding.

Mapping sourced from ISO 3780 / ISO 3779 country code assignments as documented on
Wikipedia (April 2019) and Wikibooks VIN WMI reference:
https://en.wikipedia.org/wiki/Vehicle_identification_number
https://en.wikibooks.org/wiki/Vehicle_Identification_Numbers_(VIN_codes)/World_Manufacturer_Identifier_(WMI)
"""

from __future__ import annotations

# VIN character set order used for WMI range comparisons (ISO 3779).
_VIN_CHARS = "0123456789ABCDEFGHJKLMNPRSTUVWXYZ"

# (range_start, range_end, country_name)
# Ranges are matched longest-first; first match wins.
_WMI_COUNTRY_RANGES: tuple[tuple[str, str, str], ...] = (
    # Africa
    ("AA", "AH", "South Africa"),
    ("AJ", "AK", "Côte d'Ivoire"),
    ("AL", "AM", "Lesotho"),
    ("AN", "AP", "Botswana"),
    ("AR", "AS", "Namibia"),
    ("AT", "AU", "Madagascar"),
    ("AV", "AW", "Mauritius"),
    ("AX", "AY", "Tunisia"),
    ("AZ", "A1", "Cyprus"),
    ("A2", "A3", "Zimbabwe"),
    ("A4", "A5", "Mozambique"),
    ("BA", "BB", "Angola"),
    ("BC", "BC", "Ethiopia"),
    ("BF", "BG", "Kenya"),
    ("BH", "BH", "Rwanda"),
    ("BL", "BL", "Nigeria"),
    ("BR", "BR", "Algeria"),
    ("BT", "BT", "Eswatini"),
    ("BU", "BU", "Uganda"),
    ("B3", "B4", "Libya"),
    ("CA", "CB", "Egypt"),
    ("CF", "CG", "Morocco"),
    ("CL", "CM", "Zambia"),
    # Asia
    ("KF", "KH", "Israel"),
    ("KL", "KR", "South Korea"),
    ("KS", "KT", "Jordan"),
    ("K1", "K3", "South Korea"),
    ("K5", "K5", "Kyrgyzstan"),
    ("MA", "ME", "India"),
    ("MF", "MK", "Indonesia"),
    ("ML", "MR", "Thailand"),
    ("MS", "MS", "Myanmar"),
    ("MU", "MU", "Mongolia"),
    ("MX", "MX", "Kazakhstan"),
    ("MY", "M0", "India"),
    ("NA", "NE", "Iran"),
    ("NF", "NG", "Pakistan"),
    ("NJ", "NJ", "Iraq"),
    ("NL", "NR", "Turkey"),
    ("NS", "NT", "Uzbekistan"),
    ("NV", "NV", "Azerbaijan"),
    ("NX", "NX", "Tajikistan"),
    ("NY", "NY", "Armenia"),
    ("N1", "N5", "Iran"),
    ("N7", "N8", "Turkey"),
    ("PA", "PC", "Philippines"),
    ("PF", "PG", "Singapore"),
    ("PL", "PR", "Malaysia"),
    ("PS", "PT", "Bangladesh"),
    ("PV", "PV", "Cambodia"),
    ("P5", "P0", "India"),
    ("RA", "RB", "United Arab Emirates"),
    ("RF", "RK", "Taiwan"),
    ("RL", "RN", "Vietnam"),
    ("RP", "RP", "Laos"),
    ("RS", "RT", "Saudi Arabia"),
    ("R1", "R7", "Hong Kong"),
    ("H", "H", "China"),
    ("J", "J", "Japan"),
    ("L", "L", "China"),
    # Europe
    ("SA", "SM", "United Kingdom"),
    ("SN", "ST", "Germany"),
    ("SU", "SZ", "Poland"),
    ("S1", "S2", "Latvia"),
    ("S3", "S3", "Georgia"),
    ("S4", "S4", "Iceland"),
    ("TA", "TH", "Switzerland"),
    ("TJ", "TP", "Czech Republic"),
    ("TR", "TV", "Hungary"),
    ("TW", "T2", "Portugal"),
    ("T3", "T5", "Serbia"),
    ("T6", "T6", "Andorra"),
    ("T7", "T8", "Netherlands"),
    ("UA", "UC", "Spain"),
    ("UH", "UM", "Denmark"),
    ("UN", "UR", "Ireland"),
    ("UU", "UX", "Romania"),
    ("U1", "U2", "North Macedonia"),
    ("U5", "U7", "Slovakia"),
    ("U8", "U0", "Bosnia and Herzegovina"),
    ("VA", "VE", "Austria"),
    ("VF", "VR", "France"),
    ("VS", "VW", "Spain"),
    ("VX", "V2", "France"),
    ("V3", "V5", "Croatia"),
    ("V6", "V8", "Estonia"),
    ("XA", "XC", "Bulgaria"),
    ("XD", "XE", "Russia"),
    ("XF", "XH", "Greece"),
    ("XJ", "XK", "Russia"),
    ("XL", "XR", "Netherlands"),
    ("XS", "XW", "Russia"),
    ("XX", "XY", "Luxembourg"),
    ("XZ", "X1", "Russia"),
    ("YA", "YE", "Belgium"),
    ("YF", "YK", "Finland"),
    ("YN", "YN", "Malta"),
    ("YS", "YW", "Sweden"),
    ("YX", "Y2", "Norway"),
    ("Y3", "Y5", "Belarus"),
    ("Y6", "Y9", "Ukraine"),
    ("ZA", "ZU", "Italy"),
    ("ZX", "ZZ", "Slovenia"),
    ("Z1", "Z1", "San Marino"),
    ("Z3", "Z5", "Lithuania"),
    ("Z6", "Z0", "Russia"),
    ("E", "E", "Russia"),
    ("W", "W", "Germany"),
    # North America
    ("3A", "3X", "Mexico"),
    ("34", "34", "Nicaragua"),
    ("35", "35", "Dominican Republic"),
    ("36", "36", "Honduras"),
    ("37", "37", "Panama"),
    ("38", "39", "Puerto Rico"),
    ("7F", "70", "United States"),
    ("1", "1", "United States"),
    ("2", "2", "Canada"),
    ("4", "4", "United States"),
    ("5", "5", "United States"),
    ("7", "7", "United States"),
    # Oceania
    ("6A", "6X", "Australia"),
    ("6Y", "61", "New Zealand"),
    ("7A", "7E", "New Zealand"),
    ("6", "6", "Australia"),
    # South America
    ("8A", "8E", "Argentina"),
    ("8F", "8G", "Chile"),
    ("8L", "8N", "Ecuador"),
    ("8S", "8W", "Peru"),
    ("8X", "8Z", "Venezuela"),
    ("82", "82", "Bolivia"),
    ("84", "84", "Costa Rica"),
    ("9A", "9E", "Brazil"),
    ("9F", "9G", "Colombia"),
    ("9S", "9V", "Uruguay"),
    ("90", "91", "Brazil"),
)

_SORTED_WMI_RANGES = sorted(_WMI_COUNTRY_RANGES, key=lambda item: len(item[0]), reverse=True)


def _char_index(char: str) -> int:
    return _VIN_CHARS.index(char)


def _prefix_in_range(prefix: str, start: str, end: str) -> bool:
    length = len(start)
    if len(end) != length or len(prefix) < length:
        return False

    prefix_part = prefix[:length]
    start_indices = tuple(_char_index(char) for char in start)
    end_indices = tuple(_char_index(char) for char in end)
    prefix_indices = tuple(_char_index(char) for char in prefix_part)

    if start_indices > end_indices:
        start_indices, end_indices = end_indices, start_indices

    return start_indices <= prefix_indices <= end_indices


def decode_wmi_country(vin: str | None) -> str | None:
    """Return the country name derived from the VIN WMI, or None if unknown."""
    if not vin:
        return None

    normalized_vin = vin.strip().replace(" ", "").upper()
    if len(normalized_vin) < 1:
        return None

    invalid_chars = set(normalized_vin) - set(_VIN_CHARS)
    if invalid_chars:
        return None

    for start, end, country in _SORTED_WMI_RANGES:
        if _prefix_in_range(normalized_vin, start, end):
            return country

    return None
