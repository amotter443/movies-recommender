"""
streaming_tool.py — streaming availability for Max, Hulu, Criterion Channel, and Kanopy.
Max/Hulu/Criterion are checked via TMDB. Kanopy is checked directly via SAPL's Kanopy
catalog API (kanopy_tool.py) for library-accurate results.

Cache schema (data/tmdb_cache.json):
{
  "<tmdb_id>": {
    "title": "Le Samourai",
    "streaming": ["Criterion Channel"],
    "runtime": 105,
    "genres": ["Crime", "Thriller"],
    "overview": "...",
    "tmdb_rating": 8.1,
    "poster_path": "/abc123.jpg",
    "cached_at": "2026-02-27"
  }
}
Cache entries expire after 7 days.
"""
import json
import os
import time
from datetime import datetime, timedelta

import requests
from langchain_core.tools import tool
from dotenv import load_dotenv
from tools.kanopy_tool import batch_check_kanopy

load_dotenv("local.env")

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_CACHE_PATH = os.path.join(_DATA_DIR, "tmdb_cache.json")
_TMDB_BASE = "https://api.themoviedb.org/3"
_CACHE_TTL_DAYS = 7

# Streaming service provider IDs (US) — subscription services only.
# Kanopy is checked separately via kanopy_tool.py (direct Kanopy API).
_PROVIDER_MAP = {
    15: "Hulu",
    29: "Max",
    258: "Criterion Channel",
}
_VALID_PROVIDER_IDS = set(_PROVIDER_MAP.keys())


def _get_api_key() -> str:
    key = os.getenv("TMDB_API_KEY", "")
    if not key:
        raise RuntimeError("TMDB_API_KEY not set. Add it to your .env file.")
    return key


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


def _search_tmdb_id(title: str, api_key: str) -> str | None:
    """Search TMDB for a movie title and return its ID as a string."""
    resp = requests.get(
        f"{_TMDB_BASE}/search/movie",
        params={"api_key": api_key, "query": title, "language": "en-US"},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        return None
    return str(results[0]["id"])


def _fetch_movie_details(tmdb_id: str, api_key: str) -> dict:
    """Fetch movie metadata + streaming providers in a single API call."""
    resp = requests.get(
        f"{_TMDB_BASE}/movie/{tmdb_id}",
        params={
            "api_key": api_key,
            "append_to_response": "watch/providers",
            "language": "en-US",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    # Extract genre names
    genres = [g["name"] for g in data.get("genres", [])]

    # Extract US streaming services (flatrate only)
    providers_data = data.get("watch/providers", {}).get("results", {}).get("US", {})
    flatrate = providers_data.get("flatrate", [])
    streaming = [
        _PROVIDER_MAP[p["provider_id"]]
        for p in flatrate
        if p["provider_id"] in _VALID_PROVIDER_IDS
    ]

    return {
        "title": data.get("title", ""),
        "streaming": streaming,
        "runtime": data.get("runtime"),
        "genres": genres,
        "overview": data.get("overview", ""),
        "tmdb_rating": data.get("vote_average"),
        "poster_path": data.get("poster_path"),
        "cached_at": datetime.now().strftime("%Y-%m-%d"),
    }


def _lookup_movie(title: str, api_key: str, cache: dict) -> dict | None:
    """
    Look up a movie: check cache first, then hit TMDB.
    Returns the entry dict or None if not found.
    """
    # Check if we already have a cache entry keyed by title (title-keyed lookup)
    title_key = f"title:{title.lower().strip()}"
    tmdb_id = cache.get(title_key)

    if tmdb_id and tmdb_id in cache and not _is_expired(cache[tmdb_id]):
        return cache[tmdb_id]

    # Search TMDB for the ID
    try:
        tmdb_id = _search_tmdb_id(title, api_key)
    except requests.RequestException as e:
        return {"title": title, "streaming": [], "error": str(e)}

    if not tmdb_id:
        return {"title": title, "streaming": [], "error": "Not found on TMDB"}

    # Fetch full details
    try:
        entry = _fetch_movie_details(tmdb_id, api_key)
        time.sleep(0.25)  # gentle rate limiting
    except requests.RequestException as e:
        return {"title": title, "streaming": [], "error": str(e)}

    # Store in cache
    cache[tmdb_id] = entry
    cache[title_key] = tmdb_id  # title → id mapping

    return entry


@tool
def check_streaming(movie_titles: list[str]) -> list[dict]:
    """
    Check streaming availability for a list of movie titles.
    Checks Max, Hulu, and Criterion Channel via TMDB, and Kanopy via SAPL's
    Kanopy catalog directly. Uses local disk caches with 7-day TTL.

    Args:
        movie_titles: List of movie title strings to check (e.g. ["Chinatown", "Le Samourai"]).

    Returns:
        List of dicts: {title, streaming, runtime, genres, overview, tmdb_rating, poster_path}
        "streaming" is a list of service names the film is available on (may be empty).
    """
    api_key = _get_api_key()
    cache = _load_cache()

    # Build results and track which original input title maps to each entry
    results = []
    original_titles = []  # parallel list: original input title for each result

    for title in movie_titles:
        entry = _lookup_movie(title, api_key, cache)
        if entry:
            results.append(
                {
                    "title": entry.get("title", title),
                    "streaming": entry.get("streaming", []),
                    "runtime": entry.get("runtime"),
                    "genres": entry.get("genres", []),
                    "overview": entry.get("overview", ""),
                    "tmdb_rating": entry.get("tmdb_rating"),
                    "poster_path": entry.get("poster_path"),
                }
            )
            original_titles.append(title)

    _save_cache(cache)

    # Check Kanopy directly via SAPL's catalog using the original input titles
    kanopy_results = batch_check_kanopy(original_titles)
    for result, original in zip(results, original_titles):
        if kanopy_results.get(original) and "Kanopy" not in result["streaming"]:
            result["streaming"].append("Kanopy")

    return results


if __name__ == "__main__":
    test_titles = ["Chinatown", "Le Samourai", "Mulholland Drive"]
    results = check_streaming.invoke({"movie_titles": test_titles})
    for r in results:
        print(f"\n{r['title']} ({r.get('runtime')} min) — TMDB: {r.get('tmdb_rating')}")
        print(f"  Genres: {r.get('genres')}")
        print(f"  Streaming: {r.get('streaming')}")
        print(f"  Overview: {r.get('overview', '')[:120]}...")
