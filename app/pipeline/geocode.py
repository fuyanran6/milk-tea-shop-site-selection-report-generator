"""Geocoding and place search via Amap Web API."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

AMAP_BASE = "https://restapi.amap.com/v3"
_QPS_MARKERS = ("CUQPS", "QPS", "EXCEEDED", "访问过于频繁", "超限")


def _normalize_city(city: str) -> str:
    city = (city or "").strip()
    if city.endswith("市"):
        return city[:-1]
    return city


def _valid_location(loc: Any) -> bool:
    if not loc or loc == "[]":
        return False
    if not isinstance(loc, str) or "," not in loc:
        return False
    try:
        lng, lat = loc.split(",", 1)
        float(lng)
        float(lat)
        return True
    except (TypeError, ValueError):
        return False


def _parse_location(loc: str) -> Optional[Dict[str, float]]:
    if not _valid_location(loc):
        return None
    lng, lat = loc.split(",", 1)
    return {"lng": float(lng), "lat": float(lat)}


def _format_error(exc: BaseException) -> str:
    text = str(exc).strip()
    if text:
        return text
    return type(exc).__name__


async def _amap_get(path: str, params: dict) -> dict:
    """Never raises — returns {status, info, ...} or {status:0, info:...} on failure."""
    try:
        async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
            resp = await client.get(f"{AMAP_BASE}/{path}", params=params)
            resp.raise_for_status()
            data = resp.json()
        if not isinstance(data, dict):
            return {"status": "0", "info": "接口返回格式异常"}
        return data
    except json.JSONDecodeError as exc:
        return {"status": "0", "info": f"接口返回非 JSON：{_format_error(exc)}"}
    except httpx.HTTPError as exc:
        return {"status": "0", "info": f"网络请求失败：{_format_error(exc)}"}
    except Exception as exc:
        logger.warning("amap_get_fail path=%s err=%s", path, _format_error(exc))
        return {"status": "0", "info": _format_error(exc)}


async def geocode(city: str, address: str, key: str) -> dict:
    city_norm = _normalize_city(city)
    query = address if city_norm in address else f"{city_norm}{address}"
    params = {"key": key, "address": query, "city": city_norm or city, "output": "JSON"}
    data = await _amap_get("geocode/geo", params)
    if data.get("status") != "1" or not data.get("geocodes"):
        info = str(data.get("info") or "地理编码失败")
        raise ValueError(f"{info}{_amap_key_hint(info)}")
    geocodes = data.get("geocodes") or []
    if not geocodes:
        raise ValueError("地理编码未返回结果")
    geo = geocodes[0] if isinstance(geocodes[0], dict) else {}
    if not _valid_location(geo.get("location")):
        raise ValueError("地理编码未返回有效坐标")
    lng, lat = geo["location"].split(",")
    return {
        "address": geo.get("formatted_address", address),
        "city": city,
        "location": {"lng": float(lng), "lat": float(lat)},
        "level": geo.get("level"),
    }


def _looks_like_address(keywords: str) -> bool:
    if any(ch in keywords for ch in "路街巷道号弄里"):
        return True
    return len(keywords) <= 12


async def search_locations(keywords: str, city: str, key: str) -> dict:
    """Combined place search for the UI 检索 button."""
    keywords = (keywords or "").strip()
    city_raw = (city or "").strip()
    city_norm = _normalize_city(city_raw)
    if not key:
        return {"tips": [], "error": "未提供 Web 服务 Key", "count": 0}

    results: List[dict] = []
    seen: set = set()
    last_error = ""

    def add_item(name: str, address: str, location: str, source: str):
        if not name or not _valid_location(location):
            return
        key_tuple = (name, location)
        if key_tuple in seen:
            return
        seen.add(key_tuple)
        results.append({
            "name": name,
            "address": address or name,
            "location": location,
            "source": source,
        })

    try:
        last_error = await _search_locations_impl(
            keywords, city_raw, city_norm, key, results, seen, last_error, add_item
        )
    except Exception as exc:
        logger.exception("search_locations_fail keywords=%s", keywords[:40])
        if results:
            return {"tips": results[:15], "error": "", "count": len(results)}
        return {
            "tips": [],
            "error": _format_error(exc) or "检索服务异常，请稍后重试",
            "count": 0,
        }

    return {
        "tips": results[:15],
        "error": last_error if not results else "",
        "count": len(results),
    }


def _amap_key_hint(info: str) -> str:
    upper = (info or "").upper()
    if any(tok in upper for tok in ("INVALID_USER_KEY", "USERKEY", "USER_KEY", "PLATFORM", "PLAT")):
        return "（请确认使用的是「Web 服务」类型 Key，不是 JS API Key）"
    if any(tok in upper for tok in _QPS_MARKERS):
        return "（调用过于频繁，请稍后重试）"
    return ""


async def _search_locations_impl(
    keywords: str,
    city_raw: str,
    city_norm: str,
    key: str,
    results: List[dict],
    seen: set,
    last_error: str,
    add_item,
) -> str:
    # 1) 道路/地址类优先地理编码（如「四川北路」）
    if _looks_like_address(keywords):
        try:
            geo = await geocode(city_raw or city_norm, keywords, key)
            loc = f"{geo['location']['lng']},{geo['location']['lat']}"
            add_item(keywords, geo.get("address", keywords), loc, "geocode")
        except ValueError as exc:
            last_error = str(exc)

    # 2) POI 文本搜索（精简参数组合，降低 QPS 与超时概率）
    if len(results) < 5:
        text_attempts = [
            (keywords, city_norm, "true"),
            (keywords, city_norm, "false"),
        ]
        if city_norm and city_norm not in keywords:
            text_attempts.insert(0, (f"{city_norm}{keywords}", city_norm, "true"))

        for kw_try, city_try, citylimit in text_attempts:
            text_params: dict[str, Any] = {
                "key": key,
                "keywords": kw_try,
                "offset": 10,
                "page": 1,
                "extensions": "base",
                "output": "JSON",
            }
            if city_try:
                text_params["city"] = city_try
                text_params["citylimit"] = citylimit
            text_data = await _amap_get("place/text", text_params)
            if text_data.get("status") != "1":
                info = str(text_data.get("info") or "POI 搜索失败")
                if not last_error:
                    last_error = info + _amap_key_hint(info)
                continue
            for poi in text_data.get("pois") or []:
                if not isinstance(poi, dict):
                    continue
                name = poi.get("name") or ""
                addr = poi.get("address") or poi.get("cityname") or ""
                loc = poi.get("location") or ""
                add_item(name, addr, loc, "place/text")
            if len(results) >= 3:
                break

    # 3) 输入提示（仅采纳带坐标的项）
    if len(results) < 5:
        tips_params = {
            "key": key,
            "keywords": keywords,
            "city": city_norm or city_raw,
            "citylimit": "false",
            "datatype": "all",
            "output": "JSON",
        }
        tips_data = await _amap_get("assistant/inputtips", tips_params)
        if tips_data.get("status") != "1":
            if not last_error:
                info = str(tips_data.get("info") or "输入提示接口失败")
                last_error = info + _amap_key_hint(info)
        else:
            for tip in tips_data.get("tips") or []:
                if not isinstance(tip, dict):
                    continue
                name = tip.get("name") or ""
                addr = tip.get("address") or tip.get("district") or ""
                if isinstance(addr, list):
                    addr = "".join(str(x) for x in addr)
                loc = tip.get("location") or ""
                add_item(name, str(addr), loc, "inputtips")

    # 4) 地理编码兜底
    if not results:
        try:
            geo = await geocode(city_raw or city_norm, keywords, key)
            loc = f"{geo['location']['lng']},{geo['location']['lat']}"
            add_item(keywords, geo.get("address", keywords), loc, "geocode")
        except ValueError as exc:
            if not last_error:
                last_error = str(exc)

    return last_error if not results else ""


async def input_tips(keywords: str, city: str, key: str) -> List[dict]:
    """Legacy wrapper — prefer search_locations."""
    data = await search_locations(keywords, city, key)
    return data.get("tips", [])
