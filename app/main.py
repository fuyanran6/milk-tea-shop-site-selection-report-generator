"""Vercel entrypoint. Full app lives in app.web so a boot failure can still serve a page."""

from __future__ import annotations

import traceback

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

try:
    from app.web import app
except Exception:  # pragma: no cover - only used when cloud boot fails
    _ERR = traceback.format_exc()
    app = FastAPI(title="启动失败")

    def _error_page() -> HTMLResponse:
        safe = _ERR.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return HTMLResponse(
            "<!doctype html><meta charset='utf-8'><title>启动失败</title>"
            "<body style='font-family:sans-serif;max-width:900px;margin:2rem auto'>"
            "<h1>网站启动失败</h1>"
            "<p>请把下面这段报错发给开发者：</p>"
            f"<pre style='white-space:pre-wrap;background:#f6f8fa;padding:1rem'>{safe}</pre>"
            "</body>",
            status_code=200,
        )

    @app.get("/")
    async def boot_index():
        return _error_page()

    @app.get("/health")
    async def boot_health():
        return JSONResponse({"ok": False, "error": _ERR[:2000]})
