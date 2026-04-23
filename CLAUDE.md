# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the app
streamlit run app.py

# Terminal test the LangGraph agent (no UI)
python graph.py

# Regenerate analog_watchlist.csv from analog_list.txt
python parse_analog_list.py

# Test individual tools
python tools/watchlist_tool.py
python tools/streaming_tool.py
python tools/history_tool.py
python tools/kanopy_tool.py
python tools/watch_history_tool.py
```

## Environment

Secrets go in `local.env` (gitignored):
- `ANTHROPIC_API_KEY` — for `claude-sonnet-4-6` via `langchain-anthropic`
- `TMDB_API_KEY` — for streaming availability and watchlist enrichment

## Architecture

This is a **LangGraph ReAct agent** with a **Streamlit chat UI**.

### Data flow

1. **Startup**: `app.py` calls `compute_taste_profile_summary()` (reads `data/movie_data_final.csv`) and `enrich_watchlist()` (fetches TMDB metadata for all watchlist titles not yet cached). Both are `@st.cache_data`.

2. **Per-request**: Streamlit builds a `RecommenderState` dict with the user message and sidebar filter values, then calls `graph.stream(state)`.

3. **Graph** (`graph.py`): Single supervisor node (`claude-sonnet-4-6`) in a ReAct loop with a `ToolNode`. The supervisor calls tools, gets results back, and loops until it produces a final text response.

4. **System prompt** (`prompts.py`): `build_system_prompt(state)` injects the pre-computed taste profile and active sidebar filters into the system prompt on every turn.

### LangGraph topology

```
[START] → supervisor → (tool calls?) → tools → supervisor → ...
                            (done?) → [END]
```

`should_continue` routes to `"tools"` if the last message has `tool_calls`, otherwise `END`.

### State (`state.py`)

`RecommenderState` carries the full message history (via LangGraph's `add_messages` reducer) plus filter values set by the sidebar and intermediate tool results.

### Tools (`tools/`)

Three `@tool`-decorated LangChain tools exposed to the agent:

| Tool | File | What it does |
|------|------|---|
| `search_watchlist` | `watchlist_tool.py` | Merges Letterboxd + analog CSVs, deduplicates against watch history, attaches TMDB metadata from `watchlist_enriched.json`. Always call with `query="all"`. |
| `search_watch_history` | `watch_history_tool.py` | Searches `movie_data_final.csv` by title keyword; returns rating, log date, genres, runtime, and sentiment. Use when Alex asks about films he has already seen or wants to rewatch. |
| `get_taste_profile` | `history_tool.py` | Computes genre affinity scores (`avg_rating × log(count+1)`), decade preferences, and runtime median from `movie_data_final.csv`. Cached in-memory after first call. |
| `check_streaming` | `streaming_tool.py` | Checks Max/Hulu/Criterion via TMDB `watch/providers`, and Kanopy via SAPL's Kanopy API (`kanopy_tool.py`). Uses a 7-day disk cache at `data/tmdb_cache.json`. |

### Data files

| File | Purpose |
|------|---------|
| `data/movie_data_final.csv` | Full Letterboxd watch history with ratings, genre flags, runtime |
| `data/letterboxd_watchlist.csv` | Letterboxd watchlist export (Date, Name, Year, Letterboxd URI) |
| `data/analog_watchlist.csv` | Parsed output of `analog_list.txt` (free-text notes list) |
| `data/analog_list.txt` | Hand-maintained free-text movie list; parse with `parse_analog_list.py` |
| `data/watchlist_enriched.json` | TMDB metadata cache for watchlist titles (genres, runtime, rating) |
| `data/tmdb_cache.json` | Shared TMDB response cache (7-day TTL); used by both `streaming_tool` and `enrich_watchlist` |
| `data/kanopy_cache.json` | Kanopy availability cache (7-day TTL) |

### Watchlist enrichment

`enrich_watchlist.py` shares the TMDB disk cache (`tmdb_cache.json`) with `streaming_tool.py` — it imports `_lookup_movie`, `_load_cache`, `_save_cache` directly. Films already looked up for streaming don't trigger extra API calls.

### Analog list parsing (`parse_analog_list.py`)

Converts the free-text `analog_list.txt` into `analog_watchlist.csv`. Handles section prefixes (`Criterion:`, `Kanopy:`), inline service tags, `RW` (rewatch) markers, leading director names, trailing annotations, and Unicode normalization. Edit `TITLE_CORRECTIONS` to fix persistent mis-parses.
