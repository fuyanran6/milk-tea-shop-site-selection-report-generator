"""Project paths — use /tmp on Vercel (serverless FS is read-only except /tmp)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def is_vercel() -> bool:
    return bool(os.getenv("VERCEL"))


def writable_root() -> Path:
    if is_vercel():
        base = Path("/tmp") / "site-assessor"
        base.mkdir(parents=True, exist_ok=True)
        return base
    return ROOT


OUTPUT_DIR = writable_root() / "output"
DB_PATH = writable_root() / "data" / "users.db"
OSM_CACHE_DIR = writable_root() / "tmp" / "osm_cache"
DEMO_DIR = ROOT / "data" / "demo"
