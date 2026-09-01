"""Shared helpers for analysis map PNG / SVG export."""

from __future__ import annotations

import base64
import io
import json
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from app.pipeline.report_insights import map_headline

logger = logging.getLogger(__name__)

METERS_PER_DEG_LAT = 111320
MAP_VIEW_RADIUS_M = 1000
MAP_VIEW_PADDING = 1.38
BASEMAP_IMG_SIZE = 512
BASEMAP_IMG_SCALE = 2

COLOR_TEA_NEAR = "#E03131"
COLOR_TEA_FAR = "#1B3A6B"

RADIUS_STYLES = (
    (1000, "#FFF3BF", "#FFD43B", 1.2),
    (500, "#FFE8CC", "#FFA94D", 1.5),
    (300, "#FFE3E3", "#FA5252", 2.2),
)


@dataclass
class MapLayerContext:
    lng: float
    lat: float
    cos_lat: float
    extent: list[float]
    title: str
    basemap_note: str
    basemap_ok: bool
    basemap_image: Optional[Any] = None
    tea_near: list[tuple[float, float]] = field(default_factory=list)
    tea_other: list[tuple[float, float]] = field(default_factory=list)
    indirect: list[tuple[float, float]] = field(default_factory=list)
    transit: list[tuple[float, float]] = field(default_factory=list)


def analysis_extent(lng: float, lat: float, cos_lat: float) -> list[float]:
    """Geographic bounds with margin beyond the outer 1000m circle."""
    half_lng = (MAP_VIEW_RADIUS_M * MAP_VIEW_PADDING) / (METERS_PER_DEG_LAT * cos_lat)
    half_lat = (MAP_VIEW_RADIUS_M * MAP_VIEW_PADDING) / METERS_PER_DEG_LAT
    return [lng - half_lng, lng + half_lng, lat - half_lat, lat + half_lat]


def compute_basemap_zoom(lat: float, target_half_m: float, img_pixels: int) -> int:
    cos_lat = max(0.7, abs(math.cos(math.radians(lat))))
    for zoom in range(18, 9, -1):
        mpp = 156543.03392 * cos_lat / (2 ** zoom)
        if (img_pixels / 2) * mpp >= target_half_m:
            return zoom
    return 10


def build_map_context(
    features: dict,
    amap_key: Optional[str] = None,
    basemap_override: Optional[tuple[Any, str]] = None,
) -> MapLayerContext:
    lng = features["location"]["lng"]
    lat = features["location"]["lat"]
    cos_lat = max(0.7, abs(math.cos(math.radians(lat))))

    basemap_image = None
    basemap_note = ""
    basemap_ok = False
    extent = analysis_extent(lng, lat, cos_lat)

    if basemap_override is not None:
        basemap_image, basemap_note = basemap_override
        basemap_ok = True
    elif amap_key:
        basemap_image, extent, basemap_note, basemap_ok = fetch_amap_basemap(lng, lat, amap_key)
        if not basemap_ok:
            logger.warning("amap_basemap_fail lng=%s lat=%s note=%s", lng, lat, basemap_note)

    tea_near, tea_other, indirect_pts, transit_pts = _collect_map_points(features, lng, lat)

    return MapLayerContext(
        lng=lng,
        lat=lat,
        cos_lat=cos_lat,
        extent=extent,
        title=map_headline(features),
        basemap_note=basemap_note,
        basemap_ok=basemap_ok,
        basemap_image=basemap_image,
        tea_near=tea_near,
        tea_other=tea_other,
        indirect=indirect_pts,
        transit=transit_pts,
    )


def _collect_map_points(
    features: dict, lng: float, lat: float
) -> tuple[list, list, list, list]:
    tea_all = (
        features.get("tea_shops_1000m")
        or features.get("tea_shops_500m")
        or features.get("tea_shops_300m")
        or []
    )
    shops = sorted(tea_all, key=lambda s: s.get("distance_m") or 9999)
    nearest_ids = {id(s) for s in shops[:3]}
    tea_near, tea_other = [], []
    for i, shop in enumerate(shops):
        slng, slat = shop_coords(lng, lat, shop, i)
        if id(shop) in nearest_ids:
            tea_near.append((slng, slat))
        else:
            tea_other.append((slng, slat))

    indirect_all = (
        features.get("indirect_beverages_1000m")
        or features.get("indirect_beverages_500m")
        or features.get("indirect_beverages_300m")
        or []
    )
    indirect_pts = []
    for j, shop in enumerate(indirect_all):
        if shop.get("lng") is not None and shop.get("lat") is not None:
            indirect_pts.append((shop["lng"], shop["lat"]))
        else:
            indirect_pts.append(offset_point(lng, lat, shop.get("distance_m") or 80, 200 + j * 22))

    transit_pts = []
    for j, t in enumerate(features.get("transit", []) or []):
        if t.get("lng") is not None and t.get("lat") is not None:
            transit_pts.append((t["lng"], t["lat"]))
        else:
            transit_pts.append(offset_point(lng, lat, t.get("distance_m") or 100, 110 + j * 25))

    return tea_near, tea_other, indirect_pts, transit_pts


def fetch_amap_basemap(
    lng: float, lat: float, key: str,
) -> tuple[Optional[Any], list[float], str, bool]:
    from app.pipeline.runtime import imaging_stack_available

    if not imaging_stack_available():
        cos_lat = max(0.7, abs(math.cos(math.radians(lat))))
        return None, analysis_extent(lng, lat, cos_lat), "云端环境未加载图像库，仅显示分析图层", False

    from PIL import Image

    width, height = BASEMAP_IMG_SIZE, BASEMAP_IMG_SIZE
    scale = BASEMAP_IMG_SCALE
    pixel_size = width * scale
    target_half_m = MAP_VIEW_RADIUS_M * MAP_VIEW_PADDING
    zoom = compute_basemap_zoom(lat, target_half_m, pixel_size)
    params = {
        "location": f"{lng},{lat}",
        "zoom": str(zoom),
        "size": f"{width}*{height}",
        "scale": str(scale),
        "key": key,
    }
    last_err = ""
    for attempt in range(3):
        try:
            with httpx.Client(timeout=25.0, trust_env=False) as client:
                resp = client.get("https://restapi.amap.com/v3/staticmap", params=params)
                resp.raise_for_status()
                ctype = resp.headers.get("content-type", "")
                if "json" in ctype or resp.content[:1] == b"{":
                    try:
                        payload = resp.json()
                        info = payload.get("info") or payload.get("infocode") or str(payload)[:120]
                    except json.JSONDecodeError:
                        info = resp.text[:120]
                    return None, analysis_extent(lng, lat, max(0.7, abs(math.cos(math.radians(lat))))), (
                        f"高德静态底图获取失败（{info}），仅显示分析图层"
                    ), False
                img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                extent = static_map_extent(lng, lat, zoom, pixel_size, pixel_size)
                return img, extent, "街道底图：高德静态地图", True
        except Exception as exc:
            last_err = str(exc)[:120]
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
    cos_lat = max(0.7, abs(math.cos(math.radians(lat))))
    note = f"高德静态底图获取失败（{last_err or '网络请求失败'}），仅显示分析图层"
    return None, analysis_extent(lng, lat, cos_lat), note, False


def static_map_extent(lng: float, lat: float, zoom: int, width: int, height: int) -> list[float]:
    mpp = 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom)
    half_w_m = (width / 2) * mpp
    half_h_m = (height / 2) * mpp
    dlng = half_w_m / (METERS_PER_DEG_LAT * max(0.7, abs(math.cos(math.radians(lat)))))
    dlat = half_h_m / METERS_PER_DEG_LAT
    return [lng - dlng, lng + dlng, lat - dlat, lat + dlat]


def shop_coords(lng: float, lat: float, shop: dict, index: int) -> tuple[float, float]:
    if shop.get("lng") is not None and shop.get("lat") is not None:
        return shop["lng"], shop["lat"]
    return offset_point(lng, lat, shop.get("distance_m") or 50, 40 + (index % 9) * 38)


def offset_point(lng: float, lat: float, distance_m: float, bearing_deg: float) -> tuple[float, float]:
    br = math.radians(bearing_deg)
    dlat = (distance_m * math.cos(br)) / METERS_PER_DEG_LAT
    dlng = (distance_m * math.sin(br)) / (METERS_PER_DEG_LAT * max(0.7, abs(math.cos(math.radians(lat)))))
    return lng + dlng, lat + dlat


def radius_deg(radius_m: float, cos_lat: float) -> float:
    return radius_m / (METERS_PER_DEG_LAT * cos_lat)


def image_to_data_uri(img: Any, fmt: str = "JPEG", *, quality: int = 88) -> str:
    from PIL import Image

    if not isinstance(img, Image.Image):
        raise TypeError("expected PIL Image")
    buf = io.BytesIO()
    if fmt.upper() == "JPEG":
        img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
        mime = "jpeg"
    else:
        img.save(buf, format=fmt)
        mime = fmt.lower()
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/{mime};base64,{b64}"


def meters_to_pixel(radius_m: float, extent: list[float], cos_lat: float, width: float) -> float:
    xmin, xmax = extent[0], extent[1]
    span_x_m = (xmax - xmin) * METERS_PER_DEG_LAT * cos_lat
    if span_x_m <= 0 or width <= 0:
        return 1.0
    return radius_m / (span_x_m / width)


def geo_to_pixel(lng: float, lat: float, extent: list[float], width: float, height: float) -> tuple[float, float]:
    xmin, xmax, ymin, ymax = extent
    x = (lng - xmin) / (xmax - xmin) * width if xmax != xmin else width / 2
    y = (ymax - lat) / (ymax - ymin) * height if ymax != ymin else height / 2
    return x, y
