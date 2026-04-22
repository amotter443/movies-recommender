"""
watchlist_tool.py — search the merged Letterboxd + analog watchlist.

Letterboxd watchlist CSV columns: Date, Name, Year, Letterboxd URI
Analog watchlist CSV columns:     Name, Year, Notes

At load time, enriched TMDB metadata (genres, runtime, tmdb_rating) is merged
in from data/watchlist_enriched.json (populated by enrich_watchlist.py).
Deduplicates against watch history (movie_data_final.csv) via
the get_watched_titles() helper in history_tool.py.
"""
import os

import pandas as pd
from langchain_core.tools import tool

from tools.enrich_watchlist import _load_enriched
from tools.history_tool import get_watched_titles

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_LB_PATH = os.path.join(_DATA_DIR, "letterboxd_watchlist.csv")
_ANALOG_PATH = os.path.join(_DATA_DIR, "analog_watchlist.csv")


def _load_watchlist() -> pd.DataFrame:
    """Load and merge both watchlists, dedup against watch history, attach TMDB metadata."""
    frames = []

    if os.path.exists(_LB_PATH):
        lb = pd.read_csv(_LB_PATH)
        if not lb.empty and "Name" in lb.columns:
            lb = lb[["Name", "Year"]].copy()
            lb["source"] = "Letterboxd"
            lb["notes"] = ""
            frames.append(lb)

    if os.path.exists(_ANALOG_PATH):
        analog = pd.read_csv(_ANALOG_PATH)
        if not analog.empty and "Name" in analog.columns:
            analog = analog[["Name", "Year", "Notes"]].rename(columns={"Notes": "notes"}).copy()
            analog["source"] = "Analog"
            frames.append(analog)

    if not frames:
        return pd.DataFrame(columns=["Name", "Year", "source", "notes", "genres", "runtime", "tmdb_rating"])

    merged = pd.concat(frames, ignore_index=True)
    merged["Name"] = merged["Name"].astype(str).str.strip()
    merged["Year"] = merged["Year"].astype(str).str.strip()
    merged["notes"] = merged["notes"].fillna("").astype(str).str.strip()

    # Dedup within watchlist (keep first occurrence)
    merged = merged.drop_duplicates(subset=["Name"], keep="first")

    # Remove already-watched titles
    watched = get_watched_titles()
    merged = merged[~merged["Name"].str.lower().isin(watched)]

    # Attach TMDB metadata from enriched cache
    enriched = _load_enriched()

    def _get(name: str, field: str):
        return enriched.get(name.lower().strip(), {}).get(field)

    merged["genres"] = merged["Name"].apply(lambda n: _get(n, "genres") or [])
    merged["runtime"] = merged["Name"].apply(lambda n: _get(n, "runtime"))
    merged["tmdb_rating"] = merged["Name"].apply(lambda n: _get(n, "tmdb_rating"))

    return merged.reset_index(drop=True)


def _matches_genre(row: pd.Series, genre: str) -> bool:
    """Match genre against TMDB genres list; fall back to title keyword if unenriched."""
    if not genre or genre.lower() == "any":
        return True

    # Use real TMDB genres when available
    genres: list = row.get("genres") or []
    if genres:
        return any(genre.lower() in g.lower() for g in genres)

    # Fallback: keyword match on title (notes have no genre info)
    return genre.lower() in str(row.get("Name", "")).lower()


@tool
def search_watchlist(query: str = "all", genre: str = None, max_runtime: int = None) -> list[dict]:
    """
    Search Alex's merged Letterboxd + analog watchlist for movies to watch.
    Excludes films already watched. Returns up to 50 candidates with TMDB metadata.

    IMPORTANT: Always call with query="all" to get the full unwatched watchlist.
    Genre and runtime filters use real TMDB data — do not rely on keyword guessing.

    Args:
        query: Pass "all" (default) for the full watchlist, or a title keyword for
               a specific name search.
        genre: Optional genre to filter by (e.g. "Thriller", "Drama", "Sci_Fi").
        max_runtime: Optional maximum runtime in minutes.

    Returns:
        List of dicts with keys: title, year, source, notes, genres, runtime, tmdb_rating
    """
    df = _load_watchlist()

    if df.empty:
        return []

    # Title keyword filter (only when not "all")
    if query and query.lower() not in ("all", "*", ""):
        query_lower = query.lower()
        mask = (
            df["Name"].str.lower().str.contains(query_lower, na=False)
            | df["notes"].str.lower().str.contains(query_lower, na=False)
        )
        df = df[mask]

    # Genre filter using TMDB genres
    if genre and genre.lower() != "any":
        df = df[df.apply(lambda row: _matches_genre(row, genre), axis=1)]

    # Runtime filter using TMDB runtime
    if max_runtime:
        df = df[df["runtime"].isna() | (df["runtime"] <= max_runtime)]

    candidates = df.head(50)
    return [
        {
            "title": row["Name"],
            "year": row["Year"],
            "source": row["source"],
            "notes": row["notes"],
            "genres": row["genres"] if isinstance(row["genres"], list) else [],
            "runtime": row["runtime"],
            "tmdb_rating": row["tmdb_rating"],
        }
        for _, row in candidates.iterrows()
    ]


if __name__ == "__main__":
    results = search_watchlist.invoke({"query": "all"})
    print(f"Watchlist candidates: {len(results)}")
    for r in results[:10]:
        print(f"  {r['title']} ({r['year']}) — {r['source']} — {r['genres']} — {r['runtime']}min — {r['tmdb_rating']}")
