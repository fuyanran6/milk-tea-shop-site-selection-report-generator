"""Pre-built demo report bundles — instant serve without running the pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.paths import DEMO_DIR

_DEMO_ALIASES = {
    "demo_a": "demo_a",
    "a": "demo_a",
}


def demo_slug(demo_id: str) -> Optional[str]:
    return _DEMO_ALIASES.get((demo_id or "").strip())


def bundle_dir(demo_id: str) -> Optional[Path]:
    slug = demo_slug(demo_id)
    if not slug:
        return None
    path = DEMO_DIR / "bundles" / slug
    if (path / "result.json").is_file():
        return path
    return None


def has_prebuilt(demo_id: str) -> bool:
    return bundle_dir(demo_id) is not None


def load_prebuilt(demo_id: str) -> dict[str, Any]:
    path = bundle_dir(demo_id)
    if not path:
        raise ValueError(f"演示点不存在：{demo_id}")
    return json.loads((path / "result.json").read_text(encoding="utf-8"))


def bundle_asset_path(report_id: str, filename: str) -> Optional[Path]:
    base = bundle_dir(report_id)
    if not base:
        return None
    path = (base / filename).resolve()
    if not str(path).startswith(str(base.resolve())):
        return None
    if path.is_file():
        return path
    return None
