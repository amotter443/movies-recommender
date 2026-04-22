"""
kanopy_tool.py — check SAPL Kanopy availability via Kanopy's search API.

Endpoint: GET https://www.kanopy.com/kapi/search/videos
  ?query={title}&sort=relevance&rfp=exclude&domainId=7815&isKids=false&page=0&perPage=10

domainId=7815 is San Antonio Public Library (SAPL). No authentication required.

Cache schema (data/kanopy_cache.json):
{
  "<lowercased title>": {
    "available": true,
    "cached_at": "2026-03-29"
  }
}
Cache TTL: 7 days.
"""
import json
import os
import time
from datetime import datetime, timedelta
from difflib import SequenceMatcher

import requests

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_CACHE_PATH = os.path.join(_DATA_DIR, "kanopy_cache.json")
_SEARCH_URL = "https://www.kanopy.com/kapi/search/videos"
_DOMAIN_ID = 7815  # San Antonio Public Library (SAPL)
_CACHE_TTL_DAYS = 7
_MATCH_THRESHOLD = 0.85


def _load_cache() -> dict:
    if os.path.exists(_CACHE_PATH):
        try:
            with open(_CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def _is_expired(entry: dict) -> bool:
    cached_at = entry.get("cached_at")
    if not cached_at:
        return True
    try:
        age = datetime.now() - datetime.strptime(cached_at, "%Y-%m-%d")
        return age > timedelta(days=_CACHE_TTL_DAYS)
    except ValueError:
        return True


def _normalize(title: str) -> str:
    """Lowercase and strip leading articles for fairer comparison."""
    t = title.lower().strip()
    for article in ("the ", "a ", "an ", "le ", "la ", "les ", "l'", "un ", "une "):
        if t.startswith(article):
            t = t[len(article):]
            break
    return t


def _title_matches(query: str, candidate: str) -> bool:
    """True if candidate is a close enough match for the queried title."""
    q = _normalize(query)
    c = _normalize(candidate)
    if q == c:
        return True
    # Allow the candidate to be the query plus a subtitle (e.g. "Chinatown: Director's Cut")
    if c.startswith(q):
        return True
    return SequenceMatcher(None, q, c).ratio() >= _MATCH_THRESHOLD


def _search_kanopy(title: str) -> bool:
    """Query the Kanopy API and return True if a matching title is found."""
    try:
        resp = requests.get(
            _SEARCH_URL,
            params={
                "query": title,
                "sort": "relevance",
                "rfp": "exclude",
                "domainId": _DOMAIN_ID,
                "isKids": "false",
                "page": 0,
                "perPage": 10,
            },
            headers={"Accept": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("list", [])
    except requests.RequestException:
        return False

    return any(_title_matches(title, r.get("title", "")) for r in results)


def check_kanopy(title: str, cache: dict | None = None) -> bool:
    """
    Check if a film is available on SAPL's Kanopy catalog.

    Args:
        title: Movie title to look up.
        cache: Pre-loaded cache dict (modified in-place). If None, loads and
               saves its own cache — use batch_check_kanopy for multiple titles.

    Returns:
        True if the film is in SAPL's Kanopy catalog.
    """
    own_cache = cache is None
    if own_cache:
        cache = _load_cache()

    key = title.lower().strip()
    entry = cache.get(key)
    if entry and not _is_expired(entry):
        return entry["available"]

    available = _search_kanopy(title)
    cache[key] = {"available": available, "cached_at": datetime.now().strftime("%Y-%m-%d")}

    if own_cache:
        _save_cache(cache)

    return available


def batch_check_kanopy(titles: list[str]) -> dict[str, bool]:
    """
    Check Kanopy availability for multiple titles with a single cache load/save.
    Returns {title: available}.
    """
    cache = _load_cache()
    results: dict[str, bool] = {}
    changed = False

    for title in titles:
        key = title.lower().strip()
        entry = cache.get(key)
        if entry and not _is_expired(entry):
            results[title] = entry["available"]
            continue

        available = _search_kanopy(title)
        cache[key] = {"available": available, "cached_at": datetime.now().strftime("%Y-%m-%d")}
        results[title] = available
        changed = True
        time.sleep(0.15)  # gentle rate limiting

    if changed:
        _save_cache(cache)

    return results


if __name__ == "__main__":
    test_titles = ["Chinatown", "Le Samourai", "Mulholland Drive", "Ratcatcher"]
    results = batch_check_kanopy(test_titles)
    for title, available in results.items():
        print(f"  {'✓' if available else '✗'} {title}")
