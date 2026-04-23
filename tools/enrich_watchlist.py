"""
enrich_watchlist.py — enrich watchlist entries with TMDB metadata.

Reads both watchlist CSVs, fetches genre/runtime/rating from TMDB for any
titles not already cached, and writes to data/watchlist_enriched.json.

Cache schema (data/watchlist_enriched.json):
{
  "<lowercased title>": {
    "genres": ["Crime", "Thriller"],
    "runtime": 105,
    "tmdb_rating": 8.1
  },
  ...
}

Only titles absent from the cache trigger API calls. The underlying TMDB
cache (tmdb_cache.json) is shared with streaming_tool, so films already
looked up for streaming availability are instant hits.
"""
import json
import os

import pandas as pd
from dotenv import load_dotenv

load_dotenv("local.env")

from tools.streaming_tool import _get_api_key, _load_cache, _lookup_movie, _save_cache

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_ENRICHED_PATH = os.path.join(_DATA_DIR, "watchlist_enriched.json")
_LB_PATH = os.path.join(_DATA_DIR, "letterboxd_watchlist.csv")
_ANALOG_PATH = os.path.join(_DATA_DIR, "analog_watchlist.csv")


def _load_enriched() -> dict:
    if os.path.exists(_ENRICHED_PATH):
        try:
            with open(_ENRICHED_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_enriched(data: dict) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_ENRICHED_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _all_watchlist_titles() -> list[str]:
    """Return all unique title strings across both watchlist CSVs."""
    titles: list[str] = []
    for path in (_LB_PATH, _ANALOG_PATH):
        if os.path.exists(path):
            df = pd.read_csv(path)
            if "Name" in df.columns:
                titles.extend(df["Name"].dropna().str.strip().tolist())

    seen: set[str] = set()
    unique: list[str] = []
    for t in titles:
        key = t.lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(t)
    return unique


def enrich_watchlist() -> dict:
    """
    Ensure every watchlist title has TMDB metadata in the enriched cache.
    Only fetches titles not already present — subsequent calls are instant.
    Returns the full enriched dict: {lowercased_title: {genres, runtime, tmdb_rating}}.
    """
    enriched = _load_enriched()
    titles = _all_watchlist_titles()
    missing = [t for t in titles if t.lower().strip() not in enriched]

    if not missing:
        return enriched

    try:
        api_key = _get_api_key()
    except RuntimeError:
        return enriched  # No API key configured — skip silently

    tmdb_cache = _load_cache()
    fetched = 0

    for title in missing:
        entry = _lookup_movie(title, api_key, tmdb_cache)
        if entry and not entry.get("error"):
            enriched[title.lower().strip()] = {
                "genres": entry.get("genres", []),
                "runtime": entry.get("runtime"),
                "tmdb_rating": entry.get("tmdb_rating"),
            }
            fetched += 1

    if fetched:
        _save_cache(tmdb_cache)
        _save_enriched(enriched)

    return enriched
