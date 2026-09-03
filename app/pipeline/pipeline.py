"""Fixed pipeline orchestrator — tools called in order, no model autonomy."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from app.paths import DEMO_DIR, OUTPUT_DIR, ROOT
from app.pipeline.amap_poi import fetch_poi_bundle
from app.pipeline.export_docx import export_docx
from app.pipeline.features import build_evidence_table, build_features
from app.pipeline.generate import generate_report
from app.pipeline.geocode import geocode
from app.pipeline.report_state import validate_report_consistency
from app.pipeline.runtime import imaging_stack_available
from app.pipeline.validation import normalize_poi_bundle, run_report_qc

from app.pipeline.scoring import compute_score

DEMO_A_MAP = DEMO_DIR / "demo_a_map.png"
PLACEHOLDER_PNG = ROOT / "app" / "static" / "placeholder-analysis.png"

# 1x1 gray PNG — fallback when imaging stack unavailable
_MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x00\x03\x00\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _ensure_png(path: Path, *, prefer: Optional[Path] = None) -> None:
    if prefer and prefer.exists():
        shutil.copy2(prefer, path)
        return
    if PLACEHOLDER_PNG.exists():
        shutil.copy2(PLACEHOLDER_PNG, path)
        return
    path.write_bytes(_MINIMAL_PNG)


def _format_poi_error(exc: BaseException) -> str:
    if isinstance(exc, ValueError):
        return str(exc).strip()
    if isinstance(exc, RuntimeError):
        return str(exc).strip() or type(exc).__name__
    text = str(exc).strip()
    if text:
        return text
    name = type(exc).__name__
    if name in ("ReadTimeout", "ConnectTimeout", "TimeoutError", "PoolTimeout"):
        return "请求高德接口超时，请稍后重试（周边 POI 查询请求较多）"
    if name == "ConnectError":
        return (
            "无法连接高德服务器。请检查本机网络/代理，"
            "确认能访问 restapi.amap.com 后重试"
        )
    return name or "未知错误"


def _resolve_amap_key(params: dict[str, Any]) -> str:
    key = (params.get("amap_key") or params.get("env_amap_key") or "").strip()
    if key.lower() == "server":
        key = (params.get("env_amap_key") or "").strip()
    return key


async def run_pipeline(params: dict[str, Any]) -> dict[str, Any]:
    report_id = str(uuid.uuid4())[:8]
    out_dir = OUTPUT_DIR / report_id
    out_dir.mkdir(parents=True, exist_ok=True)

    demo_id = (params.get("demo_id") or "").strip()
    amap_key = _resolve_amap_key(params)
    llm_key = params.get("llm_key")

    user_inputs = {
        "area": params.get("area"),
        "rent": params.get("rent"),
        "brand_positioning": params.get("brand_positioning"),
        "price": params.get("price"),
        "revenue": params.get("revenue"),
        "daily_cups": params.get("daily_cups"),
        "place_name": params.get("place_name", ""),
        "address_detail": params.get("address", ""),
    }

    errors: list[str] = []

    if demo_id:
        demo_id = _sanitize_demo_id(demo_id, params)
    is_demo = bool(demo_id)

    if demo_id:
        bundle = _load_demo(demo_id)
    elif not amap_key:
        raise ValueError("无高德 Key 且非演示点：请填写高德 Key 或选择演示点")
    else:
        city = params.get("city", "")
        address = params.get("address", "")
        lng = params.get("lng")
        lat = params.get("lat")
        try:
            if lng and lat:
                location = {"lng": float(lng), "lat": float(lat)}
                full_address = (address or "").strip() or f"{city} {params.get('place_name', '')}".strip()
            else:
                geo = await geocode(city, address or params.get("place_name", ""), amap_key)
                location = geo["location"]
                full_address = geo["address"]
        except (TypeError, ValueError) as exc:
            raise ValueError("落点坐标无效，请在地图上重新选点或检索地点") from exc
        try:
            bundle = await fetch_poi_bundle(location, amap_key, full_address, city)
        except Exception as exc:
            msg = _format_poi_error(exc)
            if "QPS" in msg or "CUQPS" in msg or "过于频繁" in msg:
                raise ValueError(msg) from exc
            raise ValueError(f"高德 POI 查询失败：{msg}") from exc

    bundle, validation_internal, validation_user_notes = normalize_poi_bundle(bundle)
    features = build_features(bundle, user_inputs)
    if validation_internal:
        features["validation_internal"] = validation_internal
    if validation_user_notes:
        features["validation_user_notes"] = validation_user_notes
    features["transit_data_status"] = bundle.get("transit_data_status", "OK")

    score_result = compute_score(features, user_inputs)
    evidence = build_evidence_table(features, score_result)

    qc_internal, qc_user = run_report_qc(features, score_result, evidence)
    if qc_internal:
        features.setdefault("validation_internal", []).extend(qc_internal)
        for note in qc_internal:
            errors.append(note)
    if qc_user:
        features.setdefault("validation_user_notes", []).extend(qc_user)

    png_path = out_dir / "analysis.png"
    svg_path = out_dir / "analysis.svg"
    docx_path = out_dir / "report.docx"

    from app.pipeline.export_svg import render_analysis_svg
    from app.pipeline.map_common import build_map_context

    basemap_key = None if is_demo else amap_key
    basemap_override = None
    if imaging_stack_available() and is_demo and demo_id in ("demo_a", "a") and DEMO_A_MAP.exists():
        from PIL import Image

        basemap_override = (Image.open(DEMO_A_MAP).convert("RGB"), "街道底图：高德静态地图")

    map_ctx = build_map_context(features, basemap_key, basemap_override=basemap_override)

    if is_demo and demo_id in ("demo_a", "a") and DEMO_A_MAP.exists():
        shutil.copy2(DEMO_A_MAP, png_path)
        basemap_note = map_ctx.basemap_note or "街道底图：高德静态地图（演示）"
        basemap_ok = True
    elif imaging_stack_available():
        from app.pipeline.export_png import render_analysis_png

        _, basemap_note, basemap_ok = render_analysis_png(
            features, png_path, amap_key=basemap_key, ctx=map_ctx
        )
    else:
        _ensure_png(png_path, prefer=DEMO_A_MAP if is_demo else None)
        basemap_note = map_ctx.basemap_note or "云端环境：分析图已简化（无底图渲染）"
        basemap_ok = bool(is_demo and DEMO_A_MAP.exists())

    render_analysis_svg(features, svg_path, ctx=map_ctx)
    features["basemap_note"] = basemap_note
    features["basemap_ok"] = basemap_ok
    if not basemap_ok and basemap_key and not is_demo:
        errors.append(f"高德静态底图：{basemap_note}")

    chart_files: dict[str, list[str]] = {}
    if imaging_stack_available():
        from app.pipeline.export_charts import render_report_charts

        chart_files = render_report_charts(features, score_result, out_dir)
    features["charts"] = chart_files

    report = await generate_report(
        features, score_result, evidence, llm_key, basemap_note=basemap_note
    )

    consistency_issues = validate_report_consistency(features, score_result, report)
    if consistency_issues:
        features.setdefault("validation_internal", []).extend(consistency_issues)
        errors.extend(consistency_issues)
        raise ValueError("报告数据状态不一致，已中止导出：" + "；".join(consistency_issues[:3]))

    meta = {
        "address": features.get("address"),
        "generated_at": _now_iso(),
        "report_id": report_id,
        "is_demo": is_demo,
    }
    try:
        export_docx(report, png_path, docx_path, meta)
    except Exception as exc:
        errors.append(f"Word 导出跳过：{type(exc).__name__}")
        if docx_path.exists():
            docx_path.unlink(missing_ok=True)

    result_path = out_dir / "result.json"
    exports = {
        "png": png_path.name,
        "svg": svg_path.name,
    }
    if docx_path.exists():
        exports["docx"] = docx_path.name
    result = {
        "report_id": report_id,
        "features": features,
        "score": score_result,
        "evidence": evidence,
        "report": report,
        "charts": chart_files,
        "errors": errors,
        "exports": exports,
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result


def _sanitize_demo_id(demo_id: str, params: dict) -> str:
    presets = {
        "demo_a": (121.473701, 31.230416),
        "a": (121.473701, 31.230416),
        "demo_b": (121.480000, 31.235000),
        "b": (121.480000, 31.235000),
    }
    lng, lat = params.get("lng"), params.get("lat")
    if not lng or not lat:
        return demo_id
    try:
        plng, plat = float(lng), float(lat)
    except (TypeError, ValueError):
        return demo_id
    ref = presets.get(demo_id)
    if not ref:
        return demo_id
    if abs(plng - ref[0]) > 0.002 or abs(plat - ref[1]) > 0.002:
        return ""
    return demo_id


def _load_demo(demo_id: str) -> dict[str, Any]:
    mapping = {"demo_a": "demo_a.json", "demo_b": "demo_b.json", "demo_c": "demo_c.json", "a": "demo_a.json", "b": "demo_b.json"}
    filename = mapping.get(demo_id, demo_id if demo_id.endswith(".json") else f"{demo_id}.json")
    path = DEMO_DIR / filename
    if not path.exists():
        raise ValueError(f"演示点不存在：{demo_id}")
    bundle = json.loads(path.read_text(encoding="utf-8"))
    if bundle.get("id") == "demo_a":
        _hydrate_demo_a_bundle(bundle)
    return bundle


def _hydrate_demo_a_bundle(bundle: dict[str, Any]) -> None:
    """Expand indirect POI lists to match report演示点.docx counts."""
    indirect: list[dict[str, Any]] = []
    near_300 = [95, 128, 155, 188, 235]
    for i, dist in enumerate(near_300, 1):
        indirect.append({
            "name": f"示例咖啡{i}",
            "distance_m": dist,
            "competitor_type": "indirect_beverage",
            "beverage_subtype": "coffee",
        })
    dist = 310
    idx = 6
    while len(indirect) < 42:
        indirect.append({
            "name": f"示例咖啡{idx}",
            "distance_m": dist,
            "competitor_type": "indirect_beverage",
            "beverage_subtype": "coffee",
        })
        idx += 1
        dist += 5
    for dist in range(550, 950, 50):
        indirect.append({
            "name": f"示例咖啡远场{dist}",
            "distance_m": dist,
            "competitor_type": "indirect_beverage",
            "beverage_subtype": "coffee",
        })
    poi = bundle.setdefault("poi_by_radius", {})
    poi.setdefault("1000", {})["indirect_beverages"] = indirect


def _now_iso() -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).isoformat()
