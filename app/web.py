"""FastAPI application — single process web MVP."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.users import (
    authenticate,
    create_session,
    delete_session,
    get_user_by_session,
    get_user_keys,
    init_db,
    register_user,
    update_user_keys,
)

from app.paths import OUTPUT_DIR, ROOT

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

SESSION_COOKIE = "session_token"
SESSION_MAX_AGE = 30 * 24 * 3600

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("site_assessor")


app = FastAPI(title="奶茶店选址 AI 分析评估助手")
templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))
try:
    init_db()
except Exception:
    logger.exception("Database init failed — auth disabled for this instance")


@app.get("/health")
async def health():
    return {"ok": True}


def _is_meta_gray_line(stripped: str) -> bool:
    if not stripped:
        return False
    if "图层说明" in stripped:
        return True
    if "数据来源" in stripped:
        return True
    if stripped.startswith("街道底图：") or stripped.startswith("未提供高德"):
        return True
    if stripped.startswith("高德静态底图"):
        return True
    low = stripped.lower()
    if "osm" in low and any(k in stripped for k in ("缓存", "覆盖", "暂未获取", "稀疏", "建筑轮廓")):
        return True
    return False


def _render_chapter_content(text: str) -> str:
    """Lightweight markdown-ish → HTML for report chapters."""
    if not text:
        return ""
    text = re.sub(
        r"\*本段参考知识库：([^*]+)\*",
        r'<p class="kb-ref">本段参考知识库：\1</p>',
        text,
    )
    if 'class="kb-ref"' not in text and "class='kb-ref'" not in text:
        text = re.sub(
            r"(本段参考知识库：[^\n<]+)",
            r'<p class="kb-ref">\1</p>',
            text,
        )

    lines = text.split("\n")
    html_parts: list[str] = []
    in_table = False
    in_ul = False

    def close_ul():
        nonlocal in_ul
        if in_ul:
            html_parts.append("</ul>")
            in_ul = False

    def close_table():
        nonlocal in_table
        if in_table:
            html_parts.append("</tbody></table>")
            in_table = False

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        # table rows
        if stripped.startswith("|") and stripped.endswith("|"):
            close_ul()
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(set(c) <= set("-: ") and c for c in cells):
                continue  # separator
            if not in_table:
                html_parts.append('<table class="md-table"><thead><tr>')
                html_parts.append("".join(f"<th>{_inline_md(c)}</th>" for c in cells))
                html_parts.append("</tr></thead><tbody>")
                in_table = True
            else:
                html_parts.append("<tr>" + "".join(f"<td>{_inline_md(c)}</td>" for c in cells) + "</tr>")
            continue

        close_table()

        hdr = re.match(r"^\*\*(.+?)\*\*:?\s*$", stripped)
        if hdr:
            close_ul()
            html_parts.append(f"<h3>{hdr.group(1).rstrip('：')}</h3>")
            continue
        if stripped.startswith("### "):
            close_ul()
            html_parts.append(f"<h3>{_inline_md(stripped[4:])}</h3>")
            continue
        if stripped.startswith("## "):
            close_ul()
            html_parts.append(f"<h3>{_inline_md(stripped[3:])}</h3>")
            continue
        if stripped.startswith("> "):
            html_parts.append(f'<p class="kb-snippet">{_inline_md(stripped[2:].strip())}</p>')
            continue
        if stripped.startswith("**知识库要点摘录：**"):
            continue
        if stripped.startswith("- "):
            if not in_ul:
                html_parts.append("<ul>")
                in_ul = True
            html_parts.append(f"<li>{_inline_md(stripped[2:])}</li>")
            continue
        if re.match(r"^\d+\.\s+", stripped):
            if not in_ul:
                html_parts.append("<ul>")
                in_ul = True
            num_text = re.sub(r"^\d+\.\s+", "", stripped)
            html_parts.append(f"<li>{_inline_md(num_text)}</li>")
            continue

        close_ul()
        if not stripped:
            html_parts.append("<br>")
        elif stripped.startswith("<p ") or stripped.startswith("<"):
            html_parts.append(_inline_md(stripped) if "*" in stripped else stripped)
        elif _is_meta_gray_line(stripped):
            html_parts.append(f'<p class="meta-gray">{_inline_md(stripped)}</p>')
        else:
            html_parts.append(f"<p>{_inline_md(stripped)}</p>")

    close_ul()
    close_table()
    html = "\n".join(html_parts)
    return _move_kb_ref_to_end(html)


def _move_kb_ref_to_end(html: str) -> str:
    """确保本段参考知识库出现在章节 HTML 最后。"""
    import re as _re
    refs = _re.findall(r'<p class="kb-ref">[^<]*</p>', html)
    if not refs:
        return html
    for block in refs:
        html = html.replace(block, "")
    html = html.rstrip() + "\n" + refs[-1]
    return html


def _inline_md(text: str) -> str:
    """Convert lightweight markdown emphasis; never leave literal * in UI output."""
    if not text:
        return text
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<em>\1</em>", text)
    return text.replace("*", "").replace("＊", "")


templates.env.filters["render_chapter"] = _render_chapter_content  # 备用，报告页在 Python 侧预处理
_static_dir = ROOT / "app" / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE") or "10")
_hits = defaultdict(list)


def _check_rate_limit(request: Request, limit: int = None):
    limit = limit or RATE_LIMIT
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = _hits[ip]
    _hits[ip] = [t for t in window if now - t < 60]
    if len(_hits[ip]) >= limit:
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
    _hits[ip].append(now)


def _current_user(session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE)):
    return get_user_by_session(session_token)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/")


def _auth_json(
    content: dict,
    *,
    token: Optional[str] = None,
    clear_session: bool = False,
) -> JSONResponse:
    """Return JSON and attach session cookie on the same response object."""
    resp = JSONResponse(content)
    if token:
        _set_session_cookie(resp, token)
    if clear_session:
        _clear_session_cookie(resp)
    return resp


def _resolve_web_key(
    session_token: Optional[str],
    amap_key_param: str,
    *,
    demo_id: str = "",
) -> str:
    if (demo_id or "").strip():
        return ""
    key = (amap_key_param or "").strip()
    if key.lower() == "server":
        key = ""
    if key:
        return key
    user = get_user_by_session(session_token)
    if user:
        keys = get_user_keys(user["id"])
        if keys and keys.get("amap_web_key"):
            return keys["amap_web_key"]
    return os.getenv("AMAP_WEB_KEY", "").strip()


@app.get("/api/auth/me")
async def api_auth_me(user: Optional[dict] = Depends(_current_user)):
    if not user:
        return JSONResponse({"logged_in": False})
    return JSONResponse({"logged_in": True, "user": user})


@app.post("/api/auth/register")
async def api_auth_register(
    username: str = Form(""),
    password: str = Form(""),
    display_name: str = Form(""),
):
    try:
        user = register_user(username, password, display_name)
        token = create_session(user["id"])
        return _auth_json({"ok": True, "user": user}, token=token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/auth/login")
async def api_auth_login(
    username: str = Form(""),
    password: str = Form(""),
):
    try:
        user = authenticate(username, password)
        token = create_session(user["id"])
        return _auth_json({"ok": True, "user": user}, token=token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/auth/logout")
async def api_auth_logout(
    session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
):
    delete_session(session_token or "")
    return _auth_json({"ok": True}, clear_session=True)


@app.post("/api/auth/keys")
async def api_auth_keys(
    user: Optional[dict] = Depends(_current_user),
    amap_web_key: str = Form(""),
    amap_js_key: str = Form(""),
    amap_security_code: str = Form(""),
):
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    web_in = (amap_web_key or "").strip()
    js_in = (amap_js_key or "").strip()
    sec_in = (amap_security_code or "").strip()
    keep_web = web_in in ("", "__keep__")
    keep_js = js_in in ("", "__keep__")
    keep_sec = sec_in == "__keep__"
    try:
        updated = update_user_keys(
            user["id"],
            web_in,
            js_in,
            sec_in,
            keep_web=keep_web,
            keep_js=keep_js,
            keep_security=keep_sec,
        )
        return JSONResponse({"ok": True, "user": updated})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/config")
async def api_config():
    """站点级 Key 配置（Web Key 仅服务端用，不下发）。"""
    web = os.getenv("AMAP_WEB_KEY", "").strip()
    js = os.getenv("AMAP_JS_KEY", "").strip()
    return JSONResponse({
        "has_server_web_key": bool(web),
        "has_server_js_key": bool(js),
        "amap_js_key": js,
        "amap_security_code": os.getenv("AMAP_SECURITY_JS_CODE", "").strip(),
    })


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "product_name": "奶茶店选址 AI 分析评估助手",
        "has_server_web_key": bool(os.getenv("AMAP_WEB_KEY", "").strip()),
    })


@app.get("/api/tips")
async def api_tips(
    request: Request,
    keywords: str = Query(""),
    city: str = Query(""),
    amap_key: str = Query(""),
    session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
):
    _check_rate_limit(request, 30)
    key = _resolve_web_key(session_token, amap_key)
    if not key:
        return JSONResponse({"tips": [], "error": "未配置 Web 服务 Key，请在个人中心填写", "count": 0})
    if not keywords.strip():
        return JSONResponse({"tips": [], "error": "请输入地点名", "count": 0})
    try:
        from app.pipeline.geocode import search_locations

        result = await search_locations(keywords, city, key)
        if result.get("error") and not result.get("tips"):
            logger.warning("tips_fail info=%s", result["error"][:80])
        return JSONResponse(result)
    except Exception as exc:
        logger.error("tips_error code=%s detail=%s", type(exc).__name__, str(exc)[:120])
        detail = str(exc).strip() or type(exc).__name__
        return JSONResponse({"tips": [], "error": detail or "检索服务异常，请稍后重试", "count": 0})


@app.post("/api/generate")
async def api_generate(
    request: Request,
    city: str = Form(""),
    address: str = Form(""),
    place_name: str = Form(""),
    lng: str = Form(""),
    lat: str = Form(""),
    area: str = Form(""),
    rent: str = Form(""),
    brand_positioning: str = Form(""),
    price: str = Form(""),
    revenue: str = Form(""),
    daily_cups: str = Form(""),
    amap_key: str = Form(""),
    demo_id: str = Form(""),
    session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
):
    _check_rate_limit(request)
    resolved_key = _resolve_web_key(session_token, amap_key, demo_id=demo_id)
    if not (demo_id or "").strip() and not resolved_key:
        raise HTTPException(status_code=400, detail="未配置 Web 服务 Key，请在个人中心填写或使用演示点")
    params = {
        "city": city.strip(),
        "address": address.strip(),
        "place_name": place_name.strip(),
        "lng": lng.strip(),
        "lat": lat.strip(),
        "area": area.strip(),
        "rent": rent.strip(),
        "brand_positioning": brand_positioning.strip(),
        "price": price.strip(),
        "revenue": revenue.strip(),
        "daily_cups": daily_cups.strip(),
        "amap_key": resolved_key,
        "demo_id": demo_id.strip(),
        "env_amap_key": os.getenv("AMAP_WEB_KEY", ""),
    }
    try:
        from app.pipeline.pipeline import run_pipeline

        result = await run_pipeline(params)
        logger.info("generate_ok report_id=%s demo=%s", result["report_id"], bool(demo_id))
        return JSONResponse({"ok": True, "report_id": result["report_id"], "result": result})
    except ValueError as exc:
        logger.warning("generate_fail reason=user_input")
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("generate_fail code=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="生成失败，请稍后重试或使用演示点")


def _sanitize_legacy_osm_text(text: str, *, for_appendix: bool = False) -> str:
    """Old reports cached raw Overpass HTTP errors in chapter body — scrub on read."""
    if not text:
        return text
    from app.pipeline.osm import format_osm_note_for_appendix, format_osm_note_for_report

    formatter = format_osm_note_for_appendix if for_appendix else format_osm_note_for_report
    if any(tok in text.lower() for tok in ("406", "not acceptable", "client error", "查询失败", "分析图将降级")):
        text = re.sub(
            r"OSM 查询失败[^\n]*(?:\nFor more information check:[^\n]*)?(?:，分析图将降级)?",
            formatter("OSM 查询失败 406"),
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"OpenStreetMap（OSM 查询失败[^）]*）",
            f"OpenStreetMap（{formatter('OSM 查询失败 406')}）",
            text,
            flags=re.IGNORECASE,
        )
    return text


def _prepare_report_result(result: dict) -> dict:
    result = _sanitize_legacy_report(result)
    for ch in result.get("report", {}).get("chapters", {}).values():
        ch["content_html"] = _render_chapter_content(ch.get("content", ""))
    return result


def _report_context(result: dict, report_id: str) -> dict:
    return {
        "result": result,
        "report_id": report_id,
    }


@app.post("/api/render-report", response_class=HTMLResponse)
async def api_render_report(request: Request):
    """Serverless fallback: render report HTML from client sessionStorage payload."""
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="无效请求") from exc
    report_id = (payload.get("report_id") or "").strip()
    result = payload.get("result")
    if not report_id or not isinstance(result, dict):
        raise HTTPException(status_code=400, detail="缺少报告数据")
    result = _prepare_report_result(result)
    return templates.TemplateResponse("report.html", {
        "request": request,
        **_report_context(result, report_id),
    })


def _sanitize_legacy_report(result: dict) -> dict:
    chapters = result.get("report", {}).get("chapters", {})
    for key, ch in chapters.items():
        raw = ch.get("content", "")
        if not raw:
            continue
        ch["content"] = _sanitize_legacy_osm_text(raw, for_appendix=(key == "appendix"))
    return result


@app.get("/report/{report_id}", response_class=HTMLResponse)
async def report_page(request: Request, report_id: str):
    try:
        result = _prepare_report_result(_load_result(report_id))
        return templates.TemplateResponse("report.html", {
            "request": request,
            **_report_context(result, report_id),
        })
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return templates.TemplateResponse("report_hydrate.html", {
            "request": request,
            "report_id": report_id,
        })


@app.get("/download/{report_id}/{file_type}")
async def download(report_id: str, file_type: str):
    result = _load_result(report_id)
    exports = result.get("exports", {})
    mapping = {"png": "png", "svg": "svg", "docx": "docx", "word": "docx"}
    key = mapping.get(file_type)
    if not key or key not in exports:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = OUTPUT_DIR / report_id / Path(exports[key]).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    media = {
        "png": "image/png",
        "svg": "image/svg+xml",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    return FileResponse(path, media_type=media.get(key, "application/octet-stream"), filename=path.name)


@app.get("/download/{report_id}/chart/{chart_name}")
async def download_chart(report_id: str, chart_name: str):
    if ".." in chart_name or "/" in chart_name or "\\" in chart_name:
        raise HTTPException(status_code=400, detail="非法文件名")
    path = OUTPUT_DIR / report_id / chart_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="图表不存在")
    return FileResponse(path, media_type="image/png", filename=chart_name)


def _load_result(report_id: str) -> dict:
    path = OUTPUT_DIR / report_id / "result.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="报告不存在或已过期")
    return json.loads(path.read_text(encoding="utf-8"))
