"""Amap POI search for tea shops, categories, and transit."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx

from app.paths import is_vercel

AMAP_BASE = "https://restapi.amap.com/v3"

# 个人开发者 Key 并发/QPS 较低，请求串行并限速
_REQUEST_LOCK = asyncio.Lock()
_MIN_REQUEST_GAP_SEC = 0.28 if not is_vercel() else 0.12

TEA_KEYWORDS = "奶茶|茶饮|柠檬茶|果茶|喜茶|奈雪|茶百道|古茗|蜜雪冰城|CoCo都可|一点点|沪上阿姨|书亦"

INDIRECT_KEYWORDS = "咖啡|咖啡厅|咖啡馆|果汁|鲜榨果汁|瑞幸|星巴克|库迪|Costa|MANNER"

NON_TEA_BLOCKLIST = (
    "必胜客", "肯德基", "麦当劳", "汉堡", "披萨", "壱番屋", "一番屋",
)

CHAIN_BRANDS = (
    "喜茶", "奈雪", "茶百道", "古茗", "蜜雪冰城", "蜜雪", "CoCo都可", "CoCo都可",
    "一点点", "沪上阿姨", "书亦烧仙草", "书亦", "茶颜悦色", "霸王茶姬",
    "七分甜", "益禾堂", "甜啦啦", "快乐柠檬", "乐乐茶",
)

CATEGORY_TYPES = {
    "mall": "060100|060101|060102",
    "dining": "050000",
    "leisure": "080000",
    "school": "141200|141201",
    "office": "120000|120201|120202",
    "community": "120300",
    "transit": "150500|150700",
    "hotel": "100000",
}

CATEGORY_FETCH_PAGE_SIZE = 25
CATEGORY_FETCH_MAX_PAGES = 2 if is_vercel() else 4
TEA_FETCH_MAX_PAGES = 2 if is_vercel() else 3
CATEGORY_FETCH_CAP = CATEGORY_FETCH_PAGE_SIZE * CATEGORY_FETCH_MAX_PAGES

# 国内高德直连；系统代理常导致 ConnectError（浏览器 JS 不受影响）
_AMAP_HTTPX_KW = {"timeout": 45.0 if is_vercel() else 120.0, "trust_env": False}

_QPS_MARKERS = ("CUQPS", "QPS", "EXCEEDED", "访问过于频繁", "超限")


async def _amap_get_json(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any],
    *,
    required: bool = True,
) -> dict[str, Any]:
    """Rate-limited Amap GET with QPS and connection retry."""
    async with _REQUEST_LOCK:
        for attempt in range(6):
            gap = _MIN_REQUEST_GAP_SEC - (time.monotonic() - getattr(_amap_get_json, "_last_at", 0.0))
            if gap > 0:
                await asyncio.sleep(gap)
            try:
                resp = await client.get(f"{AMAP_BASE}/{path}", params=params)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPError as exc:
                if attempt < 5 and _is_transient_http_error(exc):
                    await asyncio.sleep(0.8 * (attempt + 1))
                    continue
                raise RuntimeError(_friendly_network_error(exc)) from exc
            except ValueError as exc:
                raise RuntimeError(f"高德接口返回非 JSON：{exc}") from exc
            _amap_get_json._last_at = time.monotonic()  # type: ignore[attr-defined]

            if data.get("status") == "1":
                return data

            info = str(data.get("info") or data.get("infocode") or "未知错误")
            if _is_qps_error(info) and attempt < 5:
                await asyncio.sleep(0.6 * (attempt + 1))
                continue
            if not required:
                return data
            raise RuntimeError(_friendly_amap_error(info))
    raise RuntimeError("高德接口繁忙，请等待 10～20 秒后重试")


def _is_transient_http_error(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout)):
        return True
    name = type(exc).__name__
    return name in ("ConnectError", "ConnectTimeout", "ReadTimeout", "PoolTimeout", "RemoteProtocolError")


def _friendly_network_error(exc: BaseException) -> str:
    name = type(exc).__name__
    if name in ("ConnectError", "ConnectTimeout") or isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return (
            "无法连接高德服务器（ConnectError）。请检查本机网络/代理/VPN，"
            "确认 Python 进程能访问 restapi.amap.com 后重试"
        )
    if isinstance(exc, httpx.ReadTimeout) or name == "ReadTimeout":
        return "请求高德接口超时，请稍后重试"
    text = str(exc).strip()
    return text or name or "网络请求失败"


def _is_qps_error(info: str) -> bool:
    upper = info.upper()
    return any(m in upper for m in _QPS_MARKERS)


def _friendly_amap_error(info: str) -> str:
    if _is_qps_error(info):
        return "高德接口调用过于频繁（QPS 超限），请等待 10～20 秒后再次点击「生成完整报告」"
    if "DAILY" in info.upper() or "配额" in info:
        return "高德 Key 当日查询配额已用尽，请明日再试或更换 Key"
    return f"高德接口返回异常：{info}"


async def fetch_poi_bundle(location: dict[str, float], key: str, address: str, city: str) -> dict[str, Any]:
    lng, lat = location["lng"], location["lat"]
    async with httpx.AsyncClient(**_AMAP_HTTPX_KW) as client:
        # 串行拉取，避免个人 Key 触发 CUQPS_HAS_EXCEEDED_THE_LIMIT
        all_tea = await _search_tea(lng, lat, 1000, key, client)
        all_indirect, indirect_capped = await _search_indirect_beverage(lng, lat, 1000, key, client)
        category_counts, category_capped = await _count_categories_by_distance(lng, lat, key, client)
        transit = await _search_transit(lng, lat, key, address=address, client=client)

    poi_by_radius: dict[str, Any] = {}
    for radius in (300, 500, 1000):
        tea_shops = [s for s in all_tea if (s.get("distance_m") or 9999) <= radius]
        indirect = [s for s in all_indirect if (s.get("distance_m") or 9999) <= radius]
        categories = category_counts.get(str(radius), {})
        poi_by_radius[str(radius)] = {
            "tea_shops": tea_shops,
            "indirect_beverages": indirect,
            "categories": categories,
        }

    display_address = (address or "").strip() or f"{city} 候选点（{lng:.6f},{lat:.6f}）"
    return {
        "address": display_address,
        "city": city,
        "location": location,
        "query_time": _now_iso(),
        "data_source": "amap_web",
        "poi_by_radius": poi_by_radius,
        "transit": transit,
        "buildings": [],
        "poi_meta": {"category_capped": category_capped, "indirect_capped": indirect_capped},
    }


async def _search_tea(
    lng: float, lat: float, radius: int, key: str,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    pois: list[dict] = []
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=30.0, trust_env=False)
    try:
        for page in range(1, TEA_FETCH_MAX_PAGES + 1):
            params = {
                "key": key,
                "location": f"{lng},{lat}",
                "radius": radius,
                "keywords": TEA_KEYWORDS,
                "types": "050000",
                "extensions": "all",
                "offset": 25,
                "page": page,
                "output": "JSON",
            }
            data = await _amap_get_json(client, "place/around", params)
            batch = data.get("pois") or []
            if not batch:
                break
            pois.extend(batch)
            if len(batch) < 25:
                break
    finally:
        if own:
            await client.aclose()

    shops = []
    seen = set()
    for poi in pois:
        name = poi.get("name", "")
        if not _is_direct_tea_competitor(name):
            continue
        dist = int(float(poi.get("distance", 0)))
        if dist > radius:
            continue
        loc = poi.get("location", "")
        dedupe = (name, loc)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        rating = None
        biz_ext = poi.get("biz_ext") or {}
        if biz_ext.get("rating"):
            try:
                rating = float(biz_ext["rating"])
            except (TypeError, ValueError):
                rating = None
        slng, slat = _parse_location(poi.get("location", ""))
        shops.append({
            "name": name,
            "distance_m": dist,
            "chain": _is_chain(name),
            "competitor_type": "direct_tea",
            "rating": rating,
            "lng": slng,
            "lat": slat,
        })
    return sorted(shops, key=lambda x: x["distance_m"])


async def _search_indirect_beverage(
    lng: float, lat: float, radius: int, key: str,
    client: Optional[httpx.AsyncClient] = None,
) -> tuple[list[dict[str, Any]], bool]:
    pois: list[dict] = []
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=30.0, trust_env=False)
    try:
        for page in range(1, CATEGORY_FETCH_MAX_PAGES + 1):
            params = {
                "key": key,
                "location": f"{lng},{lat}",
                "radius": radius,
                "keywords": INDIRECT_KEYWORDS,
                "types": "050000",
                "extensions": "all",
                "offset": CATEGORY_FETCH_PAGE_SIZE,
                "page": page,
                "output": "JSON",
            }
            data = await _amap_get_json(client, "place/around", params, required=False)
            if data.get("status") != "1":
                break
            batch = data.get("pois") or []
            if not batch:
                break
            pois.extend(batch)
            if len(batch) < CATEGORY_FETCH_PAGE_SIZE:
                break
    finally:
        if own:
            await client.aclose()

    capped = len(pois) >= CATEGORY_FETCH_CAP

    shops = []
    seen = set()
    for poi in pois:
        name = poi.get("name", "")
        if not _is_indirect_beverage(name):
            continue
        if _is_direct_tea_competitor(name):
            continue
        dist = int(float(poi.get("distance", 0)))
        if dist > radius:
            continue
        loc = poi.get("location", "")
        dedupe = (name, loc)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        subtype = "coffee" if _is_coffee_name(name) else "other_beverage"
        slng, slat = _parse_location(loc)
        shops.append({
            "name": name,
            "distance_m": dist,
            "competitor_type": "indirect_beverage",
            "beverage_subtype": subtype,
            "lng": slng,
            "lat": slat,
        })
    return sorted(shops, key=lambda x: x["distance_m"]), capped


async def _count_categories_by_distance(
    lng: float, lat: float, key: str,
    client: Optional[httpx.AsyncClient] = None,
) -> tuple[dict[str, dict[str, int]], dict[str, bool]]:
    """One paginated fetch per category at 1000m; flag possible API page cap."""
    per_radius = {str(r): {cat: 0 for cat in CATEGORY_TYPES} for r in (300, 500, 1000)}
    capped: dict[str, bool] = {}
    for cat, types in CATEGORY_TYPES.items():
        pois = await _search_category_pois(lng, lat, 1000, types, key, client)
        capped[cat] = len(pois) >= CATEGORY_FETCH_CAP
        for poi in pois:
            dist = poi.get("distance_m") or 9999
            for radius in (300, 500, 1000):
                if dist <= radius:
                    per_radius[str(radius)][cat] += 1
    return per_radius, capped


async def _search_category_pois(
    lng: float, lat: float, radius: int, types: str, key: str,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    pois: list[dict] = []
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=30.0, trust_env=False)
    try:
        for page in range(1, CATEGORY_FETCH_MAX_PAGES + 1):
            params = {
                "key": key,
                "location": f"{lng},{lat}",
                "radius": radius,
                "types": types,
                "extensions": "base",
                "offset": CATEGORY_FETCH_PAGE_SIZE,
                "page": page,
                "output": "JSON",
            }
            data = await _amap_get_json(client, "place/around", params, required=False)
            if data.get("status") != "1":
                break
            batch = data.get("pois") or []
            if not batch:
                break
            pois.extend(batch)
            if len(batch) < CATEGORY_FETCH_PAGE_SIZE:
                break
    finally:
        if own:
            await client.aclose()

    seen: set[tuple[str, str]] = set()
    results: list[dict[str, Any]] = []
    for poi in pois:
        name = poi.get("name", "")
        loc = poi.get("location", "")
        dedupe = (name, loc)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        dist = int(float(poi.get("distance", 0)))
        if dist > radius:
            continue
        results.append({"name": name, "distance_m": dist, "location": loc})
    return results


async def _search_transit(
    lng: float, lat: float, key: str, address: str = "",
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    pois: list[dict] = []
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=30.0, trust_env=False)
    try:
        queries = [
            {"types": "150500|150700|150400", "keywords": ""},
            {"types": "150500", "keywords": "地铁站"},
        ]
        for q in queries:
            params = {
                "key": key,
                "location": f"{lng},{lat}",
                "radius": 2000,
                "types": q["types"],
                "keywords": q["keywords"],
                "extensions": "base",
                "offset": 25,
                "page": 1,
                "output": "JSON",
            }
            data = await _amap_get_json(client, "place/around", params, required=False)
            if data.get("status") != "1":
                continue
            pois.extend(data.get("pois") or [])
    finally:
        if own:
            await client.aclose()

    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for poi in pois:
        dedupe = (poi.get("name", ""), poi.get("location", ""))
        if dedupe in seen:
            continue
        seen.add(dedupe)
        unique.append(poi)

    results = []
    for i, poi in enumerate(sorted(unique, key=lambda p: float(p.get("distance", 99999)))[:12]):
        dist = int(float(poi.get("distance", 0)))
        ttype = "subway" if "地铁" in poi.get("type", "") or "150500" in str(poi.get("typecode", "")) else "bus"
        if i == 0 and client and not is_vercel():
            walk_dist, walk_note = await _walking_distance(lng, lat, poi, key, client)
        else:
            walk_dist, walk_note = None, "仅直线距离"
        slng, slat = _parse_location(poi.get("location", ""))
        results.append({
            "name": poi.get("name", ""),
            "type": ttype,
            "distance_m": dist,
            "walk_distance_m": walk_dist,
            "walk_note": walk_note,
            "lng": slng,
            "lat": slat,
        })
    return results


async def _walking_distance(origin_lng, origin_lat, poi, key, client=None):
    dest = poi.get("location", "")
    if not dest:
        return None, "仅直线距离"
    params = {
        "key": key,
        "origin": f"{origin_lng},{origin_lat}",
        "destination": dest,
        "output": "JSON",
    }
    try:
        if client:
            data = await _amap_get_json(client, "direction/walking", params, required=False)
        else:
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as c:
                data = await _amap_get_json(c, "direction/walking", params, required=False)
        if data.get("status") == "1" and data.get("route", {}).get("paths"):
            meters = int(data["route"]["paths"][0].get("distance", 0))
            straight = int(float(poi.get("distance", 0)))
            if meters < straight:
                return None, "步行路径异常，仅直线距离"
            return meters, "步行路径规划成功"
    except Exception:
        pass
    return None, "路径规划失败，仅直线距离"


def _parse_location(loc_str: str):
    if loc_str and "," in str(loc_str):
        try:
            parts = str(loc_str).split(",")
            return float(parts[0]), float(parts[1])
        except (TypeError, ValueError):
            pass
    return None, None


def _is_coffee_name(name: str) -> bool:
    markers = ("咖啡", "Coffee", "coffee", "瑞幸", "星巴克", "Starbucks", "库迪", "Cotti", "Costa", "MANNER")
    return any(m in name for m in markers)


def _is_indirect_beverage(name: str) -> bool:
    if not name:
        return False
    if any(b in name for b in ("奶茶", "茶饮", "柠檬茶", "果茶")):
        return False
    return _is_coffee_name(name) or any(m in name for m in ("果汁", "鲜榨", "饮品店"))


def _is_direct_tea_competitor(name: str) -> bool:
    if not name:
        return False
    for bad in NON_TEA_BLOCKLIST:
        if bad in name:
            return False
    if "CoCo" in name and ("壱" in name or "番" in name or "屋" in name):
        return False
    tea_markers = ("奶茶", "茶饮", "柠檬茶", "果茶", "茶铺", "茶店")
    if any(m in name for m in tea_markers):
        return True
    return any(brand in name for brand in CHAIN_BRANDS)


def _is_chain(name: str) -> bool:
    if not _is_direct_tea_competitor(name):
        return False
    if "CoCo" in name and ("壱" in name or "番" in name):
        return False
    return any(brand in name for brand in CHAIN_BRANDS)


def _now_iso() -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).isoformat()
