"""Stock photo fill-in, free for commercial use with no credit required.

Uses Pixabay (PIXABAY_API_KEY, free at pixabay.com/api/docs) or Pexels
(PEXELS_API_KEY, if you already have one; Pexels paused new keys in 2026).
Searches and downloaded photos are cached in .stock-cache/, so a service keeps
the same photo across rebuilds and Pixabay's "download, don't hotlink" rule is met.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

CACHE = Path(os.environ.get("DATA_DIR") or Path(__file__).resolve().parent.parent) / ".stock-cache"
UA = "SiteBuilder/1.0"
# Words too generic to prove a photo matches ("Roof Soft Washing" must show a roof, not hand washing).
GENERIC = {"and", "the", "of", "for", "service", "services", "removal", "cleaning", "washing", "wash", "soft",
           "repair", "repairs", "installation", "install", "replacement", "maintenance", "care", "pickup", "local",
           "deep", "recurring", "regular", "general", "standard", "basic", "full", "complete", "professional",
           "residential", "commercial", "move", "in", "out", "clean", "new", "custom", "quality", "free", "same", "day"}


def available() -> bool:
    return bool(os.environ.get("PIXABAY_API_KEY") or os.environ.get("PEXELS_API_KEY"))


def key_words(text: str) -> set[str]:
    """Specific words a matching photo should be tagged with."""
    words = set(re.findall(r"[a-z]+", text.lower())) - GENERIC
    return {w[:-1] if w.endswith("s") and len(w) > 4 else w for w in words}


def _get(url: str, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def _pixabay(query: str) -> list[dict]:
    q = urllib.parse.urlencode({"key": os.environ["PIXABAY_API_KEY"], "q": query[:100], "image_type": "photo",
                                "orientation": "horizontal", "safesearch": "true", "min_width": 1200, "per_page": 30})
    return [{"id": f"pixabay-{h['id']}", "url": h["largeImageURL"], "source": "Pixabay", "page": h["pageURL"],
             "photographer": h.get("user", ""), "tags": h.get("tags", "")}
            for h in json.loads(_get(f"https://pixabay.com/api/?{q}")).get("hits") or []]


def _pexels(query: str) -> list[dict]:
    q = urllib.parse.urlencode({"query": query, "per_page": 30, "orientation": "landscape", "size": "large"})
    res = json.loads(_get(f"https://api.pexels.com/v1/search?{q}", {"Authorization": os.environ["PEXELS_API_KEY"]}))
    return [{"id": f"pexels-{p['id']}", "url": p["src"]["large2x"], "source": "Pexels", "page": p["url"],
             "photographer": p.get("photographer", ""), "tags": p.get("alt", "")}
            for p in res.get("photos") or []]


def _search(query: str, log) -> list[dict]:
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"q-{hashlib.md5(query.lower().encode()).hexdigest()[:16]}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    hits = []
    for env, fn in (("PIXABAY_API_KEY", _pixabay), ("PEXELS_API_KEY", _pexels)):
        if os.environ.get(env):
            try:
                hits += fn(query)
            except Exception as e:  # stock is a nice-to-have; never fail the build
                log(f"  Stock photo search failed for '{query}' ({type(e).__name__}: {e}); check the API key")
                return []  # don't cache a failure
    f.write_text(json.dumps(hits), encoding="utf-8")
    return hits


def find(queries: list[tuple[str, set[str]]], avoid: set[str], log=print) -> tuple[Path, dict] | None:
    """First photo across (query, must-words) pairs whose tags include one of that
    query's must-words and whose id isn't in `avoid` (photos already used on this
    site). A query with no must-words is skipped: unfiltered results are how a
    "Deep Cleaning" search ends up showing a swimming pool. Returns (file, info)."""
    seen = set()
    for query, must in queries:
        query = (query or "").strip()
        if not query or not must or query.lower() in seen:
            continue
        seen.add(query.lower())
        for h in _search(query, log):
            if h["id"] in avoid:
                continue
            tags = key_words(h["tags"]) | set(re.findall(r"[a-z]+", h["tags"].lower()))
            # One shared word isn't enough for a detailed search ("tile" alone found a mosaic for bathroom scrubbing).
            if len(must & tags) < (2 if len(must) >= 3 else 1):
                continue
            img = CACHE / f"{h['id']}.jpg"
            if not img.exists():
                try:
                    img.write_bytes(_get(h["url"]))
                except Exception as e:
                    log(f"  Stock photo download failed ({type(e).__name__}: {e})")
                    continue
            return img, {"query": query, **{k: h[k] for k in ("id", "source", "page", "photographer", "tags")}}
    return None
