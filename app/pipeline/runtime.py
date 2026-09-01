"""Runtime capability checks for serverless vs local."""

from __future__ import annotations

from functools import lru_cache

from app.paths import is_vercel


@lru_cache(maxsize=1)
def imaging_stack_available() -> bool:
    """matplotlib + Pillow need native libjpeg — unavailable on Vercel serverless."""
    if is_vercel():
        return False
    try:
        import matplotlib

        matplotlib.use("Agg")
        from PIL import Image  # noqa: F401

        return True
    except ImportError:
        return False
