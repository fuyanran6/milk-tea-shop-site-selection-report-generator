"""OSM Overpass building footprints with grid cache."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, List, Tuple

import httpx

from app.paths import OSM_CACHE_DIR as CACHE_DIR
CACHE_TTL_SECONDS = 3600

# 多节点容错；部分节点对缺 User-Agent / Content-Type 会返回 406
OVERPASS_ENDPOINTS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)

USER_AGENT = "MilkteaSiteAssessor/1.0 (site-selection-mvp; contact=local)"

OSM_NOTE_DEFAULT = "建筑轮廓来自 OpenStreetMap，覆盖因城市而异。"
OSM_NOTE_FAILURE = "本区域 OSM 建筑轮廓暂未获取（不影响街道底图与分析图层）"


def format_osm_note_for_report(note: str) -> str:
    """Chapter body: no raw HTTP / exception strings."""
    if not note:
        return OSM_NOTE_DEFAULT
    if note == OSM_NOTE_FAILURE:
        return OSM_NOTE_FAILURE
    if "已获取" in note or "缓存命中" in note or "覆盖稀疏" in note:
        return note
    low = note.lower()
    if any(tok in low for tok in ("406", "http", "client error", "not acceptable", "查询失败", "降级", "不可用")):
        return OSM_NOTE_FAILURE
    return note


def format_osm_note_for_appendix(note: str) -> str:
    """Appendix: brief status only; technical detail lives in result.errors."""
    if not note:
        return "见分析图备注"
    if "已获取" in note or "缓存命中" in note:
        return note
    if "覆盖稀疏" in note:
        return "本区域无 OSM 建筑轮廓（国内常见）"
    low = note.lower()
    if any(tok in low for tok in ("406", "http", "client error", "not acceptable", "查询失败", "降级")):
        return "Overpass 未返回建筑轮廓（服务不可用或覆盖稀疏）"
    return note


async def fetch_buildings(lng: float, lat: float, radius_m: int = 500) -> Tuple[List[dict], str]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    grid_key = _grid_key(lng, lat)
    cache_file = CACHE_DIR / f"{grid_key}.json"

    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if cached.get("failed"):
            try:
                cache_file.unlink()
            except FileNotFoundError:
                pass
        elif time.time() - cached.get("ts", 0) < CACHE_TTL_SECONDS:
            buildings = cached.get("buildings", [])
            if buildings:
                return buildings, "OSM 缓存命中"
            return [], "OSM 覆盖稀疏，本区域无建筑轮廓（国内常见）"

    query = (
        f'[out:json][timeout:25];('
        f'way["building"](around:{radius_m},{lat},{lng});'
        f'relation["building"](around:{radius_m},{lat},{lng});'
        f");out geom;"
    )

    data, endpoint = await _overpass_query(query)
    if data is None:
        cache_file.write_text(
            json.dumps({"ts": time.time(), "failed": True, "buildings": []}),
            encoding="utf-8",
        )
        return [], OSM_NOTE_FAILURE

    buildings = []
    for el in data.get("elements", []):
        coords = _extract_coords(el)
        if coords:
            buildings.append({"id": str(el.get("id")), "coords": coords})

    cache_file.write_text(json.dumps({"ts": time.time(), "buildings": buildings}), encoding="utf-8")
    if buildings:
        note = f"OSM 建筑轮廓已获取（{endpoint}）"
    else:
        note = "OSM 覆盖稀疏，本区域无建筑轮廓（国内常见）"
    return buildings, note


async def _overpass_query(query: str):
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }
    last_err = ""
    for url in OVERPASS_ENDPOINTS:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=8.0, read=40.0, write=10.0, pool=5.0)) as client:
                # 方式 1：标准 form 提交（Overpass 推荐）
                resp = await client.post(
                    url,
                    data={"data": query},
                    headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
                )
                if resp.status_code == 406:
                    # 方式 2：纯文本 body
                    resp = await client.post(
                        url,
                        content=query.encode("utf-8"),
                        headers={**headers, "Content-Type": "text/plain; charset=utf-8"},
                    )
                if resp.status_code == 406:
                    # 方式 3：GET（部分镜像仅接受 query 参数）
                    resp = await client.get(
                        url,
                        params={"data": query},
                        headers=headers,
                    )
                if resp.status_code in (429, 502, 504):
                    last_err = f"HTTP {resp.status_code}"
                    continue
                resp.raise_for_status()
                return resp.json(), url.split("/")[2]
        except Exception as exc:
            last_err = str(exc)
            continue
    return None, last_err


def _grid_key(lng: float, lat: float) -> str:
    grid_lng = round(lng, 3)
    grid_lat = round(lat, 3)
    return hashlib.md5(f"{grid_lng},{grid_lat}".encode()).hexdigest()[:16]


def _extract_coords(element):
    if "geometry" in element:
        coords = [[pt["lon"], pt["lat"]] for pt in element["geometry"]]
        if len(coords) >= 3:
            return coords
    if "members" in element:
        for m in element["members"]:
            if "geometry" in m:
                coords = [[pt["lon"], pt["lat"]] for pt in m["geometry"]]
                if len(coords) >= 3:
                    return coords
    return None
