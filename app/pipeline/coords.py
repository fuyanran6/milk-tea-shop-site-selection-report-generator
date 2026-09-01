"""Coordinate transforms for overlaying OSM (WGS-84) on Amap (GCJ-02)."""

from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

_PI = math.pi
_A = 6378245.0
_EE = 0.00669342162296594323


def _out_of_china(lng: float, lat: float) -> bool:
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)


def _transform_lat(lng: float, lat: float) -> float:
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * _PI) + 20.0 * math.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * _PI) + 40.0 * math.sin(lat / 3.0 * _PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * _PI) + 320 * math.sin(lat * _PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng: float, lat: float) -> float:
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * _PI) + 20.0 * math.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * _PI) + 40.0 * math.sin(lng / 3.0 * _PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * _PI) + 300.0 * math.sin(lng / 30.0 * _PI)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng: float, lat: float) -> Tuple[float, float]:
    """Convert WGS-84 lon/lat to GCJ-02 for Amap basemap alignment."""
    if _out_of_china(lng, lat):
        return lng, lat
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * _PI
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * _PI)
    dlng = (dlng * 180.0) / (_A / sqrt_magic * math.cos(radlat) * _PI)
    return lng + dlng, lat + dlat


def convert_polygon_wgs84_to_gcj02(coords: Sequence[Sequence[float]]) -> List[List[float]]:
    return [list(wgs84_to_gcj02(float(lng), float(lat))) for lng, lat in coords]


def convert_buildings_to_gcj02(buildings: Iterable[dict]) -> List[dict]:
    out: List[dict] = []
    for b in buildings:
        coords = b.get("coords") or []
        if len(coords) < 3:
            continue
        out.append({**b, "coords": convert_polygon_wgs84_to_gcj02(coords)})
    return out
