"""
history_tool.py — taste profile from movie_data_final.csv

Genre columns (18): Adventure, Action, Sci_Fi, Comedy, Thriller, Fantasy,
Mystery, Crime, Animation, Music, Drama, Romance, War, Horror, History,
Western, Documentary, Rom_Com

Affinity score = avg_rating_for_genre * log(count_in_genre + 1)
"""
import math
import os
import pandas as pd
from langchain_core.tools import tool

_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "movie_data_final.csv")

GENRE_COLS = [
    "Adventure", "Action", "Sci_Fi", "Comedy", "Thriller", "Fantasy",
    "Mystery", "Crime", "Animation", "Music", "Drama", "Romance",
    "War", "Horror", "History", "Western", "Documentary", "Rom_Com",
]

_cached_profile: dict | None = None
_watched_titles: set | None = None


def compute_taste_profile_summary() -> dict:
    """
    Parse movie_data_final.csv once and return a taste profile dict.
    Also populates the module-level _watched_titles set used by watchlist_tool.
    """
    global _cached_profile, _watched_titles

    if _cached_profile is not None:
        return _cached_profile

    df = pd.read_csv(_DATA_PATH)

    # Build watched titles set for deduplication in watchlist tool
    _watched_titles = set(df["Name"].str.lower().str.strip())

    # Only use rows with a rating for affinity scoring
    rated = df[df["Rating"].notna() & (df["Rating"] > 0)].copy()

    genre_stats = {}
    for genre in GENRE_COLS:
        if genre not in rated.columns:
            continue
        genre_films = rated[rated[genre] == 1]
        count = len(genre_films)
        avg_rating = genre_films["Rating"].mean() if count > 0 else 0
        affinity = avg_rating * math.log(count + 1)
        genre_stats[genre] = {
            "count": count,
            "avg_rating": round(avg_rating, 2),
            "affinity": round(affinity, 3),
        }

    sorted_genres = sorted(genre_stats.items(), key=lambda x: x[1]["affinity"], reverse=True)
    top_genres = [g for g, _ in sorted_genres[:5]]
    bottom_genres = [g for g, _ in sorted_genres[-3:]]

    # Decade preferences
    if "Year" in df.columns:
        df["decade"] = (df["Year"] // 10 * 10).astype("Int64")
        decade_avgs = (
            df[df["Rating"].notna() & (df["Rating"] > 0)]
            .groupby("decade")["Rating"]
            .mean()
            .round(2)
            .sort_values(ascending=False)
        )
        decade_prefs = {str(k): v for k, v in decade_avgs.items() if pd.notna(k)}
    else:
        decade_prefs = {}

    runtime_median = int(df["runtime"].median()) if "runtime" in df.columns else None
    overall_avg = round(df["Rating"].mean(), 2) if "Rating" in df.columns else None
    total_films = len(df)

    # Sentiment skew
    sentiment_cols = ["negativity_percentage", "neutrality_percentage", "positivity_percentage"]
    sentiment = {}
    for col in sentiment_cols:
        if col in df.columns:
            sentiment[col.replace("_percentage", "")] = round(df[col].mean(), 3)

    _cached_profile = {
        "total_films_watched": total_films,
        "overall_avg_rating": overall_avg,
        "top_genres": top_genres,
        "bottom_genres": bottom_genres,
        "genre_affinities": {g: s["affinity"] for g, s in sorted_genres},
        "genre_details": {g: s for g, s in sorted_genres},
        "decade_preferences": decade_prefs,
        "runtime_median_minutes": runtime_median,
        "review_sentiment": sentiment,
    }
    return _cached_profile


def get_watched_titles() -> set:
    """Return the set of lowercased watched titles (populated after compute_taste_profile_summary)."""
    global _watched_titles
    if _watched_titles is None:
        compute_taste_profile_summary()
    return _watched_titles


@tool
def get_taste_profile(focus: str = "general") -> dict:
    """
    Returns Alex's taste profile derived from 8+ years of Letterboxd watch history.
    Includes top/bottom genres by affinity, decade preferences, runtime median, and sentiment.
    Call this at the start of every recommendation session.

    Args:
        focus: One of "general", "genres", "decades", "runtime". Returns full profile for "general".
    """
    profile = compute_taste_profile_summary()

    if focus == "genres":
        return {
            "top_genres": profile["top_genres"],
            "bottom_genres": profile["bottom_genres"],
            "genre_details": profile["genre_details"],
        }
    if focus == "decades":
        return {"decade_preferences": profile["decade_preferences"]}
    if focus == "runtime":
        return {"runtime_median_minutes": profile["runtime_median_minutes"]}

    return profile


if __name__ == "__main__":
    profile = compute_taste_profile_summary()
    print("=== Taste Profile ===")
    print(f"Total films: {profile['total_films_watched']}")
    print(f"Overall avg rating: {profile['overall_avg_rating']}")
    print(f"Top genres: {profile['top_genres']}")
    print(f"Bottom genres: {profile['bottom_genres']}")
    print(f"Runtime median: {profile['runtime_median_minutes']} min")
    print(f"Decade prefs (top 5): {list(profile['decade_preferences'].items())[:5]}")
    print(f"Sentiment: {profile['review_sentiment']}")
    print(f"Watched titles count: {len(get_watched_titles())}")
