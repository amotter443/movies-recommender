# movies-recommender
An agentic, LangGraph-backed project helping aide with the exhausting process of finding a movie to watch tonight

When the user provides search parameters, the site searches your Letterboxd and analog watchlists, profiles your taste from watch history, and checks what's currently streaming.

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Create `local.env` with your API keys:
   ```
   ANTHROPIC_API_KEY=...
   TMDB_API_KEY=...
   ```

## Running

```bash
streamlit run app.py
```

## How it works

On startup, the app loads your watch history (`data/movie_data_final.csv`) to build a taste profile and fetches TMDB metadata for all watchlist titles. When you send a message, a `claude-sonnet-4-6` ReAct agent runs a tool loop:

1. **`search_watchlist`** — merges your Letterboxd + analog watchlists, strips already-watched titles, and returns candidates with genre/runtime metadata
2.  **`search_watch_history`** - returns rating, log date, runtime, genres, and review/sentiment when requesting a film you've already seen
3. **`get_taste_profile`** — returns genre affinities, decade preferences, and runtime median from your history
4. **`check_streaming`** — checks Max, Hulu, and Criterion Channel via TMDB, and Kanopy via SAPL's catalog directly

Results are cached to disk (`data/tmdb_cache.json`, `data/kanopy_cache.json`) with a 7-day TTL.

## Watchlist sources

| File | How to update |
|------|--------------|
| `data/letterboxd_watchlist.csv` | Export from Letterboxd and replace |
| `data/analog_list.txt` | Edit the free-text list, then run `python parse_analog_list.py` |
