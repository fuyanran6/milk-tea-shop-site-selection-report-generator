"""Local knowledge base retrieval by chapter and scene tags."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
KB_DIR = ROOT / "知识库"


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, Any] = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            key = k.strip()
            val = v.strip()
            if key in ("chapter", "scene"):
                meta[key] = [x.strip() for x in val.split(",")]
            else:
                meta[key] = val
    return meta, parts[2].strip()


def load_all_documents() -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    if not KB_DIR.exists():
        return docs
    for path in sorted(KB_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        docs.append({
            "filename": path.name,
            "title": meta.get("title", path.stem),
            "chapter": meta.get("chapter", []),
            "scene": meta.get("scene", ["all"]),
            "source": meta.get("source", ""),
            "body": body,
        })
    return docs


def retrieve(chapter: str, scene_type: str, limit: int = 3) -> list[dict[str, Any]]:
    docs = load_all_documents()
    hits: list[tuple[int, dict]] = []

    for doc in docs:
        chapters = doc.get("chapter", [])
        scenes = doc.get("scene", ["all"])
        if chapter not in chapters and "all" not in chapters:
            continue
        if scene_type not in scenes and "all" not in scenes and "mixed" not in scenes:
            if scene_type == "mixed" and any(s in scenes for s in ("office", "community", "mall")):
                pass
            elif "all" not in scenes:
                continue

        score = 0
        if chapter in chapters:
            score += 2
        if scene_type in scenes:
            score += 2
        elif "all" in scenes:
            score += 1
        body = doc["body"]
        if scene_type in body:
            score += 1
        hits.append((score, doc))

    hits.sort(key=lambda x: x[0], reverse=True)
    return [h[1] for h in hits[:limit]]


def search_keywords(query: str, limit: int = 5) -> list[dict[str, Any]]:
    docs = load_all_documents()
    q = query.lower()
    results = []
    for doc in docs:
        if q in doc["body"].lower() or q in doc["title"].lower():
            snippet = _extract_snippet(doc["body"], q)
            results.append({**doc, "snippet": snippet})
    return results[:limit]


def _extract_snippet(body: str, query: str, radius: int = 80) -> str:
    idx = body.lower().find(query.lower())
    if idx < 0:
        return body[:160] + "..."
    start = max(0, idx - radius)
    end = min(len(body), idx + len(query) + radius)
    return body[start:end].replace("\n", " ")
