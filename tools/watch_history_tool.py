"""
watch_history_tool.py — search Alex's personal watch history in movie_data_final.csv
"""
import os

import pandas as pd
from langchain_core.tools import tool

_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "movie_data_final.csv")

_RETURN_COLS = [
    "Name", "Year", "Rating", "Logged_Date", "runtime",
    "Adventure", "Action", "Sci_Fi", "Comedy", "Thriller", "Fantasy",
    "Mystery", "Crime", "Animation", "Music", "Drama", "Romance",
    "War", "Horror", "History", "Western", "Documentary", "Rom_Com",
    "Review", "movie_sentiment",
]

_df: pd.DataFrame | None = None


def _load() -> pd.DataFrame:
    global _df
    if _df is None:
        _df = pd.read_csv(_DATA_PATH)
    return _df


def _genre_flags(row: pd.Series) -> list[str]:
    genre_cols = [
        "Adventure", "Action", "Sci_Fi", "Comedy", "Thriller", "Fantasy",
        "Mystery", "Crime", "Animation", "Music", "Drama", "Romance",
        "War", "Horror", "History", "Western", "Documentary", "Rom_Com",
    ]
    return [g for g in genre_cols if row.get(g) == 1]


@tool
def search_watch_history(query: str, max_results: int = 20) -> list[dict]:
    """
    Search Alex's personal watch history (movie_data_final.csv) by title keyword.
    Use this when Alex asks about a film he has already seen, wants to recall his
    rating, or asks to rewatch something from his history.

    Args:
        query: Title keyword to search for (case-insensitive substring match).
        max_results: Maximum number of results to return (default 20).

    Returns:
        List of dicts with keys: title, year, rating, logged_date, runtime,
        genres, review, sentiment.
    """
    df = _load()
    mask = df["Name"].str.lower().str.contains(query.lower().strip(), na=False)
    hits = df[mask].head(max_results)

    results = []
    for _, row in hits.iterrows():
        results.append({
            "title": row["Name"],
            "year": row.get("Year"),
            "rating": row.get("Rating"),
            "logged_date": row.get("Logged_Date"),
            "runtime": row.get("runtime"),
            "genres": _genre_flags(row),
            "review": row.get("Review") if pd.notna(row.get("Review")) else None,
            "sentiment": row.get("movie_sentiment"),
        })
    return results


if __name__ == "__main__":
    results = search_watch_history.invoke({"query": "Guardians"})
    for r in results:
        print(r)
